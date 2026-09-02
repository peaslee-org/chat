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
  description = "Browser origins allowed to PUT uploads to, and fetch() presigned objects (e.g. the photogrammetry GLB for <model-viewer>) from, the audio S3 bucket."
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

variable "sample_files_path" {
  type        = string
  description = "Local path to the directory containing sample WAV files (conversation.wav, barry.wav, jane.wav). Used by Terraform to upload them once to the samples/ S3 prefix."
}

variable "image_tag" {
  type        = string
  description = "Image tag the task definition points at. CI deploys immutable tags and registers new revisions outside Terraform; set this to the deployed tag so plan stays clean."
  default     = "latest"
}

variable "idle_exit_seconds" {
  type        = number
  description = "Seconds the worker waits on an empty queue before exiting (lets the GPU pool scale to zero)."
  default     = 900
}

variable "max_lifetime_seconds" {
  type        = number
  description = "Maximum seconds the worker task runs before exiting regardless of queue state."
  default     = 10800
}

variable "github_org_id" {
  type        = string
  description = "GitHub organization's immutable numeric id (gh api orgs/<org> --jq .id). Appears as org@id in post-rename OIDC sub claims."
  default     = "263481008"
}

variable "github_repo_id" {
  type        = string
  description = "GitHub repository's immutable numeric id (gh api repos/<org>/<repo> --jq .id). Appears as repo@id in post-rename OIDC sub claims."
  default     = "1176238406"
}
