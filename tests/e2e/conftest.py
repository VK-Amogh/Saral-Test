"""
Saral AI — End-to-End Test Suite Configuration and Fixtures
File: tests/e2e/conftest.py

Provides:
- Dual-mode execution harness (Specification Oracle or Live Server)
- Standardized test fixtures and test credentials
- High-level SaralApiClient and MockPortalClient
- Verhoeff algorithm verification and PII scrubbing rules
- Deterministic 12-state task machine engine
- 5-point document security verifier
"""

import os
import sys
import json
import time
import uuid
import re
import io
import hashlib
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.error
import pytest

# ---------------------------------------------------------------------------
# Verhoeff Dihedral D5 Algorithm Implementation
# ---------------------------------------------------------------------------

D_TABLE = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
]

P_TABLE = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]
]

INV_TABLE = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]

def validate_verhoeff(num_str: str) -> bool:
    digits = [int(c) for c in num_str if c.isdigit()]
    if not digits:
        return False
    c = 0
    for i, digit in enumerate(reversed(digits)):
        c = D_TABLE[c][P_TABLE[i % 8][digit]]
    return c == 0

def compute_verhoeff_checksum(num_str: str) -> int:
    digits = [int(c) for c in num_str if c.isdigit()]
    c = 0
    for i, digit in enumerate(reversed(digits)):
        c = D_TABLE[c][P_TABLE[(i + 1) % 8][digit]]
    return INV_TABLE[c]

def generate_valid_aadhaar(prefix_11_digits: str = "23456789012") -> str:
    cs = compute_verhoeff_checksum(prefix_11_digits)
    return f"{prefix_11_digits}{cs}"

# ---------------------------------------------------------------------------
# PII Scrubber Function
# ---------------------------------------------------------------------------

