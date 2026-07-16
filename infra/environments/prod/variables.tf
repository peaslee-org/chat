variable "environment" {
  default = "prod"
}

variable "aws_region" {
  default = "us-east-1"
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
  type    = string
  default = "chat-audio-prod-123456789012"
}

variable "transcribe_sqs_queue_url" {
  type    = string
  default = "https://sqs.us-east-1.amazonaws.com/123456789012/transcription-prod"
}
