# AWS VPC Configuration

> Region: `us-east-1` | Account: `123456789012` | Snapshot: 2026-03-13

---

## VPCs

| Name | VPC ID | CIDR | Default? |
|---|---|---|---|
| `chat-api-prod` | `vpc-00000000000000001` | `10.0.0.0/16` | No |
| _(AWS default)_ | `vpc-00000000000000002` | `172.31.0.0/16` | Yes |

Production app resources live in `chat-api-prod`. The default VPC hosts two EC2 instances — a Mail-in-a-Box mail server and a general web application server.

---

## Subnets

Both subnets are **public** (`MapPublicIpOnLaunch: true`). There are **no private subnets** and **no NAT gateway** — all ECS tasks (API + transcription worker) run in public subnets and reach the internet directly via the IGW.

| Name | Subnet ID | AZ | CIDR | Available IPs |
|---|---|---|---|---|
| `chat-api-prod-public-1` | `subnet-00000000000000001` | `us-east-1a` | `10.0.0.0/24` | 249 |
| `chat-api-prod-public-2` | `subnet-00000000000000002` | `us-east-1b` | `10.0.1.0/24` | 247 |

---

## Internet Gateway

`igw-00000000000000001` — attached and available.

---

## Route Tables

| Name | ID | Subnets | Routes |
|---|---|---|---|
| `chat-api-prod-public` | `rtb-00000000000000001` | public-1, public-2 | `10.0.0.0/16 → local`, `0.0.0.0/0 → IGW` |
| _(main, untagged)_ | `rtb-00000000000000002` | implicit (main) | `10.0.0.0/16 → local` only |

The main table has no internet route — it acts as a safe default for any subnet not explicitly associated.

---

## Security Groups

### `chat-api-prod-alb` (`sg-00000000000000001`)
ALB — public-facing load balancer.

| Direction | Port | Source/Dest |
|---|---|---|
| Inbound | 80 (TCP) | `0.0.0.0/0` |
| Inbound | 443 (TCP) | `0.0.0.0/0` |
| Outbound | All | `0.0.0.0/0` |

### `chat-api-prod-tasks` (`sg-00000000000000002`)
ECS tasks for `chat-api`. Inbound locked to traffic from the ALB only.

| Direction | Port | Source/Dest |
|---|---|---|
| Inbound | 8000 (TCP) | `sg-00000000000000001` (ALB SG) |
| Outbound | All | `0.0.0.0/0` |

### `chat-api-prod-rds` (`sg-00000000000000003`)
RDS PostgreSQL. Only reachable from within the VPC CIDR — not from the public internet.

| Direction | Port | Source/Dest |
|---|---|---|
| Inbound | 5432 (TCP) | `10.0.0.0/16` |
| Outbound | All | `0.0.0.0/0` |

### `transcription-prod-worker` (`sg-00000000000000004`)
Transcription worker ECS tasks. No inbound rules — worker is purely outbound (polls SQS, writes to S3, calls AWS Transcribe, writes to RDS, logs to CloudWatch).

| Direction | Port | Source/Dest |
|---|---|---|
| Inbound | None | — |
| Outbound | All | `0.0.0.0/0` |

### `default` (`sg-00000000000000005`)
Default SG. Has an inbound rule allowing NFS (port 2049) from the `chat-api-prod-tasks` SG — indicates EFS may be mounted by API tasks.

| Direction | Port | Source/Dest |
|---|---|---|
| Inbound | All | Self (`sg-00000000000000005`) |
| Inbound | 2049 (NFS/EFS) | `sg-00000000000000002` (tasks SG) |
| Outbound | All | `0.0.0.0/0` |

---

## Network ACLs

Single default NACL (`acl-00000000000000001`) applied to both subnets. Effectively open — all traffic allowed inbound and outbound at rule 100. Access control is enforced exclusively at the security group layer.

---

## Notable Observations

1. **No private subnets / no NAT gateway.** RDS and ECS tasks all sit in public subnets. The RDS SG restricts PostgreSQL to `10.0.0.0/16` so it isn't directly reachable from the internet, but the instance itself has a public IP. Adding a private subnet + NAT gateway would be a defence-in-depth improvement.

