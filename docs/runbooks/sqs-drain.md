# SQS Drain / DLQ Runbook

## Check DLQ depth

```bash
aws sqs get-queue-attributes \
  --queue-url $(aws sqs get-queue-url --queue-name transcription-dlq-prod --query QueueUrl --output text) \
  --attribute-names ApproximateNumberOfMessages
```

## Redrive DLQ messages back to main queue

```bash
# Get queue URLs
MAIN_URL=$(aws sqs get-queue-url --queue-name transcription-prod --query QueueUrl --output text)
DLQ_URL=$(aws sqs get-queue-url --queue-name transcription-dlq-prod --query QueueUrl --output text)
MAIN_ARN=$(aws sqs get-queue-attributes --queue-url "$MAIN_URL" --attribute-names QueueArn --query Attributes.QueueArn --output text)

# Start redrive
aws sqs start-message-move-task --source-arn "$DLQ_ARN" --destination-arn "$MAIN_ARN"
```

## Purge DLQ (discard failed messages)

```bash
aws sqs purge-queue --queue-url "$DLQ_URL"
```

## Inspect a DLQ message without deleting it

```bash
aws sqs receive-message --queue-url "$DLQ_URL" --max-number-of-messages 1 \
  --attribute-names All --message-attribute-names All
```
