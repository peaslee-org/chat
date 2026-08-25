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
