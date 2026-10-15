#!/usr/bin/env bash
# Creates the bucket, queue (+ DLQ) and status table in localstack and wires
# the S3 notification. Run after `docker compose up -d`.
set -e

ENDPOINT=http://localhost:4566
BUCKET=kb-rag-docs-dev
QUEUE=kb-rag-ingest-dev
DLQ=kb-rag-ingest-dlq-dev
TABLE=kb-rag-doc-status-dev

aws --endpoint-url $ENDPOINT s3 mb s3://$BUCKET || true

DLQ_URL=$(aws --endpoint-url $ENDPOINT sqs create-queue --queue-name $DLQ --query QueueUrl --output text)
DLQ_ARN=$(aws --endpoint-url $ENDPOINT sqs get-queue-attributes --queue-url $DLQ_URL \
  --attribute-names QueueArn --query Attributes.QueueArn --output text)

QUEUE_URL=$(aws --endpoint-url $ENDPOINT sqs create-queue --queue-name $QUEUE \
  --attributes "{\"VisibilityTimeout\":\"300\",\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"$DLQ_ARN\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"}" \
  --query QueueUrl --output text)
QUEUE_ARN=$(aws --endpoint-url $ENDPOINT sqs get-queue-attributes --queue-url $QUEUE_URL \
  --attribute-names QueueArn --query Attributes.QueueArn --output text)

aws --endpoint-url $ENDPOINT s3api put-bucket-notification-configuration --bucket $BUCKET \
  --notification-configuration "{\"QueueConfigurations\":[{\"QueueArn\":\"$QUEUE_ARN\",\"Events\":[\"s3:ObjectCreated:*\"],\"Filter\":{\"Key\":{\"FilterRules\":[{\"Name\":\"prefix\",\"Value\":\"uploads/\"}]}}}]}"

aws --endpoint-url $ENDPOINT dynamodb create-table --table-name $TABLE \
  --attribute-definitions AttributeName=doc_id,AttributeType=S \
  --key-schema AttributeName=doc_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST > /dev/null 2>&1 || echo "table $TABLE already exists"

echo "queue url: $QUEUE_URL"
echo "set INGEST_QUEUE_URL=$QUEUE_URL in .env"
