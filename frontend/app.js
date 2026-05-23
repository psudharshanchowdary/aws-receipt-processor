/**
 * app.js — AWS Receipt Processor Frontend Logic
 * Handles: local API auto-detection, direct Flask API upload (Docker mode),
 * S3 upload via Cognito temporary credentials (AWS mode), pipeline status display,
 * results rendering, raw OCR text display, localStorage history.
 */

'use strict';

// ─── State ────────────────────────────────────────────────────────────────────
const state = {
  file: null,
  processing: false,
  history: JSON.parse(localStorage.getItem('receiptHistory') || '[]'),
};

let detectedApiUrl = '';
let isDockerMode = false;

// ─── DOM refs ─────────────────────────────────────────────────────────────────
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const browseBtn = document.getElementById('browseBtn');
const removeFileBtn = document.getElementById('removeFileBtn');
const filePreview = document.getElementById('filePreview');
const previewImage = document.getElementById('previewImage');
const previewName = document.getElementById('previewName');
const previewSize = document.getElementById('previewSize');
const uploadBtn = document.getElementById('uploadBtn');
const uploadBtnText = document.querySelector('.btn-upload-text');
const uploadBtnLoad = document.querySelector('.btn-upload-loading');
const tryDemoBtn = document.getElementById('tryDemoBtn');

// Mode Banner & Config Panel
const modeBanner = document.getElementById('modeBanner');
const modeIcon = document.getElementById('modeIcon');
const modeTitle = document.getElementById('modeTitle');
const modeDesc = document.getElementById('modeDesc');
const toggleConfigBtn = document.getElementById('toggleConfigBtn');
const configPanel = document.getElementById('configPanel');
const logoBadge = document.getElementById('logoBadge');
const statusText = document.getElementById('statusText');

// Config Inputs
const apiUrlInput = document.getElementById('apiUrlInput');
const awsRegionEl = document.getElementById('awsRegion');
const s3BucketEl = document.getElementById('s3Bucket');
const identityPoolEl = document.getElementById('identityPoolId');
const emailInput = document.getElementById('emailInput');

// Results & History
const emptyState = document.getElementById('emptyState');
const resultsGrid = document.getElementById('resultsGrid');
const historySection = document.getElementById('historySection');
const historyBody = document.getElementById('historyTableBody');
const clearHistoryBtn = document.getElementById('clearHistoryBtn');
const copyJsonBtn = document.getElementById('copyJsonBtn');
const jsonView = document.getElementById('jsonView');
const ocrCard = document.getElementById('ocrCard');
const ocrView = document.getElementById('ocrView');

// Pipeline Step Overrides for local mode
const stepNameTrigger = document.getElementById('stepNameTrigger');
const stepIconTrigger = document.getElementById('stepIconTrigger');
const stepNameOcr = document.getElementById('stepNameOcr');
const stepIconOcr = document.getElementById('stepIconOcr');

// ─── File handling ────────────────────────────────────────────────────────────
browseBtn.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', (e) => {
  if (e.target.files[0]) setFile(e.target.files[0]);
});

dropZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropZone.classList.add('drag-over');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
});

dropZone.addEventListener('click', (e) => {
  if (e.target !== browseBtn && e.target !== tryDemoBtn) fileInput.click();
});

removeFileBtn.addEventListener('click', clearFile);

function setFile(file) {
  const maxBytes = 10 * 1024 * 1024;
  if (file.size > maxBytes) {
    showToast('File too large. Maximum size is 10 MB.', 'error');
    return;
  }
  const allowed = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'application/pdf'];
  if (!allowed.includes(file.type)) {
    showToast('Unsupported file type. Use JPG, PNG, or PDF.', 'error');
    return;
  }

  state.file = file;
  previewName.textContent = file.name;
  previewSize.textContent = formatBytes(file.size);

  if (file.type.startsWith('image/')) {
    const reader = new FileReader();
    reader.onload = (e) => {
      previewImage.src = e.target.result;
      previewImage.style.display = 'block';
    };
    reader.readAsDataURL(file);
  } else {
    previewImage.style.display = 'none';
  }

  dropZone.classList.add('hidden');
  filePreview.classList.remove('hidden');
  uploadBtn.disabled = false;
}

function clearFile() {
  state.file = null;
  fileInput.value = '';
  dropZone.classList.remove('hidden');
  filePreview.classList.add('hidden');
  uploadBtn.disabled = true;
}

// ─── Mode Switching Logic ─────────────────────────────────────────────────────
toggleConfigBtn.addEventListener('click', () => {
  configPanel.classList.toggle('hidden');
  toggleConfigBtn.textContent = configPanel.classList.contains('hidden') ? 'Show Settings' : 'Hide Settings';
});

