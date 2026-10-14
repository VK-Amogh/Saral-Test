"""Comprehensive unit and integration test suite for Saral AI backend."""

import asyncio
import logging
import time
import uuid
import pytest
from pydantic import SecretStr

from backend.app.auth import UserContext, verify_token
from backend.app.broker import challenge_broker
from backend.app.config import get_settings
from backend.app.llm import llm_service
from backend.app.queue import job_queue
from backend.app.scrubber import (
    RedactingLogFilter,
    compute_verhoeff_checksum,
    generate_valid_aadhaar,
    scrub_pii,
    validate_verhoeff,
)
from backend.app.state_machine import (
    ALLOWED_TRANSITIONS,
    InvalidStateTransitionError,
    StateMachineError,
    TaskState,
    TerminalStateError,
    UnauthorizedActorError,
    can_transition,
    is_terminal,
    transition,
)
from backend.app.store import store
from .conftest import (
    CLEANUP_SECRET,
    TEST_PRIMARY_TOKEN,
    TEST_PRIMARY_USER_ID,
    TEST_SECONDARY_TOKEN,
    TEST_SECONDARY_USER_ID,
    WORKER_SECRET,
)


# ===========================================================================
# 1. Config Tests
# ===========================================================================

def test_config_values():
    """Verify all required configuration values and defaults."""
    settings = get_settings()
    assert "supabase" in settings.SUPABASE_URL.lower()
    assert settings.SUPABASE_PUBLISHABLE_KEY is not None
    assert settings.SUPABASE_SERVICE_ROLE_KEY is not None
    assert settings.GROQ_API_KEY == "gsk_mock_saral_groq_api_key_for_testing"
    assert settings.LLM_MODEL == "llama-3.3-70b-versatile"
    assert settings.CLEANUP_SECRET == "saral_cleanup_cron_secret_auth_token_7766"
    assert settings.WORKER_SECRET == "saral_worker_shared_secret_secure_key_9988"
    assert "mock-portal.local" in settings.ALLOWED_DOMAINS
    assert "uidai.gov.in" in settings.ALLOWED_DOMAINS


# ===========================================================================
# 2. Auth Tests
# ===========================================================================

def test_auth_verify_test_tokens():
    """Verify known test tokens resolve to expected user contexts."""
    user = verify_token(TEST_PRIMARY_TOKEN)
    assert user.user_id == TEST_PRIMARY_USER_ID

    sec_user = verify_token(TEST_SECONDARY_TOKEN)
    assert sec_user.user_id == TEST_SECONDARY_USER_ID


def test_auth_verify_empty_or_bogus_token():
    """Empty or bogus tokens must raise HTTPException 401."""
    with pytest.raises(Exception):
        verify_token("")

    with pytest.raises(Exception):
        verify_token("invalid_bogus_token_12345")


# ===========================================================================
# 3. Scrubber Tests (Verhoeff & PII Redaction)
# ===========================================================================

def test_verhoeff_algorithm_accuracy():
    """Verhoeff validation and checksum calculation must be 100% accurate."""
    valid_aadhaar = generate_valid_aadhaar("12345678901")
    assert len(valid_aadhaar) == 12
    assert validate_verhoeff(valid_aadhaar) is True

    # Tampered number must fail
    tampered = valid_aadhaar[:-1] + str((int(valid_aadhaar[-1]) + 1) % 10)
    assert validate_verhoeff(tampered) is False


def test_scrub_aadhaar_numbers():
    """Valid 12-digit Aadhaar numbers must be masked to XXXX-XXXX-1234."""
    valid = generate_valid_aadhaar("23456789012")
    # Formatted with spaces
    spaced = f"{valid[:4]} {valid[4:8]} {valid[8:]}"
    assert scrub_pii(f"My Aadhaar is {spaced}") == f"My Aadhaar is XXXX-XXXX-{valid[-4:]}"

    # Formatted with dashes
    dashed = f"{valid[:4]}-{valid[4:8]}-{valid[8:]}"
    assert scrub_pii(f"Number {dashed}") == f"Number XXXX-XXXX-{valid[-4:]}"

    # Continuous 12 digits
    assert scrub_pii(f"UID is {valid}") == f"UID is XXXX-XXXX-{valid[-4:]}"


