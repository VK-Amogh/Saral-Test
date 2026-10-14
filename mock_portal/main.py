"""
Saral AI — Mock Government Portal
File: mock_portal/main.py

FastAPI application running on port 8001 simulating the official UIDAI e-Aadhaar
portal identity verification journey (Aadhaar/VID -> CAPTCHA -> OTP -> PDF)
with 10 deterministic failure modes for end-to-end automation verification.
"""

import asyncio
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

try:
    from .captcha import generate_captcha_image
    from .pdf_generator import (
        generate_corrupt_pdf,
        generate_html_pdf,
        generate_malicious_pdf,
        generate_oversize_pdf,
        generate_valid_pdf,
    )
    from .state import portal_state
except ImportError:
    from captcha import generate_captcha_image
    from pdf_generator import (
        generate_corrupt_pdf,
        generate_html_pdf,
        generate_malicious_pdf,
        generate_oversize_pdf,
        generate_valid_pdf,
    )
    from state import portal_state

# Setup Jinja2 Templates
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(
    title="Mock UIDAI Government Portal",
    description="Deterministic mock service for Saral AI automated testing",
    version="1.0.0"
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SwitchRequest(BaseModel):
    switch: str = Field(..., description="Failure switch name")
    enabled: bool = Field(True, description="Whether the switch is active")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def parse_body_dict(request: Request) -> Dict[str, Any]:
    """Parse JSON or Form data from request safely."""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            return await request.json()
        except Exception:
            return {}
    elif "form" in content_type:
        try:
            form = await request.form()
            return dict(form)
        except Exception:
            pass

    # Fallback to reading raw body if json
    try:
        raw = await request.body()
        if raw:
            return json.loads(raw.decode("utf-8"))
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# Health & Status
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    """Unauthenticated health probe returning ok."""
    return {"status": "ok", "service": "mock-government-portal"}


# ---------------------------------------------------------------------------
# Failure Mode Admin Management Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/v1/admin/switch-failure")
@app.post("/__switch")
async def admin_switch_failure(request: Request):
    """Toggle any of the 10 deterministic failure switches."""
    data = await parse_body_dict(request)
    switch = data.get("switch", "")
    enabled = data.get("enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.lower() in {"true", "1", "yes"}

    success = portal_state.set_switch(switch, enabled)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": f"Unknown failure switch: {switch}"}
        )
    return {
        "status": "switch_updated",
        "switch": switch,
        "enabled": enabled
    }


@app.get("/api/v1/admin/switches")
async def admin_get_switches():
    """Retrieve state of all failure switches."""
    return {"switches": portal_state.failure_switches}


@app.post("/api/v1/admin/reset")
async def admin_reset_state():
    """Reset all sessions and failure switches to clean defaults."""
    portal_state.reset()
    return {"status": "reset_completed"}


# ---------------------------------------------------------------------------
# Flow Step 1: Landing Page & CAPTCHA Challenge
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def landing_page(
    request: Request,
    session_id: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    x_mock_mode: Optional[str] = Header(None, alias="X-Mock-Mode")
):
    """Serve Aadhaar entry form with dynamic CAPTCHA challenge."""
    # Check failure mode: Foreign Redirect
    if portal_state.is_switch_active("foreign_redirect", header_mode=x_mock_mode, query_mode=mode):
        return RedirectResponse(
            url="https://evil-unauthorized-tracker.com/phishing",
            status_code=status.HTTP_302_FOUND
        )

    # Check failure mode: Page Timeout
    if portal_state.is_switch_active("timeout", header_mode=x_mock_mode, query_mode=mode):
        await asyncio.sleep(45.0)

    # Resolve or create session
    session = portal_state.get_session(session_id) if session_id else None
    if not session:
        session = portal_state.create_session()

    changed_selectors = portal_state.is_switch_active(
        "changed_selectors",
        header_mode=x_mock_mode,
        query_mode=mode
    )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "session_id": session["session_id"],
            "uid": session.get("uid", ""),
            "changed_selectors": changed_selectors,
            "error_msg": None,
        }
    )


