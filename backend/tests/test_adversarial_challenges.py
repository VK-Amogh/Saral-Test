"""Adversarial stress-testing suite for non-negotiable security invariants.

File: backend/tests/test_adversarial_challenges.py

Covers:
1. Verifier-only completion gate (rejects orchestrator, user, llm, system, worker, admin, etc.)
2. Zero persistence of OTP / CAPTCHA (in-memory relay only, no db/disk/log leakage)
3. Route allowlist (rejects external domains, sub-domain deceptions, SSRF vectors)
4. DigiLocker state token security (rejects tampered, forged, or expired HMAC state tokens with HTTP 400)
"""

import asyncio
import io
import json
import logging
import time
import uuid
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.tasks import CreateTaskRequest, SubmitInputRequest
from app.broker import challenge_broker
from app.config import get_settings
from app.main import app
from app.scrubber import (
    RedactingLogFilter,
    generate_valid_aadhaar,
    scrub_pii,
    validate_verhoeff,
)
from app.services.digilocker_service import (
    DigiLockerService,
    DigiLockerStateExpiredError,
    DigiLockerStateInvalidError,
    digilocker_service,
    generate_digilocker_state,
    verify_digilocker_state,
)
from app.state_machine import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    InvalidStateTransitionError,
    StateMachineError,
    TaskState,
    TerminalStateError,
    UnauthorizedActorError,
    can_transition,
    is_terminal,
    transition,
)
from app.store import store
from app.worker.allowlist import DomainAllowlistInterceptor, SecurityPolicyViolation
from app.worker.verifier import DocumentVerifier, verify_document_security


# ===========================================================================
# 1. Verifier-Only Completion Gate Adversarial Tests
# ===========================================================================

class TestVerifierOnlyCompletionGate:
    """Stress-test that only actor='verifier' can transition a task to COMPLETED."""

    @pytest.mark.parametrize("unauthorized_actor", [
        "orchestrator",
        "user",
        "llm",
        "system",
        "worker",
        "admin",
        "watchdog",
        "root",
        "",
        " ",
        "VERIFIER",          # Case-sensitivity check
        "verifier ",         # Trailing whitespace
        " verifier",         # Leading whitespace
        "verifier\x00",      # Null-byte injection
        "None",
        "supervisor",
    ])
    def test_unauthorized_actors_strictly_rejected_at_completion(self, unauthorized_actor):
        """Any actor other than exact 'verifier' MUST raise UnauthorizedActorError."""
        task = {
            "id": str(uuid.uuid4()),
            "status": TaskState.VERIFYING.value,
            "created_at": time.time(),
        }

        with pytest.raises(UnauthorizedActorError) as exc_info:
            transition(task, TaskState.COMPLETED, actor=unauthorized_actor)

        assert "Only actor='verifier' can transition to COMPLETED" in str(exc_info.value)
        # Verify status remained unchanged
        assert task["status"] == TaskState.VERIFYING.value

    @pytest.mark.parametrize("unauthorized_actor", [
        "orchestrator", "user", "llm", "system", "worker", "admin", "VERIFIER", ""
    ])
    def test_can_transition_returns_false_for_unauthorized_actors(self, unauthorized_actor):
        """can_transition must return False for all unauthorized actors targeting COMPLETED."""
        assert can_transition(TaskState.VERIFYING, TaskState.COMPLETED, actor=unauthorized_actor) is False

    def test_authorized_verifier_actor_succeeds_from_verifying(self):
        """actor='verifier' MUST succeed when transitioning from VERIFYING to COMPLETED."""
        task = {
            "id": str(uuid.uuid4()),
            "status": TaskState.VERIFYING.value,
            "created_at": time.time(),
        }
        assert can_transition(TaskState.VERIFYING, TaskState.COMPLETED, actor="verifier") is True
        result = transition(task, TaskState.COMPLETED, actor="verifier")
        assert result["status"] == "COMPLETED"
        assert "finished_at" in result

    @pytest.mark.parametrize("non_verifying_state", [
        TaskState.RECEIVED,
        TaskState.VALIDATING,
        TaskState.PLANNING,
        TaskState.RUNNING,
        TaskState.WAITING_FOR_USER,
        TaskState.AUTHENTICATING,
        TaskState.DOWNLOADING,
    ])
    def test_illegal_jump_to_completed_rejected_even_for_verifier(self, non_verifying_state):
        """Even with actor='verifier', jumping directly to COMPLETED from non-VERIFYING states is illegal."""
        task = {
            "id": str(uuid.uuid4()),
            "status": non_verifying_state.value,
            "created_at": time.time(),
        }
        with pytest.raises(InvalidStateTransitionError):
            transition(task, TaskState.COMPLETED, actor="verifier")

        assert task["status"] == non_verifying_state.value

    @pytest.mark.parametrize("terminal_state", [
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELLED,
        TaskState.EXPIRED,
    ])
    def test_terminal_states_cannot_transition_further(self, terminal_state):
        """Once terminal, no transition is allowed to ANY state, even by verifier or admin."""
        task = {
            "id": str(uuid.uuid4()),
            "status": terminal_state.value,
            "created_at": time.time(),
        }
        for target in TaskState:
            with pytest.raises(TerminalStateError):
                transition(task, target, actor="verifier")


