"""
Saral AI — DigiLocker Integration & OAuth2 Test Suite
File: backend/tests/test_digilocker.py

Verifies:
1. Consent URL generation & HMAC-SHA256 signed state structure.
2. Tampered & expired state token rejection (HTTP 400).
3. Task creation with workflow='aadhaar_digilocker' (RECEIVED -> VALIDATING -> PLANNING -> WAITING_FOR_USER).
4. GET /api/v1/digilocker/authorize/{task_id} endpoint authentication & authorization.
5. End-to-end OAuth callback execution with mocked DigiLocker token & file APIs.
6. 5-point document security inspection on streamed e-Aadhaar PDF.
7. Corrupt & malicious PDF rejection (HTTP 422 and task status FAILED).
8. Verifier-only completion gate enforcement.
9. Supabase Storage upload and document persistence.
10. Download endpoint signed URL generation for completed DigiLocker tasks.
"""

import time
import uuid
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from pydantic import SecretStr

from backend.app.services.digilocker_service import (
    DigiLockerService,
    DigiLockerStateExpiredError,
    DigiLockerStateInvalidError,
    DigiLockerTokenExchangeError,
    DigiLockerVerificationError,
    digilocker_service,
    generate_digilocker_state,
    verify_digilocker_state,
)
from backend.app.state_machine import TaskState, UnauthorizedActorError, transition
from backend.app.store import store
from backend.app.worker.verifier import DocumentVerifier, verify_document_security
from mock_portal.pdf_generator import (
    generate_corrupt_pdf,
    generate_malicious_pdf,
    generate_valid_pdf,
)

TEST_USER_ID = "usr_primary_88e36780"
TEST_SECONDARY_USER_ID = "usr_secondary_99f45610"


# ===========================================================================
# 1. State Token & Consent URL Tests
# ===========================================================================

def test_generate_consent_url_and_valid_hmac_state():
    """Verify consent URL parameters and HMAC-SHA256 signed state integrity."""
    task_id = str(uuid.uuid4())
    user_id = TEST_USER_ID

    url = digilocker_service.generate_consent_url(task_id=task_id, user_id=user_id)
    assert "https://api.digitallocker.gov.in/public/oauth2/1/authorize" in url
    assert "response_type=code" in url
    assert "client_id=" in url
    assert "redirect_uri=" in url
    assert "scope=read" in url
    assert "state=" in url

    # Extract state token
    state_param = [p.split("=")[1] for p in url.split("?")[1].split("&") if p.startswith("state=")][0]
    decoded_payload = digilocker_service.verify_state(state_param)

    assert decoded_payload["task_id"] == task_id
    assert decoded_payload["user_id"] == user_id
    assert "expires_at" in decoded_payload
    assert decoded_payload["expires_at"] > time.time()
    assert "nonce" in decoded_payload


def test_tampered_state_token_rejected(client):
    """Tampering with payload or signature raises DigiLockerStateInvalidError and returns 400."""
    task_id = str(uuid.uuid4())
    user_id = TEST_USER_ID

    valid_state = generate_digilocker_state(task_id=task_id, user_id=user_id)
    parts = valid_state.split(".")
    assert len(parts) == 2

    # 1. Tamper payload
    tampered_payload = ("A" if parts[0][0] != "A" else "B") + parts[0][1:]
    tampered_state_1 = f"{tampered_payload}.{parts[1]}"
    with pytest.raises(DigiLockerStateInvalidError):
        verify_digilocker_state(tampered_state_1)

    # 2. Tamper signature
    tampered_sig = ("0" if parts[1][0] != "0" else "1") + parts[1][1:]
    tampered_state_2 = f"{parts[0]}.{tampered_sig}"
    with pytest.raises(DigiLockerStateInvalidError):
        verify_digilocker_state(tampered_state_2)

    # 3. Malformed state token (no dot)
    with pytest.raises(DigiLockerStateInvalidError):
        verify_digilocker_state("completely_invalid_state_token_without_period")

    # 4. Callback endpoint rejects tampered state with HTTP 400
    res = client.get(f"/api/v1/digilocker/callback?code=mock_code&state={tampered_state_2}")
    assert res.status_code == 400
    assert "Invalid or expired state token" in res.json().get("message", "")


