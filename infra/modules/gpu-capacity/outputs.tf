output "capacity_provider_name" {
  value = aws_ecs_capacity_provider.gpu.name
}

output "asg_name" {
  value = aws_autoscaling_group.gpu.name
}

output "security_group_id" {
  value = aws_security_group.gpu.id
}

output "instance_profile_name" {
  value = aws_iam_instance_profile.instance.name
}

output "instance_role_arn" {
  value = aws_iam_role.instance.arn
}
