# Networking

*Populate with actual IDs from Terraform state / AWS console.*

| Resource | ID / CIDR | Notes |
|---|---|---|
| VPC | (see TF output `vpc_id`) | All ECS tasks and RDS run here |
| Private subnets | (see TF output `private_subnet_ids`) | ECS tasks, RDS |
| Public subnets | (see TF output `public_subnet_ids`) | ALB (if any), NAT gateway |
| RDS security group | (see TF output) | Allows inbound 5432 from ECS task SGs only |
| ECS security group | (see TF output) | Allows outbound HTTPS; inbound from ALB |

## Access Pattern

RDS is private — no direct internet access. To query from a local machine:

```bash
# ECS exec into the chat-api task (see root CLAUDE.md for full command)
aws ecs execute-command --cluster chat-api-prod --task <TASK_ARN> \
  --container chat-api --interactive --command "python3 -c ..."
```