def scrub_pii(text: str) -> str:
    """Scrub Aadhaar/VID, phone numbers, emails, biometric terms, and OTPs."""
    scrubbed = text

    # Scrub 12-digit potential Aadhaar numbers if Verhoeff validates
    def aadhaar_replacer(m):
        raw = m.group(0).replace(" ", "").replace("-", "")
        if validate_verhoeff(raw):
            return f"XXXX-XXXX-{raw[-4:]}"
        return m.group(0)

    scrubbed = re.sub(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b", aadhaar_replacer, scrubbed)

    # Phone numbers
    scrubbed = re.sub(r"(?:\+91[ -]?)?[6-9]\d{9}\b", "[REDACTED_PHONE]", scrubbed)

    # Emails
    scrubbed = re.sub(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "[REDACTED_EMAIL]", scrubbed)

    # Biometrics
    scrubbed = re.sub(r"\b(fingerprint|iris|retina|biometrics?)\b", "[REDACTED_BIOMETRIC]", scrubbed, flags=re.IGNORECASE)

    # OTPs near keywords
    scrubbed = re.sub(r"(?i)\b(otp|code|pin)\b\s*(?:is|:)?\s*(\d{4,8})\b", r"\1 [REDACTED_OTP]", scrubbed)

    return scrubbed

# ---------------------------------------------------------------------------
# 5-Point Document Security Verifier
# ---------------------------------------------------------------------------

@dataclass
class VerifierResult:
    is_valid: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    sha256: Optional[str] = None
    size_bytes: int = 0
    pdf_encrypted: bool = False

def verify_document_security(content: bytes, max_size_mb: int = 5) -> VerifierResult:
    size = len(content)
    # Stage 1: %PDF- Header
    if not content.startswith(b"%PDF-"):
        return VerifierResult(False, "INVALID_PDF_HEADER", "Payload does not start with %PDF- header", size_bytes=size)

    # Stage 2: Size limits (100 bytes to max_size_mb)
    if size < 100:
        return VerifierResult(False, "TRUNCATED_PDF", "PDF payload is too small or truncated", size_bytes=size)
    if size > max_size_mb * 1024 * 1024:
        return VerifierResult(False, "OVERSIZE_PDF", f"PDF size {size} exceeds max threshold {max_size_mb}MB", size_bytes=size)

    # Stage 3: PDF trailer/xref marker
    if b"%%EOF" not in content:
        return VerifierResult(False, "MALFORMED_PDF_TRAILER", "Missing %%EOF marker in PDF payload", size_bytes=size)

    # Stage 4: Malicious action checks (/JavaScript, /Launch)
    if b"/JavaScript" in content or b"/JS" in content:
        return VerifierResult(False, "MALICIOUS_PDF_JAVASCRIPT", "Forbidden /JavaScript action dictionary detected", size_bytes=size)
    if b"/Launch" in content:
        return VerifierResult(False, "MALICIOUS_PDF_LAUNCH", "Forbidden /Launch action dictionary detected", size_bytes=size)

    # Stage 5: Hash & encryption determination
    is_encrypted = b"/Encrypt" in content
    digest = hashlib.sha256(content).hexdigest()
    return VerifierResult(True, sha256=digest, size_bytes=size, pdf_encrypted=is_encrypted)

# ---------------------------------------------------------------------------
# Test Credentials & Constants
# ---------------------------------------------------------------------------

TEST_PRIMARY_USER_ID = "usr_primary_88e36780"
TEST_PRIMARY_TOKEN = "jwt_bearer_valid_token_primary_usr_primary_88e36780"

TEST_SECONDARY_USER_ID = "usr_secondary_99f45610"
TEST_SECONDARY_TOKEN = "jwt_bearer_valid_token_secondary_usr_secondary_99f45610"

WORKER_SHARED_SECRET = "saral_worker_shared_secret_secure_key_9988"
CLEANUP_SECRET = "saral_cleanup_cron_secret_auth_token_7766"

ALLOWED_DOMAINS = ["mock-portal.local", "127.0.0.1", "localhost", "uidai.gov.in"]

# ---------------------------------------------------------------------------
# In-Memory Specification Oracle Database & State Store
# ---------------------------------------------------------------------------

class OracleDatabase:
    """In-memory state container simulating Postgres, RLS, Storage, and Broker."""
    def __init__(self):
        self.lock = threading.Lock()
        self.users = {
            TEST_PRIMARY_USER_ID: {"email": "citizen1@example.com"},
            TEST_SECONDARY_USER_ID: {"email": "citizen2@example.com"}
        }
        self.tokens = {
            TEST_PRIMARY_TOKEN: TEST_PRIMARY_USER_ID,
            TEST_SECONDARY_TOKEN: TEST_SECONDARY_USER_ID
        }
        self.conversations: Dict[str, Dict[str, Any]] = {}
        self.messages: List[Dict[str, Any]] = []
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.task_events: List[Dict[str, Any]] = []
        self.documents: Dict[str, Dict[str, Any]] = {}
        self.storage_objects: Dict[str, bytes] = {} # path -> bytes
        self.challenge_buffer: Dict[str, bytes] = {} # task_id -> CAPTCHA png
        self.pending_otp_relays: Dict[str, str] = {} # task_id -> OTP (cleared immediately)
        self.rate_limit_timestamps: Dict[str, List[float]] = {}
        self.active_workflows_per_user: Dict[str, str] = {} # user_id -> task_id

    def reset(self):
        with self.lock:
            self.conversations.clear()
            self.messages.clear()
            self.tasks.clear()
            self.task_events.clear()
            self.documents.clear()
            self.storage_objects.clear()
            self.challenge_buffer.clear()
            self.pending_otp_relays.clear()
            self.rate_limit_timestamps.clear()
            self.active_workflows_per_user.clear()

oracle_db = OracleDatabase()

# ---------------------------------------------------------------------------
# State Machine Engine
# ---------------------------------------------------------------------------

ALLOWED_TRANSITIONS = {
    "RECEIVED": {"VALIDATING", "FAILED", "CANCELLED"},
    "VALIDATING": {"PLANNING", "FAILED", "CANCELLED"},
    "PLANNING": {"RUNNING", "WAITING_FOR_USER", "FAILED", "CANCELLED"},
    "RUNNING": {"WAITING_FOR_USER", "AUTHENTICATING", "DOWNLOADING", "FAILED", "CANCELLED", "EXPIRED"},
    "WAITING_FOR_USER": {"RUNNING", "AUTHENTICATING", "FAILED", "CANCELLED", "EXPIRED"},
    "AUTHENTICATING": {"RUNNING", "WAITING_FOR_USER", "DOWNLOADING", "FAILED", "CANCELLED"},
    "DOWNLOADING": {"VERIFYING", "FAILED", "CANCELLED"},
    "VERIFYING": {"COMPLETED", "FAILED"},
    "COMPLETED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
    "EXPIRED": set()
}

def transition_task(task_id: str, new_status: str, actor: str = "orchestrator", reason: Optional[str] = None) -> Dict[str, Any]:
    with oracle_db.lock:
        if task_id not in oracle_db.tasks:
            raise ValueError(f"Task {task_id} not found")
        task = oracle_db.tasks[task_id]
        curr = task["status"]

        if curr in {"COMPLETED", "FAILED", "CANCELLED", "EXPIRED"}:
            raise ValueError(f"Terminal state {curr} cannot transition to {new_status}")

        if new_status not in ALLOWED_TRANSITIONS.get(curr, set()):
            raise ValueError(f"Illegal transition from {curr} to {new_status}")

        # Only verifier actor can complete
        if new_status == "COMPLETED" and actor != "verifier":
            raise ValueError("Only actor='verifier' can transition to COMPLETED")

        task["status"] = new_status
        task["updated_at"] = time.time()

        # Emit task event for Realtime simulation
        event = {
            "id": str(uuid.uuid4()),
            "task_id": task_id,
            "user_id": task["user_id"],
            "status": new_status,
            "actor": actor,
            "reason": reason,
            "created_at": time.time()
        }
        oracle_db.task_events.append(event)

        # Clear active workflow lock on terminal state
        if new_status in {"COMPLETED", "FAILED", "CANCELLED", "EXPIRED"}:
            u_id = task["user_id"]
            if oracle_db.active_workflows_per_user.get(u_id) == task_id:
                del oracle_db.active_workflows_per_user[u_id]

        return task

# ---------------------------------------------------------------------------
# Mock Portal State & Server
# ---------------------------------------------------------------------------

class MockPortalState:
    def __init__(self):
        self.lock = threading.Lock()
        self.failure_switches: Dict[str, bool] = {
            "wrong_captcha": False,
            "expired_otp": False,
            "wrong_otp_3x": False,
            "corrupt_pdf": False,
            "html_as_pdf": False,
            "oversize_pdf": False,
            "malicious_pdf": False,
            "timeout": False,
            "changed_selectors": False,
            "foreign_redirect": False
        }
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.otp_attempts: Dict[str, int] = {}
        self.otp_timer: Dict[str, float] = {}

    def reset(self):
        with self.lock:
            for k in self.failure_switches:
                self.failure_switches[k] = False
            self.sessions.clear()
            self.otp_attempts.clear()
            self.otp_timer.clear()

mock_portal_state = MockPortalState()

# Minimal valid dummy PDF payload
def build_test_pdf(encrypted: bool = False, malicious: Optional[str] = None, oversize: bool = False, corrupt: bool = False) -> bytes:
    if corrupt:
        return b"NOT_A_PDF_CORRUPT_DATA_STREAM"
    if oversize:
        # Generate 6MB payload (> 5MB threshold)
        return b"%PDF-1.4\n" + (b"A" * (6 * 1024 * 1024)) + b"\n%%EOF"

    encrypt_dict = b"/Encrypt << /Filter /Standard >>" if encrypted else b""
    malicious_dict = b""
    if malicious == "javascript":
        malicious_dict = b"/Names << /JavaScript << /Names [(DocOpen) << /S /JavaScript /JS (app.alert('evil')) >>] >> >>"
    elif malicious == "launch":
        malicious_dict = b"/OpenAction << /S /Launch /F (cmd.exe) >>"

    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R " + malicious_dict + b" >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        + encrypt_dict + b"\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000010 00000 n \n0000000079 00000 n \n0000000136 00000 n \n"
        b"trailer\n<< /Size 4 /Root 1 0 R " + (b"/Encrypt 4 0 R" if encrypted else b"") + b" >>\n"
        b"startxref\n210\n%%EOF\n"
    )
    # Pad to realistic size (~15KB)
    return pdf + (b" " * 15000)

