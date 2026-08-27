data "aws_vpc" "main" {
  default = true
}

data "aws_subnets" "main" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.main.id]
  }
  filter {
    name   = "map-public-ip-on-launch"
    values = ["true"]
  }
}

data "aws_ecs_cluster" "api" {
  cluster_name = "chat-api-${var.environment}"
}

module "transcription" {
  source = "../../modules/transcription"

  environment                  = var.environment
  aws_region                   = var.aws_region
  ecs_cluster_id               = data.aws_ecs_cluster.api.id
  subnet_ids                   = data.aws_subnets.main.ids
  vpc_id                       = data.aws_vpc.main.id
  database_url_secret_arn      = var.database_url_secret_arn
  cors_allowed_origins         = var.cors_allowed_origins
  worker_memory                = var.worker_memory
  worker_cpu                   = var.worker_cpu
  image_tag                    = var.image_tag
  alarm_email                  = var.alarm_email
  huggingface_token_secret_arn = var.huggingface_token_secret_arn
  github_repo                  = "chat"
  sample_files_path            = "${path.module}/../../../chat-vue/public/samples"
  idle_exit_seconds            = var.idle_exit_seconds
  max_lifetime_seconds         = var.max_lifetime_seconds
}

module "photogrammetry" {
  source                  = "../../modules/photogrammetry"
  environment             = var.environment
  aws_region              = var.aws_region
  audio_bucket_name       = module.transcription.bucket_name
  audio_bucket_arn        = "arn:aws:s3:::${module.transcription.bucket_name}"
  database_url_secret_arn = var.database_url_secret_arn
  github_repo             = "chat"
  image_tag               = var.photogrammetry_image_tag
  idle_exit_seconds       = var.idle_exit_seconds
  max_lifetime_seconds    = var.max_lifetime_seconds
}

output "audio_bucket_name" {
  value = module.transcription.bucket_name
}

output "transcription_queue_url" {
  value = module.transcription.queue_url
}

output "dlq_url" {
  value = module.transcription.dlq_url
}

output "worker_ecr_url" {
  value = module.transcription.worker_ecr_url
}

output "photogrammetry_queue_url" { value = module.photogrammetry.queue_url }
output "photogrammetry_worker_ecr_url" { value = module.photogrammetry.worker_ecr_url }
output "photogrammetry_github_actions_role_arn" { value = module.photogrammetry.worker_github_actions_role_arn }
