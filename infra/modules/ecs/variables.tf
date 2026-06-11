variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "ecr_repository_url" {
  type = string
}

variable "acm_certificate_arn" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "database_url" {
  type      = string
  sensitive = true
}

variable "cognito_user_pool_id" {
  type = string
}

variable "cognito_client_id" {
  type = string
}

variable "bedrock_model_id" {
  type    = string
  default = "anthropic.claude-3-sonnet-20240229-v1:0"
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "cpu" {
  type    = number
  default = 256
}

variable "memory" {
  type    = number
  default = 512
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "cloudfront_secret" {
  type      = string
  sensitive = true
}

variable "langchain_api_key_secret_arn" {
  type        = string
  description = "ARN of the Secrets Manager secret containing the LangSmith API key."
}

variable "audio_bucket_name" {
  type        = string
  description = "S3 bucket name for audio uploads and transcription output."
}

variable "transcribe_sqs_queue_url" {
  type        = string
  description = "SQS queue URL consumed by the transcription worker."
}