# Minimal 1x1 transparent PNG bytes for CAPTCHA
DUMMY_CAPTCHA_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

# ---------------------------------------------------------------------------
# HTTP Request Handlers (Specification Oracle)
# ---------------------------------------------------------------------------

class SaralApiHandler(BaseHTTPRequestHandler):
    """Specification-compliant HTTP handler for Saral API."""
    def log_message(self, format, *args):
        # Silence default stderr logging for clean pytest output
        pass

    def _get_bearer_user(self) -> Optional[str]:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
            return oracle_db.tokens.get(token)
        return None

    def _send_json(self, status: int, data: Any):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        # Health check
        if path == "/health":
            self._send_json(200, {"status": "ok", "version": "1.0.0", "service": "saral-api"})
            return

        # Tasks / Challenge / Download
        user_id = self._get_bearer_user()
        if not user_id:
            self._send_json(401, {"error": "Unauthorized", "message": "Missing or invalid Supabase JWT"})
            return

        # GET /api/v1/tasks/{id}
        m = re.match(r"^/api/v1/tasks/([a-zA-Z0-9_\-]+)$", path)
        if m:
            task_id = m.group(1)
            with oracle_db.lock:
                task = oracle_db.tasks.get(task_id)
                if not task:
                    self._send_json(404, {"error": "Not Found", "message": "Task does not exist"})
                    return
                if task["user_id"] != user_id:
                    self._send_json(403, {"error": "Forbidden", "message": "Access denied to task owned by another user"})
                    return
                # Return sanitized state without secrets
                sanitized = {
                    "id": task["id"],
                    "workflow": task["workflow"],
                    "status": task["status"],
                    "created_at": task["created_at"],
                    "pending_input": task.get("pending_input")
                }
                self._send_json(200, sanitized)
                return

        # GET /api/v1/tasks/{id}/challenge
        m = re.match(r"^/api/v1/tasks/([a-zA-Z0-9_\-]+)/challenge$", path)
        if m:
            task_id = m.group(1)
            with oracle_db.lock:
                task = oracle_db.tasks.get(task_id)
                if not task or task["user_id"] != user_id:
                    self._send_json(404 if not task else 403, {"error": "Challenge not accessible"})
                    return
                png_bytes = oracle_db.challenge_buffer.get(task_id, DUMMY_CAPTCHA_PNG)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Content-Length", str(len(png_bytes)))
                self.end_headers()
                self.wfile.write(png_bytes)
                return

        # GET /api/v1/tasks/{id}/download
        m = re.match(r"^/api/v1/tasks/([a-zA-Z0-9_\-]+)/download$", path)
        if m:
            task_id = m.group(1)
            with oracle_db.lock:
                task = oracle_db.tasks.get(task_id)
                if not task:
                    self._send_json(404, {"error": "Not Found", "message": "Task does not exist"})
                    return
                if task["user_id"] != user_id:
                    self._send_json(403, {"error": "Forbidden", "message": "Ownership check failed"})
                    return
                if task["status"] != "COMPLETED":
                    self._send_json(400, {"error": "Task Incomplete", "message": f"Cannot download in status {task['status']}"})
                    return
                signed_url = f"https://mock-supabase.local/storage/v1/signed/documents/{user_id}/{task_id}.pdf?token=sig_60s_{uuid.uuid4().hex[:8]}"
                self._send_json(200, {"download_url": signed_url, "expires_in": 60, "doc_type": "aadhaar"})
                return

        self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        content_len = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_len) if content_len > 0 else b""

        # POST /internal/cleanup
        if path == "/internal/cleanup":
            secret = self.headers.get("X-Cleanup-Secret") or self.headers.get("Authorization", "").replace("Bearer ", "")
            if secret != CLEANUP_SECRET:
                self._send_json(401, {"error": "Unauthorized", "message": "Invalid cleanup secret"})
                return
            with oracle_db.lock:
                now = time.time()
                to_delete = [d_id for d_id, doc in oracle_db.documents.items() if doc["delete_after"] <= now]
                for d_id in to_delete:
                    path_key = oracle_db.documents[d_id]["storage_path"]
                    oracle_db.storage_objects.pop(path_key, None)
                    del oracle_db.documents[d_id]
                self._send_json(200, {"status": "ok", "cleaned_documents": len(to_delete), "timestamp": now})
                return

        user_id = self._get_bearer_user()
        if not user_id:
            self._send_json(401, {"error": "Unauthorized", "message": "Missing or invalid Supabase JWT"})
            return

        body_json = {}
        if raw_body:
            try:
                body_json = json.loads(raw_body.decode("utf-8"))
            except Exception:
                self._send_json(422, {"error": "Unprocessable Entity", "message": "Invalid JSON payload"})
                return

        # POST /api/v1/chat
        if path == "/api/v1/chat":
            idempotency_key = self.headers.get("Idempotency-Key")
            if not idempotency_key:
                self._send_json(400, {"error": "Bad Request", "message": "Idempotency-Key header is strictly required"})
                return
            user_text = body_json.get("text", "")
            if not user_text or not user_text.strip():
                self._send_json(422, {"error": "Unprocessable Entity", "message": "Chat text cannot be empty"})
                return

            scrubbed_prompt = scrub_pii(user_text)
            conv_id = body_json.get("conversation_id") or str(uuid.uuid4())

            # Detect intent
            is_aadhaar_intent = bool(re.search(r"\b(aadhaar|vid|download|uidai)\b", user_text, re.IGNORECASE))
            task_id = None
            if is_aadhaar_intent:
                task_id = str(uuid.uuid4())
                with oracle_db.lock:
                    oracle_db.tasks[task_id] = {
                        "id": task_id,
                        "user_id": user_id,
                        "workflow": "aadhaar_download",
                        "status": "RECEIVED",
                        "idempotency_key": idempotency_key,
                        "created_at": time.time(),
                        "pending_input": None
                    }
                    oracle_db.active_workflows_per_user[user_id] = task_id

            # Return SSE stream
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            tokens = ["Namaste! ", "Processing ", "your ", "request..."]
            for token in tokens:
                chunk = f"data: {json.dumps({'token': token})}\n\n"
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()

            if task_id:
                task_event = f"data: {json.dumps({'task_id': task_id, 'status': 'RECEIVED', 'workflow': 'aadhaar_download'})}\n\n"
                self.wfile.write(task_event.encode("utf-8"))
                self.wfile.flush()

            done_event = f"data: [DONE]\n\n"
            self.wfile.write(done_event.encode("utf-8"))
            self.wfile.flush()
            return

        # POST /api/v1/tasks
        if path == "/api/v1/tasks":
            idempotency_key = self.headers.get("Idempotency-Key") or body_json.get("idempotency_key")
            with oracle_db.lock:
                # Check idempotency duplicate
                if idempotency_key:
                    for t in oracle_db.tasks.values():
                        if t.get("idempotency_key") == idempotency_key and t["user_id"] == user_id:
                            self._send_json(200, {"id": t["id"], "status": t["status"], "replayed": True})
                            return

                # Check one active task per workflow constraint
                workflow = body_json.get("workflow", "aadhaar_download")
                if user_id in oracle_db.active_workflows_per_user:
                    existing_id = oracle_db.active_workflows_per_user[user_id]
                    existing_task = oracle_db.tasks.get(existing_id)
                    if existing_task and existing_task["status"] not in {"COMPLETED", "FAILED", "CANCELLED", "EXPIRED"}:
                        self._send_json(409, {"error": "Conflict", "message": f"Active task {existing_id} already in progress for this workflow"})
                        return

                task_id = str(uuid.uuid4())
                task_record = {
                    "id": task_id,
                    "user_id": user_id,
                    "workflow": workflow,
                    "status": "RECEIVED",
                    "idempotency_key": idempotency_key,
                    "created_at": time.time(),
                    "pending_input": None
                }
                oracle_db.tasks[task_id] = task_record
                oracle_db.active_workflows_per_user[user_id] = task_id
                self._send_json(201, {"id": task_id, "status": "RECEIVED", "workflow": workflow})
                return

        # POST /api/v1/tasks/{id}/input
        m = re.match(r"^/api/v1/tasks/([a-zA-Z0-9_\-]+)/input$", path)
        if m:
            task_id = m.group(1)
            # Rate limit check: max 5 requests per 10s on input
            now = time.time()
            with oracle_db.lock:
                history = oracle_db.rate_limit_timestamps.setdefault(user_id, [])
                oracle_db.rate_limit_timestamps[user_id] = [t for t in history if now - t < 10.0]
                if len(oracle_db.rate_limit_timestamps[user_id]) >= 5:
                    self._send_json(429, {"error": "Too Many Requests", "message": "Rate limit exceeded on secure input endpoint"})
                    return
                oracle_db.rate_limit_timestamps[user_id].append(now)

                task = oracle_db.tasks.get(task_id)
                if not task:
                    self._send_json(404, {"error": "Not Found", "message": "Task does not exist"})
                    return
                if task["user_id"] != user_id:
                    self._send_json(403, {"error": "Forbidden", "message": "Access denied"})
                    return
                if task["status"] != "WAITING_FOR_USER":
                    self._send_json(400, {"error": "Invalid State", "message": f"Task is in {task['status']}, not waiting for input"})
                    return

                input_id = body_json.get("input_id", "otp")
                val = str(body_json.get("value", "")).strip()

                if input_id == "otp":
                    if not re.match(r"^\d{6}$", val):
                        self._send_json(422, {"error": "Unprocessable Entity", "message": "OTP must be exactly 6 numeric digits"})
                        return
                    # Relay in memory only - never persist to DB
                    oracle_db.pending_otp_relays[task_id] = val
                    self._send_json(200, {"status": "accepted", "message": "Input received into in-memory relay"})
                    return
                elif input_id == "captcha":
                    if not val or len(val) < 4:
                        self._send_json(422, {"error": "Unprocessable Entity", "message": "CAPTCHA cannot be empty"})
                        return
                    self._send_json(200, {"status": "accepted", "message": "CAPTCHA accepted"})
                    return

                self._send_json(200, {"status": "accepted"})
                return

        # POST /api/v1/tasks/{id}/cancel
        m = re.match(r"^/api/v1/tasks/([a-zA-Z0-9_\-]+)/cancel$", path)
        if m:
            task_id = m.group(1)
            with oracle_db.lock:
                task = oracle_db.tasks.get(task_id)
                if not task:
                    self._send_json(404, {"error": "Not Found"})
                    return
                if task["user_id"] != user_id:
                    self._send_json(403, {"error": "Forbidden"})
                    return
                if task["status"] in {"COMPLETED", "FAILED", "CANCELLED", "EXPIRED"}:
                    self._send_json(400, {"error": "Bad Request", "message": f"Cannot cancel terminal task in status {task['status']}"})
                    return
                task["status"] = "CANCELLED"
                oracle_db.challenge_buffer.pop(task_id, None)
                oracle_db.pending_otp_relays.pop(task_id, None)
                if oracle_db.active_workflows_per_user.get(user_id) == task_id:
                    del oracle_db.active_workflows_per_user[user_id]
                self._send_json(200, {"status": "CANCELLED", "task_id": task_id})
                return

        self._send_json(404, {"error": "Not Found"})

    def do_DELETE(self):
        path = self.path.split("?")[0]
        user_id = self._get_bearer_user()
        if not user_id:
            self._send_json(401, {"error": "Unauthorized", "message": "Missing JWT"})
            return

        # DELETE /api/v1/documents/{id}
        m = re.match(r"^/api/v1/documents/([a-zA-Z0-9_\-]+)$", path)
        if m:
            doc_id = m.group(1)
            with oracle_db.lock:
                doc = oracle_db.documents.get(doc_id)
                if not doc:
                    self._send_json(404, {"error": "Not Found", "message": "Document does not exist"})
                    return
                if doc["user_id"] != user_id:
                    self._send_json(403, {"error": "Forbidden", "message": "Document ownership violation"})
                    return
                # Delete storage object and database row
                path_key = doc["storage_path"]
                oracle_db.storage_objects.pop(path_key, None)
                del oracle_db.documents[doc_id]
                self._send_json(200, {"status": "deleted", "id": doc_id})
                return

        self._send_json(404, {"error": "Not Found"})

