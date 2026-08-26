variable "environment" {
  type    = string
  default = "dev"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "database_url_secret_arn" {
  type        = string
  description = "ARN of the Secrets Manager secret holding the asyncpg DATABASE_URL. Injected into the container as DATABASE_URL by ECS; the value never passes through Terraform."
}

variable "cors_allowed_origins" {
  type        = list(string)
  description = "Browser origins allowed to PUT directly to S3."
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

variable "image_tag" {
  type        = string
  description = "Image tag the task definition points at. CI deploys immutable tags and registers new revisions outside Terraform; set this to the deployed tag so plan stays clean."
  default     = "latest"
}

variable "idle_exit_seconds" {
  type        = number
  description = "Seconds the worker waits on an empty queue before exiting (lets the GPU pool scale to zero). Must equal prod's gpu_idle_exit_seconds — both feed the same worker via IDLE_EXIT_SECONDS / GPU_IDLE_EXIT_SECONDS."
  default     = 900
}

variable "max_lifetime_seconds" {
  type        = number
  description = "Maximum seconds the worker task runs before exiting regardless of queue state. Must equal prod's gpu_max_lifetime_seconds — both feed the same worker via MAX_LIFETIME_SECONDS / GPU_MAX_LIFETIME_SECONDS."
  default     = 10800
}
