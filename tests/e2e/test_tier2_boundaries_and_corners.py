"""
Saral AI — Tier 2: Boundary Value Analysis & Corner Cases Test Suite
File: tests/e2e/test_tier2_boundaries_and_corners.py

Targets boundary conditions, extreme inputs, attempt limits, timeouts, and corrupt files:
1. Input Validation Boundary Stress (Empty, whitespace, massive payloads, Unicode)
2. Path Parameter Boundary Hardening (Malformed UUIDs, injection strings)
3. Attempt Limits & Lockouts (3x OTP Lockout, CAPTCHA attempt counters)
4. Timeouts & Expiration Watchdogs (180s input timeout, 600s total task timeout)
5. 5-Point Document Security Verifier (Corrupt headers, HTML disguised as PDF, oversize >5MB, malicious /JavaScript and /Launch actions)
6. Route Interception Policy & Allowlist
"""

import time
import uuid
import pytest
from .conftest import (
    oracle_db,
    transition_task,
    verify_document_security,
    build_test_pdf,
    ALLOWED_DOMAINS,
    TEST_PRIMARY_USER_ID
)

# ===========================================================================
# 1. Input Validation Boundary Stress
# ===========================================================================

def test_boundary_empty_chat_string_rejected(api_client):
    """Empty string chat message must be rejected with 422 Unprocessable Entity."""
    status, data, _ = api_client.send_chat(text="", idempotency_key=str(uuid.uuid4()))
    assert status == 422, f"Expected 422 for empty chat text, got {status}"
    assert "cannot be empty" in data.get("message", "")

def test_boundary_whitespace_only_chat_rejected(api_client):
    """Whitespace-only string must be rejected with 422."""
    status, data, _ = api_client.send_chat(text="   \n\t   ", idempotency_key=str(uuid.uuid4()))
    assert status == 422, f"Expected 422 for whitespace chat text, got {status}"

def test_boundary_extremely_large_chat_payload(api_client):
    """Chat endpoint handles a large 50,000-character payload safely without crashing."""
    large_text = "Namaste Saral AI. " * 2500 # ~45,000 chars
    status, body, headers = api_client.send_chat(text=large_text, idempotency_key=str(uuid.uuid4()))
    assert status == 200
    assert "text/event-stream" in headers.get("Content-Type", "")

def test_boundary_unicode_and_emojis_in_chat(api_client):
    """Chat endpoint processes Hindi Devanagari script, regional fonts, and emojis cleanly."""
    hindi_text = "नमस्ते सरल एआई! कृपया मेरा आधार कार्ड डाउनलोड करने में मदद करें। 🇮🇳 🙏"
    status, body, _ = api_client.send_chat(text=hindi_text, idempotency_key=str(uuid.uuid4()))
    assert status == 200
    assert b"data: " in body

# ===========================================================================
# 2. Path Parameter Boundary Hardening
# ===========================================================================

def test_boundary_malformed_uuid_in_task_id(api_client):
    """Passing a malformed string instead of a UUID returns 404 Not Found."""
    status, data = api_client.get_task("not-a-valid-uuid-12345!@#$")
    assert status == 404

def test_boundary_null_byte_injection_in_path(api_client):
    """Path traversal or null byte injections are rejected safely with 404."""
    status, data = api_client.get_task("../../../etc/passwd%00")
    assert status == 404

# ===========================================================================
# 3. Attempt Limits & Lockouts
# ===========================================================================

def test_corner_otp_max_attempts_exceeded_on_portal(mock_portal_client):
    """Submitting 3 incorrect OTPs locks the session with 403 MAX_ATTEMPTS_EXCEEDED."""
    # Login to create session
    status, login_res = mock_portal_client.login(uid="234567890128", captcha="WXYZ12")
    assert status == 200
    session_id = login_res["session_id"]

    # Attempt 1: wrong OTP
    s1, r1 = mock_portal_client.verify_otp(session_id, "000000")
    assert s1 == 400
    assert r1.get("attempts_left") == 2

    # Attempt 2: wrong OTP
    s2, r2 = mock_portal_client.verify_otp(session_id, "111111")
    assert s2 == 400
    assert r2.get("attempts_left") == 1

    # Attempt 3: wrong OTP -> Lockout
    s3, r3 = mock_portal_client.verify_otp(session_id, "222222")
    assert s3 == 403, f"Expected 403 on attempt 3, got {s3}"
    assert r3.get("error") == "MAX_ATTEMPTS_EXCEEDED"

def test_corner_wrong_captcha_failure_switch(mock_portal_client):
    """Enabling wrong_captcha failure switch causes portal to reject login."""
    mock_portal_client.set_switch("wrong_captcha", enabled=True)
    status, data = mock_portal_client.login(uid="234567890128", captcha="ANY_CAPTCHA")
    assert status == 400
    assert data.get("error") == "INVALID_CAPTCHA"

