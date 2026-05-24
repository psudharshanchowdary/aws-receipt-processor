# AWS Receipt Processor

## About it
AWS Receipt Processor is a serverless, dual-mode expense management portal designed to upload receipts, automatically extract key financial data using OCR, store structured transaction metadata.

---

## Cloud Computing Principles & Architecture

This project is architected specifically to demonstrate core modern Cloud Computing principles, architectural patterns, and serverless best practices:

- Serverless Compute (FaaS) — Implements event-driven backend logic using AWS Lambda. The application runs compute routines on-demand, scaling automatically to handle concurrent scans without requiring any provisioned or persistent server infrastructure.
- Decoupled Cloud Object Storage — Uses Amazon S3 for secure, encrypted object storage (AES-256) to separate file uploads, pipeline results, and application state from the compute layer.
- Managed NoSQL Database (DBaaS) — Uses Amazon DynamoDB configured in Pay-Per-Request billing mode. Demonstrates key-value store performance, high throughput, and zero-cost schema-less database operations during development.
- Federated Identity & Client-Side Security — Integrates Amazon Cognito Identity Pools to safely exchange public federations for temporary, highly-restricted IAM credentials, allowing direct-to-S3 browser uploads without exposing AWS secrets.
- AI/ML Cloud Integration (AIaaS) — Integrates AWS Textract (AnalyzeExpense API) to show how pre-trained computer vision models can be consumed as an API service without managing any underlying ML infrastructure.
- Cloud Emulation (Sandboxing) — Leverages LocalStack in a Docker Compose network to emulate AWS cloud services locally. This represents the industry pattern of setting up offline, zero-cost development environments that mirror production cloud topologies.

---

## Technologies

# Frontend Client
 
- Vanilla HTML5, CSS3 (dark-mode, glassmorphism layouts, floating status badges, dynamic scanning line animations, custom CSS micro-animations)
- Vanilla JavaScript (ES6+)
- AWS SDK for JavaScript (v3)
- Amazon Cognito Identity SDK

# Backend Server — Local Docker Stack

- Python 3.11, Flask API, PyTesseract OCR Engine, PIL (Pillow)
- Docker & Docker Compose
- Nginx (Reverse Proxy & Web Server)
- LocalStack (S3, DynamoDB, SES emulation)
- DynamoDB Admin UI
  
#Backend Server — AWS Cloud

- AWS S3 (AES-256 encrypted)
- AWS Lambda (Python 3.11 runtime)
- AWS Textract (AnalyzeExpense API & fallback DetectDocumentText)
- Amazon DynamoDB (Pay-Per-Request)
- Amazon SES (email delivery)
- Amazon Cognito Identity Pools
- AWS IAM

---

## Features

