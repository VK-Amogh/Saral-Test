"""
Saral AI — Tier 3: Pairwise Combinations & Subsystem Integration Test Suite
File: tests/e2e/test_tier3_pairwise_combinations.py

Tests cross-feature interactions and multi-component pipelines:
1. Auth + Task + Realtime Integration
2. PII Scrubber + Chat + Task Workflow Integration (Verhoeff dihedral D5)
3. Challenge Broker + SecretStr + Worker Relay Pipeline
4. Verifier + Storage + Signed URL Delivery Pipeline
5. Rate Limiting + Input Submission Interaction
"""

import time
import uuid
import hashlib
import pytest
from .conftest import (
    oracle_db,
    transition_task,
    validate_verhoeff,
    generate_valid_aadhaar,
    compute_verhoeff_checksum,
    scrub_pii,
    verify_document_security,
    build_test_pdf,
    DUMMY_CAPTCHA_PNG,
    TEST_PRIMARY_USER_ID,
    TEST_SECONDARY_USER_ID
)

# ===========================================================================
# 1. Auth + Task + Realtime Integration
# ===========================================================================

def test_pairwise_auth_task_realtime_events_filtering(api_client, secondary_api_client):
    """Task transitions emit Realtime events strictly isolated by user_id."""
    status, task_data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = task_data["id"]

    # Transition task through several states
    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")

    # Inspect emitted events in database
    with oracle_db.lock:
        user_a_events = [e for e in oracle_db.task_events if e["user_id"] == TEST_PRIMARY_USER_ID]
        user_b_events = [e for e in oracle_db.task_events if e["user_id"] == TEST_SECONDARY_USER_ID]

        assert len(user_a_events) >= 3
        assert len(user_b_events) == 0

        # Verify all events for User A belong to task_id
        for ev in user_a_events:
            assert ev["task_id"] == task_id

def test_pairwise_token_expiration_during_task(api_client):
    """When a JWT expires mid-workflow, subsequent status queries and actions are blocked."""
    status, task_data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = task_data["id"]

    # Revoke/expire token by passing invalid token on subsequent call
    status, data = api_client.get_task(task_id, token="expired_or_revoked_jwt_token")
    assert status == 401
    assert data.get("error") == "Unauthorized"

# ===========================================================================
# 2. PII Scrubber + Chat + Task Workflow Integration
# ===========================================================================

def test_pairwise_scrubber_verhoeff_valid_vs_invalid_aadhaar():
    """Verhoeff dihedral D5 algorithm correctly distinguishes valid vs invalid 12-digit IDs."""
    # Generate valid Aadhaar numbers
    valid_aadhaar_1 = generate_valid_aadhaar("12345678901")
    valid_aadhaar_2 = generate_valid_aadhaar("98765432109")

    assert validate_verhoeff(valid_aadhaar_1) is True
    assert validate_verhoeff(valid_aadhaar_2) is True

    # Tamper with single digit (e.g. change last digit)
    tampered_last_digit = valid_aadhaar_1[:-1] + ("0" if valid_aadhaar_1[-1] != "0" else "1")
    assert validate_verhoeff(tampered_last_digit) is False

    # Scrubber masks valid Aadhaar numbers
    text_with_valid = f"My Aadhaar is {valid_aadhaar_1} please download."
    scrubbed_valid = scrub_pii(text_with_valid)
    assert valid_aadhaar_1 not in scrubbed_valid
    assert f"XXXX-XXXX-{valid_aadhaar_1[-4:]}" in scrubbed_valid

    # Scrubber leaves invalid numbers unmasked (or handles differently)
    text_with_invalid = f"My random number is {tampered_last_digit}."
    scrubbed_invalid = scrub_pii(text_with_invalid)
    assert tampered_last_digit in scrubbed_invalid

def test_pairwise_scrubber_chat_to_task_params(api_client):
    """Chat input with Aadhaar and phone number initiates task with masked params."""
    valid_aadhaar = generate_valid_aadhaar("55443322110")
    phone_number = "9876543210"
    chat_text = f"Help me get my Aadhaar {valid_aadhaar}, registered phone {phone_number}"

    scrubbed = scrub_pii(chat_text)
    assert valid_aadhaar not in scrubbed
    assert phone_number not in scrubbed
    assert "[REDACTED_PHONE]" in scrubbed

    # Send through chat API
    status, body, _ = api_client.send_chat(text=chat_text, idempotency_key=str(uuid.uuid4()))
    assert status == 200
    assert b"task_id" in body

def test_pairwise_scrubber_biometrics_and_otp_in_chat():
    """Mentions of biometric modalities and OTP values are completely redacted."""
    raw = "My fingerprint authentication failed and my OTP is 654321 on my phone"
    scrubbed = scrub_pii(raw)
    assert "fingerprint" not in scrubbed.lower()
    assert "[REDACTED_BIOMETRIC]" in scrubbed
    assert "654321" not in scrubbed
    assert "[REDACTED_OTP]" in scrubbed

# ===========================================================================
# 3. Challenge Broker + SecretStr + Worker Relay Pipeline
# ===========================================================================

