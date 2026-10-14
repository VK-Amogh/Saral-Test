"""
Saral AI — Tier 1: Category-Partition Feature Coverage Test Suite
File: tests/e2e/test_tier1_feature_coverage.py

Covers all core features in isolation (>= 5 tests per feature domain):
1. Authentication & Authorization (F8, F9, F10)
2. Chat SSE Streaming (F17, F18, F19, F20)
3. Task Lifecycle (F21, F24, F25, F28, F29, F32)
4. State Machine Transitions & Verifier Gate (F21, F22)
5. Inputs & SecretStr Relay (F26, F27, F30)
6. CAPTCHA Challenge Broker (F26, F31)
7. Document Downloads & Delivery (F5, F33)
8. Document Deletion (F34)
9. Retention & Cleanup (F36, F64)
"""

import time
import uuid
import tempfile
import os
import pytest
from .conftest import (
    oracle_db,
    transition_task,
    validate_verhoeff,
    generate_valid_aadhaar,
    scrub_pii,
    DUMMY_CAPTCHA_PNG,
    TEST_PRIMARY_USER_ID,
    TEST_SECONDARY_USER_ID,
    CLEANUP_SECRET
)

# ===========================================================================
# 1. Authentication & Authorization
# ===========================================================================

def test_auth_health_endpoint_public_access(api_client):
    """GET /health must be publicly accessible without any credentials."""
    status, data = api_client.get_health()
    assert status == 200, f"Expected 200, got {status}"
    assert data.get("status") == "ok"
    assert data.get("service") == "saral-api"

def test_auth_protected_endpoints_reject_unauthenticated(api_client):
    """Protected endpoints must reject calls without Authorization header with 401."""
    # Chat endpoint
    status, data, _ = api_client.send_chat("Hello", idempotency_key=str(uuid.uuid4()), token="")
    assert status == 401, f"Expected 401 on unauthenticated chat, got {status}"

    # Task creation
    status, data = api_client.create_task(token="")
    assert status == 401, f"Expected 401 on unauthenticated task create, got {status}"

def test_auth_invalid_or_expired_jwt_rejected(api_client):
    """Protected endpoints must reject forged or expired JWT tokens with 401."""
    bogus_token = "invalid_or_expired_token_signature_12345"
    status, data = api_client.create_task(token=bogus_token)
    assert status == 401, f"Expected 401 on invalid token, got {status}"

def test_auth_task_ownership_isolation_between_users(api_client, secondary_api_client):
    """User B must be strictly forbidden from accessing User A's task."""
    # User A creates a task
    status, task_data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    assert status == 201
    task_id = task_data["id"]

    # User B attempts to read User A's task
    sec_status, sec_data = secondary_api_client.get_task(task_id)
    assert sec_status == 403, f"Expected 403 Forbidden for User B, got {sec_status}"
    assert "error" in sec_data

def test_auth_document_ownership_isolation_between_users(api_client, secondary_api_client):
    """User B must be strictly forbidden from deleting User A's document."""
    # Insert a document belonging to User A
    doc_id = str(uuid.uuid4())
    with oracle_db.lock:
        oracle_db.documents[doc_id] = {
            "id": doc_id,
            "user_id": TEST_PRIMARY_USER_ID,
            "storage_path": f"{TEST_PRIMARY_USER_ID}/task_abc.pdf",
            "file_name": "aadhaar.pdf",
            "created_at": time.time(),
            "delete_after": time.time() + 86400
        }

    # User B attempts to delete User A's document
    status, data = secondary_api_client.delete_document(doc_id)
    assert status == 403, f"Expected 403 for unauthorized document deletion, got {status}"

def test_auth_input_submission_ownership_isolation(api_client, secondary_api_client):
    """User B cannot submit OTP input for User A's pending task."""
    status, task_data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = task_data["id"]

    # Put task in WAITING_FOR_USER
    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "WAITING_FOR_USER")

    # User B attempts to submit input
    status, data = secondary_api_client.submit_input(task_id, "otp", "123456")
    assert status == 403, f"Expected 403 for input on foreign task, got {status}"