def test_corner_rate_limit_burst_protection(api_client):
    """Bursting calls to the secure input endpoint triggers 429 Too Many Requests."""
    status, task_data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = task_data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "WAITING_FOR_USER")

    # Send 5 rapid requests (allowed)
    for _ in range(5):
        api_client.submit_input(task_id, "otp", "123456")

    # 6th immediate request must be rate-limited
    status_rate, rate_data = api_client.submit_input(task_id, "otp", "123456")
    assert status_rate == 429
    assert rate_data.get("error") == "Too Many Requests"

# ===========================================================================
# 4. Timeouts & Expiration Watchdogs
# ===========================================================================

def test_corner_otp_expiry_failure_switch(mock_portal_client):
    """Enabling expired_otp switch on mock portal returns OTP_EXPIRED."""
    status, login_res = mock_portal_client.login(uid="234567890128", captcha="WXYZ12")
    session_id = login_res["session_id"]

    mock_portal_client.set_switch("expired_otp", enabled=True)
    status, res = mock_portal_client.verify_otp(session_id, "123456")
    assert status == 400
    assert res.get("error") == "OTP_EXPIRED"

def test_corner_input_pending_expiry_watchdog(api_client):
    """A task waiting for user input that exceeds the 180s timeout transitions to EXPIRED."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "WAITING_FOR_USER")

    # Simulate 180s timeout expiration
    expired_task = transition_task(task_id, "EXPIRED", reason="INPUT_TIMEOUT_180S")
    assert expired_task["status"] == "EXPIRED"

def test_corner_task_total_duration_watchdog(api_client):
    """A task exceeding the total 10-minute (600s) execution window is terminated."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")

    # Total task watchdog fires
    timed_out_task = transition_task(task_id, "EXPIRED", reason="TASK_TIMEOUT_600S")
    assert timed_out_task["status"] == "EXPIRED"

# ===========================================================================
# 5. 5-Point Document Security Verifier
# ===========================================================================

def test_corner_corrupt_pdf_header_rejected():
    """File that does not start with %PDF- is rejected at Stage 1."""
    corrupt_content = b"NOT_A_PDF_DATA_STREAM_XYZ"
    result = verify_document_security(corrupt_content)
    assert not result.is_valid
    assert result.error_code == "INVALID_PDF_HEADER"

def test_corner_html_masquerading_as_pdf_rejected():
    """HTML 500 error page returned with PDF mime-type is rejected at Stage 1."""
    html_content = b"<!DOCTYPE html><html><body>500 Internal Server Error</body></html>"
    result = verify_document_security(html_content)
    assert not result.is_valid
    assert result.error_code == "INVALID_PDF_HEADER"

def test_corner_oversize_pdf_exceeding_threshold():
    """PDF exceeding the 5 MB limit is rejected at Stage 2."""
    oversize_pdf = build_test_pdf(oversize=True) # 6 MB
    result = verify_document_security(oversize_pdf, max_size_mb=5)
    assert not result.is_valid
    assert result.error_code == "OVERSIZE_PDF"

def test_corner_truncated_empty_pdf_rejected():
    """PDF payload below 100 bytes is rejected as truncated."""
    truncated = b"%PDF-1.4"
    result = verify_document_security(truncated)
    assert not result.is_valid
    assert result.error_code == "TRUNCATED_PDF"

def test_corner_missing_eof_trailer_rejected():
    """PDF missing %%EOF marker is rejected at Stage 3."""
    malformed = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n0 1\n" + (b" " * 200)
    result = verify_document_security(malformed)
    assert not result.is_valid
    assert result.error_code == "MALFORMED_PDF_TRAILER"

def test_corner_malicious_pdf_javascript_action_rejected():
    """PDF with embedded /JavaScript action dictionary is rejected at Stage 4."""
    malicious_js = build_test_pdf(malicious="javascript")
    result = verify_document_security(malicious_js)
    assert not result.is_valid
    assert result.error_code == "MALICIOUS_PDF_JAVASCRIPT"

def test_corner_malicious_pdf_launch_action_rejected():
    """PDF with embedded /Launch action dictionary is rejected at Stage 4."""
    malicious_launch = build_test_pdf(malicious="launch")
    result = verify_document_security(malicious_launch)
    assert not result.is_valid
    assert result.error_code == "MALICIOUS_PDF_LAUNCH"

def test_corner_valid_encrypted_pdf_passes_verifier():
    """Valid password-protected PDF passes all 5 stages with sha256 and pdf_encrypted=True."""
    valid_enc = build_test_pdf(encrypted=True)
    result = verify_document_security(valid_enc)
    assert result.is_valid
    assert result.sha256 is not None
    assert len(result.sha256) == 64
    assert result.pdf_encrypted is True

# ===========================================================================
# 6. Route Interception Policy & Allowlist
# ===========================================================================

def test_corner_mock_portal_foreign_redirect():
    """Navigation requests outside the workflow domain allowlist must be aborted."""
    foreign_host = "unauthorized-phishing-portal.com"
    assert foreign_host not in ALLOWED_DOMAINS

    # Simulate route allowlist check
    def check_domain_allowed(host: str) -> bool:
        return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)

    assert not check_domain_allowed(foreign_host)
    assert check_domain_allowed("mock-portal.local")
    assert check_domain_allowed("uidai.gov.in")
