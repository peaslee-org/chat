output "repository_url" {
  description = "Full ECR repository URL (registry/name) for docker push."
  value       = aws_ecr_repository.this.repository_url
}

output "repository_name" {
  value = aws_ecr_repository.this.name
}
