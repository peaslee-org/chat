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
  database_url                 = var.worker_database_url
  cors_allowed_origins         = var.cors_allowed_origins
  worker_memory                = var.worker_memory
  worker_cpu                   = var.worker_cpu
  alarm_email                  = var.alarm_email
  huggingface_token_secret_arn = var.huggingface_token_secret_arn
  github_repo                  = "chat"
  sample_files_path            = "${path.module}/../../../chat-vue/public/samples"
  # Pinned — see the variable description before updating.
  worker_ami_id = var.worker_ami_id
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
