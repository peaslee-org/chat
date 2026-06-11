output "role_arn" {
  description = "ARN of the IAM role assumed by GitHub Actions. Set this as the AWS_DEPLOY_ROLE_ARN secret in your GitHub repo."
  value       = aws_iam_role.github_actions.arn
}

output "oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider. Pass to other modules that need to create additional GitHub Actions roles."
  value       = local.oidc_provider_arn
}