def test_expired_state_token_rejected(client):
    """Expired state token (> 180s TTL) raises DigiLockerStateExpiredError and returns 400."""
    task_id = str(uuid.uuid4())
    user_id = TEST_USER_ID

    # Generate token that expired 10 seconds ago
    expired_state = generate_digilocker_state(task_id=task_id, user_id=user_id, ttl_seconds=-10)

    with pytest.raises(DigiLockerStateExpiredError):
        verify_digilocker_state(expired_state)

    # Callback endpoint rejects expired state with HTTP 400
    res = client.get(f"/api/v1/digilocker/callback?code=mock_code&state={expired_state}")
    assert res.status_code == 400
    assert "expired" in res.json().get("message", "").lower()


# ===========================================================================
# 2. Task Creation & Authorize Endpoints
# ===========================================================================

def test_task_creation_digilocker_workflow(client, auth_headers):
    """POST /api/v1/tasks with workflow='aadhaar_digilocker' initializes in WAITING_FOR_USER."""
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    res = client.post("/api/v1/tasks", json={"workflow": "aadhaar_digilocker"}, headers=headers)

    assert res.status_code == 201
    data = res.json()
    task_id = data["id"]
    assert data["workflow"] == "aadhaar_digilocker"
    assert data["status"] == "WAITING_FOR_USER"
    assert "pending_input" in data
    assert data["pending_input"]["kind"] == "oauth_consent"
    assert "auth_url" in data["pending_input"]
    assert "https://api.digitallocker.gov.in/public/oauth2/1/authorize" in data["pending_input"]["auth_url"]

    # Verify GET /api/v1/tasks/{task_id} also reflects pending_input
    get_res = client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["status"] == "WAITING_FOR_USER"
    assert get_data["pending_input"]["kind"] == "oauth_consent"


def test_authorize_endpoint_access_and_ownership(client, auth_headers, secondary_auth_headers):
    """GET /api/v1/digilocker/authorize/{id} returns consent URL and enforces ownership."""
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    create_res = client.post("/api/v1/tasks", json={"workflow": "aadhaar_digilocker"}, headers=headers)
    task_id = create_res.json()["id"]

    # Primary user gets authorize URL
    auth_res = client.get(f"/api/v1/digilocker/authorize/{task_id}", headers=auth_headers)
    assert auth_res.status_code == 200
    auth_data = auth_res.json()
    assert auth_data["task_id"] == task_id
    assert "auth_url" in auth_data
    assert "scope=read" in auth_data["auth_url"]

    # Secondary user blocked with 403 Forbidden
    sec_res = client.get(f"/api/v1/digilocker/authorize/{task_id}", headers=secondary_auth_headers)
    assert sec_res.status_code == 403

    # Non-existent task returns 404 Not Found
    missing_res = client.get(f"/api/v1/digilocker/authorize/{uuid.uuid4()}", headers=auth_headers)
    assert missing_res.status_code == 404


def test_authorize_endpoint_terminal_task_rejected(client, auth_headers):
    """GET /api/v1/digilocker/authorize/{id} rejects tasks already in terminal state."""
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    create_res = client.post("/api/v1/tasks", json={"workflow": "aadhaar_digilocker"}, headers=headers)
    task_id = create_res.json()["id"]

    # Force task to CANCELLED
    store.tasks[task_id]["status"] = "CANCELLED"

    res = client.get(f"/api/v1/digilocker/authorize/{task_id}", headers=auth_headers)
    assert res.status_code == 400
    assert "terminal state" in res.json().get("message", "")


# ===========================================================================
# 3. Callback Handling with Mocked DigiLocker APIs
# ===========================================================================

