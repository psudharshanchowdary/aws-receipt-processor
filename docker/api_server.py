import os
import re
import uuid
import json
import logging
import base64
from datetime import datetime
from io import BytesIO
from flask import Flask, request, jsonify
from flask_cors import CORS
import boto3
from PIL import Image
import pytesseract

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("receipt-api")

app = Flask(__name__)
CORS(app) # Enable CORS for all routes

# Config from environment variables
LOCALSTACK_ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT", None)
S3_BUCKET = os.environ.get("S3_BUCKET", "receipts-bucket")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "Receipts")
SES_SENDER_EMAIL = os.environ.get("SES_SENDER_EMAIL", "noreply@receiptai.local")
SES_RECIPIENT_EMAIL = os.environ.get("SES_RECIPIENT_EMAIL", "test@example.com")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-south-1")

logger.info(f"Initializing AWS clients with Region: {AWS_REGION}, LocalStack Endpoint: {LOCALSTACK_ENDPOINT}")

# Helper to create boto3 resource/client pointing to LocalStack if endpoint is set
def get_boto_client(service_name):
    if LOCALSTACK_ENDPOINT:
        return boto3.client(service_name, endpoint_url=LOCALSTACK_ENDPOINT, region_name=AWS_REGION)
    return boto3.client(service_name, region_name=AWS_REGION)

def get_boto_resource(service_name):
    if LOCALSTACK_ENDPOINT:
        return boto3.resource(service_name, endpoint_url=LOCALSTACK_ENDPOINT, region_name=AWS_REGION)
    return boto3.resource(service_name, region_name=AWS_REGION)

# Initialize AWS clients
s3_client = get_boto_client("s3")
db_resource = get_boto_resource("dynamodb")
ses_client = get_boto_client("ses")

# Heuristics Parser (copied from lambda_function.py)
def parse_receipt_text(text: str) -> dict:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    result = {}

    if lines:
        result['vendor'] = lines[0][:120]

    date_patterns = [
        r'\b(\d{4}-\d{2}-\d{2})\b',
        r'\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\b',
        r'\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{2,4})\b',
    ]
    for pattern in date_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            result['date'] = normalise_date(m.group(1))
            break

    total_pattern = re.compile(
        r'(?:total|grand\s*total|amount\s*due|net\s*amount|payable|bill\s*amount)'
        r'[:\s]*(?:rs\.?|inr|₹|usd|\$)?[\s]*([0-9,]+(?:\.\d{1,2})?)',
        re.IGNORECASE,
    )
    m = total_pattern.search(text)
    if m:
        raw_amount = m.group(1).replace(',', '')
        result['total'] = raw_amount
    else:
        amounts = re.findall(r'(?:rs\.?|inr|₹|usd|\$)\s*([0-9,]+(?:\.\d{1,2})?)', text, re.IGNORECASE)
        if not amounts:
            amounts = re.findall(r'\b([0-9]{1,6}(?:,[0-9]{3})*(?:\.\d{1,2})?)\b', text)
        if amounts:
            parsed_amounts = [float(a.replace(',','')) for a in amounts]
            result['total'] = f"{max(parsed_amounts):.2f}"

    if re.search(r'₹|inr|rs\.?', text, re.IGNORECASE):
        result['currency'] = 'INR'
    elif re.search(r'\$|usd', text, re.IGNORECASE):
        result['currency'] = 'USD'
    else:
        result['currency'] = 'INR'

    return result

def normalise_date(raw: str) -> str:
    raw = raw.strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', raw):
        return raw
    m = re.match(r'^(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})$', raw)
    if m:
        d, mo, y = m.group(1), m.group(2), m.group(3)
        if len(y) == 2:
            y = '20' + y
        return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
    for fmt in ('%d %b %Y', '%d %B %Y', '%d %b %y'):
        try:
            return datetime.strptime(raw, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return raw

def detect_category(vendor: str) -> str:
    v = vendor.lower()
    if re.search(r'reliance|bigbasket|dmart|grofer|zepto|blinkit|mart|fresh|supermarket|kirana', v):
        return 'Groceries'
    if re.search(r'restaurant|cafe|zomato|swiggy|food|pizza|burger|eat|dhaba|canteen', v):
        return 'Food & Dining'
    if re.search(r'amazon|flipkart|myntra|ajio|meesho|retail|shop|bazaar', v):
        return 'Shopping'
    if re.search(r'uber|ola|rapido|cab|taxi|petrol|fuel|travel|irctc|redbus', v):
        return 'Transport'
    if re.search(r'apollo|medplus|pharmacy|clinic|hospital|health|medical', v):
        return 'Healthcare'
    if re.search(r'electricity|water|gas|jio|airtel|bsnl|utility|bill|recharge', v):
        return 'Utilities'
    return 'General'

def send_ses_email(recipient: str, item: dict):
    subject = f"Receipt Processed: {item.get('vendor','Unknown')} — {item.get('currency','')} {item.get('totalAmount','')}"
    text_body = f"""Receipt Processed Successfully

Receipt ID   : {item.get('receiptId')}
Vendor       : {item.get('vendor','—')}
Date         : {item.get('date','—')}
Total Amount : {item.get('currency','')} {item.get('totalAmount','—')}
Category     : {item.get('category','General')}
S3 Key       : {item.get('s3Key','—')}
Processed At : {item.get('uploadedAt','—')}

Processed by ReceiptAI (Local Docker Mode)
"""
    try:
        ses_client.send_email(
            Source=SES_SENDER_EMAIL,
            Destination={'ToAddresses': [recipient]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Text': {'Data': text_body, 'Charset': 'UTF-8'}
                },
            },
        )
        logger.info(f"SES email alert sent to {recipient}")
    except Exception as e:
        logger.error(f"Failed to send SES email: {e}")

