# Service Quotas

*Track limits that have been hit or are approaching.*

| Service | Limit | Current Usage | Notes |
|---|---|---|---|
| Bedrock — claude-3-sonnet | Requests per minute (RPM) | — | Monitor via CloudWatch |
| AWS Transcribe | Concurrent jobs | — | Default 250; unlikely to hit |
| ECS Fargate GPU | Tasks per region | — | GPU Fargate availability can be constrained |
| SQS | Messages in flight | — | 120,000 for standard queues |

*Update this table when you request a quota increase or hit a throttle.*