@pytest.mark.asyncio
async def test_digilocker_callback_success_end_to_end(client, auth_headers):
    """Complete OAuth callback flow: token exchange -> streaming PDF -> 5-point verification -> COMPLETED."""
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    create_res = client.post("/api/v1/tasks", json={"workflow": "aadhaar_digilocker"}, headers=headers)
    task_id = create_res.json()["id"]

    # Generate valid password-protected e-Aadhaar PDF
    valid_pdf_bytes = generate_valid_pdf(encrypted=True, size_kb=15)
    verifier_result = verify_document_security(valid_pdf_bytes)
    assert verifier_result.is_valid is True
    assert verifier_result.pdf_encrypted is True

    # Generate valid state token
    state = generate_digilocker_state(task_id=task_id, user_id=TEST_USER_ID)

    # Mock token exchange and document fetch
    mock_token = SecretStr("mock_digilocker_access_token_xyz987")
    with patch.object(digilocker_service, "exchange_code_for_token", new_callable=AsyncMock) as mock_exchange, \
         patch.object(digilocker_service, "fetch_eaadhaar_document", new_callable=AsyncMock) as mock_fetch:

        mock_exchange.return_value = mock_token
        mock_fetch.return_value = valid_pdf_bytes

        cb_res = client.get(f"/api/v1/digilocker/callback?code=mock_code_abc&state={state}")

        assert cb_res.status_code == 200
        data = cb_res.json()
        assert data["status"] == "COMPLETED"
        assert data["task_id"] == task_id
        assert "document_id" in data
        assert data["pdf_encrypted"] is True
        assert data["sha256"] == verifier_result.sha256

        mock_exchange.assert_awaited_once()
        mock_fetch.assert_awaited_once_with(mock_token, http_client=None)

    # Verify task state in store
    task = store.tasks[task_id]
    assert task["status"] == "COMPLETED"
    assert task["pending_input"] is None

    # Verify document record in store
    doc_id = data["document_id"]
    assert doc_id in store.documents
    doc = store.documents[doc_id]
    assert doc["user_id"] == TEST_USER_ID
    assert doc["task_id"] == task_id
    assert doc["doc_type"] == "aadhaar"
    assert doc["pdf_encrypted"] is True
    assert doc["sha256"] == verifier_result.sha256

    # Verify binary stored in storage_objects
    storage_path = f"{TEST_USER_ID}/{task_id}.pdf"
    assert storage_path in store.storage_objects
    assert store.storage_objects[storage_path] == valid_pdf_bytes

    # Verify download endpoint generates signed URL
    dl_res = client.get(f"/api/v1/tasks/{task_id}/download", headers=auth_headers)
    assert dl_res.status_code == 200
    dl_data = dl_res.json()
    assert "download_url" in dl_data
    assert dl_data["expires_in"] == 60


def test_digilocker_callback_corrupt_pdf_fails_verification(client, auth_headers):
    """Corrupt PDF payload fails 5-point verification, returns 422, and transitions task to FAILED."""
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    create_res = client.post("/api/v1/tasks", json={"workflow": "aadhaar_digilocker"}, headers=headers)
    task_id = create_res.json()["id"]

    corrupt_bytes = generate_corrupt_pdf()
    state = generate_digilocker_state(task_id=task_id, user_id=TEST_USER_ID)

    mock_token = SecretStr("mock_token_123")
    with patch.object(digilocker_service, "exchange_code_for_token", new_callable=AsyncMock) as mock_exchange, \
         patch.object(digilocker_service, "fetch_eaadhaar_document", new_callable=AsyncMock) as mock_fetch:

        mock_exchange.return_value = mock_token
        mock_fetch.return_value = corrupt_bytes

        cb_res = client.get(f"/api/v1/digilocker/callback?code=mock_code&state={state}")

        assert cb_res.status_code == 422
        assert "Verification Failed" in cb_res.json().get("error", "")

    # Task must transition to FAILED
    task = store.tasks[task_id]
    assert task["status"] == "FAILED"
    assert len(store.documents) == 0


def test_digilocker_callback_malicious_pdf_rejected(client, auth_headers):
    """Malicious PDF containing /JavaScript action is blocked by verifier, returning 422."""
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    create_res = client.post("/api/v1/tasks", json={"workflow": "aadhaar_digilocker"}, headers=headers)
    task_id = create_res.json()["id"]

    malicious_bytes = generate_malicious_pdf("javascript")
    state = generate_digilocker_state(task_id=task_id, user_id=TEST_USER_ID)

    mock_token = SecretStr("mock_token_123")
    with patch.object(digilocker_service, "exchange_code_for_token", new_callable=AsyncMock) as mock_exchange, \
         patch.object(digilocker_service, "fetch_eaadhaar_document", new_callable=AsyncMock) as mock_fetch:

        mock_exchange.return_value = mock_token
        mock_fetch.return_value = malicious_bytes

        cb_res = client.get(f"/api/v1/digilocker/callback?code=mock_code&state={state}")

        assert cb_res.status_code == 422
        assert "Verification Failed" in cb_res.json().get("error", "")

    task = store.tasks[task_id]
    assert task["status"] == "FAILED"