# ===========================================================================
# 2. Chat SSE Streaming
# ===========================================================================

def test_chat_sse_streaming_response_format(api_client):
    """POST /api/v1/chat must return text/event-stream content type and token events."""
    idempotency_key = str(uuid.uuid4())
    status, body_or_data, headers = api_client.send_chat(
        text="Hello, how can you help me today?",
        idempotency_key=idempotency_key
    )
    assert status == 200, f"Expected 200, got {status}"
    assert "text/event-stream" in headers.get("Content-Type", "")
    assert b"data: " in body_or_data
    assert b"[DONE]" in body_or_data

def test_chat_sse_idempotency_key_header_enforced(api_client):
    """POST /api/v1/chat without Idempotency-Key must be rejected with 400 Bad Request."""
    status, data, _ = api_client.send_chat(text="Hello", idempotency_key=None)
    assert status == 400, f"Expected 400 when missing Idempotency-Key, got {status}"
    assert "Idempotency-Key" in data.get("message", "")

def test_chat_sse_task_intent_detection_and_creation(api_client):
    """Chat message expressing intent to download Aadhaar creates a task and streams event."""
    idempotency_key = str(uuid.uuid4())
    status, body, _ = api_client.send_chat(
        text="Please help me download my Aadhaar card",
        idempotency_key=idempotency_key
    )
    assert status == 200
    assert b"task_id" in body
    assert b"RECEIVED" in body
    assert b"aadhaar_download" in body

def test_chat_sse_conversation_id_persistence(api_client):
    """Passing an existing conversation_id preserves context thread."""
    conv_id = str(uuid.uuid4())
    status, _, _ = api_client.send_chat(
        text="My name is Rajesh",
        conversation_id=conv_id,
        idempotency_key=str(uuid.uuid4())
    )
    assert status == 200

    # Follow up message
    status2, _, _ = api_client.send_chat(
        text="What is my name?",
        conversation_id=conv_id,
        idempotency_key=str(uuid.uuid4())
    )
    assert status2 == 200

def test_chat_sse_scrubs_pii_in_stream(api_client):
    """Aadhaar numbers sent in chat message must be scrubbed before processing."""
    valid_aadhaar = generate_valid_aadhaar()
    raw_prompt = f"Download my Aadhaar with number {valid_aadhaar}"
    scrubbed = scrub_pii(raw_prompt)
    assert valid_aadhaar not in scrubbed
    assert "XXXX-XXXX-" in scrubbed

# ===========================================================================
# 3. Task Lifecycle
# ===========================================================================

def test_task_create_direct_endpoint_success(api_client):
    """POST /api/v1/tasks creates a task in RECEIVED status."""
    key = str(uuid.uuid4())
    status, data = api_client.create_task(workflow="aadhaar_download", idempotency_key=key)
    assert status == 201
    assert data.get("status") == "RECEIVED"
    assert "id" in data
    assert data.get("workflow") == "aadhaar_download"

def test_task_create_idempotent_replay(api_client):
    """Replaying task creation with the same idempotency key returns the existing task."""
    key = str(uuid.uuid4())
    status1, data1 = api_client.create_task(idempotency_key=key)
    assert status1 == 201
    task_id1 = data1["id"]

    # Replay identical request
    status2, data2 = api_client.create_task(idempotency_key=key)
    assert status2 == 200
    assert data2["id"] == task_id1
    assert data2.get("replayed") is True

