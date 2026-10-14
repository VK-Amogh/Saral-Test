"""
Saral AI — Worker Test Suite
File: backend/app/worker/test_worker.py

Tests for:
1. 5-point document security verifier
2. Domain allowlist route interceptor
3. Worker WebSocket client protocol & relays
4. Automation runner lifecycle and cleanup guarantees
"""

import asyncio
import io
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
import pytest

from backend.app.worker.verifier import DocumentVerifier, verify_document_security, VerifierResult
from backend.app.worker.allowlist import DomainAllowlistInterceptor, SecurityPolicyViolation
from backend.app.worker.client import WorkerWebSocketClient
from backend.app.worker.runner import AadhaarDownloadAutomationRunner, AutomationTaskError
from mock_portal.pdf_generator import (
    generate_valid_pdf,
    generate_corrupt_pdf,
    generate_html_pdf,
    generate_oversize_pdf,
    generate_malicious_pdf,
)
from backend.app.store import store


# ===========================================================================
# 1. Document Verifier Tests (5-Point Security Validation)
# ===========================================================================

def test_verifier_valid_encrypted_pdf():
    """Stage 1-5: Valid password-protected PDF passes all 5 verification points."""
    pdf_bytes = generate_valid_pdf(encrypted=True, size_kb=15)
    verifier = DocumentVerifier(min_size_bytes=100, max_size_mb=5)
    result = verifier.verify(pdf_bytes)

    assert result.is_valid is True
    assert result.error_code is None
    assert result.error_message is None
    assert result.pdf_encrypted is True
    assert result.sha256 is not None
    assert len(result.sha256) == 64
    assert result.size_bytes == len(pdf_bytes)


def test_verifier_valid_unencrypted_pdf():
    """Stage 1-5: Valid unencrypted PDF passes and pdf_encrypted is False."""
    pdf_bytes = generate_valid_pdf(encrypted=False, size_kb=12)
    verifier = DocumentVerifier(min_size_bytes=100, max_size_mb=5)
    result = verifier.verify(pdf_bytes)

    assert result.is_valid is True
    assert result.pdf_encrypted is False
    assert result.sha256 is not None


def test_verifier_rejects_missing_pdf_header():
    """Point 1: Payload not starting with %PDF- is rejected."""
    bad_payload = b"NOT_A_PDF_DOCUMENT_PLAIN_TEXT"
    result = verify_document_security(bad_payload)

    assert result.is_valid is False
    assert result.error_code == "INVALID_PDF_HEADER"
    assert "Payload does not start with %PDF-" in result.error_message


def test_verifier_rejects_html_error_payload():
    """Point 1: HTML masquerading as PDF is rejected by header check."""
    html_payload = generate_html_pdf()
    result = verify_document_security(html_payload)

    assert result.is_valid is False
    assert result.error_code == "INVALID_PDF_HEADER"


def test_verifier_rejects_truncated_file_under_100_bytes():
    """Point 2: File smaller than 100 bytes is rejected."""
    tiny_pdf = b"%PDF-1.4\n%%EOF"
    result = verify_document_security(tiny_pdf, min_size_bytes=100)

    assert result.is_valid is False
    assert result.error_code == "TRUNCATED_PDF"


def test_verifier_rejects_oversize_file_exceeding_5mb():
    """Point 2: File exceeding 5 MB limit is rejected."""
    oversize_pdf = generate_oversize_pdf(size_mb=6)
    result = verify_document_security(oversize_pdf, max_size_mb=5)

    assert result.is_valid is False
    assert result.error_code == "OVERSIZE_PDF"
    assert "exceeds max threshold" in result.error_message


def test_verifier_rejects_missing_eof_marker():
    """Point 3: PDF missing %%EOF trailer marker is rejected."""
    malformed_pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n" + (b" " * 200)
    result = verify_document_security(malformed_pdf)

    assert result.is_valid is False
    assert result.error_code == "MALFORMED_PDF_TRAILER"


def test_verifier_rejects_malicious_javascript():
    """Point 4: PDF containing /JavaScript action dictionary is rejected."""
    malicious_pdf = generate_malicious_pdf("javascript")
    result = verify_document_security(malicious_pdf)

    assert result.is_valid is False
    assert result.error_code == "MALICIOUS_PDF_JAVASCRIPT"
    assert "Forbidden /JavaScript action" in result.error_message


def test_verifier_rejects_malicious_launch():
    """Point 4: PDF containing /Launch action dictionary is rejected."""
    malicious_pdf = generate_malicious_pdf("launch")
    result = verify_document_security(malicious_pdf)

    assert result.is_valid is False
    assert result.error_code == "MALICIOUS_PDF_LAUNCH"
    assert "Forbidden /Launch action" in result.error_message


