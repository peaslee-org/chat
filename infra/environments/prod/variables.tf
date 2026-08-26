variable "environment" {
  default = "prod"
}

variable "aws_region" {
  default = "us-east-1"
}

variable "alb_subnet_count" {
  type        = number
  default     = 2
  description = <<-EOT
    How many public subnets to place the ALB in. Two is the AWS minimum; each
    additional one costs another public IPv4 address and buys nothing while the
    service runs a single task.
  EOT
}

variable "bedrock_model_id" {
  type    = string
  default = "anthropic.claude-3-sonnet-20240229-v1:0"
}

variable "langchain_api_key_secret_arn" {
  type        = string
  description = "ARN of the Secrets Manager secret containing the LangSmith API key."
}

variable "database_url_secret_arn" {
  type        = string
  description = "ARN of the Secrets Manager secret holding the asyncpg DATABASE_URL. Injected into the container as DATABASE_URL by ECS; the value never passes through Terraform."
}

variable "audio_bucket_name" {
  type        = string
  description = "S3 bucket for audio uploads (created by the transcription environment)."
}

variable "transcribe_sqs_queue_url" {
  type        = string
  description = "SQS queue URL the API enqueues transcription jobs to (created by the transcription environment)."
}

variable "domain_name" {
  type        = string
  description = "Public hostname served by CloudFront and named on the ACM certificate."
}

variable "frontend_bucket_name" {
  type        = string
  description = "S3 bucket that holds the built SPA (CloudFront origin). Bucket names are global."
}

variable "image_tag" {
  type        = string
  description = "Image tag the task definition points at. CI deploys immutable tags and registers new revisions outside Terraform; set this to the deployed tag so plan stays clean."
  default     = "latest"
}

variable "alb_subnet_ids" {
  type        = list(string)
  default     = null
  description = <<-EOT
    Explicit public subnets for the ALB (at least two, in different AZs). When null, the first
    alb_subnet_count subnets by sorted id are used — which picks AZs arbitrarily. Pin this so a
    plan never proposes moving a live ALB between AZs.
  EOT
}

variable "task_subnet_ids" {
  type        = list(string)
  default     = null
  description = <<-EOT
    Subnets the ECS tasks may run in. When null, every public subnet of the VPC. Pin it to the
    AZ of a single-AZ dependency (e.g. a self-hosted database) so tasks are not spread across
    AZs that can never be resilient anyway.
  EOT
}

variable "gpu_ami_id" {
  type        = string
  description = "Pre-baked GPU AMI (build-gpu-ami.sh)."
}

variable "gpu_max_size" {
  type    = number
  default = 2
}

variable "gpu_alert_email" {
  type    = string
  default = ""
}

variable "gpu_budget_actual_usd" {
  type    = number
  default = 40
}

variable "gpu_budget_forecast_usd" {
  type    = number
  default = 60
}

variable "gpu_controller_enabled" {
  type    = bool
  default = false
}

variable "gpu_daily_cap_hours" {
  type    = number
  default = 3
}

variable "gpu_monthly_cap_hours" {
  type    = number
  default = 30
}

variable "gpu_warm_per_user_per_day" {
  type    = number
  default = 3
}

variable "gpu_hourly_rate_usd" {
  type    = number
  default = 0.20
}

variable "gpu_idle_exit_seconds" {
  type        = number
  default     = 900
  description = "Must equal transcription-prod's idle_exit_seconds — both feed the same worker via GPU_IDLE_EXIT_SECONDS / IDLE_EXIT_SECONDS."
}

variable "gpu_max_lifetime_seconds" {
  type        = number
  default     = 10800
  description = "Must equal transcription-prod's max_lifetime_seconds — both feed the same worker via GPU_MAX_LIFETIME_SECONDS / MAX_LIFETIME_SECONDS."
}
