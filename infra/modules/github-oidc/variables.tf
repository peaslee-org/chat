variable "environment" {
  type = string
}

variable "github_org" {
  type = string
}

variable "github_repo" {
  type = string
}

variable "deploy_branch" {
  type    = string
  default = "main"
}

variable "aws_region" {
  type = string
}

variable "aws_account_id" {
  type = string
}

variable "ecr_repository_name" {
  type    = string
  default = "chat-api"
}

variable "create_oidc_provider" {
  description = "Set to false if the GitHub Actions OIDC provider already exists in this AWS account (only one per account is allowed)."
  type        = bool
  default     = true
}
