variable "environment" {
  type = string
}

variable "domain_name" {
  type = string
}

variable "alb_dns_name" {
  type = string
}

variable "acm_certificate_arn" {
  type = string
}

variable "cloudfront_secret" {
  type      = string
  sensitive = true
}

variable "github_oidc_provider_arn" {
  type = string
}

variable "github_org" {
  type = string
}

variable "frontend_github_repo" {
  type = string
}

variable "frontend_deploy_branch" {
  type    = string
  default = "main"
}

variable "frontend_bucket_name" {
  type        = string
  description = "Name of the S3 bucket holding the built SPA."
}

variable "alternate_domain_names" {
  type        = list(string)
  description = "Extra CloudFront aliases; each must be on the ACM certificate."
  default     = []
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