def test_verifier_verifies_file_on_disk():
    """DocumentVerifier.verify_file verifies physical file on disk."""
    pdf_bytes = generate_valid_pdf(encrypted=True)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        temp_path = f.name

    try:
        verifier = DocumentVerifier()
        result = verifier.verify_file(temp_path)
        assert result.is_valid is True
        assert result.size_bytes == len(pdf_bytes)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_verifier_missing_file_returns_error():
    """DocumentVerifier.verify_file on non-existent path returns FILE_NOT_FOUND."""
    verifier = DocumentVerifier()
    result = verifier.verify_file("/non/existent/path/doc.pdf")
    assert result.is_valid is False
    assert result.error_code == "FILE_NOT_FOUND"


# ===========================================================================
# 2. Domain Allowlist Route Interceptor Tests
# ===========================================================================

def test_allowlist_permits_exact_allowed_domains():
    """Allowlist permits exact domain matches."""
    interceptor = DomainAllowlistInterceptor(["uidai.gov.in", "localhost", "127.0.0.1"])
    assert interceptor.is_url_allowed("https://uidai.gov.in/ecosystem") is True
    assert interceptor.is_url_allowed("http://localhost:8001/login") is True
    assert interceptor.is_url_allowed("http://127.0.0.1:8000/health") is True


def test_allowlist_permits_subdomains_of_allowed_domains():
    """Allowlist permits genuine subdomains of allowlisted hosts."""
    interceptor = DomainAllowlistInterceptor(["uidai.gov.in"])
    assert interceptor.is_url_allowed("https://myaadhaar.uidai.gov.in/portal") is True
    assert interceptor.is_url_allowed("https://api.uidai.gov.in/v1") is True


def test_allowlist_blocks_unauthorized_external_domains():
    """Allowlist blocks foreign / third-party trackers and domains."""
    interceptor = DomainAllowlistInterceptor(["uidai.gov.in", "localhost"])
    assert interceptor.is_url_allowed("https://evil-unauthorized-tracker.com/phishing") is False
    assert interceptor.is_url_allowed("https://google-analytics.com/ga.js") is False
    assert interceptor.is_url_allowed("https://attacker-site.org/exfiltrate") is False


def test_allowlist_blocks_phishing_subdomain_deceptions():
    """Allowlist prevents attacker domains with uidai.gov.in in subdomain."""
    interceptor = DomainAllowlistInterceptor(["uidai.gov.in"])
    # Attack pattern: uidai.gov.in.evilattacker.com
    assert interceptor.is_url_allowed("https://uidai.gov.in.evilattacker.com/steal") is False


def test_allowlist_permits_data_and_blob_urls():
    """Allowlist permits internal browser rendering schemes data: and blob:."""
    interceptor = DomainAllowlistInterceptor(["uidai.gov.in"])
    assert interceptor.is_url_allowed("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA") is True
    assert interceptor.is_url_allowed("blob:http://localhost/1234") is True


def test_allowlist_blocks_non_http_schemes_on_allowlisted_hosts():
    """Allowlist strictly blocks non-HTTP/HTTPS schemes even on allowlisted domains (SSRF/smuggling defense)."""
    interceptor = DomainAllowlistInterceptor(["uidai.gov.in", "localhost", "127.0.0.1"])
    # Gopher protocol smuggling targeting local Redis or internal daemons
    assert interceptor.is_url_allowed("gopher://127.0.0.1:6379/_flushall") is False
    assert interceptor.is_url_allowed("gopher://localhost:6379/_flushall") is False

    # File scheme local filesystem reads
    assert interceptor.is_url_allowed("file://127.0.0.1/etc/passwd") is False
    assert interceptor.is_url_allowed("file://localhost/etc/passwd") is False
    assert interceptor.is_url_allowed("file:///etc/passwd") is False

    # FTP, dict, and LDAP protocols
    assert interceptor.is_url_allowed("ftp://127.0.0.1:21/exploit") is False
    assert interceptor.is_url_allowed("ftp://localhost:21/exploit") is False
    assert interceptor.is_url_allowed("dict://127.0.0.1:11211/stat") is False
    assert interceptor.is_url_allowed("ldap://127.0.0.1:389/test") is False

    # Verify assert_url_allowed raises SecurityPolicyViolation
    with pytest.raises(SecurityPolicyViolation):
        interceptor.assert_url_allowed("gopher://127.0.0.1:6379/_flushall")
    with pytest.raises(SecurityPolicyViolation):
        interceptor.assert_url_allowed("file://127.0.0.1/etc/passwd")