# ---------------------------------------------------------------------------
# Mock Portal Handler
# ---------------------------------------------------------------------------

class MockPortalHandler(BaseHTTPRequestHandler):
    """Specification-compliant HTTP handler for Mock Government Portal."""
    def log_message(self, format, *args):
        pass

    def _send_json(self, status: int, data: Any):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            self._send_json(200, {"status": "ok", "service": "mock-government-portal"})
            return

        if path == "/":
            html = "<html><body><h1>Mock UIDAI Portal</h1><form id='login_form'><input id='uid_input'/><img id='captcha_img'/><input id='captcha_input'/></form></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        if path == "/captcha":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(DUMMY_CAPTCHA_PNG)))
            self.end_headers()
            self.wfile.write(DUMMY_CAPTCHA_PNG)
            return

        if path == "/verify-otp":
            html = "<html><body><h1>Verify OTP</h1><form id='otp_form'><input id='otp_input'/><button id='submit_otp_btn'></button></form></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        if path == "/download":
            switches = mock_portal_state.failure_switches
            if switches.get("corrupt_pdf"):
                payload = build_test_pdf(corrupt=True)
            elif switches.get("html_as_pdf"):
                payload = b"<html><body>500 Internal Server Error</body></html>"
            elif switches.get("oversize_pdf"):
                payload = build_test_pdf(oversize=True)
            elif switches.get("malicious_pdf"):
                payload = build_test_pdf(malicious="javascript")
            else:
                payload = build_test_pdf(encrypted=True)

            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", "attachment; filename=\"eaadhaar.pdf\"")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        content_len = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_len) if content_len > 0 else b""
        data = {}
        if raw_body:
            try:
                data = json.loads(raw_body.decode("utf-8"))
            except Exception:
                pass

        # Switch management endpoint for test harness
        if path == "/__switch":
            switch = data.get("switch")
            enabled = data.get("enabled", True)
            if switch in mock_portal_state.failure_switches:
                mock_portal_state.failure_switches[switch] = enabled
                self._send_json(200, {"status": "switch_updated", "switch": switch, "enabled": enabled})
                return
            self._send_json(400, {"error": "Unknown switch"})
            return

        if path == "/login":
            if mock_portal_state.failure_switches.get("wrong_captcha"):
                self._send_json(400, {"error": "INVALID_CAPTCHA", "message": "CAPTCHA entered is invalid"})
                return
            session_id = str(uuid.uuid4())
            mock_portal_state.sessions[session_id] = {"stage": "OTP_SENT", "otp": "123456"}
            mock_portal_state.otp_attempts[session_id] = 3
            mock_portal_state.otp_timer[session_id] = time.time()
            self._send_json(200, {"status": "otp_sent", "session_id": session_id, "expires_in": 180})
            return

        if path == "/verify-otp":
            session_id = data.get("session_id", "default")
            otp = data.get("otp", "")
            if mock_portal_state.failure_switches.get("expired_otp"):
                self._send_json(400, {"error": "OTP_EXPIRED", "message": "The OTP has expired"})
                return

            if mock_portal_state.failure_switches.get("wrong_otp_3x") or otp != "123456":
                attempts = mock_portal_state.otp_attempts.get(session_id, 3) - 1
                mock_portal_state.otp_attempts[session_id] = attempts
                if attempts <= 0:
                    self._send_json(403, {"error": "MAX_ATTEMPTS_EXCEEDED", "message": "Session locked due to 3 failed OTP attempts"})
                    return
                self._send_json(400, {"error": "INVALID_OTP", "attempts_left": attempts})
                return

            self._send_json(200, {"status": "authenticated", "download_token": "valid_token_xyz"})
            return

        if path == "/resend-otp":
            session_id = data.get("session_id", "default")
            mock_portal_state.otp_attempts[session_id] = 3
            mock_portal_state.otp_timer[session_id] = time.time()
            self._send_json(200, {"status": "otp_resent", "expires_in": 180, "attempts_left": 3})
            return

        self._send_json(404, {"error": "Not Found"})

