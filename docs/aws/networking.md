# Networking

Everything lives in the account's **default VPC** (`172.31.0.0/16`, six public subnets, one per
AZ, internet gateway, no NAT, no private subnets). Ids are on the private docs track
(`docs/private/aws-vpc-config.md`); placeholders below.

| Resource | Id | Notes |
|---|---|---|
| VPC | `vpc-00000000000000002` | AWS default VPC, tagged `peaslee-org` |
| Subnets | `subnet-0000000000000000a…f` | Public, `MapPublicIpOnLaunch`. API tasks are pinned to one AZ (`task_subnet_ids`) to sit next to the single-AZ database host; the ALB spans two; GPU instances may use any |
| ALB SG `chat-api-prod-alb` | `sg-00000000000000001` | 80/443 from the internet (CloudFront); listener rules drop requests without the CloudFront secret header |
| Tasks SG `chat-api-prod-tasks` | `sg-00000000000000002` | 8000 from the ALB SG only; all egress |
| GPU SG `gpu-prod` | `sg-00000000000000004` | No inbound; all egress (S3, SQS, ECR, Secrets Manager, CloudWatch over the public internet) |
| Database host | self-hosted EC2 (not in this Terraform) | PostgreSQL 16 + pgvector on 5432, reachable inside the VPC from the tasks and GPU SGs |

Traffic paths:

```
Internet → CloudFront → ALB (HTTPS, secret header) → chat-api task :8000 → PostgreSQL :5432 (VPC)
GPU instance (ASG gpu-prod) → SQS / S3 / ECR / Secrets Manager / CloudWatch  (public endpoints)
                             → PostgreSQL :5432 (VPC)
```

No VPC endpoints are defined by this Terraform; AWS-service traffic leaves via the internet
gateway (public IPs on every task and instance).

## Reaching things

**API container** — ECS exec is enabled on the service:

```bash
aws ecs execute-command --cluster chat-api-prod --task <task-id> --container chat-api \
  --interactive --command /bin/sh
# psql is not installed; query with python + asyncpg using $DATABASE_URL
```

**GPU worker** — the worker task has no exec. Use SSM Session Manager to the instance
(`scripts/deploy/gpu-status.sh` prints the instance id; the instance profile carries
`AmazonSSMManagedInstanceCore`), then `docker ps` / `docker logs` on the host. Logs are also in
`/ecs/photogrammetry-prod-worker` and `/ecs/transcription-worker-prod`.

**Database** — from the API container (above), or from the database host itself.
