# Service Quotas

*Track limits that have been hit or are approaching.*

| Service | Limit | Current Usage | Notes |
|---|---|---|---|
| Bedrock — claude-3-sonnet | Requests per minute (RPM) | — | Monitor via CloudWatch |
| AWS Transcribe | Concurrent jobs | — | Default 250; unlikely to hit |
| EC2 Spot — G/VT instances (`g4dn.xlarge`) | Spot request vCPU limit | — | GPU spot capacity can be constrained; `gpu-<env>` ASG only scales 0–2 |
| SQS | Messages in flight | — | 120,000 for standard queues |

*Update this table when you request a quota increase or hit a throttle.*