# ---------------------------------------------------------------------------
# High-Level Test Clients
# ---------------------------------------------------------------------------

class SaralApiClient:
    """Synchronous test client interacting with Saral API over HTTP."""
    def __init__(self, base_url: str, default_token: str = TEST_PRIMARY_TOKEN):
        self.base_url = base_url.rstrip("/")
        self.default_token = default_token

    def _request(self, method: str, path: str, headers: Optional[Dict[str, str]] = None, data: Optional[Any] = None) -> Tuple[int, Any, Dict[str, str]]:
        url = f"{self.base_url}{path}"
        req_headers = {"User-Agent": "Saral-E2E-TestClient/1.0"}
        if self.default_token:
            req_headers["Authorization"] = f"Bearer {self.default_token}"
        if headers:
            req_headers.update(headers)

        payload_bytes = None
        if data is not None:
            if isinstance(data, (dict, list)):
                payload_bytes = json.dumps(data).encode("utf-8")
                req_headers["Content-Type"] = "application/json"
            elif isinstance(data, (bytes, str)):
                payload_bytes = data.encode("utf-8") if isinstance(data, str) else data

        req = urllib.request.Request(url, data=payload_bytes, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                resp_headers = dict(resp.headers)
                body = resp.read()
                content_type = resp_headers.get("Content-Type", "")
                if "application/json" in content_type:
                    return status, json.loads(body.decode("utf-8")), resp_headers
                return status, body, resp_headers
        except urllib.error.HTTPError as e:
            status = e.code
            resp_headers = dict(e.headers)
            body = e.read()
            try:
                parsed = json.loads(body.decode("utf-8"))
            except Exception:
                parsed = body
            return status, parsed, resp_headers

    def get_health(self) -> Tuple[int, Any]:
        status, data, _ = self._request("GET", "/health", headers={"Authorization": ""})
        return status, data

    def send_chat(self, text: str, conversation_id: Optional[str] = None, idempotency_key: Optional[str] = None, token: Optional[str] = None) -> Tuple[int, Any, Dict[str, str]]:
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if token is not None:
            headers["Authorization"] = f"Bearer {token}" if token else ""
        return self._request("POST", "/api/v1/chat", headers=headers, data={"text": text, "conversation_id": conversation_id})

    def create_task(self, workflow: str = "aadhaar_download", idempotency_key: Optional[str] = None, token: Optional[str] = None) -> Tuple[int, Any]:
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if token is not None:
            headers["Authorization"] = f"Bearer {token}" if token else ""
        status, data, _ = self._request("POST", "/api/v1/tasks", headers=headers, data={"workflow": workflow})
        return status, data

    def get_task(self, task_id: str, token: Optional[str] = None) -> Tuple[int, Any]:
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}" if token else ""
        status, data, _ = self._request("GET", f"/api/v1/tasks/{task_id}", headers=headers)
        return status, data

    def submit_input(self, task_id: str, input_id: str, value: str, token: Optional[str] = None) -> Tuple[int, Any]:
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}" if token else ""
        status, data, _ = self._request("POST", f"/api/v1/tasks/{task_id}/input", headers=headers, data={"input_id": input_id, "value": value})
        return status, data

    def get_challenge(self, task_id: str, token: Optional[str] = None) -> Tuple[int, Any, Dict[str, str]]:
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}" if token else ""
        return self._request("GET", f"/api/v1/tasks/{task_id}/challenge", headers=headers)

    def cancel_task(self, task_id: str, token: Optional[str] = None) -> Tuple[int, Any]:
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}" if token else ""
        status, data, _ = self._request("POST", f"/api/v1/tasks/{task_id}/cancel", headers=headers, data={})
        return status, data

    def get_download_url(self, task_id: str, token: Optional[str] = None) -> Tuple[int, Any]:
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}" if token else ""
        status, data, _ = self._request("GET", f"/api/v1/tasks/{task_id}/download", headers=headers)
        return status, data

    def delete_document(self, document_id: str, token: Optional[str] = None) -> Tuple[int, Any]:
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}" if token else ""
        status, data, _ = self._request("DELETE", f"/api/v1/documents/{document_id}", headers=headers)
        return status, data

    def run_cleanup(self, secret: str = CLEANUP_SECRET) -> Tuple[int, Any]:
        headers = {"X-Cleanup-Secret": secret}
        status, data, _ = self._request("POST", "/internal/cleanup", headers=headers)
        return status, data