2. **No VPC endpoints.** Traffic to S3, SQS, ECR, Bedrock, Secrets Manager, and CloudWatch all traverses the public internet (via IGW). VPC endpoints (Gateway type for S3/DynamoDB; Interface type for the rest) would keep that traffic on the AWS backbone, reduce data transfer cost, and tighten the network perimeter.

3. **EFS mount suspected.** The NFS inbound rule on the default SG from `chat-api-prod-tasks` suggests an EFS file system may be in use by the API. Not reflected in the current Terraform docs — worth verifying.

4. **Dual-AZ subnets.** Public subnets span `us-east-1a` and `us-east-1b`, providing AZ redundancy for the ALB and ECS services.

---

---

# Default VPC (`vpc-00000000000000002`, `172.31.0.0/16`)

> AWS-managed default VPC. Hosts two EC2 instances — a Mail-in-a-Box mail server and a general-purpose web application server.

---

## EC2 Instances

| Name | Instance ID | Type | AZ | Public IP | Key Pair | IAM Profile | Launched |
|---|---|---|---|---|---|---|---|
| `MailServerInstance` | `i-00000000000000001` | t2.micro | us-east-1b | `203.0.113.10` | `mailserver` | `MailInABoxInstanceProfile` | 2024-01-11 (rebuilt 2024-05-23) |
| `WebAppServer_Instance` | `i-00000000000000002` | t2.small | us-east-1b | `203.0.113.11` | `Web Application Server` | `chat-server` | 2024-06-27 |

Both instances are in the same subnet (`subnet-00000000000000003`, `172.31.16.0/20`, us-east-1b). The mail server was deployed via a CloudFormation stack (`example-mailserver`).

**IMDSv2 posture:**
- Mail server: `HttpTokens: required` — IMDSv2 enforced (fixed 2026-03-13).
- Web app server: `HttpTokens: required` — IMDSv2 enforced (good).

---

## Subnets

### Public (default, `MapPublicIpOnLaunch: true`)

Six AWS-default public subnets, one per AZ:

| Subnet ID | AZ | CIDR |
|---|---|---|
| `subnet-00000000000000004` | us-east-1a | `172.31.80.0/20` |
| `subnet-00000000000000003` | us-east-1b | `172.31.16.0/20` ← instances here |
| `subnet-00000000000000005` | us-east-1c | `172.31.32.0/20` |
| `subnet-00000000000000006` | us-east-1d | `172.31.0.0/20` |
| `subnet-00000000000000007` | us-east-1e | `172.31.48.0/20` |
| `subnet-00000000000000008` | us-east-1f | `172.31.64.0/20` |

### Private (`RDS-Pvt-subnet-*`, `MapPublicIpOnLaunch: false`)

Five private subnets created for RDS, spread across AZs:

| Name | Subnet ID | AZ | CIDR |
|---|---|---|---|
| `RDS-Pvt-subnet-1` | `subnet-00000000000000009` | us-east-1b | `172.31.96.0/25` |
| `RDS-Pvt-subnet-2` | `subnet-00000000000000010` | us-east-1a | `172.31.96.128/25` |
| `RDS-Pvt-subnet-3` | `subnet-00000000000000011` | us-east-1c | `172.31.97.0/25` |
| `RDS-Pvt-subnet-4` | `subnet-00000000000000012` | us-east-1f | `172.31.97.128/25` |
| `RDS-Pvt-subnet-5` | `subnet-00000000000000013` | us-east-1d | `172.31.98.0/25` |

---

## Internet Gateway

`igw-00000000000000002` — attached and available (untagged).

---

## Route Tables

| Name | ID | Subnets | Routes |
|---|---|---|---|
| _(main, untagged)_ | `rtb-00000000000000003` | all default public | `172.31.0.0/16 → local`, `0.0.0.0/0 → IGW`, `pl-00000000000000001 → vpce-00000000000000001` (S3 Gateway) |
| `RDS-Pvt-rt` | `rtb-00000000000000004` | all 5 RDS-Pvt subnets | `172.31.0.0/16 → local` only |

