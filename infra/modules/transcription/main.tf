locals {
  name = "transcription-${var.environment}"
}

data "aws_caller_identity" "current" {}

# ── GitHub Actions OIDC ───────────────────────────────────────────────────────

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_role" "worker_github_actions" {
  name = "${local.name}-worker-github-actions"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = data.aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/main"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "worker_github_actions" {
  name = "worker-github-actions-deploy"
  role = aws_iam_role.worker_github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ECRAuth"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid    = "ECRPush"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
        ]
        Resource = aws_ecr_repository.worker.arn
      },
      {
        Sid    = "ECSRead"
        Effect = "Allow"
        Action = [
          "ecs:DescribeTaskDefinition",
          "ecs:DescribeServices",
          "ecs:DescribeClusters",
        ]
        Resource = "*"
      },
      {
        Sid    = "ECSDeploy"
        Effect = "Allow"
        Action = [
          "ecs:RegisterTaskDefinition",
          "ecs:TagResource",
        ]
        Resource = "*"
      },
      {
        Sid      = "IAMPassRole"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = [aws_iam_role.worker_execution.arn, aws_iam_role.worker_task.arn]
        Condition = {
          StringLike = {
            "iam:PassedToService" = "ecs-tasks.amazonaws.com"
          }
        }
      },
    ]
  })
}

# ── S3 ────────────────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "audio" {
  bucket = "chat-audio-${var.environment}-${data.aws_caller_identity.current.account_id}"

  tags = { Environment = var.environment }
}

resource "aws_s3_bucket_public_access_block" "audio" {
  bucket = aws_s3_bucket.audio.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_cors_configuration" "audio" {
  bucket = aws_s3_bucket.audio.id

  cors_rule {
    allowed_origins = var.cors_allowed_origins
    allowed_methods = ["PUT"]
    allowed_headers = ["*"]
    max_age_seconds = 3600
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "audio" {
  bucket = aws_s3_bucket.audio.id

  rule {
    id     = "expire-audio-objects"
    status = "Enabled"

    filter {
      prefix = "audio/"
    }

    expiration {
      days = 30
    }
  }
}

# ── Sample audio objects ──────────────────────────────────────────────────────
# These files are uploaded once and never deleted; the lifecycle rule above only
# targets the audio/ prefix so the samples/ prefix is permanently retained.

resource "aws_s3_object" "sample_conversation" {
  bucket       = aws_s3_bucket.audio.id
  key          = "samples/conversation.wav"
  source       = "${var.sample_files_path}/conversation.wav"
  content_type = "audio/wav"
  etag         = filemd5("${var.sample_files_path}/conversation.wav")
}

resource "aws_s3_object" "sample_barry" {
  bucket       = aws_s3_bucket.audio.id
  key          = "samples/speakers/barry.wav"
  source       = "${var.sample_files_path}/barry.wav"
  content_type = "audio/wav"
  etag         = filemd5("${var.sample_files_path}/barry.wav")
}

resource "aws_s3_object" "sample_jane" {
  bucket       = aws_s3_bucket.audio.id
  key          = "samples/speakers/jane.wav"
  source       = "${var.sample_files_path}/jane.wav"
  content_type = "audio/wav"
  etag         = filemd5("${var.sample_files_path}/jane.wav")
}

# ── SQS ───────────────────────────────────────────────────────────────────────

resource "aws_sqs_queue" "dlq" {
  name                      = "transcription-dlq-${var.environment}"
  message_retention_seconds = 1209600 # 14 days

  tags = { Environment = var.environment }
}

resource "aws_sqs_queue" "main" {
  name                       = "transcription-${var.environment}"
  visibility_timeout_seconds = 600    # matches worker SQS_VISIBILITY_TIMEOUT
  message_retention_seconds  = 345600 # 4 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })

  tags = { Environment = var.environment }
}

# ── IAM: API task role ────────────────────────────────────────────────────────
# Adds transcription permissions to the existing chat-api ECS task role.

data "aws_iam_role" "api_task" {
  name = "chat-api-${var.environment}-task"
}

resource "aws_iam_role_policy" "api_transcription" {
  name = "transcription"
  role = data.aws_iam_role.api_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:DeleteObject",
        ]
        Resource = "${aws_s3_bucket.audio.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.audio.arn
      },
      {
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.main.arn
      },
      {
        Effect   = "Allow"
        Action   = "transcribe:StartTranscriptionJob"
        Resource = "*"
      },
      {
        Sid       = "GpuRunWorker"
        Effect    = "Allow"
        Action    = "ecs:RunTask"
        Resource  = "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:task-definition/${local.name}-worker:*"
        Condition = { ArnEquals = { "ecs:cluster" = var.ecs_cluster_id } }
      },
      {
        Sid       = "GpuReadTasks"
        Effect    = "Allow"
        Action    = ["ecs:ListTasks", "ecs:DescribeTasks"]
        Resource  = "*"
        Condition = { ArnEquals = { "ecs:cluster" = var.ecs_cluster_id } }
      },
      {
        Sid      = "GpuPassWorkerRoles"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = [aws_iam_role.worker_execution.arn, aws_iam_role.worker_task.arn]
        Condition = {
          StringLike = {
            "iam:PassedToService" = "ecs-tasks.amazonaws.com"
          }
        }
      },
      {
        Sid      = "GpuCostExplorer"
        Effect   = "Allow"
        Action   = "ce:GetCostAndUsage"
        Resource = "*"
      },
    ]
  })
}

