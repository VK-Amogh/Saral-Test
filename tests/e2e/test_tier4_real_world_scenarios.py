"""
Saral AI — Tier 4: Real-World Application Scenarios Test Suite
File: tests/e2e/test_tier4_real_world_scenarios.py

Simulates multi-step, end-to-end user journeys and failure recovery workflows:
1. Complete Aadhaar Download Journey (Happy path across all systems)
2. Wrong CAPTCHA Recovery Journey (Error handling, fresh challenge, retry)
3. Wrong OTP Retry Recovery Journey (Attempt decrement, retry to success)
4. Expired OTP Recovery Journey (Countdown expiration, resend OTP, completion)
5. Cooperative Cancellation Mid-Flight (Cancellation, cleanup, state reset)
6. Tampered Payload Failure Recovery (Corrupt file, verifier abort, user guidance)
"""

import time
import json
import uuid
import hashlib
import pytest
from .conftest import (
    oracle_db,
    transition_task,
    validate_verhoeff,
    generate_valid_aadhaar,
    verify_document_security,
    build_test_pdf,
    DUMMY_CAPTCHA_PNG,
    TEST_PRIMARY_USER_ID
)

# ===========================================================================
# 1. Complete Aadhaar Download Journey
# ===========================================================================

def test_scenario_complete_aadhaar_download_journey(api_client, mock_portal_client):
    """Full end-to-end journey: Chat -> Task -> CAPTCHA -> OTP -> PDF -> Verifier -> Storage -> Vault."""
    # Step 1: Citizen initiates request via chat
    valid_uid = generate_valid_aadhaar("12345678901")
    chat_prompt = f"Namaste, please help me download my Aadhaar card with number {valid_uid}"
    status, body, headers = api_client.send_chat(
        text=chat_prompt,
        idempotency_key=str(uuid.uuid4())
    )
    assert status == 200

    # Step 2: Extract task_id created by chat intent
    task_id = None
    for line in body.decode("utf-8").split("\n"):
        if line.startswith("data: ") and "task_id" in line:
            chunk = json.loads(line[6:])
            task_id = chunk.get("task_id")
            break
    assert task_id is not None, "Chat stream must return task_id event"

    # Verify task in RECEIVED status
    status, task_info = api_client.get_task(task_id)
    assert status == 200
    assert task_info["status"] == "RECEIVED"

    # Step 3: Orchestrator advances through planning
    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")

    # Step 4: Worker loads portal and encounters CAPTCHA challenge
    with oracle_db.lock:
        oracle_db.challenge_buffer[task_id] = DUMMY_CAPTCHA_PNG
        oracle_db.tasks[task_id]["pending_input"] = {
            "kind": "CAPTCHA",
            "prompt": "Enter letters shown in image",
            "expires_in": 180,
            "attempts_left": 3
        }
    transition_task(task_id, "WAITING_FOR_USER")

    # Step 5: Mobile app fetches in-memory CAPTCHA
    s_cap, img_bytes, _ = api_client.get_challenge(task_id)
    assert s_cap == 200
    assert img_bytes.startswith(b"\x89PNG")

    # Step 6: Citizen submits solved CAPTCHA
    s_in1, r_in1 = api_client.submit_input(task_id, "captcha", "K7M9P2")
    assert s_in1 == 200
    assert r_in1["status"] == "accepted"

    # Step 7: Portal validates login and sends OTP
    status, login_res = mock_portal_client.login(uid=valid_uid, captcha="K7M9P2")
    assert status == 200
    session_id = login_res["session_id"]

    transition_task(task_id, "AUTHENTICATING")
    with oracle_db.lock:
        oracle_db.tasks[task_id]["pending_input"] = {
            "kind": "OTP",
            "prompt": "Enter 6-digit OTP sent to registered mobile",
            "expires_in": 180,
            "attempts_left": 3
        }
    transition_task(task_id, "WAITING_FOR_USER")

    # Step 8: Citizen enters 6-digit OTP into secure input sheet
    s_in2, r_in2 = api_client.submit_input(task_id, "otp", "123456")
    assert s_in2 == 200

    # Step 9: Worker relays OTP to portal
    transition_task(task_id, "AUTHENTICATING")
    s_otp, r_otp = mock_portal_client.verify_otp(session_id, "123456")
    assert s_otp == 200
    assert r_otp["status"] == "authenticated"

    # Step 10: Portal streams password-protected PDF
    transition_task(task_id, "DOWNLOADING")
    s_dl, pdf_bytes = mock_portal_client.download_pdf()
    assert s_dl == 200

    # Step 11: Worker 5-point document security verifier
    transition_task(task_id, "VERIFYING")
    v_res = verify_document_security(pdf_bytes)
    assert v_res.is_valid is True
    assert v_res.pdf_encrypted is True

    # Step 12: Upload to private Supabase Storage
    storage_path = f"{TEST_PRIMARY_USER_ID}/{task_id}.pdf"
    doc_id = str(uuid.uuid4())
    with oracle_db.lock:
        oracle_db.storage_objects[storage_path] = pdf_bytes
        oracle_db.documents[doc_id] = {
            "id": doc_id,
            "user_id": TEST_PRIMARY_USER_ID,
            "task_id": task_id,
            "storage_path": storage_path,
            "sha256": v_res.sha256,
            "size_bytes": v_res.size_bytes,
            "pdf_encrypted": True,
            "created_at": time.time(),
            "delete_after": time.time() + 86400
        }

    # Step 13: Verifier transitions task to COMPLETED
    completed_task = transition_task(task_id, "COMPLETED", actor="verifier")
    assert completed_task["status"] == "COMPLETED"

    # Step 14: Mobile app queries download endpoint
    s_url, dl_meta = api_client.get_download_url(task_id)
    assert s_url == 200
    assert "download_url" in dl_meta
    assert dl_meta["expires_in"] == 60

    # Step 15: Delivered document SHA-256 matches verified hash
    assert hashlib.sha256(pdf_bytes).hexdigest() == v_res.sha256

