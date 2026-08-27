output "queue_url" {
  value       = aws_sqs_queue.main.url
  description = "SQS queue URL for photogrammetry job messages."
}

output "dlq_url" {
  value       = aws_sqs_queue.dlq.url
  description = "Dead-letter queue URL."
}

output "worker_ecr_url" {
  value       = aws_ecr_repository.worker.repository_url
  description = "ECR repository URL for the photogrammetry worker image."
}

output "worker_github_actions_role_arn" {
  value       = aws_iam_role.worker_github_actions.arn
  description = "IAM role ARN for GitHub Actions to assume when deploying the worker."
}

output "worker_task_family" {
  value       = aws_ecs_task_definition.worker.family
  description = "ECS task definition family for the worker (used by the API's RunTask call)."
}
