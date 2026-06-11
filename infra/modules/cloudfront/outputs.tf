output "distribution_domain_name" {
  description = "Point chat.example.com CNAME to this value (replaces the ALB DNS name)."
  value       = aws_cloudfront_distribution.this.domain_name
}

output "distribution_id" {
  description = "Set as AWS_CF_DISTRIBUTION_ID secret in the chat-vue GitHub repo."
  value       = aws_cloudfront_distribution.this.id
}

output "s3_bucket_name" {
  description = "Set as AWS_S3_BUCKET secret in the chat-vue GitHub repo."
  value       = aws_s3_bucket.frontend.bucket
}

output "frontend_deploy_role_arn" {
  description = "Set as AWS_DEPLOY_ROLE_ARN secret in the chat-vue GitHub repo."
  value       = aws_iam_role.frontend_deploy.arn
}
