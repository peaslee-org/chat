variable "environment" {
  type    = string
  default = "dev"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "worker_database_url" {
  type        = string
  sensitive   = true
  description = "Full asyncpg DATABASE_URL for the transcription worker (postgresql+asyncpg://...)."
}

variable "cors_allowed_origins" {
  type        = list(string)
  description = "Browser origins allowed to PUT directly to S3."
}

variable "worker_ami_id" {
  type        = string
  description = <<-EOT
    AMI for the ECS GPU launch template (al2023-ami-ecs-gpu-hvm-* in the region). Pinned on
    purpose — a new AMI creates a new launch template version and the next instance boots from it.
    Look up the current one with:
      aws ec2 describe-images --owners amazon \
        --filters "Name=name,Values=al2023-ami-ecs-gpu-hvm-*" "Name=architecture,Values=x86_64" \
        --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text
  EOT
}

variable "worker_memory" {
  type        = number
  description = "Memory (MB) for the ECS Fargate task."
  default     = 3072
}

variable "worker_cpu" {
  type        = number
  description = "CPU units for the ECS Fargate task (1024 = 1 vCPU)."
  default     = 1024
}

variable "alarm_email" {
  type        = string
  description = "Email address to notify when messages land in the DLQ. Leave empty to skip alarm."
  default     = ""
}

variable "huggingface_token_secret_arn" {
  type        = string
  description = "ARN of the Secrets Manager secret containing the HuggingFace token."
  default     = ""
}
