locals {
  name = "gpu-${var.environment}"
  tags = {
    Environment        = var.environment
    (var.cost_tag_key) = var.cost_tag_value
  }
}

# ── network ────────────────────────────────────────────────────────────────

resource "aws_security_group" "gpu" {
  name        = local.name
  description = "Shared GPU capacity instances - egress only" # ASCII only: EC2 rejects other characters
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, { Name = local.name })
}

# ── instance role ─────────────────────────────────────────────────────────

resource "aws_iam_role" "instance" {
  name = "${local.name}-instance"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "ecs_agent" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "instance" {
  name = "${local.name}-instance"
  role = aws_iam_role.instance.name
}

# ── launch template ──────────────────────────────────────────────────────

resource "aws_launch_template" "gpu" {
  name_prefix   = "${local.name}-"
  image_id      = var.ami_id
  instance_type = var.instance_type

  iam_instance_profile {
    arn = aws_iam_instance_profile.instance.arn
  }

  network_interfaces {
    associate_public_ip_address = true
    security_groups             = [aws_security_group.gpu.id]
  }

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = var.root_volume_gb
      volume_type           = "gp3"
      delete_on_termination = true
    }
  }

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2 # bridge-mode containers reach IMDS through one hop
  }

  user_data = base64encode(join("\n", [
    "#!/bin/bash",
    "echo ECS_CLUSTER=${var.cluster_name} >> /etc/ecs/ecs.config",
    "echo ECS_ENABLE_GPU_SUPPORT=true >> /etc/ecs/ecs.config",
    "echo ECS_ENABLE_SPOT_INSTANCE_DRAINING=true >> /etc/ecs/ecs.config",
  ]))

  tag_specifications {
    resource_type = "instance"
    tags          = merge(local.tags, { Name = local.name })
  }

  tag_specifications {
    resource_type = "volume"
    tags          = local.tags
  }

  tags = local.tags
}

# ── ASG (ECS managed scaling owns desired_capacity) ────────────────────────

resource "aws_autoscaling_group" "gpu" {
  name_prefix               = "${local.name}-"
  min_size                  = 0
  max_size                  = var.max_size
  vpc_zone_identifier       = var.subnet_ids
  protect_from_scale_in     = true # required by managed termination protection
  wait_for_capacity_timeout = "0"

  metrics_granularity = "1Minute"
  enabled_metrics     = ["GroupInServiceInstances"]

  mixed_instances_policy {
    instances_distribution {
      on_demand_base_capacity                  = 0
      on_demand_percentage_above_base_capacity = var.on_demand_percentage
      # capacity-optimized picks the pool most likely to have capacity; lowest-price with 2 pools
      # kept choosing AZs with none (2026-08-26). spot_instance_pools only applies to lowest-price.
      spot_allocation_strategy = var.spot_allocation_strategy
      spot_instance_pools      = var.spot_allocation_strategy == "lowest-price" ? 2 : 0 # provider default is 2; AWS requires 0 for other strategies
    }
    launch_template {
      launch_template_specification {
        launch_template_id = aws_launch_template.gpu.id
        version            = "$Latest"
      }
      # Several GPU types widen the spot pools; the worker's CUDA image runs on any of them.
      # Order = priority for on-demand; capacity-optimized ignores order for spot.
      dynamic "override" {
        for_each = var.instance_types
        content {
          instance_type = override.value
        }
      }
    }
  }

  tag {
    key                 = "AmazonECSManaged"
    value               = ""
    propagate_at_launch = true
  }

  tag {
    key                 = "Name"
    value               = local.name
    propagate_at_launch = true
  }

  tag {
    key                 = "Environment"
    value               = var.environment
    propagate_at_launch = true
  }

  tag {
    key                 = var.cost_tag_key
    value               = var.cost_tag_value
    propagate_at_launch = true
  }

  lifecycle {
    create_before_destroy = true
    ignore_changes        = [desired_capacity]
  }
}

# ── capacity provider ───────────────────────────────────────────────────────

resource "aws_ecs_capacity_provider" "gpu" {
  name = local.name

  auto_scaling_group_provider {
    auto_scaling_group_arn         = aws_autoscaling_group.gpu.arn
    managed_termination_protection = "ENABLED"

    managed_scaling {
      status                    = "ENABLED"
      target_capacity           = 100
      minimum_scaling_step_size = 1
      maximum_scaling_step_size = 1
      instance_warmup_period    = 300
    }
  }

  tags = local.tags
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = var.cluster_name
  capacity_providers = [aws_ecs_capacity_provider.gpu.name]
  # No default strategy: the Fargate API service keeps launch_type = FARGATE; GPU tenants name gpu-<env> explicitly.
}

# ── alerting (all gated on alert_email) ─────────────────────────────────────

resource "aws_sns_topic" "gpu" {
  count = var.alert_email != "" ? 1 : 0
  name  = "${local.name}-alerts"
  tags  = local.tags
}

resource "aws_sns_topic_subscription" "gpu_email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.gpu[0].arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "running_4h" {
  count             = var.alert_email != "" ? 1 : 0
  alarm_name        = "${local.name}-instance-running-4h"
  alarm_description = "A GPU instance has been in service for 4 consecutive hours"

  namespace   = "AWS/AutoScaling"
  metric_name = "GroupInServiceInstances"
  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.gpu.name
  }
  statistic           = "Minimum"
  period              = 3600
  evaluation_periods  = 4
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.gpu[0].arn]

  tags = local.tags
}

resource "aws_budgets_budget" "gpu" {
  count             = var.alert_email != "" ? 1 : 0
  name              = "${local.name}-monthly"
  budget_type       = "COST"
  limit_amount      = tostring(var.budget_actual_usd)
  limit_unit        = "USD"
  time_unit         = "MONTHLY"
  time_period_start = var.budget_start

  cost_filter {
    name = "TagKeyValue"
    # AWS Budgets tag filter format is "user:<Key>$<Value>"; format() avoids HCL's $${ escape trap.
    values = [format("user:%s$%s", var.cost_tag_key, var.cost_tag_value)]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100 * var.budget_forecast_usd / var.budget_actual_usd
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