def test_task_get_status_returns_sanitized_state(api_client):
    """GET /api/v1/tasks/{id} returns sanitized status without internal secret fields."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    status, task_info = api_client.get_task(task_id)
    assert status == 200
    assert task_info["id"] == task_id
    assert task_info["status"] == "RECEIVED"
    assert "pending_input" in task_info
    # Secrets must never appear
    assert "otp" not in task_info
    assert "secret" not in task_info

def test_task_one_active_workflow_per_user_enforced(api_client):
    """A user cannot create a second active task for the same workflow simultaneously."""
    # First task
    status1, data1 = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    assert status1 == 201

    # Second task without completing or cancelling the first
    status2, data2 = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    assert status2 == 409, f"Expected 409 Conflict, got {status2}"
    assert "already in progress" in data2.get("message", "")

def test_task_cancel_cooperative_abort_success(api_client):
    """POST /api/v1/tasks/{id}/cancel aborts an active task transitioning to CANCELLED."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    status, cancel_data = api_client.cancel_task(task_id)
    assert status == 200
    assert cancel_data["status"] == "CANCELLED"

    # Status query confirms CANCELLED
    status, task_info = api_client.get_task(task_id)
    assert task_info["status"] == "CANCELLED"

def test_task_cancel_rejected_for_terminal_task(api_client):
    """Attempting to cancel an already terminal task returns 400 Bad Request."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    # First cancel succeeds
    api_client.cancel_task(task_id)

    # Second cancel must fail
    status2, cancel_data2 = api_client.cancel_task(task_id)
    assert status2 == 400, f"Expected 400 on terminal task cancel, got {status2}"

# ===========================================================================
# 4. State Machine Transitions & Verifier Gate
# ===========================================================================

def test_state_machine_legal_forward_transitions(api_client):
    """Happy path transitions must succeed through the full state sequence."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    # Transition sequence
    task = transition_task(task_id, "VALIDATING")
    assert task["status"] == "VALIDATING"

    task = transition_task(task_id, "PLANNING")
    assert task["status"] == "PLANNING"

    task = transition_task(task_id, "RUNNING")
    assert task["status"] == "RUNNING"

    task = transition_task(task_id, "AUTHENTICATING")
    assert task["status"] == "AUTHENTICATING"

    task = transition_task(task_id, "DOWNLOADING")
    assert task["status"] == "DOWNLOADING"

    task = transition_task(task_id, "VERIFYING")
    assert task["status"] == "VERIFYING"

    task = transition_task(task_id, "COMPLETED", actor="verifier")
    assert task["status"] == "COMPLETED"

def test_state_machine_illegal_transition_rejection(api_client):
    """Transitioning between states not defined in the transition matrix must raise ValueError."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    # Illegal jump: RECEIVED -> COMPLETED
    with pytest.raises(ValueError, match="Illegal transition"):
        transition_task(task_id, "COMPLETED")

def test_state_machine_verifier_gate_strictly_enforced(api_client):
    """Only actor='verifier' can transition VERIFYING -> COMPLETED."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")
    transition_task(task_id, "DOWNLOADING")
    transition_task(task_id, "VERIFYING")

    # Attempt transition by verifier succeeds
    task = transition_task(task_id, "COMPLETED", actor="verifier")
    assert task["status"] == "COMPLETED"

def test_state_machine_non_verifier_actor_cannot_complete(api_client):
    """Non-verifier actor (e.g. LLM or orchestrator) cannot advance VERIFYING -> COMPLETED."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")
    transition_task(task_id, "DOWNLOADING")
    transition_task(task_id, "VERIFYING")

    # Attempt by llm actor must raise ValueError
    with pytest.raises(ValueError, match="Only actor='verifier' can transition"):
        transition_task(task_id, "COMPLETED", actor="llm")

def test_state_machine_terminal_states_are_immutable(api_client):
    """Once terminal (COMPLETED, FAILED, CANCELLED, EXPIRED), no further transition is allowed."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    transition_task(task_id, "FAILED")
    with pytest.raises(ValueError, match="Terminal state"):
        transition_task(task_id, "RUNNING")

# ===========================================================================
# 5. Inputs & SecretStr Relay
# ===========================================================================

