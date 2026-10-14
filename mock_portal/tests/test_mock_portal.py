"""
Saral AI — Mock Portal Unit and Integration Test Suite
File: mock_portal/tests/test_mock_portal.py

Verifies all 10 deterministic failure modes and the happy path flow
against the mock government UIDAI portal.
"""

import pytest
from starlette.testclient import TestClient

try:
    from mock_portal.main import app
    from mock_portal.state import portal_state
    from mock_portal.captcha import generate_captcha_image
    from mock_portal.pdf_generator import (
        generate_valid_pdf,
        generate_corrupt_pdf,
        generate_html_pdf,
        generate_oversize_pdf,
        generate_malicious_pdf,
    )
except ImportError:
    from main import app
    from state import portal_state
    from captcha import generate_captcha_image
    from pdf_generator import (
        generate_valid_pdf,
        generate_corrupt_pdf,
        generate_html_pdf,
        generate_oversize_pdf,
        generate_malicious_pdf,
    )


@pytest.fixture(autouse=True)
def reset_portal():
    """Ensure each test runs with pristine portal state."""
    portal_state.reset()
    yield
    portal_state.reset()


@pytest.fixture
def client():
    """Test client for FastAPI app."""
    return TestClient(app)


# ===========================================================================
# 1. Health & Meta Endpoints
# ===========================================================================