def test_scrub_phone_email_biometrics_otp():
    """Scrubber must redact phone numbers, emails, biometric terms, and OTPs."""
    text = (
        "Contact me at +91 9876543210 or citizen@example.com. "
        "Do not store my fingerprint or iris data. "
        "Your otp is 482910."
    )
    scrubbed = scrub_pii(text)
    assert "[REDACTED_PHONE]" in scrubbed
    assert "[REDACTED_EMAIL]" in scrubbed
    assert "[REDACTED_BIOMETRIC]" in scrubbed
    assert "[REDACTED_OTP]" in scrubbed
    assert "9876543210" not in scrubbed
    assert "citizen@example.com" not in scrubbed
    assert "482910" not in scrubbed


def test_redacting_log_filter():
    """RedactingLogFilter must redact PII, tokens, and Authorization headers."""
    log_filter = RedactingLogFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="User auth Bearer secret_jwt_token_1234567890 with phone 9876543210",
        args=(),
        exc_info=None
    )
    assert log_filter.filter(record) is True
    assert "secret_jwt_token_1234567890" not in record.msg
    assert "[REDACTED_TOKEN]" in record.msg
    assert "[REDACTED_PHONE]" in record.msg


# ===========================================================================
# 4. State Machine Tests
# ===========================================================================

def test_state_machine_legal_progression():
    """Task must transition through valid forward lifecycle."""
    task = {"id": "t1", "status": TaskState.RECEIVED.value}

    task = transition(task, TaskState.VALIDATING)
    assert task["status"] == "VALIDATING"

    task = transition(task, TaskState.PLANNING)
    assert task["status"] == "PLANNING"

    task = transition(task, TaskState.RUNNING)
    assert task["status"] == "RUNNING"

    task = transition(task, TaskState.WAITING_FOR_USER)
    assert task["status"] == "WAITING_FOR_USER"

    task = transition(task, TaskState.AUTHENTICATING)
    assert task["status"] == "AUTHENTICATING"

    task = transition(task, TaskState.DOWNLOADING)
    assert task["status"] == "DOWNLOADING"

    task = transition(task, TaskState.VERIFYING)
    assert task["status"] == "VERIFYING"

    task = transition(task, TaskState.COMPLETED, actor="verifier")
    assert task["status"] == "COMPLETED"
    assert "finished_at" in task


def test_state_machine_verifier_gate():
    """Only actor='verifier' can transition to COMPLETED."""
    task = {"id": "t2", "status": TaskState.VERIFYING.value}

    with pytest.raises(UnauthorizedActorError):
        transition(task, TaskState.COMPLETED, actor="orchestrator")

    with pytest.raises(UnauthorizedActorError):
        transition(task, TaskState.COMPLETED, actor="llm")

    # Verifier succeeds
    transition(task, TaskState.COMPLETED, actor="verifier")
    assert task["status"] == "COMPLETED"


def test_state_machine_terminal_immutability():
    """Terminal states (COMPLETED, FAILED, CANCELLED, EXPIRED) cannot transition."""
    for term_state in [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.EXPIRED]:
        task = {"id": "t_term", "status": term_state.value}
        assert is_terminal(term_state) is True
        with pytest.raises(TerminalStateError):
            transition(task, TaskState.RUNNING)


def test_state_machine_illegal_transition():
    """Illegal jumps must be rejected with InvalidStateTransitionError."""
    task = {"id": "t_bad", "status": TaskState.RECEIVED.value}
    with pytest.raises(InvalidStateTransitionError):
        transition(task, TaskState.DOWNLOADING)


