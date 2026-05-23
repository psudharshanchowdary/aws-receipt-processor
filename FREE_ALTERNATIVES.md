# Free Alternatives Quick Start Guide

This project can be run completely free in three different environments:

## Option A: LocalStack + Docker (Easiest — 100% Free)
Run the entire stack locally without setting up an AWS account. It uses LocalStack to mock AWS services and Tesseract for offline OCR.

### Prerequisites:
- Install [Docker Desktop](https://www.docker.com/products/docker-desktop) and start it.

### Setup and Start:
1. Open your terminal in the project directory:
   ```bash
   cd /Users/pavulurusudharshanchowdary/aws-receipt-processor
   ```
2. Start the services:
   ```bash
   docker compose up --build
   ```
3. Open the UI at: **http://localhost:3000**
4. Open the database admin at: **http://localhost:8001**
5. Upload receipts from the `test-receipts/` directory.

---

## Option B: Oracle Cloud Always-Free (Production Cloud)
Deploy this stack on Oracle Cloud Infrastructure (OCI) under their generous always-free tier (4 ARM Ampere CPUs, 24 GB RAM, 200 GB Storage).

See [oracle-cloud/ORACLE_SETUP.md](file:///Users/pavulurusudharshanchowdary/aws-receipt-processor/oracle-cloud/ORACLE_SETUP.md) for full deployment instructions.

---

## Option C: Real AWS Serverless (Production Serverless)
Deploy directly on real AWS (S3, Lambda, Textract, DynamoDB, SES). S3, Lambda, Textract, and DynamoDB have generous free tier limits that reset monthly.

See [docs/SETUP.md](file:///Users/pavulurusudharshanchowdary/aws-receipt-processor/docs/SETUP.md) for step-by-step CLI commands and configurations.
