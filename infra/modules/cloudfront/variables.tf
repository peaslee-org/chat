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