# ===========================================================================
# 5. Challenge Broker Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_challenge_broker_relay():
    """Challenge broker must resolve Future in memory using SecretStr."""
    task_id = "test_task_broker_1"
    future = challenge_broker.register_challenge(task_id, kind="otp")
    assert challenge_broker.has_pending_challenge(task_id) is True

    secret = SecretStr("654321")
    resolved = challenge_broker.resolve_challenge(task_id, secret)
    assert resolved is True

    result = await future
    assert result.get_secret_value() == "654321"
    assert challenge_broker.has_pending_challenge(task_id) is False


def test_challenge_broker_captcha_in_memory():
    """CAPTCHA image bytes must be stored and retrieved from memory with zero persistence."""
    task_id = "test_task_captcha_1"
    png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00fake_captcha_data"
    challenge_broker.store_captcha(task_id, png_data)
    assert challenge_broker.get_captcha(task_id) == png_data

    challenge_broker.clear_captcha(task_id)
    assert challenge_broker.get_captcha(task_id) is None


# ===========================================================================
# 6. LLM & Intent Detection Tests
# ===========================================================================

def test_llm_intent_detection():
    """Detect Aadhaar download intent vs general chat."""
    res1 = llm_service.detect_intent("Please help me download my Aadhaar card")
    assert res1["intent"] == "aadhaar_download"
    assert res1["workflow"] == "aadhaar_download"
    assert res1["requires_task"] is True

    res2 = llm_service.detect_intent("Hello, what is the weather today?")
    assert res2["intent"] == "general_chat"
    assert res2["requires_task"] is False


@pytest.mark.asyncio
async def test_llm_stream_chat():
    """Streaming chat must yield text chunks."""
    messages = [{"role": "user", "content": "Hello"}]
    chunks = []
    async for chunk in llm_service.stream_chat_completion(messages):
        chunks.append(chunk)
    assert len(chunks) > 0


# ===========================================================================
# 7. Queue Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_job_queue_in_memory():
    """JobQueue in-memory fallback must handle enqueue, dequeue, ack, and nack."""
    await job_queue.clear()
    assert await job_queue.size() == 0

    await job_queue.enqueue("q1", "aadhaar_download", "u1", "download request")
    assert await job_queue.size() == 1

    item = await job_queue.dequeue()
    assert item is not None
    assert item["id"] == "q1"
    assert item["workflow"] == "aadhaar_download"
    assert await job_queue.size() == 0

    # Nack returns task to queue
    await job_queue.nack("q1")
    assert await job_queue.size() == 1

    # Dequeue and ack
    item2 = await job_queue.dequeue()
    assert item2["id"] == "q1"
    await job_queue.ack("q1")
    assert await job_queue.size() == 0


# ===========================================================================
# 8. API Endpoint Integration Tests
# ===========================================================================