# ===========================================================================
# 2. Zero Persistence of Sensitive Credentials (OTP & CAPTCHA)
# ===========================================================================

class TestZeroPersistenceCredentials:
    """Verify OTP and CAPTCHA values are strictly transient in memory and never leaked."""

    @pytest.fixture(autouse=True)
    def clean_store(self):
        store.reset()
        yield
        store.reset()

    @pytest.mark.asyncio
    async def test_challenge_broker_in_memory_relay_and_purge(self):
        """Challenge broker stores OTP in SecretStr, resolves future, and cleans up references."""
        task_id = str(uuid.uuid4())

        fut = challenge_broker.register_challenge(
            task_id=task_id,
            kind="otp",
            prompt="Enter 6-digit OTP",
            ttl_seconds=180,
        )

        # Check metadata is sanitized (no secret in pending_input)
        pending = challenge_broker.get_pending_input(task_id)
        assert pending is not None
        assert pending["kind"] == "otp"
        assert "value" not in pending
        assert "secret" not in pending

        # Resolve with sensitive OTP
        secret_otp = SecretStr("789123")
        success = challenge_broker.resolve_challenge(task_id, secret_otp)
        assert success is True

        # Future received the SecretStr
        resolved = await fut
        assert isinstance(resolved, SecretStr)
        assert resolved.get_secret_value() == "789123"

        # Verify references purged from broker
        assert challenge_broker.get_pending_input(task_id) is None
        assert task_id not in challenge_broker._futures
        assert task_id not in challenge_broker._pending_inputs
        assert task_id not in challenge_broker._expiry_timestamps

    def test_captcha_image_stored_in_ram_only_and_purged(self):
        """CAPTCHA image bytes are kept in RAM and can be completely cleared."""
        task_id = str(uuid.uuid4())
        fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"

        challenge_broker.store_captcha(task_id, fake_png)
        assert challenge_broker.get_captcha(task_id) == fake_png

        challenge_broker.clear_captcha(task_id)
        assert challenge_broker.get_captcha(task_id) is None

    @pytest.mark.asyncio
    async def test_api_tasks_input_does_not_persist_secret_to_store_tasks(self):
        """Submitting input via POST /api/v1/tasks/{id}/input does not write OTP to store.tasks."""
        client = TestClient(app)
        user_id = "usr_primary_88e36780"
        headers = {"Authorization": "Bearer jwt_bearer_valid_token_primary_usr_primary_88e36780"}

        # Setup task in WAITING_FOR_USER
        task_id = str(uuid.uuid4())
        store.tasks[task_id] = {
            "id": task_id,
            "user_id": user_id,
            "workflow": "aadhaar_download",
            "status": "WAITING_FOR_USER",
            "created_at": time.time(),
            "pending_input": "otp",
        }

        # Register challenge in broker (within active event loop)
        fut = challenge_broker.register_challenge(task_id=task_id, kind="otp")

        # Submit OTP
        resp = client.post(
            f"/api/v1/tasks/{task_id}/input",
            json={"input_id": "otp", "value": "654321"},
            headers=headers,
        )
        assert resp.status_code == 200

        # Inspect store.tasks[task_id] in memory
        task_record = store.tasks[task_id]
        # Ensure NO key holds the raw OTP
        for k, v in task_record.items():
            assert "654321" not in str(v), f"Leaked OTP in task field {k}: {v}"

        # Clean broker
        challenge_broker.cleanup(task_id)

    def test_redacting_log_filter_sanitizes_adversarial_leakage_attempts(self):
        """RedactingLogFilter blocks raw Aadhaar, OTP, passwords, bearer tokens, and biometrics."""
        log_filter = RedactingLogFilter()
        logger_test = logging.getLogger("test_redaction")
        logger_test.setLevel(logging.INFO)
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.addFilter(log_filter)
        logger_test.addHandler(handler)

        valid_aadhaar = generate_valid_aadhaar("12345678901")
        sensitive_messages = [
            f"Citizen entered Aadhaar: {valid_aadhaar}",
            "User provided otp: 987654 for verification",
            "Authorization: Bearer super_secret_jwt_token_1234567890",
            "Contact user at citizen@example.com or +91 9876543210",
            "Biometrics check: fingerprint scan and iris scan matched",
        ]

        for msg in sensitive_messages:
            logger_test.info(msg)

        handler.flush()
        captured_logs = log_stream.getvalue()

        # Assert no sensitive values leaked in verbatim text
        assert valid_aadhaar not in captured_logs
        assert "987654" not in captured_logs
        assert "super_secret_jwt_token_1234567890" not in captured_logs
        assert "citizen@example.com" not in captured_logs
        assert "9876543210" not in captured_logs
        assert "fingerprint" not in captured_logs.lower()
        assert "iris" not in captured_logs.lower()

        # Assert redacted placeholders exist
        assert "[REDACTED_OTP]" in captured_logs
        assert "[REDACTED_TOKEN]" in captured_logs
        assert "[REDACTED_EMAIL]" in captured_logs
        assert "[REDACTED_PHONE]" in captured_logs
        assert "[REDACTED_BIOMETRIC]" in captured_logs


