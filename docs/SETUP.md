# AWS Receipt Processor — Complete Setup & Deployment Guide

> **Stack:** S3 → Lambda (Python 3.11) → Textract → DynamoDB → SES  
> **Region:** ap-south-1 (Mumbai) — change as needed  
> **Billing:** All services have free-tier coverage for low volumes

---

## Table of Contents
1. [Prerequisites](#1-prerequisites)
2. [S3 Bucket Setup](#2-s3-bucket-setup)
3. [DynamoDB Table Setup](#3-dynamodb-table-setup)
4. [SES Email Verification](#4-ses-email-verification)
5. [IAM Role & Policy](#5-iam-role--policy)
6. [Lambda Function Deployment](#6-lambda-function-deployment)
7. [Frontend Browser Upload (Cognito Identity Pool)](#7-frontend-browser-upload-cognito-identity-pool)
8. [Frontend Configuration](#8-frontend-configuration)
9. [Testing Guide](#9-testing-guide)
10. [Cleanup Instructions](#10-cleanup-instructions)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Prerequisites

- AWS account (free tier is sufficient)
- AWS CLI installed: `brew install awscli`
- Configure CLI: `aws configure` → enter Access Key, Secret, region `ap-south-1`, output `json`
- Python 3.11 (for local testing)
- A verified email address for SES
- A web browser (Chrome/Edge/Firefox)

---

## 2. S3 Bucket Setup

### 2a. Create the bucket (replace `YOUR-BUCKET-NAME`)

```bash
aws s3api create-bucket \
  --bucket YOUR-BUCKET-NAME \
  --region ap-south-1 \
  --create-bucket-configuration LocationConstraint=ap-south-1
```

### 2b. Block all public access (security)

```bash
aws s3api put-public-access-block \
  --bucket YOUR-BUCKET-NAME \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
```

### 2c. Enable AES-256 encryption at rest

```bash
aws s3api put-bucket-encryption \
  --bucket YOUR-BUCKET-NAME \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }'
```

### 2d. Enable versioning (recommended for audit trail)

```bash
aws s3api put-bucket-versioning \
  --bucket YOUR-BUCKET-NAME \
  --versioning-configuration Status=Enabled
```

### 2e. Add S3 event notification to trigger Lambda

> Do this **after** Lambda is created (Step 6), then come back here.

```bash
aws s3api put-bucket-notification-configuration \
  --bucket YOUR-BUCKET-NAME \
  --notification-configuration '{
    "LambdaFunctionConfigurations": [{
      "LambdaFunctionArn": "arn:aws:lambda:ap-south-1:YOUR-ACCOUNT-ID:function:ReceiptProcessor",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {
        "Key": {
          "FilterRules": [{"Name": "prefix", "Value": "receipts/"}]
        }
      }
    }]
  }'
```

### 2f. CORS (required for browser uploads)

If you will upload receipts from the static frontend (Step 7/8), configure S3 CORS.

For local testing this allows:
- `http://localhost:8080`

For production, replace the origin with your HTTPS domain (CloudFront recommended).

```bash
aws s3api put-bucket-cors \
  --bucket YOUR-BUCKET-NAME \
  --cors-configuration '{
    "CORSRules": [{
      "AllowedOrigins": ["http://localhost:8080"],
      "AllowedMethods": ["GET","PUT","POST","HEAD"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag","x-amz-request-id","x-amz-id-2"],
      "MaxAgeSeconds": 3000
    }]
  }'
```

---

## 3. DynamoDB Table Setup

### 3a. Create the Receipts table

```bash
aws dynamodb create-table \
  --table-name Receipts \
  --attribute-definitions AttributeName=receiptId,AttributeType=S \
  --key-schema AttributeName=receiptId,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region ap-south-1
```

> `PAY_PER_REQUEST` = no minimum cost; pay only for reads/writes. Free tier: 25 GB storage + 25 RCU/WCU.

### 3b. Wait for table to become ACTIVE

```bash
aws dynamodb wait table-exists --table-name Receipts --region ap-south-1
echo "Table is ready!"
```

### 3c. Verify the table

```bash
aws dynamodb describe-table --table-name Receipts --region ap-south-1 \
  --query "Table.{Name:TableName,Status:TableStatus,KeySchema:KeySchema}"
```

---

## 4. SES Email Verification

> SES sandbox mode requires verifying both sender and recipient emails.

### 4a. Verify sender email

```bash
aws ses verify-email-identity \
  --email-address sender@yourdomain.com \
  --region ap-south-1
```

### 4b. Verify recipient email (sandbox only)

```bash
aws ses verify-email-identity \
  --email-address recipient@yourdomain.com \
  --region ap-south-1
```

Check your inbox and click the verification link in each email.

### 4c. Confirm verification

```bash
aws ses list-verified-email-addresses --region ap-south-1
```

### 4d. (Production) Request SES production access

In the AWS Console → SES → Account Dashboard → "Request Production Access"  
Fill the form to remove sandbox restrictions (allow sending to any email).

---

## 5. IAM Role & Policy

### 5a. Create Lambda execution role

```bash
aws iam create-role \
  --role-name ReceiptProcessorLambdaRole \
  --assume-role-policy-document '{
    "Version":"2012-10-17",
    "Statement":[{
      "Effect":"Allow",
      "Principal":{"Service":"lambda.amazonaws.com"},
      "Action":"sts:AssumeRole"
    }]
  }'
```

### 5b. Attach least-privilege policy

Edit `infrastructure/iam_policy.json` and replace:
- `YOUR-BUCKET-NAME` → your actual S3 bucket name
- `YOUR-ACCOUNT-ID` → your 12-digit AWS account ID

```bash
aws iam put-role-policy \
  --role-name ReceiptProcessorLambdaRole \
  --policy-name ReceiptProcessorPolicy \
  --policy-document file://infrastructure/iam_policy.json
```

### 5c. Get the role ARN (needed for Lambda creation)

```bash
aws iam get-role \
  --role-name ReceiptProcessorLambdaRole \
  --query "Role.Arn" --output text
```

---

## 6. Lambda Function Deployment

### 6a. Package the Lambda code

```bash
cd lambda/
zip -r ../receipt-processor.zip lambda_function.py
cd ..
```

### 6b. Create the Lambda function

```bash
aws lambda create-function \
  --function-name ReceiptProcessor \
  --runtime python3.11 \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://receipt-processor.zip \
  --role arn:aws:iam::YOUR-ACCOUNT-ID:role/ReceiptProcessorLambdaRole \
  --timeout 60 \
  --memory-size 256 \
  --environment Variables="{
    DYNAMODB_TABLE=Receipts,
    SES_SENDER_EMAIL=sender@yourdomain.com,
    SES_RECIPIENT_EMAIL=recipient@yourdomain.com,
    RESULTS_PREFIX=results/,
    AWS_REGION_NAME=ap-south-1
  }" \
  --region ap-south-1
```

### 6c. Grant S3 permission to invoke Lambda

```bash
aws lambda add-permission \
  --function-name ReceiptProcessor \
  --statement-id S3InvokePermission \
  --action lambda:InvokeFunction \
  --principal s3.amazonaws.com \
  --source-arn arn:aws:s3:::YOUR-BUCKET-NAME \
  --region ap-south-1
```

### 6d. Update function code (if you make changes)

```bash
cd lambda && zip -r ../receipt-processor.zip lambda_function.py && cd ..
aws lambda update-function-code \
  --function-name ReceiptProcessor \
  --zip-file fileb://receipt-processor.zip \
  --region ap-south-1
```

### 6e. Update environment variables

```bash
aws lambda update-function-configuration \
  --function-name ReceiptProcessor \
  --environment Variables="{
    DYNAMODB_TABLE=Receipts,
    SES_SENDER_EMAIL=sender@yourdomain.com,
    SES_RECIPIENT_EMAIL=recipient@yourdomain.com,
    RESULTS_PREFIX=results/,
    AWS_REGION_NAME=ap-south-1
  }" \
  --region ap-south-1
```

---

## 7. Frontend Browser Upload (Cognito Identity Pool)

Because your S3 bucket is private (as it should be), the browser needs **temporary AWS credentials** to:
- upload the receipt to `receipts/*`
- read the processing output from `results/*`

The simplest serverless option is **Amazon Cognito Identity Pool** with a tightly-scoped unauthenticated role.

### 7a. Create an Identity Pool (Console)

AWS Console → **Cognito** → **Federated identities** (Identity Pools) → Create.

- **Enable unauthenticated identities**: ON
- Note the **Identity Pool ID** (example: `ap-south-1:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)

### 7b. Grant least-privilege S3 permissions to the unauth role

In IAM, open the auto-created unauth role (`Cognito_<pool>Unauth_Role`) and attach this inline policy (replace `YOUR-BUCKET-NAME`).

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PutReceipts",
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/receipts/*"
    },
    {
      "Sid": "GetResults",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/results/*"
    }
  ]
}
```

---

## 8. Frontend Configuration

Run locally:
```bash
cd frontend
python3 -m http.server 8080
# Open http://localhost:8080
```

In the UI, fill:
- **AWS Region** (example: `ap-south-1`)
- **S3 Bucket Name** (your private bucket)
- **Cognito Identity Pool ID** (from Step 7a)

Then upload a receipt. The frontend will:
- upload to `receipts/<receiptId>-<filename>`
- poll `results/<receiptId>.json` until it exists
- display the extracted vendor/date/amount/category

---

## 9. Testing Guide

### 9a. Upload a test receipt via AWS CLI

```bash
aws s3 cp /path/to/test-receipt.jpg \
  s3://YOUR-BUCKET-NAME/receipts/test-receipt.jpg \
  --region ap-south-1
```

### 9b. Check Lambda execution logs

```bash
aws logs tail /aws/lambda/ReceiptProcessor --follow --region ap-south-1
```

### 9c. Verify data was saved to DynamoDB

```bash
aws dynamodb scan \
  --table-name Receipts \
  --region ap-south-1 \
  --output table
```

Or query a specific receipt:
```bash
aws dynamodb get-item \
  --table-name Receipts \
  --key '{"receiptId": {"S": "YOUR-RECEIPT-ID"}}' \
  --region ap-south-1
```

### 9d. Check SES email delivery

```bash
aws ses get-send-statistics --region ap-south-1
```

Check the inbox of your recipient email — you should receive a formatted HTML receipt summary.

### 9e. Verify the result JSON written to S3

The Lambda writes `results/<receiptId>.json` for each processed receipt.

```bash
aws s3 ls s3://YOUR-BUCKET-NAME/results/ --region ap-south-1
```

### 9e. Test Lambda manually (invoke with mock event)

```bash
aws lambda invoke \
  --function-name ReceiptProcessor \
  --payload '{
    "Records": [{
      "s3": {
        "bucket": {"name": "YOUR-BUCKET-NAME"},
        "object": {"key": "receipts/test-receipt.jpg"}
      }
    }]
  }' \
  --cli-binary-format raw-in-base64-out \
  --region ap-south-1 \
  output.json

cat output.json
```

### 9f. Suggested test receipt images

- Indian grocery receipts (Reliance Fresh, D-Mart, BigBasket)
- Restaurant bills
- Amazon/Flipkart order invoices
- Fuel station receipts
- Find sample receipts at: https://www.kaggle.com/datasets/jenswalter/receipts

---

## 10. Cleanup Instructions

> Run these commands when you're done to avoid any ongoing charges.

```bash
# 1. Delete Lambda function
aws lambda delete-function --function-name ReceiptProcessor --region ap-south-1

# 2. Delete DynamoDB table
aws dynamodb delete-table --table-name Receipts --region ap-south-1

# 3. Empty and delete S3 bucket
aws s3 rm s3://YOUR-BUCKET-NAME --recursive
aws s3api delete-bucket --bucket YOUR-BUCKET-NAME --region ap-south-1

# 4. Delete IAM role and policy
aws iam delete-role-policy \
  --role-name ReceiptProcessorLambdaRole \
  --policy-name ReceiptProcessorPolicy
aws iam delete-role --role-name ReceiptProcessorLambdaRole

# 5. Delete CloudWatch Log Group
aws logs delete-log-group \
  --log-group-name /aws/lambda/ReceiptProcessor \
  --region ap-south-1

# 6. Delete Cognito Identity Pool (Console) and its IAM roles (optional)

# 7. Remove SES verified emails (optional)
aws ses delete-verified-email-address \
  --email-address sender@yourdomain.com --region ap-south-1
```

---

## 11. Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| Lambda not triggered | S3 event not configured | Re-run Step 2e |
| `AccessDenied` from Lambda | IAM policy missing | Check `iam_policy.json` and re-attach |
| Textract returns empty text | Image too small / blurry | Use a clear, well-lit photo (min 150 DPI) |
| SES email not received | Sandbox mode | Verify recipient email (Step 4b) |
| `ResourceNotFoundException` DynamoDB | Wrong table name | Check `DYNAMODB_TABLE` env var |
| Lambda timeout | Large image | Increase timeout to 120s |
| CORS error from frontend | S3 CORS not configured | Re-check Step 2f CORS config and your AllowedOrigins |

---

## DynamoDB Schema Reference

```json
{
  "receiptId":   "rcpt-3fa85f64-5717-4562-b3fc",
  "vendor":      "Reliance Fresh",
  "date":        "2024-04-28",
  "totalAmount": "450.00",
  "currency":    "INR",
  "category":    "Groceries",
  "uploadedAt":  "2024-04-28T09:22:00Z",
  "s3Key":       "receipts/2024-04-28/receipt.jpg",
  "s3ResultKey": "results/rcpt-3fa85f64-5717-4562-b3fc.json"
}
```

---

## Environment Variables Reference

| Variable | Required | Example | Description |
|---|---|---|---|
| `DYNAMODB_TABLE` | ✅ | `Receipts` | DynamoDB table name |
| `SES_SENDER_EMAIL` | ✅ | `noreply@yourdomain.com` | Verified SES sender |
| `SES_RECIPIENT_EMAIL` | ❌ | `user@example.com` | Fixed recipient (optional; can be read from S3 metadata) |
| `AWS_REGION_NAME` | ❌ | `ap-south-1` | AWS region (default: ap-south-1) |