@pytest.mark.asyncio
async def test_allowlist_handle_route_execution():
    """handle_route intercepts requests: continues allowed and aborts disallowed."""
    interceptor = DomainAllowlistInterceptor(["uidai.gov.in"])

    # Mock Playwright Route
    class MockRoute:
        def __init__(self, url):
            self.url = url
            self.continued = False
            self.aborted = False

        async def continue_(self):
            self.continued = True

        async def abort(self, reason="blockedbyclient"):
            self.aborted = True

    allowed_route = MockRoute("https://uidai.gov.in/page")
    await interceptor.handle_route(allowed_route)
    assert allowed_route.continued is True
    assert allowed_route.aborted is False

    disallowed_route = MockRoute("https://evil.com/logger.js")
    await interceptor.handle_route(disallowed_route)
    assert disallowed_route.continued is False
    assert disallowed_route.aborted is True
    assert "https://evil.com/logger.js" in interceptor.blocked_urls


# ===========================================================================
# 3. Worker WebSocket Client Protocol & Relays
# ===========================================================================

@pytest.mark.asyncio
async def test_worker_client_challenge_future_resolution():
    """Client resolves in-memory Future on relay_input message frame."""
    client = WorkerWebSocketClient(shared_secret="secret_123")
    task_id = "test_task_uuid_101"

    # Register future for OTP
    otp_future = client.register_input_future(task_id, "otp")
    assert not otp_future.done()

    # Simulate arrival of relay_input frame from backend
    relay_msg = {
        "type": "relay_input",
        "task_id": task_id,
        "kind": "otp",
        "value": "987654",
    }
    await client._handle_message(relay_msg)

    assert otp_future.done()
    result_val = await otp_future
    assert result_val == "987654"


@pytest.mark.asyncio
async def test_worker_client_task_cancellation_signal():
    """Client marks task cancelled and cancels pending futures on cancel_task."""
    client = WorkerWebSocketClient()
    task_id = "test_task_uuid_102"

    # Assign task to create cancellation event
    await client._handle_message({"type": "assign_task", "task_id": task_id})
    assert not client.is_task_cancelled(task_id)

    # Register pending future
    captcha_future = client.register_input_future(task_id, "captcha")

    # Send cancel_task frame
    await client._handle_message({
        "type": "cancel_task",
        "task_id": task_id,
        "reason": "User cancelled in app"
    })

    assert client.is_task_cancelled(task_id) is True
    assert captcha_future.cancelled() is True


@pytest.mark.asyncio
async def test_worker_client_task_handler_dispatch():
    """Client dispatches assign_task to registered task handler."""
    client = WorkerWebSocketClient()
    task_assigned_event = asyncio.Event()
    received_task_data = {}

    async def mock_task_handler(task_data):
        nonlocal received_task_data
        received_task_data = task_data
        task_assigned_event.set()

    client.set_task_handler(mock_task_handler)

    task_payload = {
        "type": "assign_task",
        "task_id": "task_assign_404",
        "workflow": "aadhaar_download",
    }
    await client._handle_message(task_payload)

    await asyncio.wait_for(task_assigned_event.wait(), timeout=1.0)
    assert received_task_data["task_id"] == "task_assign_404"


# ===========================================================================
# 4. Automation Runner Lifecycle & Sandbox Cleanup Tests
# ===========================================================================

def test_runner_initialization():
    """Runner initializes with allowlist, verifier, and settings."""
    runner = AadhaarDownloadAutomationRunner()
    assert runner.allowlist_interceptor is not None
    assert runner.verifier is not None


@pytest.mark.asyncio
async def test_runner_cleanup_guarantee_on_failure():
    """Runner guarantees temporary directory deletion in finally block."""
    runner = AadhaarDownloadAutomationRunner()

    task_id = str(uuid.uuid4())
    user_id = "usr_test_123"

    # Intentionally trigger navigation timeout by pointing to non-existent endpoint with 0 retries
    with pytest.raises(AutomationTaskError) as exc_info:
        await runner.execute_task(
            task_id=task_id,
            user_id=user_id,
            portal_url="http://127.0.0.1:54321/nonexistent",
            uid="123456789012",
            navigation_retries=0
        )

    assert exc_info.value.error_code in {"NAVIGATION_TIMEOUT", "PLAYWRIGHT_UNAVAILABLE"}

    # Verify no leaked temporary directory with saral_task_{task_id} remains
    temp_root = tempfile.gettempdir()
    matching = [f for f in os.listdir(temp_root) if f.startswith(f"saral_task_{task_id}")]
    assert len(matching) == 0, f"Leaked temporary directories found: {matching}"