The S3 Gateway VPC endpoint (`vpce-00000000000000001`) is present in the main route table — S3 traffic from public instances stays on the AWS backbone.

The RDS private route table has no internet route, correctly isolating the private subnets.

---

## Security Groups

### Mail-in-a-Box (`sg-00000000000000006`)
Deployed by CloudFormation. Exposes all ports required for a self-hosted mail + DNS server.

| Direction | Port/Protocol | Source | Purpose |
|---|---|---|---|
| Inbound | 22 TCP | `198.51.100.10/32` | SSH — restricted to a single IP |
| Inbound | 25 TCP | `0.0.0.0/0` | SMTP (inbound mail) |
| Inbound | 53 TCP+UDP | `0.0.0.0/0` | DNS |
| Inbound | 80 TCP | `0.0.0.0/0` | HTTP (Let's Encrypt / webmail redirect) |
| Inbound | 143 TCP | `0.0.0.0/0` | IMAP |
| Inbound | 443 TCP | `0.0.0.0/0` | HTTPS (webmail / admin) |
| Inbound | 465 TCP | `0.0.0.0/0` | SMTPS |
| Inbound | 587 TCP | `0.0.0.0/0` | SMTP submission |
| Inbound | 993 TCP | `0.0.0.0/0` | IMAPS |
| Inbound | 4190 TCP | `0.0.0.0/0` | ManageSieve |
| Outbound | All | `0.0.0.0/0` | Unrestricted |

SSH is locked to a specific IP — the rest of the ports are inherently public-facing for a mail server.

### `WebApplicationServer` (`sg-00000000000000007`)

| Direction | Port | Source | Purpose |
|---|---|---|---|
| Inbound | 22 TCP | `198.51.100.10/32` | SSH — restricted to a single IP |
| Inbound | 80 TCP | `0.0.0.0/0` | HTTP |
| Inbound | 443 TCP | `0.0.0.0/0` | HTTPS |
| Outbound | All | `0.0.0.0/0` | Unrestricted |

### RDS Proxy chain (Lambda → MySQL)
Three linked SGs manage Lambda-to-RDS connectivity via RDS Proxy:

| SG | ID | Role |
|---|---|---|
| `lambda-rdsproxy-1` | `sg-00000000000000008` | Attached to Lambda; allows egress on 3306 → Proxy SG |
| `rdsproxy-lambda-1` | `sg-00000000000000009` | Attached to RDS Proxy; allows ingress from Lambda SG, egress on 3306 → RDS SG |
| `rds-rdsproxy-1` | `sg-00000000000000010` | Attached to MySQL RDS; allows ingress on 3306 from Proxy SG only |

### SageMaker NFS SGs (managed — do not delete)
Two SGs (`sg-00000000000000011`, `sg-00000000000000012`) managed by SageMaker Domain `d-xxxxxxxxxxxx`. Handle EFS NFS traffic on ports 988, 2049, 1018–1023. Do not modify or delete.

### `default` (`sg-00000000000000013`)
Self-referencing inbound (all traffic from same SG); unrestricted outbound. Not attached to active instances.

---

## Notable Observations

1. ~~**SSH wide open on the web app server.**~~ **Fixed** — SSH on `WebApplicationServer` restricted to `198.51.100.10/32` (same as mail server).

2. ~~**Mail server IMDSv1 still enabled.**~~ **Fixed** — `HttpTokens: required` enforced on both instances.

3. **Both instances in the same AZ.** Both the mail server and web app server are in `us-east-1b`. An AZ outage would take both down simultaneously.

4. **S3 Gateway VPC endpoint present.** S3 traffic from instances in the main route table stays on the AWS network — a good cost and security measure already in place.

5. **RDS Proxy + private subnets for MySQL.** The private `RDS-Pvt-subnet-*` subnets and the three-SG proxy chain correctly isolate the MySQL RDS from direct internet access. Well-structured.

6. **SageMaker domain active.** SageMaker Domain `d-xxxxxxxxxxxx` has managed NFS SGs in this VPC — an EFS file system is likely attached for notebook storage.
