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

variable "database_url" {
  type        = string
  sensitive   = true
  description = "Full asyncpg DATABASE_URL for the chat-api (postgresql+asyncpg://...)."
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
