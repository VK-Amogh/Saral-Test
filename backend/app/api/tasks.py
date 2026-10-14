"""Tasks, challenges, downloads, and documents API endpoints."""

import re
import time
import uuid
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field, SecretStr

from ..auth import UserContext, get_current_user
from ..broker import challenge_broker
from ..queue import job_queue
from ..services.digilocker_service import digilocker_service
from ..state_machine import TaskState, transition
from ..store import store

router = APIRouter(prefix="/api/v1", tags=["Tasks"])

# Minimal 1x1 valid PNG for challenge default
DEFAULT_CAPTCHA_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class CreateTaskRequest(BaseModel):
    """Payload to create a task directly."""
    workflow: str = Field("aadhaar_download", description="Target workflow key")
    idempotency_key: Optional[str] = Field(None, description="Client idempotency key")
    request_text: Optional[str] = Field(None, description="Original request prompt")


class SubmitInputRequest(BaseModel):
    """Secure input submission payload."""
    input_id: str = Field("otp", description="Input type identifier: otp or captcha")
    value: str = Field(..., description="Challenge answer value")


# ---------------------------------------------------------------------------
# Task Management Endpoints
# ---------------------------------------------------------------------------

@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: Optional[CreateTaskRequest] = None,
    user: UserContext = Depends(get_current_user),
    idempotency_key_header: Optional[str] = Header(None, alias="Idempotency-Key")
):
    """Create a task or idempotently replay existing task for user."""
    workflow = payload.workflow if payload else "aadhaar_download"
    idempotency_key = idempotency_key_header or (payload.idempotency_key if payload else None)

    with store._lock:
        # Check idempotency duplicate
        if idempotency_key:
            for t in store.tasks.values():
                if t.get("idempotency_key") == idempotency_key and t["user_id"] == user.user_id:
                    return Response(
                        content='{"id": "' + t["id"] + '", "status": "' + t["status"] + '", "replayed": true}',
                        status_code=status.HTTP_200_OK,
                        media_type="application/json"
                    )

        # Enforce single active workflow per user
        active_id = store.active_workflows.get(user.user_id)
        if active_id:
            active_task = store.tasks.get(active_id)
            if active_task and active_task.get("status") not in {"COMPLETED", "FAILED", "CANCELLED", "EXPIRED"}:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "Conflict",
                        "message": f"Active task {active_id} already in progress for this workflow"
                    }
                )

        task_id = str(uuid.uuid4())
        task_record = {
            "id": task_id,
            "user_id": user.user_id,
            "workflow": workflow,
            "status": "RECEIVED",
            "idempotency_key": idempotency_key,
            "created_at": time.time(),
            "updated_at": time.time(),
            "finished_at": None,
            "pending_input": None
        }

        if workflow == "aadhaar_digilocker":
            transition(task_record, TaskState.VALIDATING, actor="system")
            transition(task_record, TaskState.PLANNING, actor="system")
            transition(task_record, TaskState.WAITING_FOR_USER, actor="system")
            auth_url = digilocker_service.generate_consent_url(task_id=task_id, user_id=user.user_id)
            task_record["pending_input"] = {
                "kind": "oauth_consent",
                "prompt": "Authorize DigiLocker to securely provide your e-Aadhaar document",
                "auth_url": auth_url,
                "expires_at": time.time() + 180,
                "attempts_left": 1
            }

        store.tasks[task_id] = task_record
        store.active_workflows[user.user_id] = task_id

    if workflow != "aadhaar_digilocker":
        await job_queue.enqueue(task_id, workflow, user.user_id)

    response_data = {
        "id": task_id,
        "status": task_record["status"],
        "workflow": workflow
    }
    if task_record["pending_input"]:
        response_data["pending_input"] = task_record["pending_input"]

    return response_data


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    user: UserContext = Depends(get_current_user)
):
    """Retrieve sanitized task details excluding any secrets."""
    with store._lock:
        task = store.tasks.get(task_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Not Found", "message": "Task does not exist"}
            )
        if task["user_id"] != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "Forbidden", "message": "Access denied to task owned by another user"}
            )

        pending = challenge_broker.get_pending_input(task_id) or task.get("pending_input")

        return {
            "id": task["id"],
            "workflow": task["workflow"],
            "status": task["status"],
            "created_at": task["created_at"],
            "pending_input": pending
        }


