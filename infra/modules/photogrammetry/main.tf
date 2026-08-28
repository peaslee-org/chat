locals {
  name = "photogrammetry-${var.environment}"
}

data "aws_caller_identity" "current" {}
data "aws_iam_openid_connect_provider" "github" { url = "https://token.actions.githubusercontent.com" }
data "aws_iam_role" "api_task" { name = "chat-api-${var.environment}-task" }
data "aws_sns_topic" "gpu_alerts" { name = "gpu-${var.environment}-alerts" }

# ── SQS ───────────────────────────────────────────────────────────────────────
resource "aws_sqs_queue" "dlq" {
  name                      = "${local.name}-dlq"
  message_retention_seconds = 1209600
  tags                      = { Environment = var.environment, CostCenter = "gpu" }
}

resource "aws_sqs_queue" "main" {
  name                       = local.name
  visibility_timeout_seconds = 600
  message_retention_seconds  = 345600
  redrive_policy             = jsonencode({ deadLetterTargetArn = aws_sqs_queue.dlq.arn, maxReceiveCount = 5 })
  tags                       = { Environment = var.environment, CostCenter = "gpu" }
}

# ── ECR ───────────────────────────────────────────────────────────────────────
resource "aws_ecr_repository" "worker" {
  name                 = "${local.name}-worker"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration { scan_on_push = true }
  tags = { Environment = var.environment, CostCenter = "gpu" }
}

resource "aws_ecr_lifecycle_policy" "worker" {
  repository = aws_ecr_repository.worker.name
  policy = jsonencode({ rules = [{
    rulePriority = 1, description = "Keep last 2 images",
    selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 2 },
    action       = { type = "expire" }
  }] })
}

# ── IAM: execution + task roles ───────────────────────────────────────────────
resource "aws_iam_role" "worker_execution" {
  name = "${local.name}-worker-execution"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
  Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}

resource "aws_iam_role_policy_attachment" "worker_execution" {
  role       = aws_iam_role.worker_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "worker_execution_secrets" {
  name = "db-secret"
  role = aws_iam_role.worker_execution.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
  Effect = "Allow", Action = "secretsmanager:GetSecretValue", Resource = var.database_url_secret_arn }] })
}

resource "aws_iam_role" "worker_task" {
  name = "${local.name}-worker-task"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
  Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}

resource "aws_iam_role_policy" "worker_task" {
  name = "worker-permissions"
  role = aws_iam_role.worker_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"],
      Resource = ["${var.audio_bucket_arn}/photogrammetry/*", "${var.audio_bucket_arn}/samples/photogrammetry/*"] },
      { Effect = "Allow", Action = "s3:ListBucket", Resource = var.audio_bucket_arn,
      Condition = { StringLike = { "s3:prefix" = ["photogrammetry/*", "samples/photogrammetry/*"] } } },
      { Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"],
      Resource = aws_sqs_queue.main.arn },
    ]
  })
}

# ── IAM: GitHub Actions deploy role ───────────────────────────────────────────
resource "aws_iam_role" "worker_github_actions" {
  name = "${local.name}-worker-github-actions"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn },
    Action = "sts:AssumeRoleWithWebIdentity",
    Condition = {
      StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
      StringLike   = { "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/main" }
  } }] })
}

resource "aws_iam_role_policy" "worker_github_actions" {
  name = "worker-github-actions-deploy"
  role = aws_iam_role.worker_github_actions.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "ECRAuth", Effect = "Allow", Action = "ecr:GetAuthorizationToken", Resource = "*" },
      { Sid = "ECRPush", Effect = "Allow", Resource = aws_ecr_repository.worker.arn,
        Action = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage",
      "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"] },
      { Sid = "ECSRead", Effect = "Allow", Action = ["ecs:DescribeTaskDefinition"], Resource = "*" },
      { Sid = "ECSDeploy", Effect = "Allow", Action = ["ecs:RegisterTaskDefinition", "ecs:TagResource"], Resource = "*" },
      { Sid      = "IAMPassRole", Effect = "Allow", Action = "iam:PassRole",
        Resource = [aws_iam_role.worker_execution.arn, aws_iam_role.worker_task.arn],
      Condition = { StringLike = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } } },
    ]
  })
}