def test_api_health_endpoint(client):
    """GET /health must return 200 with service information."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "saral-api"


def test_api_chat_missing_idempotency_key(client, auth_headers):
    """POST /api/v1/chat without Idempotency-Key must return 400 Bad Request."""
    response = client.post("/api/v1/chat", json={"text": "hello"}, headers=auth_headers)
    assert response.status_code == 400
    data = response.json()
    assert "Idempotency-Key" in data.get("message", "")


def test_api_chat_unauthenticated(client):
    """Protected endpoints reject requests without token with 401."""
    response = client.post(
        "/api/v1/chat",
        json={"text": "hello"},
        headers={"Idempotency-Key": "key_1"}
    )
    assert response.status_code == 401


def test_api_chat_empty_text(client, auth_headers):
    """POST /api/v1/chat with empty text must return 422."""
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    response = client.post("/api/v1/chat", json={"text": "   "}, headers=headers)
    assert response.status_code == 422


def test_api_chat_aadhaar_intent_creates_task(client, auth_headers):
    """Chat message requesting Aadhaar download must create task and stream event."""
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    response = client.post(
        "/api/v1/chat",
        json={"text": "Please download my Aadhaar card"},
        headers=headers
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    body = response.text
    assert "task_id" in body
    assert "RECEIVED" in body
    assert "aadhaar_download" in body
    assert "[DONE]" in body


def test_api_tasks_crud_lifecycle(client, auth_headers):
    """POST /api/v1/tasks create, GET task, and idempotent replay."""
    idem_key = str(uuid.uuid4())
    headers = {**auth_headers, "Idempotency-Key": idem_key}

    # 1. Create task
    create_res = client.post("/api/v1/tasks", json={"workflow": "aadhaar_download"}, headers=headers)
    assert create_res.status_code == 201
    task_data = create_res.json()
    task_id = task_data["id"]
    assert task_data["status"] == "RECEIVED"

    # 2. Idempotent replay
    replay_res = client.post("/api/v1/tasks", json={"workflow": "aadhaar_download"}, headers=headers)
    assert replay_res.status_code == 200
    replay_data = replay_res.json()
    assert replay_data["id"] == task_id
    assert replay_data["replayed"] is True

    # 3. GET task status
    get_res = client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)
    assert get_res.status_code == 200
    status_data = get_res.json()
    assert status_data["id"] == task_id
    assert status_data["status"] == "RECEIVED"
    assert "otp" not in status_data


def test_api_task_one_active_workflow_conflict(client, auth_headers):
    """Creating a second active task for the same workflow returns 409 Conflict."""
    headers1 = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    client.post("/api/v1/tasks", json={"workflow": "aadhaar_download"}, headers=headers1)

    headers2 = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    res2 = client.post("/api/v1/tasks", json={"workflow": "aadhaar_download"}, headers=headers2)
    assert res2.status_code == 409
    assert "already in progress" in res2.json().get("message", "")


def test_api_task_input_validation(client, auth_headers):
    """Test OTP input submission, state checks, and format validation."""
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    create_res = client.post("/api/v1/tasks", json={"workflow": "aadhaar_download"}, headers=headers)
    task_id = create_res.json()["id"]

    # In RECEIVED status: submitting input returns 400
    inp_res1 = client.post(
        f"/api/v1/tasks/{task_id}/input",
        json={"input_id": "otp", "value": "123456"},
        headers=auth_headers
    )
    assert inp_res1.status_code == 400
    assert "not waiting for input" in inp_res1.json().get("message", "")

    # Put task in WAITING_FOR_USER
    store.tasks[task_id]["status"] = "WAITING_FOR_USER"

    # Non-numeric OTP returns 422
    inp_res2 = client.post(
        f"/api/v1/tasks/{task_id}/input",
        json={"input_id": "otp", "value": "1234AB"},
        headers=auth_headers
    )
    assert inp_res2.status_code == 422

    # Wrong length OTP returns 422
    inp_res3 = client.post(
        f"/api/v1/tasks/{task_id}/input",
        json={"input_id": "otp", "value": "1234"},
        headers=auth_headers
    )
    assert inp_res3.status_code == 422

    # Valid 6-digit OTP returns 200
    inp_res4 = client.post(
        f"/api/v1/tasks/{task_id}/input",
        json={"input_id": "otp", "value": "987654"},
        headers=auth_headers
    )
    assert inp_res4.status_code == 200
    assert inp_res4.json()["status"] == "accepted"


def test_api_challenge_endpoint(client, auth_headers, secondary_auth_headers):
    """GET /api/v1/tasks/{id}/challenge returns PNG with Cache-Control: no-store."""
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    res = client.post("/api/v1/tasks", json={"workflow": "aadhaar_download"}, headers=headers)
    task_id = res.json()["id"]

    challenge_res = client.get(f"/api/v1/tasks/{task_id}/challenge", headers=auth_headers)
    assert challenge_res.status_code == 200
    assert challenge_res.headers["content-type"] == "image/png"
    assert "no-store" in challenge_res.headers.get("cache-control", "")

    # Secondary user blocked
    sec_res = client.get(f"/api/v1/tasks/{task_id}/challenge", headers=secondary_auth_headers)
    assert sec_res.status_code == 403


def test_api_task_cancel(client, auth_headers):
    """Cancel active task transitions to CANCELLED; cancelling terminal task returns 400."""
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    res = client.post("/api/v1/tasks", json={"workflow": "aadhaar_download"}, headers=headers)
    task_id = res.json()["id"]

    # Cancel active task
    cancel_res = client.post(f"/api/v1/tasks/{task_id}/cancel", headers=auth_headers)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    # Second cancel returns 400
    cancel_res2 = client.post(f"/api/v1/tasks/{task_id}/cancel", headers=auth_headers)
    assert cancel_res2.status_code == 400


def test_api_download_signed_url(client, auth_headers):
    """Download url available only when task status is COMPLETED."""
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    res = client.post("/api/v1/tasks", json={"workflow": "aadhaar_download"}, headers=headers)
    task_id = res.json()["id"]

    # Running task returns 400
    dl_res1 = client.get(f"/api/v1/tasks/{task_id}/download", headers=auth_headers)
    assert dl_res1.status_code == 400

    # Mark COMPLETED
    store.tasks[task_id]["status"] = "COMPLETED"
    dl_res2 = client.get(f"/api/v1/tasks/{task_id}/download", headers=auth_headers)
    assert dl_res2.status_code == 200
    dl_data = dl_res2.json()
    assert "download_url" in dl_data
    assert dl_data["expires_in"] == 60
    assert dl_data["doc_type"] == "aadhaar"


def test_api_document_delete(client, auth_headers, secondary_auth_headers):
    """DELETE /api/v1/documents/{id} removes doc and storage file; forbids non-owner."""
    doc_id = str(uuid.uuid4())
    storage_path = f"{TEST_PRIMARY_USER_ID}/{doc_id}.pdf"
    store.documents[doc_id] = {
        "id": doc_id,
        "user_id": TEST_PRIMARY_USER_ID,
        "storage_path": storage_path,
        "delete_after": time.time() + 3600
    }
    store.storage_objects[storage_path] = b"%PDF-1.4 test document"

    # Secondary user blocked
    sec_del = client.delete(f"/api/v1/documents/{doc_id}", headers=secondary_auth_headers)
    assert sec_del.status_code == 403

    # Primary user deletes
    del_res = client.delete(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # Subsequent delete returns 404
    del_res2 = client.delete(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    assert del_res2.status_code == 404


def test_api_retention_cleanup(client):
    """POST /internal/cleanup purges expired documents; rejects invalid secret."""
    now = time.time()
    # Expired document
    exp_id = str(uuid.uuid4())
    store.documents[exp_id] = {
        "id": exp_id,
        "storage_path": f"path_{exp_id}",
        "delete_after": now - 100
    }
    # Unexpired document
    future_id = str(uuid.uuid4())
    store.documents[future_id] = {
        "id": future_id,
        "storage_path": f"path_{future_id}",
        "delete_after": now + 1000
    }

    # Invalid secret
    rej = client.post("/internal/cleanup", headers={"X-Cleanup-Secret": "bad_secret"})
    assert rej.status_code == 401

    # Valid secret
    sweep = client.post("/internal/cleanup", headers={"X-Cleanup-Secret": CLEANUP_SECRET})
    assert sweep.status_code == 200
    assert sweep.json()["cleaned_documents"] >= 1
    assert exp_id not in store.documents
    assert future_id in store.documents


def test_api_worker_websocket(client):
    """WS /internal/worker accepts connection with valid secret; rejects invalid."""
    # Invalid secret closes
    with pytest.raises(Exception):
        with client.websocket_connect("/internal/worker?secret=bad_secret") as ws:
            pass

    # Valid secret connects and echoes
    with client.websocket_connect(f"/internal/worker?secret={WORKER_SECRET}") as ws:
        ws.send_text('{"type": "ping"}')
        resp = ws.receive_json()
        assert resp["type"] == "pong"