def test_portal_health_check(client):
    """GET /health returns 200 with service metadata."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "service": "mock-government-portal"}


def test_portal_landing_page_renders_form(client):
    """GET / renders HTML form with semantic UIDAI selectors."""
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "uid_input" in res.text
    assert "captcha_img" in res.text
    assert "btn_send_otp" in res.text


def test_portal_captcha_endpoint(client):
    """GET /captcha generates image/png with no-store headers."""
    res = client.get("/captcha")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert "no-store" in res.headers.get("cache-control", "")
    assert res.content.startswith(b"\x89PNG")


# ===========================================================================
# 2. Happy Path Flow
# ===========================================================================

def test_happy_path_complete_workflow(client):
    """Verify standard happy path from landing to verified PDF download."""
    # 1. Access landing
    res_land = client.get("/")
    assert res_land.status_code == 200

    # 2. Login with valid UID & CAPTCHA
    res_login = client.post(
        "/login",
        json={"uid": "234567890128", "captcha": "VALID_CAP"}
    )
    assert res_login.status_code == 200
    login_data = res_login.json()
    assert login_data["status"] == "otp_sent"
    session_id = login_data["session_id"]
    assert login_data["expires_in"] == 180
    assert login_data["attempts_left"] == 3

    # 3. Verify OTP
    res_otp = client.post(
        "/verify-otp",
        json={"session_id": session_id, "otp": "123456"}
    )
    assert res_otp.status_code == 200
    otp_data = res_otp.json()
    assert otp_data["status"] == "authenticated"
    assert "download_token" in otp_data

    # 4. Download PDF
    res_dl = client.get(f"/download?session_id={session_id}")
    assert res_dl.status_code == 200
    assert res_dl.headers["content-type"] == "application/pdf"
    content = res_dl.content
    assert content.startswith(b"%PDF-")
    assert b"%%EOF" in content
    assert len(content) > 1000
    assert len(content) <= 5 * 1024 * 1024


# ===========================================================================
# 3. Failure Mode 1: Wrong CAPTCHA
# ===========================================================================

def test_failure_mode_wrong_captcha_switch(client):
    """Failure Mode 1: Portal rejects CAPTCHA when switch is enabled."""
    client.post("/api/v1/admin/switch-failure", json={"switch": "wrong_captcha", "enabled": True})
    res = client.post(
        "/login",
        json={"uid": "234567890128", "captcha": "VALID_CAP"}
    )
    assert res.status_code == 400
    data = res.json()
    assert data["error"] == "INVALID_CAPTCHA"


def test_failure_mode_wrong_captcha_via_special_uid(client):
    """Failure Mode 1: Special UID 000000000001 triggers wrong CAPTCHA failure."""
    res = client.post(
        "/login",
        json={"uid": "000000000001", "captcha": "VALID_CAP"}
    )
    assert res.status_code == 400
    assert res.json()["error"] == "INVALID_CAPTCHA"


# ===========================================================================
# 4. Failure Mode 2: Expired OTP
# ===========================================================================

def test_failure_mode_expired_otp_switch(client):
    """Failure Mode 2: Portal rejects OTP when expired_otp switch is enabled."""
    res_login = client.post("/login", json={"uid": "234567890128", "captcha": "VALID_CAP"})
    session_id = res_login.json()["session_id"]

    client.post("/api/v1/admin/switch-failure", json={"switch": "expired_otp", "enabled": True})
    res_otp = client.post("/verify-otp", json={"session_id": session_id, "otp": "123456"})
    assert res_otp.status_code == 400
    assert res_otp.json()["error"] == "OTP_EXPIRED"


# ===========================================================================
# 5. Failure Mode 3: Wrong OTP (3 Attempts Lockout)
# ===========================================================================

def test_failure_mode_wrong_otp_retry_and_lockout(client):
    """Failure Mode 3: 3 invalid OTP attempts lock the session with HTTP 403."""
    res_login = client.post("/login", json={"uid": "234567890128", "captcha": "VALID_CAP"})
    session_id = res_login.json()["session_id"]

    # Attempt 1
    r1 = client.post("/verify-otp", json={"session_id": session_id, "otp": "000000"})
    assert r1.status_code == 400
    assert r1.json()["attempts_left"] == 2

    # Attempt 2
    r2 = client.post("/verify-otp", json={"session_id": session_id, "otp": "111111"})
    assert r2.status_code == 400
    assert r2.json()["attempts_left"] == 1

    # Attempt 3 -> Locked!
    r3 = client.post("/verify-otp", json={"session_id": session_id, "otp": "222222"})
    assert r3.status_code == 403
    assert r3.json()["error"] == "MAX_ATTEMPTS_EXCEEDED"


def test_failure_mode_wrong_otp_switch_forces_failure(client):
    """Failure Mode 3: wrong_otp_3x switch forces failure regardless of OTP."""
    res_login = client.post("/login", json={"uid": "234567890128", "captcha": "VALID_CAP"})
    session_id = res_login.json()["session_id"]

    client.post("/__switch", json={"switch": "wrong_otp_3x", "enabled": True})
    r1 = client.post("/verify-otp", json={"session_id": session_id, "otp": "123456"})
    assert r1.status_code == 400
    assert r1.json()["attempts_left"] == 2


# ===========================================================================
# 6. Failure Mode 4: Corrupt PDF
# ===========================================================================

def test_failure_mode_corrupt_pdf_switch(client):
    """Failure Mode 4: corrupt_pdf switch streams malformed data without %PDF- header."""
    client.post("/api/v1/admin/switch-failure", json={"switch": "corrupt_pdf", "enabled": True})
    res = client.get("/download")
    assert res.status_code == 200
    assert not res.content.startswith(b"%PDF-")
    assert b"CORRUPT" in res.content


# ===========================================================================
# 7. Failure Mode 5: HTML as PDF
# ===========================================================================

def test_failure_mode_html_as_pdf_switch(client):
    """Failure Mode 5: html_as_pdf switch returns HTML 500 error page."""
    client.post("/api/v1/admin/switch-failure", json={"switch": "html_as_pdf", "enabled": True})
    res = client.get("/download")
    assert res.status_code == 200
    assert res.content.startswith(b"<!DOCTYPE") or res.content.startswith(b"<html")
    assert b"500 Internal Server Error" in res.content


# ===========================================================================
# 8. Failure Mode 6: Oversize PDF
# ===========================================================================

def test_failure_mode_oversize_pdf_switch(client):
    """Failure Mode 6: oversize_pdf switch returns payload exceeding 5 MB limit."""
    client.post("/api/v1/admin/switch-failure", json={"switch": "oversize_pdf", "enabled": True})
    res = client.get("/download")
    assert res.status_code == 200
    assert len(res.content) > 5 * 1024 * 1024  # Greater than 5 MB


# ===========================================================================
# 9. Failure Mode 7: Malicious PDF (/JavaScript or /Launch)
# ===========================================================================

def test_failure_mode_malicious_pdf_switch(client):
    """Failure Mode 7: malicious_pdf switch returns PDF with forbidden active scripts."""
    client.post("/api/v1/admin/switch-failure", json={"switch": "malicious_pdf", "enabled": True})
    res = client.get("/download")
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")
    assert b"/JavaScript" in res.content or b"/Launch" in res.content


# ===========================================================================
# 10. Failure Mode 8: Page Timeout
# ===========================================================================

def test_failure_mode_page_timeout_switch_state(client):
    """Failure Mode 8: timeout switch is toggled and identified correctly."""
    assert not portal_state.is_switch_active("timeout")
    client.post("/api/v1/admin/switch-failure", json={"switch": "timeout", "enabled": True})
    assert portal_state.is_switch_active("timeout")
    assert portal_state.is_switch_active("timeout", uid="000000000007")


# ===========================================================================
# 11. Failure Mode 9: Changed DOM Selectors
# ===========================================================================

def test_failure_mode_changed_selectors_switch(client):
    """Failure Mode 9: changed_selectors switch renders modified element IDs."""
    client.post("/api/v1/admin/switch-failure", json={"switch": "changed_selectors", "enabled": True})

    res_land = client.get("/")
    assert res_land.status_code == 200
    assert "broken_uid_field" in res_land.text
    assert 'id="uid_input"' not in res_land.text

    res_otp = client.get("/verify-otp")
    assert res_otp.status_code == 200
    assert "unexpected_otp_field" in res_otp.text
    assert 'id="otp_input"' not in res_otp.text


# ===========================================================================
# 12. Failure Mode 10: Foreign Redirect
# ===========================================================================

def test_failure_mode_foreign_redirect_switch(client):
    """Failure Mode 10: foreign_redirect switch triggers 302 to external domain."""
    client.post("/api/v1/admin/switch-failure", json={"switch": "foreign_redirect", "enabled": True})
    res = client.get("/", follow_redirects=False)
    assert res.status_code in {302, 303, 307}
    assert "evil-unauthorized-tracker.com" in res.headers.get("location", "")


# ===========================================================================
# 13. OTP Resend & Timer Renewal
# ===========================================================================

def test_otp_resend_resets_attempts_and_timer(client):
    """POST /resend-otp restores 3-attempt budget and resets 180s timer."""
    res_login = client.post("/login", json={"uid": "234567890128", "captcha": "VALID_CAP"})
    session_id = res_login.json()["session_id"]

    # Use 1 attempt
    client.post("/verify-otp", json={"session_id": session_id, "otp": "999999"})
    assert portal_state.otp_attempts[session_id] == 2

    # Resend OTP
    res_resend = client.post("/resend-otp", json={"session_id": session_id})
    assert res_resend.status_code == 200
    data = res_resend.json()
    assert data["status"] == "otp_resent"
    assert data["attempts_left"] == 3
    assert data["expires_in"] == 180
    assert portal_state.otp_attempts[session_id] == 3


# ===========================================================================
# 14. Admin Switch Management
# ===========================================================================

def test_admin_switch_endpoints_and_reset(client):
    """Verify admin endpoints get, set, and reset switches."""
    # List all switches
    res_list = client.get("/api/v1/admin/switches")
    assert res_list.status_code == 200
    switches = res_list.json()["switches"]
    assert "wrong_captcha" in switches
    assert "corrupt_pdf" in switches

    # Set switch via /__switch
    r_compat = client.post("/__switch", json={"switch": "corrupt_pdf", "enabled": True})
    assert r_compat.status_code == 200
    assert portal_state.failure_switches["corrupt_pdf"] is True

    # Reset
    r_reset = client.post("/api/v1/admin/reset")
    assert r_reset.status_code == 200
    assert portal_state.failure_switches["corrupt_pdf"] is False
