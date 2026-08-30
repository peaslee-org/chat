# Service Quotas

*Track limits that have been hit or are approaching. Update this table when you request an
increase or hit a throttle.*

| Service | Limit | Where we are | Notes |
|---|---|---|---|
| EC2 — On-Demand G and VT instances (vCPUs) | 8 vCPUs | 2 × `g4dn.xlarge` (4 vCPU each) = the whole quota | `gpu_max_size = 2` is set to match. A third instance, or a `g4dn.2xlarge` alongside an `xlarge`, needs a quota increase first. |
| EC2 — Spot G and VT instances (vCPUs) | 8 vCPUs | same | Spot placement scores for `g4dn.xlarge` in us-east-1 have been poor (frequent `InsufficientInstanceCapacity`); the pool runs `gpu_on_demand_percentage = 100` until they recover, and the AMI bake uses `BAKE_MARKET=on-demand`. |
| ECS managed scaling | — | launches 2 instances for 1 task from zero | Observed repeatedly; the spare idles ~10 min then scales in. Not a quota — a capacity-provider estimate quirk (`docs/TODO.md`). |
| ECS managed scale-in | — | ~15 min after the worker exits | 15 consecutive low datapoints; it is also the "warm start" window the GPU estimate uses (`gpu_scale_in_seconds`). |
| Bedrock — Claude 3 Sonnet | requests / tokens per minute | not measured | Single-user load; watch `AWS/Bedrock` throttles if it ever matters. |
| AWS Transcribe | 250 concurrent jobs (default) | far below | |
| SQS | 120 000 in-flight messages (standard) | far below | Queues hold at most a handful of jobs. |
| Secrets Manager / Cognito | defaults | far below | |
