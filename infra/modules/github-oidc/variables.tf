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
