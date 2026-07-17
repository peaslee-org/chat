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
          "ecs:UpdateService",
        ]
        Resource = "*"
      },
      {
        Sid      = "IAMPassRole"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = "*"
        Condition = {
          StringLike = {
            "iam:PassedToService" = "ecs-tasks.amazonaws.com"
          }
        }
      },
      {
        Sid      = "S3PauseFlag"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.audio.arn}/worker_paused"
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

# ── Pause flag ────────────────────────────────────────────────────────────────
# Permanent object; content ("true"/"false") is managed at runtime by
# transcription-worker.sh and the worker CI/CD workflow. Terraform only
# creates it once — ignore_changes prevents any plan from resetting it.

resource "aws_s3_object" "worker_paused" {
  bucket       = aws_s3_bucket.audio.id
  key          = "worker_paused"
  content      = "false"
  content_type = "text/plain"

  lifecycle {
    ignore_changes = [content, etag]
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
  visibility_timeout_seconds = 600   # matches worker SQS_VISIBILITY_TIMEOUT
  message_retention_seconds  = 86400 # 24 hours

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

  tags = { Environment = var.environment }
}

resource "aws_ecr_lifecycle_policy" "worker" {
  repository = aws_ecr_repository.worker.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
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
  count = var.huggingface_token_secret_arn != "" ? 1 : 0
  name  = "hf-token-secret"
  role  = aws_iam_role.worker_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = var.huggingface_token_secret_arn
    }]
  })
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

# ── Security group ────────────────────────────────────────────────────────────

resource "aws_security_group" "worker" {
  name        = "${local.name}-worker"
  description = "Transcription worker outbound-only (S3, SQS, Transcribe, RDS, CloudWatch)"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Environment = var.environment }
}

# ── IAM: EC2 instance role (ECS agent) ───────────────────────────────────────

resource "aws_iam_role" "ec2_instance" {
  name = "${local.name}-ec2-instance"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ec2_ecs_agent" {
  role       = aws_iam_role.ec2_instance.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_role_policy_attachment" "ec2_ssm" {
  role       = aws_iam_role.ec2_instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ec2_instance" {
  name = "${local.name}-ec2-instance"
  role = aws_iam_role.ec2_instance.name
}

# ── EC2: GPU Spot launch template + ASG ───────────────────────────────────────

resource "aws_launch_template" "worker_gpu" {
  name_prefix   = "${local.name}-worker-gpu-"
  image_id      = var.worker_ami_id
  instance_type = "g4dn.xlarge"

  # ECS GPU AMI default is 30 GB — too small for a 6.87 GB compressed CUDA/ML
  # image (~20 GB extracted) plus OS + ECS agent + space for the previous image
  # during rolling deploys. 80 GB gives comfortable headroom.
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = 80
      volume_type           = "gp3"
      delete_on_termination = true
    }
  }

  iam_instance_profile {
    arn = aws_iam_instance_profile.ec2_instance.arn
  }

  network_interfaces {
    associate_public_ip_address = true
    security_groups             = [aws_security_group.worker.id]
  }

  user_data = base64encode(join("\n", [
    "#!/bin/bash",
    "echo ECS_CLUSTER=chat-api-${var.environment} >> /etc/ecs/ecs.config",
    "echo ECS_ENABLE_GPU_SUPPORT=true >> /etc/ecs/ecs.config",
  ]))

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name        = "${local.name}-worker-gpu"
      Environment = var.environment
    }
  }

  tags = { Environment = var.environment }
}

resource "aws_autoscaling_group" "worker_gpu" {
  name                = "${local.name}-worker-gpu"
  desired_capacity    = 1
  min_size            = 0
  max_size            = 1
  vpc_zone_identifier = var.subnet_ids

  mixed_instances_policy {
    instances_distribution {
      on_demand_base_capacity                  = 0
      on_demand_percentage_above_base_capacity = 0
      spot_allocation_strategy                 = "lowest-price"
    }
    launch_template {
      launch_template_specification {
        launch_template_id = aws_launch_template.worker_gpu.id
        version            = "$Latest"
      }
    }
  }

  tag {
    key                 = "AmazonECSManaged"
    value               = true
    propagate_at_launch = true
  }

  tag {
    key                 = "Environment"
    value               = var.environment
    propagate_at_launch = true
  }

  wait_for_capacity_timeout = "0"

  lifecycle {
    create_before_destroy = true
    # desired_capacity is managed externally via transcription-worker.sh — never let Terraform touch it.
    ignore_changes = [desired_capacity]
  }
}

# ── ECS: worker task definition + service ────────────────────────────────────

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
    image     = "${aws_ecr_repository.worker.repository_url}:latest"
    essential = true

    resourceRequirements = [{
      type  = "GPU"
      value = "1"
    }]

    environment = [
      { name = "DATABASE_URL", value = var.database_url },
      { name = "AUDIO_BUCKET_NAME", value = aws_s3_bucket.audio.bucket },
      { name = "TRANSCRIBE_SQS_QUEUE_URL", value = aws_sqs_queue.main.url },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "DEV_CAPTURE_FIXTURES_S3_PREFIX", value = "dev-fixtures" },
    ]

    secrets = var.huggingface_token_secret_arn != "" ? [
      { name = "HUGGINGFACE_TOKEN", valueFrom = var.huggingface_token_secret_arn }
    ] : []

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.worker.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])

  tags = { Environment = var.environment }
}

resource "aws_ecs_service" "worker" {
  name            = "${local.name}-worker"
  cluster         = var.ecs_cluster_id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "EC2"

  # Single GPU instance: stop old task before starting new one.
  # AZ rebalancing must be disabled — it blocks maximumPercent <= 100.
  availability_zone_rebalancing      = "DISABLED"
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
  enable_execute_command             = true

  depends_on = [aws_autoscaling_group.worker_gpu]

  lifecycle {
    ignore_changes = [task_definition]
  }

  tags = { Environment = var.environment }
}
