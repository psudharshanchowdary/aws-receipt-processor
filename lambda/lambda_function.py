"""
lambda_function.py  —  AWS Receipt Processor Lambda
=====================================================
Triggered by: S3 PutObject event (receipts/ prefix)
Actions:
  1. Call AWS Textract AnalyzeExpense (best for receipts/invoices)
  2. Parse vendor name, date, total amount (+ currency)
  3. Save structured record to DynamoDB table "Receipts"
  4. Write a results JSON back to S3 (results/ prefix) for frontend polling
  5. Send confirmation email via AWS SES with receipt summary

Environment variables required:
  DYNAMODB_TABLE    — DynamoDB table name  (e.g. Receipts)
  SES_SENDER_EMAIL  — Verified SES sender email
  SES_RECIPIENT_EMAIL — Verified recipient email (required in SES sandbox)
  RESULTS_PREFIX    — S3 prefix for result JSON objects (default: results/)
  AWS_REGION_NAME   — AWS region  (optional; inferred by SDK if not set)
"""

import boto3
import json
import logging
import os
import re
import uuid
from datetime import datetime
from urllib.parse import unquote_plus

# ─── Logging ──────────────────────────────────────────────────────────────────
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ─── AWS clients (created once at cold-start for reuse across warm invocations)
_s3        = boto3.client('s3')
_textract  = boto3.client('textract')
_dynamodb  = boto3.resource('dynamodb')
_ses       = boto3.client('ses')

