"""
Saral AI — DigiLocker OAuth2 Service
File: backend/app/services/digilocker_service.py

Implements official DigiLocker OAuth2 / IndiaStack route for direct e-Aadhaar retrieval:
1. HMAC-SHA256 signed OAuth2 state generation & validation (180s TTL).
2. DigiLocker OAuth2 consent URL generator.
3. Server-to-server token exchange via httpx async client.
4. Direct in-memory streaming of e-Aadhaar PDF bytes (zero disk storage).
5. 5-point document security inspection via backend/app/worker/verifier.py.
6. Supabase Storage upload, document record persistence, and verifier-only completion gate.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
import uuid
from typing import Any, Dict, Optional, Tuple
from fastapi import HTTPException, status
import httpx
from pydantic import SecretStr

from ..config import get_settings
from ..state_machine import TaskState, transition
from ..store import store
from ..worker.verifier import DocumentVerifier, VerifierResult, verify_document_security

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class DigiLockerError(Exception):
    """Base exception for DigiLocker service operations."""
    pass


class DigiLockerStateError(DigiLockerError):
    """Base exception for OAuth2 state token errors."""
    pass


class DigiLockerStateInvalidError(DigiLockerStateError):
    """Raised when state signature is invalid or payload is corrupted."""
    pass


class DigiLockerStateExpiredError(DigiLockerStateError):
    """Raised when state token timestamp has expired (> 180s TTL)."""
    pass


class DigiLockerTokenExchangeError(DigiLockerError):
    """Raised when authorization code exchange fails."""
    pass


class DigiLockerDocumentFetchError(DigiLockerError):
    """Raised when document retrieval fails."""
    pass


class DigiLockerVerificationError(DigiLockerError):
    """Raised when downloaded document fails 5-point security verification."""
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


# ---------------------------------------------------------------------------
# State Token Management (HMAC-SHA256, 180s TTL)
# ---------------------------------------------------------------------------

def generate_digilocker_state(
    task_id: str,
    user_id: str,
    secret: Optional[str] = None,
    ttl_seconds: int = 180
) -> str:
    """Generate an HMAC-SHA256 signed state token embedding task_id, user_id, and expires_at.

    Args:
        task_id: UUID of the task.
        user_id: ID of the authenticated user.
        secret: Optional HMAC signing secret. Defaults to SUPABASE_JWT_SECRET.
        ttl_seconds: Lifetime of the state token (default 180 seconds).

    Returns:
        Tamper-evident URL-safe state string formatted as: {b64_payload}.{hmac_sha256_hex}
    """
    settings = get_settings()
    signing_secret = secret or getattr(settings, "SUPABASE_JWT_SECRET", "super_secret_supabase_jwt_signing_key")
    now = time.time()
    expires_at = now + ttl_seconds

    payload = {
        "task_id": str(task_id),
        "user_id": str(user_id),
        "expires_at": expires_at,
        "nonce": uuid.uuid4().hex,
    }
    raw_json = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    b64_payload = base64.urlsafe_b64encode(raw_json).decode('utf-8').rstrip('=')
    signature = hmac.new(
        signing_secret.encode('utf-8'),
        b64_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return f"{b64_payload}.{signature}"


def verify_digilocker_state(
    state: str,
    secret: Optional[str] = None
) -> Dict[str, Any]:
    """Verify HMAC signature and timestamp TTL of state token.

    Args:
        state: State token string received from OAuth callback.
        secret: Optional HMAC signing secret. Defaults to SUPABASE_JWT_SECRET.

    Returns:
        Decoded payload dictionary with task_id, user_id, expires_at, etc.

    Raises:
        DigiLockerStateInvalidError: If format, signature, or encoding is invalid.
        DigiLockerStateExpiredError: If token timestamp exceeds current time.
    """
    if not state or not isinstance(state, str) or "." not in state:
        raise DigiLockerStateInvalidError("Malformed state token: missing signature delimiter")

    parts = state.split(".")
    if len(parts) != 2:
        raise DigiLockerStateInvalidError("Malformed state token: invalid segment count")

    b64_payload, provided_sig = parts
    settings = get_settings()
    signing_secret = secret or getattr(settings, "SUPABASE_JWT_SECRET", "super_secret_supabase_jwt_signing_key")

    expected_sig = hmac.new(
        signing_secret.encode('utf-8'),
        b64_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, provided_sig):
        raise DigiLockerStateInvalidError("Invalid state signature: token has been tampered with")

    try:
        padding = '=' * (-len(b64_payload) % 4)
        raw_json = base64.urlsafe_b64decode(b64_payload + padding)
        payload = json.loads(raw_json)
    except Exception as e:
        raise DigiLockerStateInvalidError(f"Malformed state payload encoding: {str(e)}")

    expires_at = payload.get("expires_at", 0)
    if time.time() > expires_at:
        raise DigiLockerStateExpiredError(f"State token expired at {expires_at} (exceeded 180s TTL)")

    if "task_id" not in payload or "user_id" not in payload:
        raise DigiLockerStateInvalidError("State payload missing required task_id or user_id fields")

    return payload


# ---------------------------------------------------------------------------
# DigiLocker Service Class
# ---------------------------------------------------------------------------

class DigiLockerService:
    """Service orchestrating DigiLocker OAuth2 consent, retrieval, verification, and completion."""

    def __init__(self):
        self._verifier = DocumentVerifier(min_size_bytes=100, max_size_mb=5)

    def generate_consent_url(
        self,
        task_id: str,
        user_id: str,
        client_id: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        auth_base_url: Optional[str] = None,
        secret: Optional[str] = None,
        ttl_seconds: int = 180,
    ) -> str:
        """Generate DigiLocker OAuth2 consent URL with client ID, redirect URI, scope ('read'), and signed state."""
        state = generate_digilocker_state(task_id, user_id, secret=secret, ttl_seconds=ttl_seconds)

        cid = client_id or os.environ.get("DIGILOCKER_CLIENT_ID", "SARALAI_DIGILOCKER_CLIENT")
        r_uri = redirect_uri or os.environ.get(
            "DIGILOCKER_REDIRECT_URI",
            "https://api.saralai.in/api/v1/digilocker/callback"
        )
        base_url = auth_base_url or os.environ.get(
            "DIGILOCKER_AUTH_URL",
            "https://api.digitallocker.gov.in/public/oauth2/1/authorize"
        )

        params = {
            "response_type": "code",
            "client_id": cid,
            "redirect_uri": r_uri,
            "state": state,
            "scope": "read",
        }
        return f"{base_url}?{urllib.parse.urlencode(params)}"

    def verify_state(
        self,
        state: str,
        secret: Optional[str] = None
    ) -> Dict[str, Any]:
        """Validate HMAC state token signature and expiration."""
        return verify_digilocker_state(state, secret=secret)

    async def exchange_code_for_token(
        self,
        code: str,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        token_url: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> SecretStr:
        """Exchange authorization code for access token via httpx async client.

        Zero persistence guarantee: Access token is returned encapsulated in SecretStr.
        """
        cid = client_id or os.environ.get("DIGILOCKER_CLIENT_ID", "SARALAI_DIGILOCKER_CLIENT")
        c_sec = client_secret or os.environ.get("DIGILOCKER_CLIENT_SECRET", "saral_digilocker_secret_9988")
        r_uri = redirect_uri or os.environ.get(
            "DIGILOCKER_REDIRECT_URI",
            "https://api.saralai.in/api/v1/digilocker/callback"
        )
        t_url = token_url or os.environ.get(
            "DIGILOCKER_TOKEN_URL",
            "https://api.digitallocker.gov.in/public/oauth2/1/token"
        )

        payload_data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": cid,
            "client_secret": c_sec,
            "redirect_uri": r_uri,
        }

        should_close = False
        client = http_client
        if client is None:
            client = httpx.AsyncClient(timeout=15.0)
            should_close = True

        try:
            response = await client.post(t_url, data=payload_data)
            if response.status_code != 200:
                raise DigiLockerTokenExchangeError(
                    f"DigiLocker token exchange rejected with status {response.status_code}: {response.text}"
                )
            data = response.json()
            token = data.get("access_token")
            if not token:
                raise DigiLockerTokenExchangeError("DigiLocker token response missing access_token")
            return SecretStr(token)
        finally:
            if should_close:
                await client.aclose()

    async def fetch_eaadhaar_document(
        self,
        access_token: SecretStr,
        doc_uri: Optional[str] = None,
        file_url: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> bytes:
        """Stream e-Aadhaar PDF bytes directly into memory without disk storage."""
        base_file_url = file_url or os.environ.get(
            "DIGILOCKER_FILE_URL",
            "https://api.digitallocker.gov.in/public/oauth2/1/file"
        )
        target_uri = doc_uri or "in.gov.uidai-eaadhaar"
        if not base_file_url.endswith(target_uri):
            endpoint = f"{base_file_url.rstrip('/')}/{target_uri}"
        else:
            endpoint = base_file_url

        headers = {
            "Authorization": f"Bearer {access_token.get_secret_value()}",
            "Accept": "application/pdf",
        }

        should_close = False
        client = http_client
        if client is None:
            client = httpx.AsyncClient(timeout=30.0)
            should_close = True

        try:
            response = await client.get(endpoint, headers=headers)
            if response.status_code != 200:
                raise DigiLockerDocumentFetchError(
                    f"DigiLocker document fetch failed with status {response.status_code}: {response.text}"
                )
            pdf_bytes = response.content
            return pdf_bytes
        finally:
            if should_close:
                await client.aclose()

    def verify_document(self, pdf_bytes: bytes) -> VerifierResult:
        """Execute 5-point document security inspection on raw bytes."""
        return self._verifier.verify(pdf_bytes)

    async def upload_and_save_document(
        self,
        user_id: str,
        task_id: str,
        pdf_bytes: bytes,
        verifier_result: VerifierResult,
        filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Upload verified bytes to Supabase Storage and persist document record."""
        storage_path = f"{user_id}/{task_id}.pdf"
        doc_id = str(uuid.uuid4())
        doc_record = {
            "id": doc_id,
            "user_id": user_id,
            "task_id": task_id,
            "doc_type": "aadhaar",
            "file_name": filename or f"eaadhaar_{task_id[:8]}.pdf",
            "storage_path": storage_path,
            "size_bytes": verifier_result.size_bytes,
            "sha256": verifier_result.sha256,
            "pdf_encrypted": verifier_result.pdf_encrypted,
            "created_at": time.time(),
            "delete_after": time.time() + 86400,
        }

        # Store in application memory store
        with store._lock:
            store.storage_objects[storage_path] = pdf_bytes
            store.documents[doc_id] = doc_record

        # Supabase remote storage upload via service-role key if configured
        settings = get_settings()
        if settings.SUPABASE_URL and not settings.SUPABASE_URL.startswith("https://mock"):
            try:
                url = f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/documents/{storage_path}"
                headers = {
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
                    "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
                    "Content-Type": "application/pdf",
                    "x-upsert": "true",
                }
                async with httpx.AsyncClient(timeout=10.0) as remote_client:
                    await remote_client.post(url, content=pdf_bytes, headers=headers)
            except Exception as e:
                logger.warning("Remote Supabase storage upload skipped/failed: %s", str(e))

        return doc_record

    async def process_callback(
        self,
        code: str,
        state_payload: Dict[str, Any],
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """Process OAuth2 callback pipeline adhering to state machine invariants:

        WAITING_FOR_USER -> RUNNING -> DOWNLOADING -> VERIFYING -> COMPLETED (actor="verifier" only).
        """
        task_id = state_payload["task_id"]
        user_id = state_payload["user_id"]

        with store._lock:
            task = store.tasks.get(task_id)
            if not task:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"error": "Not Found", "message": f"Task {task_id} does not exist"}
                )
            if task["user_id"] != user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error": "Forbidden", "message": "Ownership check failed"}
                )
            if task["status"] in {"COMPLETED", "FAILED", "CANCELLED", "EXPIRED"}:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "Bad Request", "message": f"Task already in terminal state {task['status']}"}
                )

            # Transition from WAITING_FOR_USER to RUNNING, then DOWNLOADING
            if task["status"] == "WAITING_FOR_USER":
                transition(task, TaskState.RUNNING, actor="orchestrator")
            if task["status"] == "RUNNING":
                transition(task, TaskState.DOWNLOADING, actor="orchestrator")

        # 1. Exchange code for access token via httpx
        try:
            access_token = await self.exchange_code_for_token(code, http_client=http_client)
        except Exception as e:
            logger.error("DigiLocker token exchange error for task %s: %s", task_id, str(e))
            with store._lock:
                if task["status"] not in {"COMPLETED", "FAILED", "CANCELLED", "EXPIRED"}:
                    transition(task, TaskState.FAILED, actor="orchestrator", reason="TOKEN_EXCHANGE_FAILED")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": "Bad Gateway", "message": f"Token exchange failed: {str(e)}"}
            )

        # 2. Fetch e-Aadhaar PDF bytes directly into memory
        try:
            pdf_bytes = await self.fetch_eaadhaar_document(access_token, http_client=http_client)
        except Exception as e:
            logger.error("DigiLocker document fetch error for task %s: %s", task_id, str(e))
            with store._lock:
                if task["status"] not in {"COMPLETED", "FAILED", "CANCELLED", "EXPIRED"}:
                    transition(task, TaskState.FAILED, actor="orchestrator", reason="DOCUMENT_FETCH_FAILED")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": "Bad Gateway", "message": f"Document download failed: {str(e)}"}
            )

        # 3. Transition to VERIFYING
        with store._lock:
            transition(task, TaskState.VERIFYING, actor="orchestrator")

        # 4. 5-point document security inspection
        verifier_result = self.verify_document(pdf_bytes)
        if not verifier_result.is_valid:
            logger.warning(
                "Document verification failed for task %s: code=%s, msg=%s",
                task_id, verifier_result.error_code, verifier_result.error_message
            )
            with store._lock:
                transition(task, TaskState.FAILED, actor="verifier", reason=verifier_result.error_code)
            raise DigiLockerVerificationError(
                error_code=verifier_result.error_code or "DOCUMENT_VERIFICATION_FAILED",
                message=verifier_result.error_message or "Document failed 5-point security verification"
            )

        # 5. Save verified document to storage and record
        doc_record = await self.upload_and_save_document(
            user_id=user_id,
            task_id=task_id,
            pdf_bytes=pdf_bytes,
            verifier_result=verifier_result
        )

        # 6. Strictly transition to COMPLETED with actor="verifier"
        with store._lock:
            transition(task, TaskState.COMPLETED, actor="verifier")
            task["pending_input"] = None
            if store.active_workflows.get(user_id) == task_id:
                del store.active_workflows[user_id]

        return {
            "status": "COMPLETED",
            "task_id": task_id,
            "document_id": doc_record["id"],
            "sha256": verifier_result.sha256,
            "pdf_encrypted": verifier_result.pdf_encrypted
        }


# Global service instance
digilocker_service = DigiLockerService()