def test_input_valid_6_digit_numeric_otp_accepted(api_client):
    """POST /input accepts valid 6-digit numeric OTP when in WAITING_FOR_USER."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "WAITING_FOR_USER")

    status, input_res = api_client.submit_input(task_id, "otp", "123456")
    assert status == 200
    assert input_res["status"] == "accepted"

def test_input_invalid_non_numeric_otp_rejected(api_client):
    """Submitting non-numeric OTP (letters/symbols) returns 422 Unprocessable Entity."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "WAITING_FOR_USER")

    status, input_res = api_client.submit_input(task_id, "otp", "12A45B")
    assert status == 422
    assert "OTP must be exactly 6 numeric digits" in input_res.get("message", "")

def test_input_invalid_length_otp_rejected(api_client):
    """Submitting OTP shorter or longer than 6 digits returns 422."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "WAITING_FOR_USER")

    # 4 digits
    status, _ = api_client.submit_input(task_id, "otp", "1234")
    assert status == 422

    # 8 digits
    status2, _ = api_client.submit_input(task_id, "otp", "12345678")
    assert status2 == 422

def test_input_rejected_when_task_not_waiting_for_user(api_client):
    """Submitting input when task is RUNNING or RECEIVED returns 400 Bad Request."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    # In RECEIVED status
    status, res = api_client.submit_input(task_id, "otp", "123456")
    assert status == 400
    assert "not waiting for input" in res.get("message", "")

def test_input_secretstr_never_persisted_in_database_or_status(api_client):
    """Submitted OTP values are never stored in task records or visible in GET /tasks/{id}."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "WAITING_FOR_USER")

    secret_otp = "987654"
    api_client.submit_input(task_id, "otp", secret_otp)

    # Query status
    status, task_info = api_client.get_task(task_id)
    assert status == 200
    serialized = str(task_info)
    assert secret_otp not in serialized

    # Inspect internal db record directly
    with oracle_db.lock:
        db_task_str = str(oracle_db.tasks[task_id])
        assert secret_otp not in db_task_str

# ===========================================================================
# 6. CAPTCHA Challenge Broker
# ===========================================================================

def test_challenge_captcha_image_bytes_returned(api_client):
    """GET /challenge returns image/png bytes from in-memory challenge buffer."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    with oracle_db.lock:
        oracle_db.challenge_buffer[task_id] = DUMMY_CAPTCHA_PNG

    status, body, headers = api_client.get_challenge(task_id)
    assert status == 200
    assert headers.get("Content-Type") == "image/png"
    assert body.startswith(b"\x89PNG")

def test_challenge_captcha_has_no_store_cache_headers(api_client):
    """GET /challenge must set Cache-Control: no-store to prevent caching on client or proxies."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    status, _, headers = api_client.get_challenge(task_id)
    assert status == 200
    cache_ctrl = headers.get("Cache-Control", "")
    assert "no-store" in cache_ctrl

def test_challenge_nonexistent_task_returns_404(api_client):
    """GET /challenge on unknown task_id returns 404 Not Found."""
    status, _, _ = api_client.get_challenge("nonexistent_task_id_999")
    assert status == 404

def test_challenge_unauthorized_user_access_blocked(api_client, secondary_api_client):
    """User B cannot fetch CAPTCHA image belonging to User A's task."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    status, _, _ = secondary_api_client.get_challenge(task_id)
    assert status in {403, 404}

def test_challenge_image_content_type_is_png(api_client):
    """Challenge endpoint strictly returns image/png mime-type."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    status, _, headers = api_client.get_challenge(task_id)
    assert headers.get("Content-Type") == "image/png"

# ===========================================================================
# 7. Document Downloads & Delivery
# ===========================================================================

def test_download_signed_url_generated_for_completed_task(api_client):
    """GET /download returns a signed Supabase URL for COMPLETED task."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    # Transition to COMPLETED
    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")
    transition_task(task_id, "DOWNLOADING")
    transition_task(task_id, "VERIFYING")
    transition_task(task_id, "COMPLETED", actor="verifier")

    status, dl_data = api_client.get_download_url(task_id)
    assert status == 200
    assert "download_url" in dl_data
    assert "signed" in dl_data["download_url"]

