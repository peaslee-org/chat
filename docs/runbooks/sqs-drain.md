# SQS Drain / DLQ Runbook

Two queue pairs, same shape:

| Feature | Main queue | DLQ | Moves to DLQ after |
|---|---|---|---|
| Transcription | `transcription-prod` | `transcription-dlq-prod` | 3 receives |
| Photogrammetry | `photogrammetry-prod` | `photogrammetry-prod-dlq` | 5 receives — and the worker **fails the job row on its 5th delivery** instead of retrying, so a photogrammetry DLQ message means the worker never got to run the handler at all (crash before receipt, or a DB it couldn't reach) |

Main-queue retention is 4 days, DLQ 14 days, visibility timeout 600 s on both. A `*-dlq-depth`
CloudWatch alarm emails when a DLQ is non-empty (if `alarm_email` is set).

The worker is launched per job (`RunTask`), not a standing service — if a queue is growing, check
`./scripts/deploy/gpu-status.sh` (worker state `off`/`starting`/`running`) before assuming a
processing bug; a job stuck without a worker running is a launch problem, not a drain problem.

Set the pair first:

```bash
MAIN=transcription-prod;  DLQ=transcription-dlq-prod       # or:
MAIN=photogrammetry-prod; DLQ=photogrammetry-prod-dlq
MAIN_URL=$(aws sqs get-queue-url --queue-name "$MAIN" --query QueueUrl --output text)
DLQ_URL=$(aws sqs get-queue-url --queue-name "$DLQ" --query QueueUrl --output text)
```

## Check depth

```bash
for u in "$MAIN_URL" "$DLQ_URL"; do aws sqs get-queue-attributes --queue-url "$u" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --output text; done
```

## Inspect a DLQ message without deleting it

```bash
aws sqs receive-message --queue-url "$DLQ_URL" --max-number-of-messages 1 \
  --attribute-names All --message-attribute-names All
```
The body carries the job id; look it up in the API log (`/ecs/chat-api-prod`) and the worker log
before redriving. A photogrammetry job whose row is already `failed` should not be redriven — the
user has been told, and a re-run would restart from the checkpointed stage anyway if they resubmit.

## Redrive DLQ messages back to the main queue

```bash
MAIN_ARN=$(aws sqs get-queue-attributes --queue-url "$MAIN_URL" --attribute-names QueueArn --query Attributes.QueueArn --output text)
DLQ_ARN=$(aws sqs get-queue-attributes --queue-url "$DLQ_URL"  --attribute-names QueueArn --query Attributes.QueueArn --output text)
aws sqs start-message-move-task --source-arn "$DLQ_ARN" --destination-arn "$MAIN_ARN"
```
Redriven messages arrive with a fresh receive count. Make sure a worker will pick them up: either
a job poll from the UI triggers `RunTask`, or warm the pool from the status bar.

## Purge a DLQ (discard failed messages)

```bash
aws sqs purge-queue --queue-url "$DLQ_URL"
```