@router.post("/tasks/{task_id}/input")
async def submit_input(
    task_id: str,
    payload: SubmitInputRequest,
    user: UserContext = Depends(get_current_user)
):
    """Submit OTP or CAPTCHA challenge response to in-memory broker."""
    # 1. Rate limiting on input submissions (max 5 per 10 seconds)
    if not store.check_rate_limit(f"input_{user.user_id}", max_calls=5, window_seconds=10.0):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "Too Many Requests", "message": "Rate limit exceeded on secure input endpoint"}
        )

    with store._lock:
        task = store.tasks.get(task_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Not Found", "message": "Task does not exist"}
            )
        if task["user_id"] != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "Forbidden", "message": "Access denied"}
            )
        if task["status"] != "WAITING_FOR_USER":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "Invalid State", "message": f"Task is in {task['status']}, not waiting for input"}
            )

    input_id = payload.input_id
    val = payload.value.strip()

    if input_id == "otp":
        if not re.match(r"^\d{6}$", val):
            raise HTTPException(
                status_code=422,
                detail={"error": "Unprocessable Entity", "message": "OTP must be exactly 6 numeric digits"}
            )
        challenge_broker.resolve_challenge(task_id, SecretStr(val))
        return {
            "status": "accepted",
            "message": "Input received into in-memory relay"
        }
    elif input_id == "captcha":
        if not val or len(val) < 4:
            raise HTTPException(
                status_code=422,
                detail={"error": "Unprocessable Entity", "message": "CAPTCHA cannot be empty"}
            )
        challenge_broker.resolve_challenge(task_id, SecretStr(val))
        return {
            "status": "accepted",
            "message": "CAPTCHA accepted"
        }

    return {"status": "accepted"}


@router.get("/tasks/{task_id}/challenge")
async def get_challenge(
    task_id: str,
    user: UserContext = Depends(get_current_user)
):
    """Retrieve raw CAPTCHA image bytes from RAM with no-store cache headers."""
    with store._lock:
        task = store.tasks.get(task_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Not Found", "message": "Challenge not accessible"}
            )
        if task["user_id"] != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "Forbidden", "message": "Challenge not accessible"}
            )

    png_bytes = challenge_broker.get_captcha(task_id) or store.storage_objects.get(f"captcha_{task_id}", DEFAULT_CAPTCHA_PNG)

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Content-Length": str(len(png_bytes)),
        }
    )


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    user: UserContext = Depends(get_current_user)
):
    """Cooperatively cancel an active task."""
    with store._lock:
        task = store.tasks.get(task_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Not Found", "message": "Task does not exist"}
            )
        if task["user_id"] != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "Forbidden", "message": "Access denied"}
            )
        if task["status"] in {"COMPLETED", "FAILED", "CANCELLED", "EXPIRED"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "Bad Request", "message": f"Cannot cancel terminal task in status {task['status']}"}
            )

        task["status"] = "CANCELLED"
        task["finished_at"] = time.time()
        challenge_broker.cancel_challenge(task_id)

        if store.active_workflows.get(user.user_id) == task_id:
            del store.active_workflows[user.user_id]

    return {
        "status": "CANCELLED",
        "task_id": task_id
    }


@router.get("/tasks/{task_id}/download")
async def get_download(
    task_id: str,
    user: UserContext = Depends(get_current_user)
):
    """Generate 60-second signed URL for verified completed documents."""
    with store._lock:
        task = store.tasks.get(task_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Not Found", "message": "Task does not exist"}
            )
        if task["user_id"] != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "Forbidden", "message": "Ownership check failed"}
            )
        if task["status"] != "COMPLETED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "Task Incomplete", "message": f"Cannot download in status {task['status']}"}
            )

        signed_url = (
            f"https://mock-supabase.local/storage/v1/signed/documents/"
            f"{user.user_id}/{task_id}.pdf?token=sig_60s_{uuid.uuid4().hex[:8]}"
        )
        return {
            "download_url": signed_url,
            "expires_in": 60,
            "doc_type": "aadhaar"
        }


# ---------------------------------------------------------------------------
# Document Management Endpoints
# ---------------------------------------------------------------------------

@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    user: UserContext = Depends(get_current_user)
):
    """Delete document record and purge underlying file from storage."""
    with store._lock:
        doc = store.documents.get(document_id)
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Not Found", "message": "Document does not exist"}
            )
        if doc["user_id"] != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "Forbidden", "message": "Document ownership violation"}
            )

        storage_path = doc.get("storage_path")
        if storage_path:
            store.storage_objects.pop(storage_path, None)
        del store.documents[document_id]

    return {
        "status": "deleted",
        "id": document_id
    }