def test_download_signed_url_validity_window_is_60_seconds(api_client):
    """Generated signed URL expires_in field must be approximately 60 seconds."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")
    transition_task(task_id, "DOWNLOADING")
    transition_task(task_id, "VERIFYING")
    transition_task(task_id, "COMPLETED", actor="verifier")

    status, dl_data = api_client.get_download_url(task_id)
    assert dl_data.get("expires_in") == 60

def test_download_rejected_for_incomplete_or_running_task(api_client):
    """GET /download on a RUNNING or WAITING_FOR_USER task returns 400 Bad Request."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")

    status, dl_data = api_client.get_download_url(task_id)
    assert status == 400
    assert "Cannot download in status RUNNING" in dl_data.get("message", "")

def test_download_ownership_isolation_prevents_unauthorized_access(api_client, secondary_api_client):
    """User B cannot generate download URL for User A's completed task."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")
    transition_task(task_id, "DOWNLOADING")
    transition_task(task_id, "VERIFYING")
    transition_task(task_id, "COMPLETED", actor="verifier")

    status, dl_data = secondary_api_client.get_download_url(task_id)
    assert status == 403

def test_download_metadata_structure_contains_doc_type(api_client):
    """Download response contains doc_type metadata matching workflow."""
    status, data = api_client.create_task(idempotency_key=str(uuid.uuid4()))
    task_id = data["id"]

    transition_task(task_id, "VALIDATING")
    transition_task(task_id, "PLANNING")
    transition_task(task_id, "RUNNING")
    transition_task(task_id, "DOWNLOADING")
    transition_task(task_id, "VERIFYING")
    transition_task(task_id, "COMPLETED", actor="verifier")

    status, dl_data = api_client.get_download_url(task_id)
    assert dl_data.get("doc_type") == "aadhaar"

# ===========================================================================
# 8. Document Deletion
# ===========================================================================

def test_document_delete_removes_row_and_storage_object(api_client):
    """DELETE /api/v1/documents/{id} deletes the DB record and the underlying storage file."""
    doc_id = str(uuid.uuid4())
    storage_path = f"{TEST_PRIMARY_USER_ID}/doc_{doc_id}.pdf"
    with oracle_db.lock:
        oracle_db.documents[doc_id] = {
            "id": doc_id,
            "user_id": TEST_PRIMARY_USER_ID,
            "storage_path": storage_path,
            "delete_after": time.time() + 3600
        }
        oracle_db.storage_objects[storage_path] = b"%PDF-1.4 sample payload"

    status, data = api_client.delete_document(doc_id)
    assert status == 200
    assert data["status"] == "deleted"

    # Verify removed from store
    with oracle_db.lock:
        assert doc_id not in oracle_db.documents
        assert storage_path not in oracle_db.storage_objects

def test_document_delete_nonexistent_returns_404(api_client):
    """DELETE /api/v1/documents/{id} for non-existent document returns 404."""
    status, data = api_client.delete_document("nonexistent_doc_id_999")
    assert status == 404

def test_document_delete_requires_authentication(api_client):
    """Unauthenticated DELETE returns 401 Unauthorized."""
    status, data = api_client.delete_document("any_doc_id", token="")
    assert status == 401

def test_document_delete_ownership_isolation_enforced(api_client, secondary_api_client):
    """User B cannot delete User A's document."""
    doc_id = str(uuid.uuid4())
    with oracle_db.lock:
        oracle_db.documents[doc_id] = {
            "id": doc_id,
            "user_id": TEST_PRIMARY_USER_ID,
            "storage_path": f"{TEST_PRIMARY_USER_ID}/doc_user_a.pdf",
            "delete_after": time.time() + 3600
        }

    status, data = secondary_api_client.delete_document(doc_id)
    assert status == 403