# ── IAM: let the API RunTask this family ──────────────────────────────────────
# ecs:ListTasks/DescribeTasks for the launcher's status poll are granted unscoped by
# the transcription module's inline policy on this same role (api_transcription);
# this module relies on it.
resource "aws_iam_role_policy" "api_photogrammetry" {
  name = "photogrammetry"
  role = data.aws_iam_role.api_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid      = "GpuRunWorker", Effect = "Allow", Action = "ecs:RunTask",
        Resource = "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:task-definition/${local.name}-worker:*",
      Condition = { ArnEquals = { "ecs:cluster" = var.ecs_cluster_arn } } },
      { Sid      = "GpuPassWorkerRoles", Effect = "Allow", Action = "iam:PassRole",
        Resource = [aws_iam_role.worker_execution.arn, aws_iam_role.worker_task.arn],
      Condition = { StringLike = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } } },
      { Sid = "GpuTagTasks", Effect = "Allow", Action = "ecs:TagResource", Resource = "*",
      Condition = { StringEquals = { "ecs:CreateAction" = "RunTask" } } },
      { Sid = "PublishJobs", Effect = "Allow", Action = "sqs:SendMessage", Resource = aws_sqs_queue.main.arn },
    ]
  })
}

# ── Logs, alarm ───────────────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${local.name}-worker"
  retention_in_days = 30
  tags              = { Environment = var.environment, CostCenter = "gpu" }
}

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  alarm_name          = "${local.name}-dlq-not-empty"
  alarm_description   = "A photogrammetry job message landed in the DLQ after exhausting retries."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dlq.name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.gpu_alerts.arn]
  ok_actions          = [data.aws_sns_topic.gpu_alerts.arn]
  tags                = { Environment = var.environment, CostCenter = "gpu" }
}

# ── ECS task definition (no service; the API RunTasks it onto gpu-<env>) ─────
resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-worker"
  network_mode             = "bridge"
  requires_compatibilities = ["EC2"]
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.worker_execution.arn
  task_role_arn            = aws_iam_role.worker_task.arn

  # Job scratch lives on the instance, not in the container layer: a worker that is OOM-killed is
  # replaced on the same instance and resumes from its stage markers (spec 2026-08-28 §2).
  volume {
    name      = "scratch"
    host_path = "/var/lib/photogrammetry"
  }

  container_definitions = jsonencode([{
    name                 = "photogrammetry-worker"
    image                = "${aws_ecr_repository.worker.repository_url}:${var.image_tag}"
    essential            = true
    resourceRequirements = [{ type = "GPU", value = "1" }]
    mountPoints          = [{ sourceVolume = "scratch", containerPath = "/tmp/pg", readOnly = false }]
    environment = [
      { name = "AUDIO_BUCKET_NAME", value = var.audio_bucket_name },
      { name = "PHOTOGRAMMETRY_SQS_QUEUE_URL", value = aws_sqs_queue.main.url },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "IDLE_EXIT_SECONDS", value = tostring(var.idle_exit_seconds) },
      { name = "MAX_LIFETIME_SECONDS", value = tostring(var.max_lifetime_seconds) },
      { name = "PHOTOGRAMMETRY_JOB_TIMEOUT_SECONDS", value = tostring(var.job_timeout_seconds) },
      # Same value as the mountPoints containerPath above — one place defines the mount path and
      # the worker's WORK_DIR, rather than relying on the worker's config.py default to agree.
      { name = "WORK_DIR", value = "/tmp/pg" },
    ]
    secrets = [{ name = "DATABASE_URL", valueFrom = var.database_url_secret_arn }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.worker.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])

  tags = { Environment = var.environment, CostCenter = "gpu" }
}
