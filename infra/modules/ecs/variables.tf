variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "alb_subnet_ids" {
  type        = list(string)
  default     = null
  description = <<-EOT
    Public subnets for the ALB. Falls back to var.subnet_ids when null.

    Only the ALB's subnet count drives public-IPv4 cost: AWS bills per public IPv4
    address per hour, and an ALB claims one per subnet it sits in. Two is the AWS
    minimum. Handing it every subnet of a default VPC puts the ALB in every AZ in
    the region and pays for an address in each, while its targets live in one. ALB
    cross-zone load balancing is always on and free, so the extra AZs buy nothing.

    Kept separate from subnet_ids because task placement is NOT a cost driver: a
    service runs a fixed number of tasks and each takes one public IP regardless
    of how many subnets it could have been placed in. Give tasks every AZ; give
    the ALB two.
  EOT
}

variable "container_insights" {
  type        = string
  default     = "disabled"
  description = <<-EOT
    ECS Container Insights. "enabled" publishes a set of CloudWatch custom metrics
    per cluster/service/task, billed per metric per month. For a low-traffic
    service that can rival the cost of the compute it observes. Off by default;
    turn it on deliberately when the dashboards are worth it.
  EOT
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