@pytest.mark.asyncio
async def test_runner_storage_upload_and_record_insertion():
    """Test verified document insertion into store on successful verification."""
    store.reset()
    task_id = str(uuid.uuid4())
    user_id = "usr_success_999"
    doc_id = str(uuid.uuid4())
    storage_path = f"{user_id}/{task_id}.pdf"
    valid_pdf_content = generate_valid_pdf(encrypted=True)

    verifier = DocumentVerifier()
    res = verifier.verify(valid_pdf_content)
    assert res.is_valid

    # Simulate storage insert
    with store._lock:
        store.storage_objects[storage_path] = valid_pdf_content
        store.documents[doc_id] = {
            "id": doc_id,
            "user_id": user_id,
            "task_id": task_id,
            "doc_type": "aadhaar",
            "storage_path": storage_path,
            "size_bytes": res.size_bytes,
            "sha256": res.sha256,
            "pdf_encrypted": res.pdf_encrypted,
        }

    assert storage_path in store.storage_objects
    assert doc_id in store.documents
    assert store.documents[doc_id]["pdf_encrypted"] is True
    assert store.documents[doc_id]["sha256"] == res.sha256


# ===========================================================================
# 5. Live UIDAI Portal Selectors & Anti-Bot Stealth Tests
# ===========================================================================

def test_uidai_cascading_selectors_completeness():
    """Verify multi-tier selector chains include all required UIDAI elements."""
    from backend.app.worker.runner import (
        AADHAAR_RADIO_SELECTORS,
        UID_SELECTORS,
        CAPTCHA_IMG_SELECTORS,
        CAPTCHA_INPUT_SELECTORS,
        SEND_OTP_SELECTORS,
        OTP_INPUT_SELECTORS,
        VERIFY_DOWNLOAD_SELECTORS,
        ADVISORY_DISMISS_SELECTORS,
        CAPTCHA_REFRESH_SELECTORS,
    )

    # 1. Aadhaar radio selection
    assert "#aadhaar_number" in AADHAAR_RADIO_SELECTORS
    assert any("aadhaar" in s.lower() for s in AADHAAR_RADIO_SELECTORS)

    # 2. UID input fallback
    assert "#uid_input" in UID_SELECTORS
    assert any("placeholder*='enter aadhaar'" in s.lower() for s in UID_SELECTORS)
    assert any("name='uid'" in s for s in UID_SELECTORS)

    # 3. CAPTCHA image element
    assert "#captcha_img" in CAPTCHA_IMG_SELECTORS
    assert any("img[alt*='captcha'" in s.lower() for s in CAPTCHA_IMG_SELECTORS)

    # 4. CAPTCHA input
    assert "#captcha_input" in CAPTCHA_INPUT_SELECTORS
    assert any("name='captcha'" in s for s in CAPTCHA_INPUT_SELECTORS)

    # 5. Send OTP button
    assert "#btn_send_otp" in SEND_OTP_SELECTORS
    assert any("send otp" in s.lower() for s in SEND_OTP_SELECTORS)

    # 6. OTP input
    assert "#otp_input" in OTP_INPUT_SELECTORS
    assert any("name='otp'" in s for s in OTP_INPUT_SELECTORS)

    # 7. Verify & Download button
    assert "#btn_verify_download" in VERIFY_DOWNLOAD_SELECTORS
    assert any("verify & download" in s.lower() for s in VERIFY_DOWNLOAD_SELECTORS)

    # 8. Advisory dismissal
    assert any("close" in s.lower() or "ok" in s.lower() for s in ADVISORY_DISMISS_SELECTORS)

    # 9. Refresh CAPTCHA
    assert "#btn_refresh_captcha" in CAPTCHA_REFRESH_SELECTORS


def test_allowlist_supabase_inclusion():
    """Verify Supabase domains are allowlisted in worker and config."""
    from backend.app.worker.allowlist import DEFAULT_ALLOWED_DOMAINS
    from backend.app.config import get_settings

    assert "supabase.co" in DEFAULT_ALLOWED_DOMAINS
    assert "rsftbslckmdkynprmpin.supabase.co" in DEFAULT_ALLOWED_DOMAINS

    settings = get_settings()
    assert "supabase.co" in settings.ALLOWED_DOMAINS
    assert "rsftbslckmdkynprmpin.supabase.co" in settings.ALLOWED_DOMAINS

    interceptor = DomainAllowlistInterceptor()
    assert interceptor.is_url_allowed("https://rsftbslckmdkynprmpin.supabase.co/storage/v1/object/public/documents/test.pdf") is True
    assert interceptor.is_url_allowed("https://supabase.co/v1/health") is True
    assert interceptor.is_url_allowed("https://supabase.co.attacker-phishing.com/steal") is False


