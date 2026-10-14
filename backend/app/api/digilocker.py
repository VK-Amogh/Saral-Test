"""
Saral AI — DigiLocker API Router
File: backend/app/api/digilocker.py

Provides:
- GET /authorize/{task_id}: Generates and returns official DigiLocker consent URL for the citizen.
- GET /callback: Handles OAuth2 redirection callback, verifies HMAC state token, exchanges code,
  retrieves document, passes 5-point verification, uploads to private storage, and marks task COMPLETED.
"""

import logging
import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import UserContext, get_current_user
from ..services.digilocker_service import (
    DigiLockerStateExpiredError,
    DigiLockerStateInvalidError,
    DigiLockerVerificationError,
    digilocker_service,
)
from ..state_machine import TaskState, transition
from ..store import store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["DigiLocker"])


@router.get("/authorize/{task_id}", status_code=status.HTTP_200_OK)
async def get_digilocker_consent_url(
    task_id: str,
    user: UserContext = Depends(get_current_user)
):
    """Retrieve official DigiLocker OAuth2 consent URL for task."""
    with store._lock:
        task = store.tasks.get(task_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Not Found", "message": f"Task {task_id} does not exist"}
            )
        if task["user_id"] != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "Forbidden", "message": "Ownership check failed"}
            )
        if task["status"] in {"COMPLETED", "FAILED", "CANCELLED", "EXPIRED"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "Bad Request", "message": f"Cannot authorize task in terminal state {task['status']}"}
            )

        auth_url = digilocker_service.generate_consent_url(task_id=task_id, user_id=user.user_id)

        # Transition task to WAITING_FOR_USER if currently in earlier states
        if task["status"] == "RECEIVED":
            transition(task, TaskState.VALIDATING, actor="system")
        if task["status"] == "VALIDATING":
            transition(task, TaskState.PLANNING, actor="system")
        if task["status"] == "PLANNING":
            transition(task, TaskState.WAITING_FOR_USER, actor="system")

        task["pending_input"] = {
            "kind": "oauth_consent",
            "prompt": "Authorize DigiLocker to securely provide your e-Aadhaar document",
            "auth_url": auth_url,
            "expires_at": time.time() + 180,
            "attempts_left": 1
        }

    return {
        "task_id": task_id,
        "auth_url": auth_url,
        "status": task["status"],
        "expires_in": 180
    }


@router.get("/callback", status_code=status.HTTP_200_OK)
async def digilocker_oauth_callback(
    code: Optional[str] = Query(None, description="OAuth2 authorization code"),
    state: Optional[str] = Query(None, description="HMAC-SHA256 signed state token")
):
    """Handle DigiLocker OAuth2 callback redirect."""
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Bad Request", "message": "Missing authorization code or state token"}
        )

    # Validate HMAC signature and expiration
    try:
        state_payload = digilocker_service.verify_state(state)
    except (DigiLockerStateInvalidError, DigiLockerStateExpiredError, ValueError) as exc:
        logger.warning("DigiLocker callback invalid state token: %s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Bad Request", "message": f"Invalid or expired state token: {str(exc)}"}
        )

    # Execute full token exchange, retrieval, 5-point verification, and completion
    try:
        result = await digilocker_service.process_callback(code=code, state_payload=state_payload)
        return result
    except HTTPException:
        raise
    except DigiLockerVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "Verification Failed", "message": str(exc)}
        )
    except Exception as exc:
        logger.error("DigiLocker callback processing error: %s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Internal Error", "message": str(exc)}
        )
