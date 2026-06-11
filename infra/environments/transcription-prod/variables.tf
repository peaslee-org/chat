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
  default     = ["https://dev.chat.example.com", "http://localhost:5173"]
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