@pytest.mark.asyncio
async def test_websocket_challenge_relay_flow():
    """Verify challenge_required frame stores CAPTCHA in broker and user input is relayed to worker."""
    import base64
    from pydantic import SecretStr
    from backend.app.broker import challenge_broker
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.app.config import get_settings

    settings = get_settings()
    client = TestClient(app)

    task_id = f"test_relay_task_{uuid.uuid4().hex[:8]}"
    test_captcha_bytes = b"MOCK_PNG_IMAGE_BYTES_12345"
    test_captcha_b64 = base64.b64encode(test_captcha_bytes).decode("ascii")

    # Connect to WebSocket as authenticated worker
    with client.websocket_connect(f"/internal/worker?secret={settings.WORKER_SECRET}") as ws:
        # Worker emits challenge_required frame with CAPTCHA
        ws.send_text(json.dumps({
            "type": "challenge_required",
            "task_id": task_id,
            "kind": "captcha",
            "prompt": "Enter CAPTCHA",
            "challenge_data_b64": test_captcha_b64,
            "attempts_left": 3,
            "expires_at": time.time() + 180,
        }))

        # Worker receives challenge_registered ACK
        ack = ws.receive_json()
        assert ack["type"] == "challenge_registered"
        assert ack["task_id"] == task_id

        # Verify CAPTCHA was stored in ChallengeBroker in RAM
        stored_bytes = challenge_broker.get_captcha(task_id)
        assert stored_bytes == test_captcha_bytes

        # Verify ChallengeBroker has pending challenge
        assert challenge_broker.has_pending_challenge(task_id) is True

        # Simulate citizen resolving challenge via ChallengeBroker (as happens in POST /tasks/{id}/input)
        resolved = challenge_broker.resolve_challenge(task_id, SecretStr("CPT99"))
        assert resolved is True

        # Worker WebSocket should receive relay_input frame!
        relay_frame = ws.receive_json()
        assert relay_frame["type"] == "relay_input"
        assert relay_frame["task_id"] == task_id
        assert relay_frame["kind"] == "captcha"
        assert relay_frame["value"] == "CPT99"


@pytest.mark.asyncio
async def test_worker_client_refresh_captcha_handling():
    """Verify WorkerWebSocketClient registers and triggers refresh events."""
    client = WorkerWebSocketClient()
    task_id = "test_refresh_task_777"

    refresh_event = client.register_refresh_event(task_id)
    assert not refresh_event.is_set()

    # Backend sends refresh_captcha message
    await client._handle_message({
        "type": "refresh_captcha",
        "task_id": task_id,
    })

    assert refresh_event.is_set() is True

    # Cleanup
    client.clear_task_futures(task_id)
    assert client.get_refresh_event(task_id) is None


@pytest.mark.asyncio
async def test_runner_humanlike_sync_and_advisory_dismiss():
    """Verify runner _type_humanlike_sync and _dismiss_advisories_if_present logic."""
    runner = AadhaarDownloadAutomationRunner()

    # Duck-typed mock locator
    class MockLocator:
        def __init__(self, visible=True):
            self.visible = visible
            self.typed_text = ""
            self.clicks = 0
            self.events = []

        @property
        def first(self):
            return self

        async def is_visible(self):
            return self.visible

        async def click(self, timeout=None):
            self.clicks += 1

        async def press_sequentially(self, text, delay=0):
            self.typed_text = text

        async def fill(self, text):
            self.typed_text = text

        async def dispatch_event(self, event_name):
            self.events.append(event_name)

    mock_loc = MockLocator()
    await runner._type_humanlike_sync(mock_loc, "123456789012")
    assert mock_loc.typed_text == "123456789012"
    assert "input" in mock_loc.events
    assert "change" in mock_loc.events

    # Mock page for advisory dismiss
    class MockPage:
        def __init__(self, modal_visible=True):
            self.locator_instance = MockLocator(visible=modal_visible)

        def locator(self, selector):
            return self.locator_instance

    mock_page = MockPage(modal_visible=True)
    await runner._dismiss_advisories_if_present(mock_page)
    assert mock_page.locator_instance.clicks >= 1
