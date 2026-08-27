terraform {
  backend "s3" {
    # bucket is supplied at init time: terraform init -backend-config=backend.hcl
    key          = "chat-api/prod/v2/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

data "aws_caller_identity" "current" {}

resource "random_password" "cloudfront_secret" {
  length  = 32
  special = false

  lifecycle {
    # An existing secret is adopted with `terraform import random_password.cloudfront_secret <value>`,
    # which records the provider defaults (special = true). Every generation attribute is
    # replace-on-change, so without this the first plan after import would rotate the secret —
    # and with it the CloudFront custom header and both ALB listener rules. Rotate deliberately
    # (terraform apply -replace=random_password.cloudfront_secret), not as a side effect.
    ignore_changes = [special]
  }
}

data "aws_vpc" "default" {
  default = true
}

resource "aws_default_vpc" "this" {
  tags = {
    Name = "peaslee-org"
  }
}

data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "map-public-ip-on-launch"
    values = ["true"]
  }
}

# GPU pool subnets: only AZs that offer the pool's primary instance type (us-east-1e offers no
# g4dn; an ASG spanning it wasted launch attempts there — observed 2026-08-26).
data "aws_ec2_instance_type_offerings" "gpu" {
  filter {
    name   = "instance-type"
    values = ["g4dn.xlarge"]
  }
  location_type = "availability-zone"
}

data "aws_subnets" "gpu" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "map-public-ip-on-launch"
    values = ["true"]
  }
  filter {
    name   = "availability-zone"
    values = data.aws_ec2_instance_type_offerings.gpu.locations
  }
}

module "acm" {
  source      = "../../modules/acm"
  domain_name = var.domain_name
}

module "cognito" {
  source      = "../../modules/cognito"
  environment = var.environment
}

module "ecr" {
  source = "../../modules/ecr"
}


locals {
  cluster_name               = "chat-api-${var.environment}"              # mirrors modules/ecs local.name
  gpu_capacity_provider      = "gpu-${var.environment}"                   # mirrors modules/gpu-capacity local.name
  worker_task_family         = "transcription-${var.environment}-worker"  # owned by the transcription-prod state
  photogrammetry_task_family = "photogrammetry-${var.environment}-worker" # owned by the transcription-prod state
}

module "ecs" {
  source                       = "../../modules/ecs"
  environment                  = var.environment
  vpc_id                       = data.aws_vpc.default.id
  subnet_ids                   = var.task_subnet_ids != null ? var.task_subnet_ids : data.aws_subnets.public.ids
  alb_subnet_ids               = var.alb_subnet_ids != null ? var.alb_subnet_ids : slice(sort(data.aws_subnets.public.ids), 0, var.alb_subnet_count)
  ecr_repository_url           = module.ecr.repository_url
  acm_certificate_arn          = module.acm.certificate_arn
  aws_region                   = var.aws_region
  cognito_user_pool_id         = module.cognito.user_pool_id
  cognito_client_id            = module.cognito.client_id
  bedrock_model_id             = var.bedrock_model_id
  database_url_secret_arn      = var.database_url_secret_arn
  cloudfront_secret            = random_password.cloudfront_secret.result
  langchain_api_key_secret_arn = var.langchain_api_key_secret_arn
  audio_bucket_name            = var.audio_bucket_name
  transcribe_sqs_queue_url     = var.transcribe_sqs_queue_url
  image_tag                    = var.image_tag

  extra_environment = [
    { name = "GPU_CONTROLLER_ENABLED", value = tostring(var.gpu_controller_enabled) },
    { name = "GPU_CLUSTER", value = local.cluster_name },
    { name = "GPU_WORKER_TASK_FAMILY", value = local.worker_task_family },
    { name = "GPU_CAPACITY_PROVIDER", value = local.gpu_capacity_provider },
    { name = "GPU_DAILY_CAP_HOURS", value = tostring(var.gpu_daily_cap_hours) },
    { name = "GPU_MONTHLY_CAP_HOURS", value = tostring(var.gpu_monthly_cap_hours) },
    { name = "GPU_WARM_PER_USER_PER_DAY", value = tostring(var.gpu_warm_per_user_per_day) },
    { name = "GPU_HOURLY_RATE_USD", value = tostring(var.gpu_hourly_rate_usd) },
    { name = "GPU_IDLE_EXIT_SECONDS", value = tostring(var.gpu_idle_exit_seconds) },
    { name = "GPU_MAX_LIFETIME_SECONDS", value = tostring(var.gpu_max_lifetime_seconds) },
    { name = "GPU_PHOTOGRAMMETRY_TASK_FAMILY", value = var.photogrammetry_sqs_queue_url == "" ? "" : local.photogrammetry_task_family },
    { name = "PHOTOGRAMMETRY_SQS_QUEUE_URL", value = var.photogrammetry_sqs_queue_url },
  ]
}