@app.get("/captcha")
async def get_captcha(
    session_id: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    x_mock_mode: Optional[str] = Header(None, alias="X-Mock-Mode")
):
    """Serve distorted 6-character PNG CAPTCHA challenge without caching."""
    session = portal_state.get_session(session_id) if session_id else None
    solution = session.get("captcha_solution", "VALID_CAP") if session else "VALID_CAP"

    captcha_bytes = generate_captcha_image(text=solution)
    return Response(
        content=captcha_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Content-Length": str(len(captcha_bytes)),
        }
    )


# ---------------------------------------------------------------------------
# Flow Step 2: Login & Credential Submission
# ---------------------------------------------------------------------------

@app.post("/login")
async def login(
    request: Request,
    mode: Optional[str] = Query(None),
    x_mock_mode: Optional[str] = Header(None, alias="X-Mock-Mode")
):
    """Validate UID & CAPTCHA, dispatch mock OTP, advance to verify step."""
    data = await parse_body_dict(request)
    uid = str(data.get("uid", "")).strip()
    captcha = str(data.get("captcha", "")).strip()
    session_id = data.get("session_id")

    # Check failure mode: Page Timeout
    if portal_state.is_switch_active("timeout", uid=uid, header_mode=x_mock_mode, query_mode=mode):
        await asyncio.sleep(45.0)

    # Check failure mode: Foreign Redirect
    if portal_state.is_switch_active("foreign_redirect", uid=uid, header_mode=x_mock_mode, query_mode=mode):
        return RedirectResponse(url="https://evil-unauthorized-tracker.com/phishing", status_code=302)

    # Resolve or create session
    session = portal_state.get_session(session_id) if session_id else None
    if not session:
        session = portal_state.create_session(uid=uid)
        session_id = session["session_id"]

    # Check failure mode: Wrong CAPTCHA
    is_wrong_captcha = portal_state.is_switch_active(
        "wrong_captcha",
        uid=uid,
        header_mode=x_mock_mode,
        query_mode=mode
    )

    if is_wrong_captcha or not portal_state.verify_captcha(session_id, captcha):
        error_detail = {"error": "INVALID_CAPTCHA", "message": "CAPTCHA entered is invalid"}
        accept = request.headers.get("accept", "")
        content_type = request.headers.get("content-type", "")

        if "application/json" in content_type or "application/json" in accept:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_detail)

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "session_id": session_id,
                "uid": uid,
                "changed_selectors": portal_state.is_switch_active("changed_selectors", uid=uid),
                "error_msg": "CAPTCHA entered is invalid. Please enter valid characters.",
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    # Successful login -> transition to OTP_SENT
    portal_state.advance_to_otp(session_id, uid)

    accept = request.headers.get("accept", "")
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type or "application/json" in accept:
        return {
            "status": "otp_sent",
            "session_id": session_id,
            "expires_in": 180,
            "attempts_left": 3
        }

    return RedirectResponse(url=f"/verify-otp?session_id={session_id}", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------------
# Flow Step 3: OTP Verification
# ---------------------------------------------------------------------------

@app.get("/verify-otp", response_class=HTMLResponse)
async def verify_otp_page(
    request: Request,
    session_id: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    x_mock_mode: Optional[str] = Header(None, alias="X-Mock-Mode")
):
    """Render OTP submission page with countdown timer."""
    # Check failure mode: Foreign Redirect
    if portal_state.is_switch_active("foreign_redirect", header_mode=x_mock_mode, query_mode=mode):
        return RedirectResponse(url="https://evil-unauthorized-tracker.com/phishing", status_code=302)

    session = portal_state.get_session(session_id) if session_id else None
    if not session:
        session = portal_state.create_session()
        session_id = session["session_id"]

    changed_selectors = portal_state.is_switch_active("changed_selectors", header_mode=x_mock_mode, query_mode=mode)
    uid_str = session.get("uid", "")
    masked_phone = f"******{uid_str[-4:]}" if len(uid_str) >= 4 else "******1234"

    return templates.TemplateResponse(
        request=request,
        name="verify_otp.html",
        context={
            "session_id": session_id,
            "masked_phone": masked_phone,
            "changed_selectors": changed_selectors,
            "error_msg": None,
        }
    )


@app.post("/verify-otp")
async def verify_otp(
    request: Request,
    mode: Optional[str] = Query(None),
    x_mock_mode: Optional[str] = Header(None, alias="X-Mock-Mode")
):
    """Validate 6-digit OTP code against session and attempt budget."""
    data = await parse_body_dict(request)
    session_id = data.get("session_id") or "default"
    otp = str(data.get("otp", "")).strip()

    accept = request.headers.get("accept", "")
    content_type = request.headers.get("content-type", "")
    prefers_json = "application/json" in content_type or "application/json" in accept

    # Check failure mode: Expired OTP
    if portal_state.is_switch_active("expired_otp", header_mode=x_mock_mode, query_mode=mode):
        error_detail = {"error": "OTP_EXPIRED", "message": "The OTP has expired"}
        if prefers_json:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_detail)
        return templates.TemplateResponse(
            request=request,
            name="verify_otp.html",
            context={"session_id": session_id, "error_msg": "The OTP has expired. Please request a new OTP."},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    # Perform OTP verification with state machine
    res_status, attempts_left = portal_state.verify_otp(session_id, otp)

    if res_status == "EXPIRED":
        error_detail = {"error": "OTP_EXPIRED", "message": "The OTP has expired"}
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_detail)

    if res_status == "LOCKED":
        error_detail = {
            "error": "MAX_ATTEMPTS_EXCEEDED",
            "message": "Session locked due to 3 failed OTP attempts"
        }
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=error_detail)

    if res_status == "INVALID":
        error_detail = {
            "error": "INVALID_OTP",
            "message": f"Invalid OTP. {attempts_left} attempts remaining.",
            "attempts_left": attempts_left
        }
        if prefers_json:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_detail)

        return templates.TemplateResponse(
            request=request,
            name="verify_otp.html",
            context={
                "session_id": session_id,
                "error_msg": f"Invalid OTP. {attempts_left} attempts remaining.",
                "changed_selectors": portal_state.is_switch_active("changed_selectors")
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    # Authentication succeeded
    download_token = f"token_{session_id[:8]}"
    if prefers_json:
        return {
            "status": "authenticated",
            "download_token": download_token,
            "message": "OTP verification successful"
        }

    return RedirectResponse(url=f"/download?session_id={session_id}", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------------
# Flow Step 4: Resend OTP
# ---------------------------------------------------------------------------

@app.post("/resend-otp")
async def resend_otp(request: Request):
    """Renew 180s countdown and reset 3-attempt budget."""
    data = await parse_body_dict(request)
    session_id = data.get("session_id") or "default"
    portal_state.resend_otp(session_id)

    return {
        "status": "otp_resent",
        "expires_in": 180,
        "attempts_left": 3
    }


# ---------------------------------------------------------------------------
# Flow Step 5: Document Download Stream
# ---------------------------------------------------------------------------

@app.get("/download")
async def download_eaadhaar(
    session_id: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    x_mock_mode: Optional[str] = Header(None, alias="X-Mock-Mode")
):
    """Stream generated electronic Aadhaar PDF, applying failure switches if active."""
    switches = portal_state.failure_switches

    # Failure 4: Corrupt PDF
    if switches.get("corrupt_pdf") or mode == "corrupt_pdf" or x_mock_mode == "corrupt_pdf":
        payload = generate_corrupt_pdf()
        media_type = "application/pdf"

    # Failure 5: HTML masquerading as PDF
    elif switches.get("html_as_pdf") or mode == "html_as_pdf" or x_mock_mode == "html_as_pdf":
        payload = generate_html_pdf()
        media_type = "application/pdf"

    # Failure 6: Oversize PDF
    elif switches.get("oversize_pdf") or mode == "oversize_pdf" or x_mock_mode == "oversize_pdf":
        payload = generate_oversize_pdf(size_mb=6)
        media_type = "application/pdf"

    # Failure 7: Malicious PDF
    elif switches.get("malicious_pdf") or mode == "malicious_pdf" or x_mock_mode == "malicious_pdf":
        payload = generate_malicious_pdf("javascript")
        media_type = "application/pdf"

    # Happy path: Valid password-protected PDF
    else:
        payload = generate_valid_pdf(encrypted=True)
        media_type = "application/pdf"

    return Response(
        content=payload,
        media_type=media_type,
        headers={
            "Content-Disposition": 'attachment; filename="eaadhaar.pdf"',
            "Content-Length": str(len(payload)),
            "Cache-Control": "no-store",
        }
    )