function updateUiForDockerMode() {
  logoBadge.textContent = '🐳 Docker';
  logoBadge.style.background = 'rgba(6, 182, 212, 0.2)';
  logoBadge.style.color = 'var(--cyan)';
  logoBadge.style.borderColor = 'rgba(6, 182, 212, 0.3)';

  statusText.textContent = 'Local Services Online';

  modeBanner.className = 'mode-banner local';
  modeIcon.textContent = '🐳';
  modeTitle.textContent = 'Local Docker Mode Active';
  modeDesc.textContent = 'Docker stack detected at ' + detectedApiUrl + '. Processing is performed locally using Tesseract OCR & LocalStack.';

  // Adjust pipeline labels for local mode
  stepNameTrigger.textContent = 'Flask API';
  stepIconTrigger.innerHTML = '⚙️';
  stepNameOcr.textContent = 'Tesseract OCR';
  stepIconOcr.innerHTML = '🔎';

  ocrEngineTag.textContent = 'Tesseract';
}

function updateUiForAwsMode() {
  logoBadge.textContent = '☁️ AWS Mode';
  logoBadge.style.background = 'rgba(108, 99, 255, 0.2)';
  logoBadge.style.color = 'var(--purple-light)';
  logoBadge.style.borderColor = 'rgba(108, 99, 255, 0.3)';

  statusText.textContent = 'AWS Mode (Manual)';

  modeBanner.className = 'mode-banner aws';
  modeIcon.textContent = '☁️';
  modeTitle.textContent = 'AWS Cloud Mode Active';
  modeDesc.textContent = 'Running directly against your AWS infrastructure. Enter S3, Cognito and Region parameters below.';

  configPanel.classList.remove('hidden');
  toggleConfigBtn.textContent = 'Hide Settings';

  // Adjust pipeline labels for AWS mode
  stepNameTrigger.textContent = 'Lambda Trigger';
  stepIconTrigger.innerHTML = '⚡';
  stepNameOcr.textContent = 'Textract OCR';
  stepIconOcr.innerHTML = '📝';

  ocrEngineTag.textContent = 'AWS Textract';
}

// ─── Upload Handler ───────────────────────────────────────────────────────────
uploadBtn.addEventListener('click', handleUpload);

async function handleUpload() {
  if (!state.file || state.processing) return;

  if (isDockerMode) {
    await runDockerPipeline();
  } else {
    await runAwsPipeline();
  }
}

// ─── Docker Mode Pipeline ─────────────────────────────────────────────────────
async function runDockerPipeline() {
  state.processing = true;
  setButtonLoading(true);
  resetPipeline();

  try {
    setStep('upload', 'active', 'Uploading…');

    // Create form data
    const formData = new FormData();
    formData.append('file', state.file);
    if (emailInput.value.trim()) {
      formData.append('email', emailInput.value.trim());
    }

    const uploadUrl = apiUrlInput.value.trim() || detectedApiUrl;

    // Simulate pipeline steps animation
    setTimeout(() => {
      if (state.processing) {
        setStep('upload', 'done', 'Uploaded');
        setStep('lambda', 'active', 'Running...');
      }
    }, 800);

    setTimeout(() => {
      if (state.processing) {
        setStep('lambda', 'done', 'Finished');
        setStep('textract', 'active', 'Scanning...');
      }
    }, 1800);

    // Call local Flask endpoint
    const response = await fetch(`${uploadUrl}/upload`, {
      method: 'POST',
      body: formData
    });

    if (!response.ok) {
      throw new Error(`Server returned status ${response.status}`);
    }

    const data = await response.json();
    if (data.status === 'error') {
      throw new Error(data.message || 'Server error occurred');
    }

    // Complete pipeline animation
    setStep('upload', 'done', 'Uploaded');
    setStep('lambda', 'done', 'Finished');
    setStep('textract', 'done', 'Completed');
    setStep('dynamodb', 'active', 'Saving...');

    setTimeout(() => {
      setStep('dynamodb', 'done', 'Saved');
      setStep('ses', 'done', 'Sent');

      renderResults(data);
      addToHistory(data);
      showToast('Bill processed successfully locally!', 'success');
      clearFile();
    }, 800);

  } catch (err) {
    console.error(err);
    setCurrentActiveStep('error', 'Failed');
    showToast(`Upload failed: ${err.message}`, 'error');
  } finally {
    setTimeout(() => {
      state.processing = false;
      setButtonLoading(false);
    }, 1000);
  }
}