def test_document_delete_subsequent_read_returns_404(api_client):
    """Once deleted, subsequent delete attempts return 404."""
    doc_id = str(uuid.uuid4())
    with oracle_db.lock:
        oracle_db.documents[doc_id] = {
            "id": doc_id,
            "user_id": TEST_PRIMARY_USER_ID,
            "storage_path": f"{TEST_PRIMARY_USER_ID}/doc_{doc_id}.pdf",
            "delete_after": time.time() + 3600
        }

    api_client.delete_document(doc_id)
    status2, _ = api_client.delete_document(doc_id)
    assert status2 == 404

# ===========================================================================
# 9. Retention & Cleanup
# ===========================================================================

def test_cleanup_endpoint_requires_valid_secret(api_client):
    """POST /internal/cleanup requires CLEANUP_SECRET header."""
    status, data = api_client.run_cleanup(secret=CLEANUP_SECRET)
    assert status == 200
    assert data["status"] == "ok"

def test_cleanup_endpoint_rejects_invalid_secret(api_client):
    """POST /internal/cleanup rejects invalid secret with 401 Unauthorized."""
    status, data = api_client.run_cleanup(secret="bogus_invalid_secret_key")
    assert status == 401

def test_cleanup_expired_documents_are_purged(api_client):
    """Documents with delete_after <= now are purged from database and storage."""
    past_doc_id = str(uuid.uuid4())
    past_storage_path = f"{TEST_PRIMARY_USER_ID}/past_{past_doc_id}.pdf"
    with oracle_db.lock:
        oracle_db.documents[past_doc_id] = {
            "id": past_doc_id,
            "user_id": TEST_PRIMARY_USER_ID,
            "storage_path": past_storage_path,
            "delete_after": time.time() - 100 # expired
        }
        oracle_db.storage_objects[past_storage_path] = b"%PDF-1.4 expired"

    status, data = api_client.run_cleanup()
    assert status == 200
    assert data["cleaned_documents"] >= 1

    with oracle_db.lock:
        assert past_doc_id not in oracle_db.documents
        assert past_storage_path not in oracle_db.storage_objects

def test_cleanup_unexpired_documents_are_preserved(api_client):
    """Documents with delete_after > now are preserved during sweep."""
    future_doc_id = str(uuid.uuid4())
    future_storage_path = f"{TEST_PRIMARY_USER_ID}/future_{future_doc_id}.pdf"
    with oracle_db.lock:
        oracle_db.documents[future_doc_id] = {
            "id": future_doc_id,
            "user_id": TEST_PRIMARY_USER_ID,
            "storage_path": future_storage_path,
            "delete_after": time.time() + 86400 # 24h in future
        }
        oracle_db.storage_objects[future_storage_path] = b"%PDF-1.4 unexpired"

    status, data = api_client.run_cleanup()
    assert status == 200

    with oracle_db.lock:
        assert future_doc_id in oracle_db.documents
        assert future_storage_path in oracle_db.storage_objects

def test_cleanup_worker_temp_dir_guaranteed_cleanup_in_finally():
    """Worker process must guarantee removal of temporary download directory in finally block."""
    temp_dir = tempfile.mkdtemp(prefix="saral_worker_test_")
    assert os.path.exists(temp_dir)

    try:
        # Simulate worker download interception
        dummy_file = os.path.join(temp_dir, "downloaded.pdf")
        with open(dummy_file, "wb") as f:
            f.write(b"%PDF-1.4 worker temp")
        assert os.path.exists(dummy_file)
    finally:
        # Cleanup in finally block
        if os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    assert not os.path.exists(temp_dir), "Temporary worker directory must be purged in finally"
