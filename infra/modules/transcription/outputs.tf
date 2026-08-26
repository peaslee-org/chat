output "bucket_name" {
  value       = aws_s3_bucket.audio.bucket
  description = "S3 bucket name for audio uploads and transcription output."
}

output "queue_url" {
  value       = aws_sqs_queue.main.url
  description = "SQS queue URL for transcription job messages."
}

output "dlq_url" {
  value       = aws_sqs_queue.dlq.url
  description = "Dead-letter queue URL."
}

output "worker_ecr_url" {
  value       = aws_ecr_repository.worker.repository_url
  description = "ECR repository URL for the transcription worker image."
}

output "worker_github_actions_role_arn" {
  value       = aws_iam_role.worker_github_actions.arn
  description = "IAM role ARN for GitHub Actions to assume when deploying the worker."
}

output "worker_task_family" {
  value       = aws_ecs_task_definition.worker.family
  description = "ECS task definition family for the worker (used by the API's RunTask call)."
}

output "worker_task_role_arn" {
  value       = aws_iam_role.worker_task.arn
  description = "IAM role ARN assumed by the worker task at runtime."
}

output "worker_execution_role_arn" {
  value       = aws_iam_role.worker_execution.arn
  description = "IAM role ARN used by ECS to pull the image and inject secrets for the worker task."
}
