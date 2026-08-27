variable "environment" {
  type = string
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "audio_bucket_name" {
  type        = string
  description = "The transcription module's audio bucket; photogrammetry/ and samples/photogrammetry/ live in it."
}

variable "audio_bucket_arn" {
  type = string
}

variable "database_url_secret_arn" {
  type        = string
  description = "Secrets Manager secret holding DATABASE_URL; injected by ECS, never read by Terraform."
}

variable "github_org" {
  type    = string
  default = "peaslee-org"
}

variable "github_repo" {
  type = string
}

variable "image_tag" {
  type        = string
  description = "Image tag the task definition points at. CI registers new revisions outside Terraform; set this to the deployed tag so plan stays clean."
  default     = "latest"
}

variable "idle_exit_seconds" {
  type        = number
  description = "Must equal prod's gpu_idle_exit_seconds (same rule as the transcription worker)."
  default     = 900
}

variable "max_lifetime_seconds" {
  type        = number
  description = "Must equal prod's gpu_max_lifetime_seconds."
  default     = 10800
}

variable "job_timeout_seconds" {
  type        = number
  description = "Per-job wall clock; the worker kills the current tool and fails the job past this."
  default     = 3600
}

variable "worker_cpu" {
  type    = number
  default = 3072
}

variable "worker_memory" {
  type        = number
  description = "g4dn.xlarge has 16 GiB; dense reconstruction is RAM-bound. 14000 leaves room for the agent and pins one task per instance."
  default     = 14000
}