module "gpu_capacity" {
  source               = "../../modules/gpu-capacity"
  environment          = var.environment
  vpc_id               = data.aws_vpc.default.id
  subnet_ids           = data.aws_subnets.gpu.ids
  cluster_name         = local.cluster_name
  ami_id               = var.gpu_ami_id
  max_size             = var.gpu_max_size
  on_demand_percentage = var.gpu_on_demand_percentage
  alert_email          = var.gpu_alert_email
  budget_actual_usd    = var.gpu_budget_actual_usd
  budget_forecast_usd  = var.gpu_budget_forecast_usd

  depends_on = [module.ecs] # the cluster must exist before capacity providers attach
}

module "cloudfront" {
  source                   = "../../modules/cloudfront"
  environment              = var.environment
  domain_name              = var.domain_name
  frontend_bucket_name     = var.frontend_bucket_name
  alb_dns_name             = module.ecs.alb_dns_name
  acm_certificate_arn      = module.acm.certificate_arn
  cloudfront_secret        = random_password.cloudfront_secret.result
  github_oidc_provider_arn = module.github_oidc.oidc_provider_arn
  github_org               = "peaslee-org"
  frontend_github_repo     = "chat"
}

module "monitoring" {
  source      = "../../modules/monitoring"
  environment = var.environment
}

module "github_oidc" {
  source         = "../../modules/github-oidc"
  environment    = var.environment
  github_org     = "peaslee-org"
  github_repo    = "chat"
  deploy_branch  = "main"
  aws_region     = var.aws_region
  aws_account_id = data.aws_caller_identity.current.account_id
}

# ── Outputs ───────────────────────────────────────────────────────────────────

output "acm_validation_records" {
  description = "Step 1: Add these CNAMEs to your DNS provider, wait for cert status to show 'Issued' in ACM, then run terraform apply again."
  value       = module.acm.validation_records
}

output "cloudfront_domain_name" {
  description = "Point the domain_name CNAME to this value (replaces the ALB DNS name)."
  value       = module.cloudfront.distribution_domain_name
}

output "cloudfront_distribution_id" {
  description = "Set as AWS_CF_DISTRIBUTION_ID secret in the chat-vue GitHub repo."
  value       = module.cloudfront.distribution_id
}

output "frontend_s3_bucket" {
  description = "Set as AWS_S3_BUCKET secret in the chat-vue GitHub repo."
  value       = module.cloudfront.s3_bucket_name
}

output "frontend_deploy_role_arn" {
  description = "Set as AWS_DEPLOY_ROLE_ARN secret in the chat-vue GitHub repo."
  value       = module.cloudfront.frontend_deploy_role_arn
}

output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "github_actions_role_arn" {
  description = "Set as AWS_DEPLOY_ROLE_ARN secret in GitHub."
  value       = module.github_oidc.role_arn
}

output "ecs_cluster_name" {
  value = module.ecs.cluster_name
}

output "ecs_service_name" {
  value = module.ecs.service_name
}

output "task_definition_family" {
  value = module.ecs.task_definition_family
}

output "cognito_user_pool_id" {
  value = module.cognito.user_pool_id
}

output "cognito_client_id" {
  value = module.cognito.client_id
}

output "gpu_capacity_provider_name" {
  value = module.gpu_capacity.capacity_provider_name
}

output "gpu_asg_name" {
  value = module.gpu_capacity.asg_name
}

output "gpu_security_group_id" {
  value = module.gpu_capacity.security_group_id
}

output "gpu_instance_profile_name" {
  value = module.gpu_capacity.instance_profile_name
}