# ===========================================================================
# 3. Route Allowlist Adversarial Interception Tests
# ===========================================================================

class TestRouteAllowlistEnforcement:
    """Stress-test domain allowlist against SSRF, phishing, and hostname spoofing."""

    @pytest.fixture
    def interceptor(self):
        return DomainAllowlistInterceptor()

    @pytest.mark.parametrize("allowed_url", [
        "https://uidai.gov.in",
        "https://uidai.gov.in/en/my-aadhaar.html",
        "https://myaadhaar.uidai.gov.in/gen-download-eaadhaar",
        "https://subdomain.myaadhaar.uidai.gov.in/api",
        "http://localhost:8000/mock_portal",
        "http://127.0.0.1:8080/portal",
        "https://mock-portal.local/login",
        "https://supabase.co/storage/v1",
        "https://rsftbslckmdkynprmpin.supabase.co/object/authenticated",
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB",
        "blob:http://localhost:8000/1234-uuid",
        "about:blank",
    ])
    def test_allowlisted_urls_permitted(self, interceptor, allowed_url):
        """Legitimate portal and backend endpoints must be permitted."""
        assert interceptor.is_url_allowed(allowed_url) is True

    @pytest.mark.parametrize("malicious_url", [
        # Domain suffix deception (phishing / domain spoofing)
        "https://uidai.gov.in.evil.com/fake-login",
        "https://myaadhaar.uidai.gov.in.attacker.org/steal",
        "https://supabase.co.phishing.io/collect",
        # Prefix spoofing
        "https://evil-uidai.gov.in/login",
        "https://not-supabase.co/object",
        # Cloud Metadata SSRF vectors
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.169.254/computeMetadata/v1/",
        "http://metadata.google.internal/computeMetadata/v1/",
        # Private RFC-1918 internal IPs
        "http://10.0.0.1:8080/internal",
        "http://192.168.1.1/router",
        "http://172.16.0.5:5432/db",
        # External websites
        "https://google.com",
        "https://pastebin.com/raw/malware",
        "https://webhook.site/test",
        # Scheme attacks targeting unauthorized external hosts
        "file:///etc/passwd",
        "file:///C:/Windows/win.ini",
        "gopher://attacker.com:6379/_flushall",
        "ftp://attacker.com/leak",
        # Empty and malformed
        "",
        " ",
        "not_a_valid_url",
    ])
    def test_non_allowlisted_urls_strictly_blocked(self, interceptor, malicious_url):
        """Any URL not strictly belonging to allowed domains must be rejected."""
        assert interceptor.is_url_allowed(malicious_url) is False
        with pytest.raises(SecurityPolicyViolation):
            interceptor.assert_url_allowed(malicious_url)

    @pytest.mark.asyncio
    async def test_playwright_route_abort_execution(self, interceptor):
        """handle_route must invoke route.abort('blockedbyclient') on unauthorized requests."""
        class MockRoute:
            def __init__(self, url):
                self.url = url
                self.aborted = False
                self.abort_reason = None
                self.continued = False

            async def abort(self, reason=None):
                self.aborted = True
                self.abort_reason = reason

            async def continue_(self):
                self.continued = True

        # Test blocked route
        blocked_route = MockRoute("https://evil-attacker.com/malicious.js")
        await interceptor.handle_route(blocked_route)
        assert blocked_route.aborted is True
        assert blocked_route.abort_reason == "blockedbyclient"
        assert blocked_route.continued is False
        assert "https://evil-attacker.com/malicious.js" in interceptor.blocked_urls

        # Test allowed route
        allowed_route = MockRoute("https://myaadhaar.uidai.gov.in/script.js")
        await interceptor.handle_route(allowed_route)
        assert allowed_route.continued is True
        assert allowed_route.aborted is False
        assert "https://myaadhaar.uidai.gov.in/script.js" in interceptor.allowed_urls