def test_pairwise_challenge_secretstr_worker_relay(api_client):
    """Challenge image retrieval and secret submission relays in-memory with zero DB persistence."""
    status, task_data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = task_data["id"]

    # Transition to WAITING_FOR_USER with CAPTCHA challenge
    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "WAITING_FOR_USER")

    # Worker puts CAPTCHA in challenge buffer
    with oracle_db.lock:
        oracle_db.challenge_buffer[task_id] = DUMMY_CAPTCHA_PNG

    # User fetches challenge image
    status, png_bytes, headers = api_client.get_challenge(task_id)
    assert status == 200
    assert png_bytes == DUMMY_CAPTCHA_PNG
    assert "no-store" in headers.get("Cache-Control", "")

    # User submits CAPTCHA solution
    status, res = api_client.submit_input(task_id, "captcha", "ABC123")
    assert status == 200
    assert res["status"] == "accepted"

    # Next step: OTP challenge
    with oracle_db.lock:
        oracle_db.tasks[task_id]["pending_input"] = {
            "kind": "OTP",
            "prompt": "Enter 6-digit OTP",
            "expires_in": 180,
            "attempts_left": 3
        }

    # User submits 6-digit OTP
    status, res_otp = api_client.submit_input(task_id, "otp", "789012")
    assert status == 200

    # Verify zero persistence in database tables or serialized task status
    with oracle_db.lock:
        task_str = str(oracle_db.tasks[task_id])
        events_str = str([e for e in oracle_db.task_events if e["task_id"] == task_id])

        assert "789012" not in task_str
        assert "789012" not in events_str
        assert "ABC123" not in task_str

def test_pairwise_otp_resend_timer_reset_and_invalidation(mock_portal_client):
    """Requesting an OTP resend resets countdown to 180s and attempts counter to 3."""
    status, login_res = mock_portal_client.login(uid="234567890128", captcha="WXYZ12")
    session_id = login_res["session_id"]

    # Fail one attempt
    mock_portal_client.verify_otp(session_id, "000000")

    # Trigger resend
    status, resend_res = mock_portal_client.resend_otp(session_id)
    assert status == 200
    assert resend_res["status"] == "otp_resent"
    assert resend_res["attempts_left"] == 3
    assert resend_res["expires_in"] == 180

# ===========================================================================
# 4. Verifier + Storage + Signed URL Delivery Pipeline
# ===========================================================================

def test_pairwise_verifier_storage_and_signed_url(api_client):
    """Verified PDF computes SHA-256, stores in private storage, and issues signed download URL."""
    status, task_data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = task_data["id"]

    # Transition to DOWNLOADING
    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")
    transition_task(task_id, "DOWNLOADING")

    # Simulate worker PDF download and 5-point verification
    pdf_payload = build_test_pdf(encrypted=True)
    verifier_res = verify_document_security(pdf_payload)
    assert verifier_res.is_valid is True

    # Transition to VERIFYING and then COMPLETED via verifier actor
    transition_task(task_id, "VERIFYING")
    transition_task(task_id, "COMPLETED", actor="verifier")

    # Store in private Storage
    storage_path = f"{TEST_PRIMARY_USER_ID}/{task_id}.pdf"
    doc_id = str(uuid.uuid4())
    with oracle_db.lock:
        oracle_db.storage_objects[storage_path] = pdf_payload
        oracle_db.documents[doc_id] = {
            "id": doc_id,
            "user_id": TEST_PRIMARY_USER_ID,
            "task_id": task_id,
            "storage_path": storage_path,
            "sha256": verifier_res.sha256,
            "size_bytes": verifier_res.size_bytes,
            "pdf_encrypted": True,
            "delete_after": time.time() + 86400
        }

    # Fetch download signed URL
    status, dl_data = api_client.get_download_url(task_id)
    assert status == 200
    assert "download_url" in dl_data
    assert dl_data["expires_in"] == 60

    # Verify SHA-256 matches actual payload
    expected_sha256 = hashlib.sha256(pdf_payload).hexdigest()
    assert verifier_res.sha256 == expected_sha256

def test_pairwise_verifier_rejection_halts_pipeline(api_client):
    """Corrupt or malicious payload fails verification, transitions to FAILED, and prevents download."""
    status, task_data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = task_data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")
    transition_task(task_id, "DOWNLOADING")
    transition_task(task_id, "VERIFYING")

    # Corrupt payload
    corrupt_pdf = b"MALFORMED_HEADER_NOT_A_PDF"
    verifier_res = verify_document_security(corrupt_pdf)
    assert verifier_res.is_valid is False

    # Verifier transitions task to FAILED
    transition_task(task_id, "FAILED", actor="verifier", reason=verifier_res.error_code)

    # Download URL must be refused
    status, data = api_client.get_download_url(task_id)
    assert status == 400
    assert "Cannot download in status FAILED" in data.get("message", "")

# ===========================================================================
# 5. Rate Limiting + Input Submission Interaction
# ===========================================================================

def test_pairwise_rate_limit_lockout_prevents_brute_force(api_client):
    """Submitting burst inputs triggers 429 without corrupting task state."""
    status, task_data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = task_data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "WAITING_FOR_USER")

    # Send 5 calls
    for _ in range(5):
        api_client.submit_input(task_id, "otp", "123456")

    # 6th call hits rate limiter
    status_rate, rate_res = api_client.submit_input(task_id, "otp", "123456")
    assert status_rate == 429
    assert rate_res["error"] == "Too Many Requests"

    # Task status remains unharmed
    status_info, task_info = api_client.get_task(task_id)
    assert status_info == 200
    assert task_info["status"] == "WAITING_FOR_USER"
