variable "environment" {
  type = string
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "ecs_cluster_id" {
  type        = string
  description = "ARN or name of the ECS cluster to run the worker in."
}

variable "subnet_ids" {
  type        = list(string)
  description = "Subnets for the worker ECS service (must have internet access for S3/SQS/Transcribe)."
}

variable "vpc_id" {
  type = string
}

variable "database_url_secret_arn" {
  type        = string
  description = "ARN of the Secrets Manager secret holding the asyncpg DATABASE_URL. Injected into the container as DATABASE_URL by ECS; the value never passes through Terraform."
}

variable "worker_cpu" {
  type    = number
  default = 1024
}

variable "worker_memory" {
  type    = number
  default = 3072
}

variable "github_org" {
  type        = string
  description = "GitHub organisation or user that owns the transcription-worker repo."
  default     = "peaslee-org"
}

variable "cors_allowed_origins" {
  type        = list(string)
  description = "Origins allowed to PUT directly to the audio S3 bucket from the browser."
  default     = []
}

variable "alarm_email" {
  type        = string
  description = "Email address to notify when messages land in the DLQ. Leave empty to skip alarm."
  default     = ""
}

variable "huggingface_token_secret_arn" {
  type        = string
  description = "ARN of the Secrets Manager secret containing the HuggingFace token. When set, grants the worker task role GetSecretValue on this secret."
  default     = ""
}

variable "github_repo" {
  type        = string
  description = "GitHub repo name that the worker CI/CD workflow lives in."
  default     = "transcription-worker"
}

variable "worker_ami_id" {
  type        = string
  description = <<-EOT
    AMI ID for the ECS GPU launch template (al2023-ami-ecs-gpu-hvm-* in us-east-1).
    Pinned intentionally — do NOT use a dynamic data lookup. The host NVIDIA driver
    in this AMI must be compatible with CUDA 12.8.1 used by the worker container.
    To update: find the latest AMI with:
      aws ec2 describe-images \
        --owners amazon \
        --filters "Name=name,Values=al2023-ami-ecs-gpu-hvm-*" "Name=architecture,Values=x86_64" \
        --query "sort_by(Images, &CreationDate)[-1].{ImageId:ImageId,Name:Name,Created:CreationDate}" \
        --output table
    Then verify the NVIDIA driver version in the AMI release notes is compatible,
    update this value, and apply.
  EOT
}

variable "sample_files_path" {
  type        = string
  description = "Local path to the directory containing sample WAV files (conversation.wav, barry.wav, jane.wav). Used by Terraform to upload them once to the samples/ S3 prefix."
}

variable "image_tag" {
  type        = string
  description = "Image tag the task definition points at. CI deploys immutable tags and registers new revisions outside Terraform; set this to the deployed tag so plan stays clean."
  default     = "latest"
}

variable "worker_desired_count" {
  type        = number
  description = "Desired count of the worker service. 0 parks the worker (the GPU ASG is scaled by transcription-worker.sh); 1 runs it."
  default     = 1
}
