output "alb_dns_name" {
  description = "Point chat.example.com CNAME to this value in your DNS provider."
  value       = aws_lb.this.dns_name
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  value = aws_ecs_service.this.name
}

output "task_definition_family" {
  value = aws_ecs_task_definition.this.family
}

output "task_security_group_id" {
  value = aws_security_group.tasks.id
}