// ─── AWS Cloud Mode Pipeline ──────────────────────────────────────────────────
async function runAwsPipeline() {
  const region = (awsRegionEl.value.trim() || 'ap-south-1').trim();
  const bucket = s3BucketEl.value.trim();
  const identityPoolId = identityPoolEl.value.trim();

  if (!bucket) { showToast('Please enter your S3 bucket name.', 'error'); return; }
  if (!identityPoolId) { showToast('Please enter your Cognito Identity Pool ID.', 'error'); return; }

  state.processing = true;
  setButtonLoading(true);
  resetPipeline();

  try {
    setStep('upload', 'active', 'Uploading…');

    const receiptId = (crypto && typeof crypto.randomUUID === 'function')
      ? crypto.randomUUID()
      : `rcpt-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

    const safeName = sanitizeFilename(state.file.name);
    const objectKey = `receipts/${receiptId}-${safeName}`;
    const resultKey = `results/${receiptId}.json`;

    // AWS SDK direct S3 Upload
    const s3 = await createS3Client({ region, identityPoolId });
    await putReceiptObject({ s3, bucket, key: objectKey, file: state.file });

    setStep('upload', 'done', 'Uploaded');

    // Poll for results generated by Lambda trigger
    setStep('lambda', 'active', 'Triggering…');
    setStep('textract', 'active', 'Scanning…');
    setStep('dynamodb', 'active', 'Saving…');
    setStep('ses', 'active', 'Notifying…');

    const responseData = await pollForResultJson({ s3, bucket, resultKey, timeoutMs: 120000 });

    setStep('lambda', 'done', 'Triggered');
    setStep('textract', 'done', 'Completed');
    setStep('dynamodb', 'done', 'Saved');
    setStep('ses', 'done', 'Sent');

    renderResults(responseData);
    addToHistory(responseData);
    showToast('Receipt processed successfully in cloud!', 'success');
    clearFile();

  } catch (err) {
    console.error(err);
    setCurrentActiveStep('error', 'Failed');
    showToast(`AWS Error: ${err.message}`, 'error');
  } finally {
    state.processing = false;
    setButtonLoading(false);
  }
}

// ─── Demo Mode (Offline Simulator) ────────────────────────────────────────────
tryDemoBtn.addEventListener('click', runDemo);

async function runDemo() {
  if (state.processing) return;

  state.processing = true;
  setButtonLoading(true);
  resetPipeline();

  showToast('Simulating Receipt Processing Pipeline...', 'info');

  try {
    setStep('upload', 'active', 'Uploading receipt...');
    await delay(1200);
    setStep('upload', 'done', 'Uploaded');

    setStep('lambda', 'active', isDockerMode ? 'Invoking API...' : 'Triggering Lambda...');
    await delay(1000);
    setStep('lambda', 'done', 'Completed');

    setStep('textract', 'active', isDockerMode ? 'Running Tesseract OCR...' : 'Running Textract...');
    await delay(1500);
    setStep('textract', 'done', 'Parsed Text');

    setStep('dynamodb', 'active', 'Writing record...');
    await delay(800);
    setStep('dynamodb', 'done', 'Saved');

    setStep('ses', 'active', 'Sending confirmation...');
    await delay(600);
    setStep('ses', 'done', 'Sent');

    // Mock response payload
    const demoData = {
      status: "success",
      receipt: {
        receiptId: `rcpt-${Math.random().toString(36).substr(2, 9)}`,
        vendor: "Reliance Fresh",
        date: new Date().toISOString().split('T')[0],
        totalAmount: "866.25",
        currency: "INR",
        category: "Groceries",
        uploadedAt: new Date().toISOString(),
        s3Key: "receipts/demo-reliance-fresh.png",
        rawText: "RELIANCE FRESH\nStore #4561, Bangalore\nGSTIN: 29AABCR1234\n------------------\n1. Basmati Rice 5kg   450.00\n2. Amul Butter 500g   275.00\n3. Fortune Sunflower Oil  141.25\n------------------\nSUBTOTAL:             866.25\nTOTAL AMOUNT:         866.25\n------------------\nThank you for shopping!\n"
      }
    };

    renderResults(demoData);
    addToHistory(demoData);
    showToast('Demo simulated successfully!', 'success');

  } catch (e) {
    showToast(`Demo failed: ${e.message}`, 'error');
  } finally {
    state.processing = false;
    setButtonLoading(false);
  }
}

// ─── UI Render Helpers ────────────────────────────────────────────────────────
function renderResults(data) {
  const r = data.receipt || data;

  document.getElementById('fieldReceiptId').textContent = r.receiptId || '—';
  document.getElementById('fieldVendor').textContent = r.vendor || '—';
  document.getElementById('fieldDate').textContent = r.date || '—';
  document.getElementById('fieldAmount').textContent = r.totalAmount ? `${r.currency || ''} ${r.totalAmount}` : '—';
  document.getElementById('fieldCurrency').textContent = r.currency || '—';
  document.getElementById('fieldS3Key').textContent = r.s3Key || '—';
  document.getElementById('resultTimestamp').textContent = r.uploadedAt ? new Date(r.uploadedAt).toLocaleString() : new Date().toLocaleString();

  // Category badge
  const cat = r.category || 'General';
  document.getElementById('categoryBadge').textContent = cat;

  // Raw OCR Text
  ocrView.textContent = r.rawText || "No raw text extracted.";
  ocrCard.classList.remove('hidden');

  // DynamoDB JSON
  const dbRecord = {
    receiptId: r.receiptId,
    vendor: r.vendor,
    date: r.date,
    totalAmount: r.totalAmount,
    currency: r.currency,
    category: cat,
    uploadedAt: r.uploadedAt,
    s3Key: r.s3Key,
  };
  jsonView.textContent = JSON.stringify(dbRecord, null, 2);

  emptyState.classList.add('hidden');
  resultsGrid.classList.remove('hidden');
}

// ─── History Helpers ──────────────────────────────────────────────────────────
function addToHistory(data) {
  const r = data.receipt || data;
  const entry = {
    receiptId: r.receiptId,
    vendor: r.vendor || '—',
    date: r.date || '—',
    totalAmount: r.totalAmount || '—',
    currency: r.currency || '',
    category: r.category || 'General',
    status: 'ok',
    ts: Date.now(),
  };
  state.history.unshift(entry);
  if (state.history.length > 50) state.history.pop();
  localStorage.setItem('receiptHistory', JSON.stringify(state.history));
  renderHistory();
}

function renderHistory() {
  if (!state.history.length) { historySection.classList.add('hidden'); return; }
  historySection.classList.remove('hidden');
  historyBody.innerHTML = state.history.map(h => `
    <tr>
      <td class="mono" style="font-size:0.7rem">${h.receiptId || '—'}</td>
      <td>${h.vendor}</td>
      <td>${h.date}</td>
      <td style="font-weight:700;color:#10B981">${h.currency} ${h.totalAmount}</td>
      <td>${h.category}</td>
      <td><span class="status-pill ${h.status === 'ok' ? 'ok' : 'err'}">${h.status === 'ok' ? 'Success' : 'Failed'}</span></td>
    </tr>
  `).join('');
}

clearHistoryBtn.addEventListener('click', () => {
  state.history = [];
  localStorage.removeItem('receiptHistory');
  renderHistory();
  historySection.classList.add('hidden');
  showToast('History cleared.', 'info');
});

copyJsonBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(jsonView.textContent).then(() => {
    copyJsonBtn.textContent = 'Copied!';
    setTimeout(() => { copyJsonBtn.textContent = 'Copy JSON'; }, 1800);
  });
});

// ─── Pipeline State Helpers ───────────────────────────────────────────────────
const pipelineSteps = ['upload', 'lambda', 'textract', 'dynamodb', 'ses'];
let currentStep = null;

function resetPipeline() {
  pipelineSteps.forEach(id => {
    const el = document.getElementById(`step-${id}`);
    el.classList.remove('active', 'done', 'error');
    el.querySelector('.step-status').textContent = 'Waiting';
  });
  currentStep = null;
}

function setStep(id, state, label) {
  currentStep = id;
  const el = document.getElementById(`step-${id}`);
  el.classList.remove('active', 'done', 'error');
  el.classList.add(state);
  el.querySelector('.step-status').textContent = label;
}

function setCurrentActiveStep(cls, label) {
  if (!currentStep) return;
  setStep(currentStep, cls, label);
}

// ─── AWS SDK Client Helpers ───────────────────────────────────────────────────
async function createS3Client({ region, identityPoolId }) {
  if (!window.AWS || !AWS.CognitoIdentityCredentials) {
    throw new Error('AWS SDK not loaded. Please reload.');
  }
  AWS.config.region = region;
  AWS.config.credentials = new AWS.CognitoIdentityCredentials({ IdentityPoolId: identityPoolId });
  await new Promise((resolve, reject) => {
    AWS.config.credentials.get((err) => (err ? reject(err) : resolve()));
  });
  return new AWS.S3({ apiVersion: '2006-03-01', region });
}

async function putReceiptObject({ s3, bucket, key, file }) {
  const params = {
    Bucket: bucket,
    Key: key,
    Body: file,
    ContentType: file.type || 'application/octet-stream',
    ServerSideEncryption: 'AES256',
  };
  await s3.putObject(params).promise();
}

async function pollForResultJson({ s3, bucket, resultKey, timeoutMs }) {
  const start = Date.now();
  const pollEveryMs = 2000;

  while (Date.now() - start < timeoutMs) {
    try {
      const obj = await s3.getObject({ Bucket: bucket, Key: resultKey }).promise();
      const text = new TextDecoder('utf-8').decode(obj.Body);
      const data = JSON.parse(text);

      if (data && data.status === 'error') {
        throw new Error(data.message || 'Processing failed.');
      }
      return data;
    } catch (e) {
      const code = e && (e.code || e.name);
      if (code === 'NoSuchKey' || code === 'NotFound') {
        await delay(pollEveryMs);
        continue;
      }
      throw new Error(e.message || String(e));
    }
  }
  throw new Error('Timed out waiting for processing result.');
}

// ─── Utilities ────────────────────────────────────────────────────────────────
function setButtonLoading(loading) {
  uploadBtn.disabled = loading;
  uploadBtnText.classList.toggle('hidden', loading);
  uploadBtnLoad.classList.toggle('hidden', !loading);
}

document.getElementById('dynamoAdminLink').addEventListener('click', (e) => {
  if (!isDockerMode) {
    e.preventDefault();
    showToast('DynamoDB Admin is only available in Docker mode.', 'info');
  }
});

function sanitizeFilename(name) {
  return (name || 'receipt')
    .replace(/[/\\?%*:|"<>]/g, '-')
    .replace(/\s+/g, '-')
    .slice(0, 120);
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

function showToast(msg, type = 'info') {
  const icons = { success: '✓', error: '✕', info: 'ℹ' };
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span class="toast-icon">${icons[type]}</span><span class="toast-msg">${msg}</span>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// ─── Auto-Detect Local API ───────────────────────────────────────────────────
async function detectLocalApi() {
  const savedUrl = localStorage.getItem('receiptApiUrl');
  const urlsToCheck = savedUrl ? [savedUrl] : ['http://localhost:8000', 'http://127.0.0.1:8000'];

  for (const url of urlsToCheck) {
    try {
      const res = await fetch(`${url}/health`, { method: 'GET', mode: 'cors' });
      if (res.ok) {
        const data = await res.json();
        if (data.status === 'ok') {
          detectedApiUrl = url;
          isDockerMode = true;
          apiUrlInput.value = url;
          localStorage.setItem('receiptApiUrl', url);
          updateUiForDockerMode();
          return;
        }
      }
    } catch (e) {
      // Ignored
    }
  }

  try {
    const res = await fetch('/api/health');
    if (res.ok) {
      const data = await res.json();
      if (data.status === 'ok') {
        detectedApiUrl = '/api';
        isDockerMode = true;
        apiUrlInput.value = '/api';
        updateUiForDockerMode();
        return;
      }
    }
  } catch (e) {
    // Ignored
  }

  updateUiForAwsMode();
}

// ─── Init ─────────────────────────────────────────────────────────────────────
(function init() {
  renderHistory();

  // Restore saved config
  const savedRegion = localStorage.getItem('receiptAwsRegion');
  const savedBucket = localStorage.getItem('receiptS3Bucket');
  const savedPoolId = localStorage.getItem('receiptIdentityPoolId');
  const savedEmail = localStorage.getItem('receiptEmail');

  if (savedRegion) awsRegionEl.value = savedRegion;
  if (savedBucket) s3BucketEl.value = savedBucket;
  if (savedPoolId) identityPoolEl.value = savedPoolId;
  if (savedEmail) emailInput.value = savedEmail;

  // Persist config changes
  awsRegionEl.addEventListener('input', () => localStorage.setItem('receiptAwsRegion', awsRegionEl.value.trim()));
  s3BucketEl.addEventListener('input', () => localStorage.setItem('receiptS3Bucket', s3BucketEl.value.trim()));
  identityPoolEl.addEventListener('input', () => localStorage.setItem('receiptIdentityPoolId', identityPoolEl.value.trim()));
  emailInput.addEventListener('input', () => localStorage.setItem('receiptEmail', emailInput.value.trim()));
  apiUrlInput.addEventListener('input', () => {
    localStorage.setItem('receiptApiUrl', apiUrlInput.value.trim());
    detectLocalApi();
  });

  detectLocalApi();
})();