def test_digilocker_callback_token_exchange_failure(client, auth_headers):
    """Failure during token exchange returns HTTP 502 and marks task as FAILED."""
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    create_res = client.post("/api/v1/tasks", json={"workflow": "aadhaar_digilocker"}, headers=headers)
    task_id = create_res.json()["id"]

    state = generate_digilocker_state(task_id=task_id, user_id=TEST_USER_ID)

    with patch.object(digilocker_service, "exchange_code_for_token", new_callable=AsyncMock) as mock_exchange:
        mock_exchange.side_effect = DigiLockerTokenExchangeError("Invalid client secret or code expired")

        cb_res = client.get(f"/api/v1/digilocker/callback?code=bad_code&state={state}")
        assert cb_res.status_code == 502

    task = store.tasks[task_id]
    assert task["status"] == "FAILED"


def test_digilocker_callback_missing_parameters(client):
    """Callback with missing code or state returns 400 Bad Request."""
    res1 = client.get("/api/v1/digilocker/callback")
    assert res1.status_code == 400

    res2 = client.get("/api/v1/digilocker/callback?code=code_only")
    assert res2.status_code == 400

    res3 = client.get("/api/v1/digilocker/callback?state=state_only")
    assert res3.status_code == 400


# ===========================================================================
# 4. Verifier Actor Gate Enforcement
# ===========================================================================

def test_digilocker_verifier_only_completion_gate():
    """Verify that only actor='verifier' can transition task to COMPLETED."""
    task = {"id": "dl_test_task", "status": TaskState.VERIFYING.value}

    # Orchestrator actor is rejected
    with pytest.raises(UnauthorizedActorError):
        transition(task, TaskState.COMPLETED, actor="orchestrator")

    # Worker actor is rejected
    with pytest.raises(UnauthorizedActorError):
        transition(task, TaskState.COMPLETED, actor="worker")

    # System actor is rejected
    with pytest.raises(UnauthorizedActorError):
        transition(task, TaskState.COMPLETED, actor="system")

    # Verifier actor succeeds
    transition(task, TaskState.COMPLETED, actor="verifier")
    assert task["status"] == "COMPLETED"


# ===========================================================================
# 5. Direct HTTP Client Functions Coverage
# ===========================================================================

@pytest.mark.asyncio
async def test_direct_exchange_code_for_token_httpx_mock():
    """Verify exchange_code_for_token handles standard OAuth JSON responses."""
    code = "auth_code_9988"
    mock_resp = httpx.Response(
        200,
        json={"access_token": "bearer_access_tok_4455", "token_type": "Bearer", "expires_in": 3600},
        request=httpx.Request("POST", "https://api.digitallocker.gov.in/public/oauth2/1/token")
    )

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_resp)

    token = await digilocker_service.exchange_code_for_token(code=code, http_client=mock_client)
    assert isinstance(token, SecretStr)
    assert token.get_secret_value() == "bearer_access_tok_4455"


@pytest.mark.asyncio
async def test_direct_fetch_eaadhaar_document_httpx_mock():
    """Verify fetch_eaadhaar_document streams raw bytes into RAM."""
    token = SecretStr("mock_secret_token_1122")
    pdf_bytes = generate_valid_pdf(encrypted=False, size_kb=12)

    mock_resp = httpx.Response(
        200,
        content=pdf_bytes,
        headers={"Content-Type": "application/pdf"},
        request=httpx.Request("GET", "https://api.digitallocker.gov.in/public/oauth2/1/file/in.gov.uidai-eaadhaar")
    )

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_resp)

    result_bytes = await digilocker_service.fetch_eaadhaar_document(access_token=token, http_client=mock_client)
    assert result_bytes == pdf_bytes
    assert result_bytes.startswith(b"%PDF-")