class MockPortalClient:
    """Client for Mock Government Portal."""
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str, data: Optional[Any] = None) -> Tuple[int, Any]:
        url = f"{self.base_url}{path}"
        payload_bytes = None
        headers = {"User-Agent": "Saral-Worker-Browser/1.0"}
        if data is not None:
            payload_bytes = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=payload_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                body = resp.read()
                try:
                    return resp.status, json.loads(body.decode("utf-8"))
                except Exception:
                    return resp.status, body
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                return e.code, json.loads(body.decode("utf-8"))
            except Exception:
                return e.code, body

    def get_health(self) -> Tuple[int, Any]:
        return self._request("GET", "/health")

    def set_switch(self, switch_name: str, enabled: bool = True) -> Tuple[int, Any]:
        return self._request("POST", "/__switch", {"switch": switch_name, "enabled": enabled})

    def login(self, uid: str, captcha: str) -> Tuple[int, Any]:
        return self._request("POST", "/login", {"uid": uid, "captcha": captcha})

    def verify_otp(self, session_id: str, otp: str) -> Tuple[int, Any]:
        return self._request("POST", "/verify-otp", {"session_id": session_id, "otp": otp})

    def resend_otp(self, session_id: str) -> Tuple[int, Any]:
        return self._request("POST", "/resend-otp", {"session_id": session_id})

    def download_pdf(self) -> Tuple[int, bytes]:
        status, body = self._request("GET", "/download")
        return status, body

