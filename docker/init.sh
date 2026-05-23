#!/bin/bash
echo "=========== INITIALIZING LOCALSTACK RESOURCES ==========="

# Create S3 Bucket
awslocal s3 mb s3://receipts-bucket
echo "S3 Bucket 'receipts-bucket' created."

# Create DynamoDB Table
awslocal dynamodb create-table \
    --table-name Receipts \
    --attribute-definitions AttributeName=receiptId,AttributeType=S \
    --key-schema AttributeName=receiptId,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST
echo "DynamoDB Table 'Receipts' created."

# Verify SES sender and recipient emails
awslocal ses verify-email-identity --email-address noreply@receiptai.local
awslocal ses verify-email-identity --email-address test@example.com
echo "SES Identities verified."

echo "=========== LOCALSTACK INITIALIZATION COMPLETE ==========="