# ===========================================================================
# 2. Wrong CAPTCHA Recovery Journey
# ===========================================================================

def test_scenario_wrong_captcha_recovery_journey(api_client, mock_portal_client):
    """Citizen enters wrong CAPTCHA, receives inline error, refreshes, enters correctly, proceeds."""
    status, task_data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = task_data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")
    transition_task(task_id, "WAITING_FOR_USER")

    # Simulate portal wrong CAPTCHA failure
    mock_portal_client.set_switch("wrong_captcha", enabled=True)
    status, login_res = mock_portal_client.login(uid="234567890128", captcha="WRONG_CHARS")
    assert status == 400
    assert login_res["error"] == "INVALID_CAPTCHA"

    # Worker re-generates CAPTCHA and stays in WAITING_FOR_USER
    with oracle_db.lock:
        oracle_db.challenge_buffer[task_id] = DUMMY_CAPTCHA_PNG # fresh captcha
        oracle_db.tasks[task_id]["pending_input"] = {
            "kind": "CAPTCHA",
            "prompt": "Invalid code. Please enter the fresh CAPTCHA",
            "attempts_left": 2
        }

    # Citizen fetches new CAPTCHA
    s_cap, fresh_img, _ = api_client.get_challenge(task_id)
    assert s_cap == 200

    # Turn off failure switch and submit correct CAPTCHA
    mock_portal_client.set_switch("wrong_captcha", enabled=False)
    s_login2, login_res2 = mock_portal_client.login(uid="234567890128", captcha="CORRECT_CHARS")
    assert s_login2 == 200
    assert login_res2["status"] == "otp_sent"

    # Task advances successfully to AUTHENTICATING
    transition_task(task_id, "AUTHENTICATING")
    assert oracle_db.tasks[task_id]["status"] == "AUTHENTICATING"

# ===========================================================================
# 3. Wrong OTP Retry Recovery Journey
# ===========================================================================

def test_scenario_wrong_otp_retry_recovery_journey(api_client, mock_portal_client):
    """Citizen enters incorrect OTP, attempts left decrements to 2, citizen enters correct OTP, completes."""
    status, login_res = mock_portal_client.login(uid="234567890128", captcha="VALID_CAP")
    assert status == 200
    session_id = login_res["session_id"]

    status, task_data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = task_data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")
    transition_task(task_id, "AUTHENTICATING")
    transition_task(task_id, "WAITING_FOR_USER")

    # Attempt 1: wrong OTP submitted
    s_otp1, r_otp1 = mock_portal_client.verify_otp(session_id, "999999")
    assert s_otp1 == 400
    assert r_otp1["attempts_left"] == 2

    # App updates attempts remaining
    with oracle_db.lock:
        oracle_db.tasks[task_id]["pending_input"] = {
            "kind": "OTP",
            "prompt": "Incorrect OTP. 2 attempts remaining.",
            "attempts_left": 2
        }

    # Status check confirms attempts_left == 2
    _, task_info = api_client.get_task(task_id)
    assert task_info["pending_input"]["attempts_left"] == 2

    # Attempt 2: correct OTP submitted
    s_otp2, r_otp2 = mock_portal_client.verify_otp(session_id, "123456")
    assert s_otp2 == 200
    assert r_otp2["status"] == "authenticated"

    # Proceed through download and verification
    transition_task(task_id, "AUTHENTICATING")
    transition_task(task_id, "DOWNLOADING")
    transition_task(task_id, "VERIFYING")
    transition_task(task_id, "COMPLETED", actor="verifier")
    assert oracle_db.tasks[task_id]["status"] == "COMPLETED"