# ===========================================================================
# 4. DigiLocker State Token Security (HMAC-SHA256, 180s TTL)
# ===========================================================================

class TestDigiLockerStateTokenSecurity:
    """Stress-test DigiLocker HMAC state token validation and rejection behavior."""

    @pytest.fixture
    def test_client(self):
        return TestClient(app)

    @pytest.fixture(autouse=True)
    def clean_store(self):
        store.reset()
        yield
        store.reset()

    def test_valid_state_token_verification(self):
        """A validly generated HMAC state token successfully verifies and returns payload."""
        task_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        state = generate_digilocker_state(task_id, user_id, ttl_seconds=180)

        payload = verify_digilocker_state(state)
        assert payload["task_id"] == task_id
        assert payload["user_id"] == user_id
        assert payload["expires_at"] > time.time()

    def test_tampered_payload_raises_invalid_state_error(self):
        """Modifying any character in the base64 payload invalidates the HMAC signature."""
        task_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        state = generate_digilocker_state(task_id, user_id, ttl_seconds=180)

        b64_payload, signature = state.split(".")
        # Flip a character in payload
        tampered_b64 = ("A" if b64_payload[0] != "A" else "B") + b64_payload[1:]
        tampered_state = f"{tampered_b64}.{signature}"

        with pytest.raises(DigiLockerStateInvalidError) as exc_info:
            verify_digilocker_state(tampered_state)
        assert "Invalid state signature" in str(exc_info.value) or "tampered" in str(exc_info.value)

    def test_tampered_signature_raises_invalid_state_error(self):
        """Modifying signature bytes causes HMAC mismatch."""
        task_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        state = generate_digilocker_state(task_id, user_id, ttl_seconds=180)

        b64_payload, signature = state.split(".")
        # Tamper signature hex
        tampered_sig = ("0" if signature[0] != "0" else "1") + signature[1:]
        tampered_state = f"{b64_payload}.{tampered_sig}"

        with pytest.raises(DigiLockerStateInvalidError):
            verify_digilocker_state(tampered_state)

    def test_expired_state_token_raises_expired_state_error(self):
        """State tokens with expired timestamps (>180s TTL) are strictly rejected."""
        task_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        # Generate token with negative TTL (already expired)
        expired_state = generate_digilocker_state(task_id, user_id, ttl_seconds=-10)

        with pytest.raises(DigiLockerStateExpiredError) as exc_info:
            verify_digilocker_state(expired_state)
        assert "expired" in str(exc_info.value).lower()

    @pytest.mark.parametrize("malformed_state", [
        "",
        "no_dot_delimiter",
        "one.two.three_dots",
        ".starts_with_dot",
        "ends_with_dot.",
        "!!!invalid_base64!!!.abcdef123456",
        "eyJhbGciOiJIUzI1NiJ9.",
    ])
    def test_malformed_state_tokens_rejected(self, malformed_state):
        """Malformed state strings raise DigiLockerStateInvalidError."""
        with pytest.raises(DigiLockerStateInvalidError):
            verify_digilocker_state(malformed_state)

    def test_callback_endpoint_rejects_tampered_state_with_http_400(self, test_client):
        """GET /api/v1/digilocker/callback with tampered state returns HTTP 400 Bad Request."""
        task_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        valid_state = generate_digilocker_state(task_id, user_id, ttl_seconds=180)
        b64_part, sig_part = valid_state.split(".")
        tampered_state = f"{b64_part}.{'0' * len(sig_part)}"

        resp = test_client.get(f"/api/v1/digilocker/callback?code=mock_oauth_code&state={tampered_state}")
        assert resp.status_code == 400
        msg = resp.json().get("message", "")
        assert "Invalid or expired state token" in msg

    def test_callback_endpoint_rejects_expired_state_with_http_400(self, test_client):
        """GET /api/v1/digilocker/callback with expired state returns HTTP 400 Bad Request."""
        task_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        expired_state = generate_digilocker_state(task_id, user_id, ttl_seconds=-30)

        resp = test_client.get(f"/api/v1/digilocker/callback?code=mock_oauth_code&state={expired_state}")
        assert resp.status_code == 400
        msg = resp.json().get("message", "")
        assert "Invalid or expired state token" in msg

    def test_callback_endpoint_rejects_missing_code_or_state_with_http_400(self, test_client):
        """GET /api/v1/digilocker/callback with missing code or state returns HTTP 400 Bad Request."""
        resp = test_client.get("/api/v1/digilocker/callback")
        assert resp.status_code == 400

        resp2 = test_client.get("/api/v1/digilocker/callback?code=some_code")
        assert resp2.status_code == 400

        resp3 = test_client.get("/api/v1/digilocker/callback?state=some_state")
        assert resp3.status_code == 400

    def test_callback_endpoint_rejects_cross_user_hijack_attempt_with_http_403(self, test_client):
        """If user B generates state for a task owned by user A, callback rejects with 403."""
        task_id = str(uuid.uuid4())
        user_a = str(uuid.uuid4())
        user_b = str(uuid.uuid4())

        # Task belongs to user A
        store.tasks[task_id] = {
            "id": task_id,
            "user_id": user_a,
            "workflow": "aadhaar_digilocker",
            "status": "WAITING_FOR_USER",
            "created_at": time.time(),
        }

        # Token created by user B for user A's task
        state_attacker = generate_digilocker_state(task_id, user_b, ttl_seconds=180)

        resp = test_client.get(f"/api/v1/digilocker/callback?code=valid_code&state={state_attacker}")
        assert resp.status_code == 403
        msg = resp.json().get("message", "")
        assert "Ownership check failed" in msg