# ---------------------------------------------------------------------------
# Pytest Fixtures & Lifecycle Hooks
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def servers():
    """Starts local specification oracle servers on ephemeral ports for test session."""
    is_live = os.environ.get("E2E_LIVE") == "1"
    if is_live:
        yield {
            "api_url": os.environ.get("API_BASE_URL", "http://127.0.0.1:8000"),
            "portal_url": os.environ.get("MOCK_PORTAL_URL", "http://127.0.0.1:8001")
        }
        return

    # Start ephemeral background HTTP servers
    api_server = HTTPServer(("127.0.0.1", 0), SaralApiHandler)
    api_port = api_server.server_port
    api_thread = threading.Thread(target=api_server.serve_forever, daemon=True)
    api_thread.start()

    portal_server = HTTPServer(("127.0.0.1", 0), MockPortalHandler)
    portal_port = portal_server.server_port
    portal_thread = threading.Thread(target=portal_server.serve_forever, daemon=True)
    portal_thread.start()

    server_info = {
        "api_url": f"http://127.0.0.1:{api_port}",
        "portal_url": f"http://127.0.0.1:{portal_port}"
    }

    yield server_info

    api_server.shutdown()
    portal_server.shutdown()

@pytest.fixture(autouse=True)
def clean_state():
    """Resets in-memory databases and mock portal switches before each test."""
    oracle_db.reset()
    mock_portal_state.reset()
    yield

@pytest.fixture
def api_client(servers) -> SaralApiClient:
    return SaralApiClient(servers["api_url"], default_token=TEST_PRIMARY_TOKEN)

@pytest.fixture
def secondary_api_client(servers) -> SaralApiClient:
    return SaralApiClient(servers["api_url"], default_token=TEST_SECONDARY_TOKEN)

@pytest.fixture
def mock_portal_client(servers) -> MockPortalClient:
    return MockPortalClient(servers["portal_url"])

@pytest.fixture
def test_credentials() -> Dict[str, Any]:
    return {
        "primary_user_id": TEST_PRIMARY_USER_ID,
        "primary_token": TEST_PRIMARY_TOKEN,
        "secondary_user_id": TEST_SECONDARY_USER_ID,
        "secondary_token": TEST_SECONDARY_TOKEN,
        "worker_secret": WORKER_SHARED_SECRET,
        "cleanup_secret": CLEANUP_SECRET
    }