# ===========================================================================
# 4. Expired OTP Recovery Journey
# ===========================================================================

def test_scenario_expired_otp_recovery_journey(api_client, mock_portal_client):
    """OTP expires after 180s, user clicks Resend OTP, timer resets, user submits fresh OTP, completes."""
    status, login_res = mock_portal_client.login(uid="234567890128", captcha="VALID_CAP")
    session_id = login_res["session_id"]

    status, task_data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = task_data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")
    transition_task(task_id, "AUTHENTICATING")
    transition_task(task_id, "WAITING_FOR_USER")

    # Simulate OTP expiration on portal
    mock_portal_client.set_switch("expired_otp", enabled=True)
    s_exp, r_exp = mock_portal_client.verify_otp(session_id, "123456")
    assert s_exp == 400
    assert r_exp["error"] == "OTP_EXPIRED"

    # User triggers Resend OTP
    mock_portal_client.set_switch("expired_otp", enabled=False)
    s_resend, r_resend = mock_portal_client.resend_otp(session_id)
    assert s_resend == 200
    assert r_resend["attempts_left"] == 3
    assert r_resend["expires_in"] == 180

    # User submits newly issued OTP
    s_ok, r_ok = mock_portal_client.verify_otp(session_id, "123456")
    assert s_ok == 200
    assert r_ok["status"] == "authenticated"

# ===========================================================================
# 5. Cooperative Cancellation Mid-Flight
# ===========================================================================

def test_scenario_cooperative_cancellation_mid_flight(api_client):
    """Citizen cancels task during input wait; state transitions to CANCELLED and input is rejected."""
    status, task_data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = task_data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")
    transition_task(task_id, "WAITING_FOR_USER")

    # Citizen clicks Cancel in app
    s_cancel, r_cancel = api_client.cancel_task(task_id)
    assert s_cancel == 200
    assert r_cancel["status"] == "CANCELLED"

    # Status check confirms CANCELLED
    _, task_info = api_client.get_task(task_id)
    assert task_info["status"] == "CANCELLED"

    # Subsequent input submission rejected
    s_input, r_input = api_client.submit_input(task_id, "otp", "123456")
    assert s_input == 400
    assert "not waiting for input" in r_input.get("message", "")

    # User can now start a new task without 409 Conflict
    s_new, r_new = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    assert s_new == 201
    assert r_new["id"] != task_id

# ===========================================================================
# 6. Tampered Payload Failure Recovery
# ===========================================================================

def test_scenario_tampered_payload_failure_and_user_guidance(api_client, mock_portal_client):
    """When portal delivers a corrupt or malicious payload, verifier halts pipeline with clear error."""
    status, task_data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = task_data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")
    transition_task(task_id, "DOWNLOADING")
    transition_task(task_id, "VERIFYING")

    # Portal serves corrupt PDF
    mock_portal_client.set_switch("corrupt_pdf", enabled=True)
    _, corrupt_bytes = mock_portal_client.download_pdf()

    # Verifier execution
    v_res = verify_document_security(corrupt_bytes)
    assert v_res.is_valid is False

    # Verifier marks task FAILED with reason
    failed_task = transition_task(task_id, "FAILED", actor="verifier", reason=v_res.error_code)
    assert failed_task["status"] == "FAILED"

    # Ensure no document was stored
    with oracle_db.lock:
        stored_docs = [d for d in oracle_db.documents.values() if d.get("task_id") == task_id]
        assert len(stored_docs) == 0

    # User querying download receives 400
    s_dl, r_dl = api_client.get_download_url(task_id)
    assert s_dl == 400
    assert "Cannot download in status FAILED" in r_dl.get("message", "")