# ===========================================================================
# 5. Internal Worker WebSocket State Machine Transition Tests
# ===========================================================================

class TestWebSocketWorkerStateMachineTransitions:
    """Verify that WS /internal/worker routes all progress, challenges, failures, and completions
    strictly through deterministic state machine transitions with verifier gate enforcement."""

    @pytest.fixture
    def test_client(self):
        return TestClient(app)

    @pytest.fixture(autouse=True)
    def clean_store(self):
        store.reset()
        yield
        store.reset()

    def test_websocket_worker_enforces_verifier_completion_gate(self, test_client):
        """Worker task_completed frame steps task through VERIFYING to COMPLETED with actor='verifier'."""
        task_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        settings = get_settings()

        store.tasks[task_id] = {
            "id": task_id,
            "user_id": user_id,
            "workflow": "aadhaar_download",
            "status": "RUNNING",
            "created_at": time.time(),
            "history": [{"from": None, "to": "RUNNING", "timestamp": time.time(), "actor": "system"}],
        }

        with test_client.websocket_connect(f"/internal/worker?secret={settings.WORKER_SECRET}") as ws:
            ws.send_text(json.dumps({
                "type": "task_completed",
                "task_id": task_id,
                "document_id": "doc_123",
                "storage_path": f"{user_id}/{task_id}.pdf",
            }))
            ack = ws.receive_json()
            assert ack["type"] == "completed_ack"
            assert ack["task_id"] == task_id

        task = store.tasks[task_id]
        assert task["status"] == "COMPLETED"
        assert task["document_id"] == "doc_123"
        # Confirm that history includes transition to VERIFYING and then COMPLETED with actor='verifier'
        history_actions = [(h.get("to"), h.get("actor")) for h in task.get("history", [])]
        assert ("DOWNLOADING", "orchestrator") in history_actions
        assert ("VERIFYING", "orchestrator") in history_actions
        assert ("COMPLETED", "verifier") in history_actions

    def test_websocket_worker_progress_and_failure_transitions(self, test_client):
        """Worker task_progress and task_failed frames use state machine transitions."""
        task_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        settings = get_settings()

        store.tasks[task_id] = {
            "id": task_id,
            "user_id": user_id,
            "workflow": "aadhaar_download",
            "status": "RUNNING",
            "created_at": time.time(),
            "history": [{"from": None, "to": "RUNNING", "timestamp": time.time(), "actor": "system"}],
        }

        with test_client.websocket_connect(f"/internal/worker?secret={settings.WORKER_SECRET}") as ws:
            # 1. Progress update
            ws.send_text(json.dumps({
                "type": "task_progress",
                "task_id": task_id,
                "progress": 50,
                "message": "Authenticating with portal",
                "status": "AUTHENTICATING",
            }))
            ack = ws.receive_json()
            assert ack["type"] == "progress_ack"

            assert store.tasks[task_id]["status"] == "AUTHENTICATING"
            assert store.tasks[task_id]["progress"] == 50
            assert store.tasks[task_id]["progress_message"] == "Authenticating with portal"

            # 2. Failure update
            ws.send_text(json.dumps({
                "type": "task_failed",
                "task_id": task_id,
                "error_code": "INVALID_OTP",
                "error_message": "OTP incorrect",
            }))
            ack_fail = ws.receive_json()
            assert ack_fail["type"] == "failed_ack"

            assert store.tasks[task_id]["status"] == "FAILED"
            assert store.tasks[task_id]["error_code"] == "INVALID_OTP"
            assert store.tasks[task_id]["error_message"] == "OTP incorrect"