# Routes
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "mode": "Docker (Local)"})

@app.route("/receipts", methods=["GET"])
def list_receipts():
    try:
        table = db_resource.Table(DYNAMODB_TABLE)
        response = table.scan()
        items = response.get("Items", [])
        
        # Sort by uploadedAt descending
        items.sort(key=lambda x: x.get("uploadedAt", ""), reverse=True)
        return jsonify(items)
    except Exception as e:
        logger.error(f"Failed to list receipts: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/upload", methods=["POST"])
def upload_receipt():
    receipt_id = str(uuid.uuid4())
    filename = "receipt.png"
    file_bytes = None
    email_recipient = SES_RECIPIENT_EMAIL

    try:
        # Determine format (Multipart vs JSON base64)
        if request.is_json:
            data = request.get_json()
            if not data or 'file' not in data:
                return jsonify({"status": "error", "message": "Missing file base64 data"}), 400
            
            # Base64 parsing
            file_data = data['file']
            if "," in file_data:
                file_data = file_data.split(",")[1] # Strip header
            file_bytes = base64.b64decode(file_data)
            
            filename = data.get("filename", filename)
            email_recipient = data.get("email", email_recipient)
        else:
            # Multipart form parsing
            if 'file' not in request.files:
                return jsonify({"status": "error", "message": "Missing file form field"}), 400
            file_obj = request.files['file']
            filename = file_obj.filename
            file_bytes = file_obj.read()
            email_recipient = request.form.get("email", email_recipient)

        logger.info(f"Received file upload: {filename} ({len(file_bytes)} bytes)")

        # Upload image file to LocalStack S3
        object_key = f"receipts/{receipt_id}-{filename}"
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=object_key,
            Body=file_bytes,
            ContentType="image/png" if filename.endswith(".png") else "image/jpeg"
        )
        logger.info(f"Uploaded raw image to s3://{S3_BUCKET}/{object_key}")

        # Run Tesseract OCR on raw bytes
        img = Image.open(BytesIO(file_bytes))
        raw_text = pytesseract.image_to_string(img)
        logger.info("Tesseract OCR completed successfully.")

        # Parse extracted text
        parsed = parse_receipt_text(raw_text)
        uploaded_at = datetime.utcnow().isoformat() + 'Z'

        # Construct final receipt item
        item = {
            "receiptId": receipt_id,
            "vendor": parsed.get("vendor") or "Unknown Vendor",
            "date": parsed.get("date") or uploaded_at[:10],
            "totalAmount": parsed.get("total") or "0.00",
            "currency": parsed.get("currency") or "INR",
            "category": detect_category(parsed.get("vendor") or ""),
            "uploadedAt": uploaded_at,
            "s3Key": object_key,
            "rawText": raw_text
        }

        # Save metadata to DynamoDB
        table = db_resource.Table(DYNAMODB_TABLE)
        table.put_item(Item=item)
        logger.info(f"Saved receipt metadata to DynamoDB table {DYNAMODB_TABLE}")

        # Write results JSON to S3 for frontend polling fallback
        result_key = f"results/{receipt_id}.json"
        result_payload = {"status": "success", "receipt": item, **item}
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=result_key,
            Body=json.dumps(result_payload, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
            CacheControl="no-store"
        )
        logger.info(f"Wrote result JSON to s3://{S3_BUCKET}/{result_key}")

        # Trigger mock SES email
        if email_recipient:
            send_ses_email(email_recipient, item)

        # Return full success response
        return jsonify({
            "status": "success",
            "receipt": item,
            "rawText": raw_text
        })

    except Exception as e:
        logger.error(f"Error processing upload: {e}", exc_info=True)
        # Write error result back to S3 so the frontend doesn't hang in loading state
        try:
            error_key = f"results/{receipt_id}.json"
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=error_key,
                Body=json.dumps({"status": "error", "message": str(e)}).encode("utf-8"),
                ContentType="application/json"
            )
        except Exception as s3_err:
            logger.error(f"Failed to write S3 error JSON: {s3_err}")

        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