- Dual-Infrastructure Auto-Detection — Seamlessly detects local Flask endpoints (http://localhost:8000) to switch the UI instantly between Local Docker Mode (Tesseract OCR + LocalStack S3/DynamoDB) and AWS Cloud Mode (Textract + real S3/DynamoDB/SES), with no manual configuration required.
- Intelligent Expense Extraction — Leverages AWS Textract's specialized AnalyzeExpense API to extract vendor name, invoice date, total billing amount, transaction currency, and categories. Uses a structured fallback to DetectDocumentText for receipts that don't match standard expense layouts.
- Interactive Real-Time Pipeline Tracker — Visualizes the backend processing pipeline stages (Upload → API/Lambda Trigger → OCR Scan → DynamoDB Save → SES Email Notification) with active, completed, and pending state indicators updating in real time.
- Responsive HTML Email Receipts — Generates and sends beautiful, responsive HTML billing receipt notifications directly to verified recipient addresses via SES, containing a styled summary, S3 signed download link, and itemized expense breakdown.
- Data Inspector & Local Ledger — Stores user session receipt histories locally using HTML5 LocalStorage, with an interactive sidebar listing to inspect raw OCR text blocks and raw database-ready JSON payloads for each processed receipt.
---

## Interactive Shortcuts
- 
- Toggle API Settings Panel**: Click the "Show Settings" banner toggle at the top of the upload layout to manually override the S3 bucket name, Cognito Pool ID, region, API gateway, or custom alernative
- File Drop-Zone Operations**: Click the browse button or drag-and-drop any receipt image (JPG, PNG, GIF, WEBP, or PDF) directly onto the upload zone to automatically stage files up to 10 MB.
- Pipeline Sandbox Simulator**: Click "Try Demo" to run the offline simulator pipeline immediately without logging in or configuring any AWS services.

---

## The Process

- Serverless Python Architecture — Developed modular Lambda scripts in Python 3.11 capable of handling multipart file streams or JSON base64 payloads, performing text-extraction pipelines, updating DynamoDB records, and dispatching SES email notifications on each invocation.
- DynamoDB Schema Design — Structured a clean receipt data model detailing receiptId, vendor, date, totalAmount, currency, category, uploadedAt, s3Key, and rawText.
- LocalStack Containerization — Built a Docker Compose stack mounting initialization scripts (init.sh) to pre-provision local buckets, create matching DynamoDB schemas, and pre-verify SES identities so the full pipeline runs offline without any AWS account.
- Client-Side AWS Polling — Configured Cognito Federated Identity inline policies to allow client browser clients to write to receipts/* and poll S3 key locations (results/*.json) continuously until Lambda processing completes and results are available.

---

## What I Learned
- 
- Cognito Federated Identities**: Exchanging public identity pools for short-lived IAM credentials to allow secure direct S3 bucket puts and gets straight from the browser.
- AWS Textract Document Normalization**: Isolating and standardizing fragmented dates, tax fields, and currency symbols returned by automated OCR models into clean, system-compatible ISO types.
- Docker Network Bridging**: Coordinating separate API servers, mock cloud endpoints, Nginx servers, and visual DB management nodes into a unified compose group.

---

## Overall Growth

- Serverless Paradigm Adoption — Transitioned from building monolithic server setups to designing lightweight, decoupled, event-driven pipelines utilizing S3 notifications and Lambda execution triggers to process workloads asynchronously at scale.
- Cost-Efficient Development Sandboxing — Learned how to craft applications that are 100% free and offline-functional during local development, yet fully prepared to shift into production AWS nodes with minimal configuration changes.

---

## How It Can Be Improved

- Stripe / Payment Integration — Introduce mock invoice billing or Stripe checkout widgets to settle detected payment amounts in real-time.
- PDF Invoice Generation — Add server-side Python receipt generators (like ReportLab or Weasyprint) to allow downloading official PDF summaries.
- Lifecycle Purging Policies — Apply automated S3 lifecycle rules to move old raw receipt uploads to Glacier Deep Archive or delete temp artifacts after 30 days.
- Multi-tenant Access Controls — Incorporate Cognito User Pools (Auth) so multiple tenants can log in and view their personal receipt ledger histories separately.
---

## Running the Project

### 1. Installation
Clone the repository:
```bash
git clone https://github.com/your-username/aws-receipt-processor.git
cd aws-receipt-processor
```

### 2. Run Local Docker Stack (Easiest — 100% Free)
Ensure Docker Desktop is running, then start the services in the root folder:
```bash
docker compose up --build
```
- Client Interface**: [http://localhost:3000](http://localhost:3000)
- Flask API Server**: [http://localhost:8000](http://localhost:8000)
- DynamoDB Admin UI**: [http://localhost:8001](http://localhost:8001)
- LocalStack Endpoint**: [http://localhost:4566](http://localhost:4566)

### 3. Run Production AWS Serverless Setup
1. Set up your AWS resources (S3 bucket, DynamoDB table, SES identities, IAM role, and Cognito Identity Pool) using the CLI commands in 
2. Deploy the Lambda function from `lambda/lambda_function.py`.
3. Start a local static server to serve the frontend:
   ```bash
   cd frontend
   python3 -m http.server 8080
   ```
4. Open [http://localhost:8080](http://localhost:8080), expand **Show Settings**, configure your bucket name, Cognito Pool ID, region, and target email, and process your receipts.

---

## Demo Video
🎬 **Watch Demo Video**  
[Watch Demo Video](https://drive.google.com/file/d/1iuMJwL9OMC099hdyWn_RFoFxFF-vnJU2/view?usp=drive_link)  
Full platform walkthrough showing local Docker stack simulation and AWS serverless cloud deployment.