# ─── Config from environment variables ────────────────────────────────────────
DYNAMODB_TABLE       = os.environ['DYNAMODB_TABLE']         # e.g. Receipts
SES_SENDER_EMAIL     = os.environ['SES_SENDER_EMAIL']       # verified sender
SES_RECIPIENT_EMAIL  = os.environ['SES_RECIPIENT_EMAIL']    # verified recipient (SES sandbox)
RESULTS_PREFIX       = os.environ.get('RESULTS_PREFIX', 'results/').lstrip('/')
AWS_REGION_NAME      = os.environ.get('AWS_REGION_NAME', '')


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN HANDLER
# ═══════════════════════════════════════════════════════════════════════════════
def lambda_handler(event, context):
    """
    Entry point invoked by S3 event notification.
    Each S3 PutObject event record is processed independently.
    """
    logger.info("Event received: %s", json.dumps(event))

    results = []
    for record in event.get('Records', []):
        try:
            result = process_record(record)
            results.append({'status': 'success', 'receiptId': result['receiptId'], 's3ResultKey': result.get('s3ResultKey')})
        except Exception as exc:
            logger.error("Failed to process record: %s", exc, exc_info=True)
            results.append({'status': 'error', 'error': str(exc)})

    return {
        'statusCode': 200,
        'body': json.dumps({'processed': len(results), 'results': results}),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# RECORD PROCESSOR
# ═══════════════════════════════════════════════════════════════════════════════
def process_record(record):
    """
    Full pipeline for one S3 event record:
    Textract → parse → DynamoDB → SES.
    """
    # 1. Extract S3 bucket & key from the event record
    bucket = record['s3']['bucket']['name']
    # S3 event keys are URL-encoded
    key    = unquote_plus(record['s3']['object']['key'])
    logger.info("Processing s3://%s/%s", bucket, key)

    # 2. Run Textract (AnalyzeExpense is optimized for receipts/invoices)
    extracted = extract_receipt_fields(bucket, key)
    logger.info("Textract extracted fields: %s", extracted)

    # 3. Build the DynamoDB item (matches requested schema)
    receipt_id = str(uuid.uuid4())
    uploaded_at = datetime.utcnow().isoformat() + 'Z'

    item = {
        "receiptId": receipt_id,
        "vendor": extracted.get("vendor") or "Unknown Vendor",
        "date": extracted.get("date") or uploaded_at[:10],
        "totalAmount": extracted.get("totalAmount") or "0.00",
        "currency": extracted.get("currency") or "INR",
        "uploadedAt": uploaded_at,
        "s3Key": key,
        # Requested by frontend/UI
        "category": detect_category(extracted.get("vendor") or ""),
    }

    # 4. Save to DynamoDB (serverless NoSQL store)
    save_to_dynamodb(item)
    logger.info("Saved to DynamoDB with receiptId=%s", receipt_id)

    # 5. Write result JSON to S3 so the static frontend can poll and display it.
    #    This avoids needing an extra API just to read DynamoDB from the browser.
    result_key = f"{RESULTS_PREFIX.rstrip('/')}/{receipt_id}.json"
    put_result_json(bucket=bucket, key=result_key, payload={"status": "success", **item})
    logger.info("Wrote results JSON to s3://%s/%s", bucket, result_key)

    # 6. Send SES notification (in SES sandbox, recipient must be verified)
    send_ses_email(SES_RECIPIENT_EMAIL, item)
    logger.info("SES email sent to %s", SES_RECIPIENT_EMAIL)

    return {**item, "s3ResultKey": result_key}


# ═══════════════════════════════════════════════════════════════════════════════
# TEXTRACT (Receipts/Invoices)
# ═══════════════════════════════════════════════════════════════════════════════
def extract_receipt_fields(bucket: str, key: str) -> dict:
    """
    Uses Textract AnalyzeExpense to extract normalized receipt fields.

    Returns:
      { vendor, date, totalAmount, currency }

    Notes:
    - AnalyzeExpense is designed for receipts/invoices and usually outperforms
      plain OCR + regex for totals/dates/vendor names.
    - Textract returns many fields; we normalize just what we need.
    """
    try:
        resp = _textract.analyze_expense(
            Document={"S3Object": {"Bucket": bucket, "Name": key}}
        )
        return normalize_analyze_expense(resp)
    except Exception as e:
        # Fallback: OCR lines + regex heuristics
        logger.warning("AnalyzeExpense failed, falling back to DetectDocumentText: %s", e)
        raw_text = extract_text_lines(bucket, key)
        parsed = parse_receipt_text(raw_text)
        return {
            "vendor": parsed.get("vendor"),
            "date": parsed.get("date"),
            "totalAmount": parsed.get("total"),
            "currency": parsed.get("currency"),
        }


def extract_text_lines(bucket: str, key: str) -> str:
    """Fallback OCR: DetectDocumentText and join LINE blocks into plain text."""
    response = _textract.detect_document_text(
        Document={"S3Object": {"Bucket": bucket, "Name": key}}
    )
    lines = []
    for block in response.get("Blocks", []):
        if block.get("BlockType") == "LINE":
            lines.append(block.get("Text", ""))
    return "\n".join(lines)


def normalize_analyze_expense(resp: dict) -> dict:
    """
    Convert Textract AnalyzeExpense response into the receipt fields we store.
    """
    vendor = None
    date = None
    total_amount = None
    currency = None

    for doc in resp.get("ExpenseDocuments", []):
        for field in doc.get("SummaryFields", []):
            ftype = (field.get("Type", {}).get("Text") or "").upper()
            value = (field.get("ValueDetection", {}).get("Text") or "").strip()
            if not value:
                continue

            # Common types: VENDOR_NAME, TOTAL, INVOICE_RECEIPT_DATE, SUBTOTAL, TAX, TIP...
            if ftype == "VENDOR_NAME" and not vendor:
                vendor = value
            elif ftype in ("INVOICE_RECEIPT_DATE", "RECEIPT_DATE") and not date:
                date = normalise_date(value)
            elif ftype == "TOTAL" and not total_amount:
                # Value may contain currency symbol; keep currency separately.
                currency = currency or infer_currency(value)
                total_amount = normalize_amount(value)

        # If multiple docs, keep the first best match.
        if vendor or date or total_amount:
            break

    return {
        "vendor": vendor,
        "date": date,
        "totalAmount": total_amount,
        "currency": currency or "INR",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PARSER  — extracts vendor, date, total from raw OCR text
# ═══════════════════════════════════════════════════════════════════════════════
def parse_receipt_text(text: str) -> dict:
    """
    Heuristic parser for common Indian receipt formats.
    Returns a dict with keys: vendor, date, total, currency.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    result = {}

    # ── Vendor: usually the first non-empty line
    if lines:
        result['vendor'] = lines[0][:120]  # cap at 120 chars

    # ── Date patterns: DD/MM/YYYY, YYYY-MM-DD, DD-MM-YYYY, DD MMM YYYY
    date_patterns = [
        r'\b(\d{4}-\d{2}-\d{2})\b',                         # ISO
        r'\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\b',          # DD/MM/YY or DD-MM-YYYY
        r'\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{2,4})\b',
    ]
    for pattern in date_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            result['date'] = normalise_date(m.group(1))
            break

    # ── Total amount — look for keywords near a number
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
        # Fallback: find the largest currency-looking number in the text
        amounts = re.findall(r'(?:rs\.?|inr|₹|usd|\$)\s*([0-9,]+(?:\.\d{1,2})?)', text, re.IGNORECASE)
        if not amounts:
            amounts = re.findall(r'\b([0-9]{1,6}(?:,[0-9]{3})*(?:\.\d{1,2})?)\b', text)
        if amounts:
            parsed_amounts = [float(a.replace(',','')) for a in amounts]
            result['total'] = f"{max(parsed_amounts):.2f}"

    # ── Currency detection
    if re.search(r'₹|inr|rs\.?', text, re.IGNORECASE):
        result['currency'] = 'INR'
    elif re.search(r'\$|usd', text, re.IGNORECASE):
        result['currency'] = 'USD'
    else:
        result['currency'] = 'INR'  # default for India

    return result


def normalize_amount(value: str) -> str:
    """
    Normalize an amount string to a plain 2-decimal numeric string.
    Examples: "₹ 1,234.5" -> "1234.50"
    """
    # Keep digits, commas, and decimals; remove everything else.
    cleaned = re.sub(r"[^0-9\.,]", "", value or "").strip()
    cleaned = cleaned.replace(",", "")
    if not cleaned:
        return ""
    try:
        return f"{float(cleaned):.2f}"
    except ValueError:
        return ""


def infer_currency(text: str) -> str:
    """Best-effort currency detection from a value string."""
    if re.search(r"₹|inr|rs\.?", text, re.IGNORECASE):
        return "INR"
    if re.search(r"\$|usd", text, re.IGNORECASE):
        return "USD"
    if re.search(r"eur|€", text, re.IGNORECASE):
        return "EUR"
    if re.search(r"gbp|£", text, re.IGNORECASE):
        return "GBP"
    return "INR"


def normalise_date(raw: str) -> str:
    """Attempt to convert various date strings to YYYY-MM-DD."""
    raw = raw.strip()
    # Already ISO
    if re.match(r'^\d{4}-\d{2}-\d{2}$', raw):
        return raw
    # DD/MM/YYYY or DD-MM-YYYY
    m = re.match(r'^(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})$', raw)
    if m:
        d, mo, y = m.group(1), m.group(2), m.group(3)
        if len(y) == 2:
            y = '20' + y
        return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
    # Try with datetime for "28 Apr 2024"
    for fmt in ('%d %b %Y', '%d %B %Y', '%d %b %y'):
        try:
            return datetime.strptime(raw, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return raw  # return as-is if we can't parse


def detect_category(vendor: str) -> str:
    """Rule-based category detection from vendor name."""
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


# ═══════════════════════════════════════════════════════════════════════════════
# DYNAMODB
# ═══════════════════════════════════════════════════════════════════════════════
def save_to_dynamodb(item: dict):
    """Write the receipt record to DynamoDB."""
    table = _dynamodb.Table(DYNAMODB_TABLE)
    table.put_item(Item=item)

def put_result_json(bucket: str, key: str, payload: dict):
    """
    Store a small JSON result object in S3 so a static frontend can retrieve it.
    Bucket-level default encryption should handle SSE; we also request AES256 here.
    """
    _s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
        CacheControl="no-store",
        ServerSideEncryption="AES256",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SES  — send formatted email
# ═══════════════════════════════════════════════════════════════════════════════
def send_ses_email(recipient: str, item: dict):
    """
    Send a receipt summary email via Amazon SES.
    Both HTML and plain-text bodies are included for compatibility.
    """
    subject = f"Receipt Processed: {item.get('vendor','Unknown')} — {item.get('currency','')} {item.get('totalAmount','')}"

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#f5f5f5; margin:0; padding:0; }}
    .card {{ max-width:560px; margin:40px auto; background:#fff; border-radius:16px; overflow:hidden; box-shadow:0 4px 24px rgba(0,0,0,0.1); }}
    .header {{ background:linear-gradient(135deg,#6C63FF,#4F46E5); padding:32px; color:#fff; }}
    .header h1 {{ margin:0 0 8px; font-size:22px; }}
    .header p  {{ margin:0; opacity:0.85; font-size:13px; }}
    .body {{ padding:28px 32px; }}
    .field {{ display:flex; justify-content:space-between; padding:12px 0; border-bottom:1px solid #eee; }}
    .field:last-child {{ border-bottom:none; }}
    .label {{ color:#666; font-size:13px; }}
    .value {{ font-weight:600; font-size:14px; color:#111; }}
    .amount {{ color:#10B981; font-size:18px; font-weight:800; }}
    .footer {{ background:#f9f9f9; padding:20px 32px; font-size:12px; color:#999; text-align:center; }}
    .badge {{ display:inline-block; background:#EDE9FE; color:#6C63FF; padding:3px 12px; border-radius:20px; font-size:12px; font-weight:600; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <h1>&#10003; Receipt Processed</h1>
      <p>Your receipt has been scanned, extracted, and saved to DynamoDB.</p>
    </div>
    <div class="body">
      <div class="field"><span class="label">Receipt ID</span><span class="value" style="font-family:monospace;font-size:12px">{item.get('receiptId')}</span></div>
      <div class="field"><span class="label">Vendor</span><span class="value">{item.get('vendor','—')}</span></div>
      <div class="field"><span class="label">Date</span><span class="value">{item.get('date','—')}</span></div>
      <div class="field"><span class="label">Total Amount</span><span class="value amount">{item.get('currency','')} {item.get('totalAmount','—')}</span></div>
      <div class="field"><span class="label">Category</span><span class="value"><span class="badge">{item.get('category','General')}</span></span></div>
      <div class="field"><span class="label">S3 Key</span><span class="value" style="font-family:monospace;font-size:11px">{item.get('s3Key','—')}</span></div>
      <div class="field"><span class="label">Processed At</span><span class="value">{item.get('uploadedAt','—')}</span></div>
    </div>
    <div class="footer">
      Processed by ReceiptAI &bull; AWS Textract &bull; Data stored securely in DynamoDB
    </div>
  </div>
</body>
</html>
"""

    text_body = f"""Receipt Processed Successfully

Receipt ID   : {item.get('receiptId')}
Vendor       : {item.get('vendor','—')}
Date         : {item.get('date','—')}
Total Amount : {item.get('currency','')} {item.get('totalAmount','—')}
Category     : {item.get('category','General')}
S3 Key       : {item.get('s3Key','—')}
Processed At : {item.get('uploadedAt','—')}

Processed by ReceiptAI | AWS Textract | DynamoDB
"""

    _ses.send_email(
        Source=SES_SENDER_EMAIL,
        Destination={'ToAddresses': [recipient]},
        Message={
            'Subject': {'Data': subject, 'Charset': 'UTF-8'},
            'Body': {
                'Text': {'Data': text_body, 'Charset': 'UTF-8'},
                'Html': {'Data': html_body, 'Charset': 'UTF-8'},
            },
        },
    )