# ── ECR: worker image registry ────────────────────────────────────────────────

resource "aws_ecr_repository" "worker" {
  name                 = "transcription-worker-${var.environment}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = { Environment = var.environment, CostCenter = "gpu" }
}

resource "aws_ecr_lifecycle_policy" "worker" {
  repository = aws_ecr_repository.worker.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 2 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 2
      }
      action = { type = "expire" }
    }]
  })
}

# ── IAM: ECS execution role ───────────────────────────────────────────────────

resource "aws_iam_role" "worker_execution" {
  name = "${local.name}-worker-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "worker_execution" {
  role       = aws_iam_role.worker_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "worker_execution_secrets" {
  name = "hf-token-secret"
  role = aws_iam_role.worker_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = compact([var.database_url_secret_arn, var.huggingface_token_secret_arn])
    }]
  })
}

# The policy used to be conditional on the HF token; it is now always present.
moved {
  from = aws_iam_role_policy.worker_execution_secrets[0]
  to   = aws_iam_role_policy.worker_execution_secrets
}

# ── IAM: ECS task role ────────────────────────────────────────────────────────

resource "aws_iam_role" "worker_task" {
  name = "${local.name}-worker-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "worker_task" {
  name = "worker-permissions"
  role = aws_iam_role.worker_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Effect = "Allow"
          Action = [
            "s3:GetObject",
            "s3:PutObject",
            "s3:DeleteObject",
          ]
          Resource = "${aws_s3_bucket.audio.arn}/*"
        },
        {
          Effect   = "Allow"
          Action   = "s3:ListBucket"
          Resource = aws_s3_bucket.audio.arn
        },
        {
          Effect = "Allow"
          Action = [
            "sqs:ReceiveMessage",
            "sqs:DeleteMessage",
            "sqs:GetQueueAttributes",
            "sqs:ChangeMessageVisibility",
          ]
          Resource = aws_sqs_queue.main.arn
        },
        {
          Effect   = "Allow"
          Action   = "transcribe:GetTranscriptionJob"
          Resource = "*"
        },
        {
          Effect   = "Allow"
          Action   = "cloudwatch:PutMetricData"
          Resource = "*"
        },
        {
          Effect = "Allow"
          Action = [
            "ssmmessages:CreateControlChannel",
            "ssmmessages:CreateDataChannel",
            "ssmmessages:OpenControlChannel",
            "ssmmessages:OpenDataChannel",
          ]
          Resource = "*"
        },
      ],
      var.huggingface_token_secret_arn != "" ? [{
        Sid      = "HFTokenSecret"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = var.huggingface_token_secret_arn
      }] : []
    )
  })
}

# ── CloudWatch logs ───────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/transcription-worker-${var.environment}"
  retention_in_days = 30

  tags = { Environment = var.environment }
}

# ── DLQ alarm ─────────────────────────────────────────────────────────────────

resource "aws_sns_topic" "dlq_alarm" {
  count = var.alarm_email != "" ? 1 : 0
  name  = "transcription-dlq-alarm-${var.environment}"

  tags = { Environment = var.environment }
}

resource "aws_sns_topic_subscription" "dlq_alarm_email" {
  count     = var.alarm_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.dlq_alarm[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  count               = var.alarm_email != "" ? 1 : 0
  alarm_name          = "transcription-dlq-not-empty-${var.environment}"
  alarm_description   = "One or more SQS messages landed in the transcription DLQ after exhausting retries."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dlq.name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.dlq_alarm[0].arn]
  ok_actions          = [aws_sns_topic.dlq_alarm[0].arn]

  tags = { Environment = var.environment }
}

# ── ECS: worker task definition ──────────────────────────────────────────────
# No service, no ASG: the API task role RunTasks this on demand onto the
# shared GPU capacity pool (modules/gpu-capacity, owned by the prod
# environment). CI (worker.yml) registers new revisions with image_tag.

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-worker"
  network_mode             = "bridge"
  requires_compatibilities = ["EC2"]
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.worker_execution.arn
  task_role_arn            = aws_iam_role.worker_task.arn

  container_definitions = jsonencode([{
    name      = "transcription-worker"
    image     = "${aws_ecr_repository.worker.repository_url}:${var.image_tag}"
    essential = true

    resourceRequirements = [{
      type  = "GPU"
      value = "1"
    }]

    environment = [
      { name = "AUDIO_BUCKET_NAME", value = aws_s3_bucket.audio.bucket },
      { name = "TRANSCRIBE_SQS_QUEUE_URL", value = aws_sqs_queue.main.url },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "DEV_CAPTURE_FIXTURES_S3_PREFIX", value = "dev-fixtures" },
      { name = "IDLE_EXIT_SECONDS", value = tostring(var.idle_exit_seconds) },
      { name = "MAX_LIFETIME_SECONDS", value = tostring(var.max_lifetime_seconds) },
    ]

    secrets = concat(
      [{ name = "DATABASE_URL", valueFrom = var.database_url_secret_arn }],
      var.huggingface_token_secret_arn != "" ? [
        { name = "HUGGINGFACE_TOKEN", valueFrom = var.huggingface_token_secret_arn }
      ] : []
    )

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
