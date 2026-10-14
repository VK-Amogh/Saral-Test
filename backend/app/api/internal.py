import asyncio
import base64
import json
import logging
import time
from typing import List, Optional
from fastapi import APIRouter, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status

from ..broker import challenge_broker
from ..config import get_settings
from ..state_machine import (
    TERMINAL_STATES,
    TaskState,
    can_transition,
    transition,
)
from ..store import store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["Internal"])


# ---------------------------------------------------------------------------
# POST /internal/cleanup
# ---------------------------------------------------------------------------

@router.post("/cleanup")
async def retention_cleanup(
    request: Request,
    x_cleanup_secret: Optional[str] = Header(None, alias="X-Cleanup-Secret"),
    authorization: Optional[str] = Header(None)
):
    """Retention sweep purging expired documents from database and storage."""
    settings = get_settings()
    provided_secret = x_cleanup_secret

    if not provided_secret and authorization:
        parts = authorization.split()
        provided_secret = parts[1] if len(parts) == 2 else parts[0]

    if not provided_secret or provided_secret != settings.CLEANUP_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Unauthorized", "message": "Invalid cleanup secret"}
        )

    now = time.time()
    with store._lock:
        to_delete = [
            doc_id
            for doc_id, doc in store.documents.items()
            if doc.get("delete_after", float("inf")) <= now
        ]
        for doc_id in to_delete:
            doc = store.documents.pop(doc_id, None)
            if doc and doc.get("storage_path"):
                store.storage_objects.pop(doc["storage_path"], None)

    return {
        "status": "ok",
        "cleaned_documents": len(to_delete),
        "timestamp": now
    }


# ---------------------------------------------------------------------------
# WS /internal/worker
# ---------------------------------------------------------------------------

@router.websocket("/worker")
async def worker_websocket(
    websocket: WebSocket,
    secret: Optional[str] = Query(None)
):
    """Authenticated outbound WebSocket for headless browser worker."""
    settings = get_settings()

    # Verify worker authentication
    provided_secret = secret or websocket.headers.get("x-worker-secret")
    if not provided_secret:
        auth_hdr = websocket.headers.get("authorization", "")
        if auth_hdr.lower().startswith("bearer "):
            provided_secret = auth_hdr.split(" ")[1]

    if provided_secret not in {settings.WORKER_SECRET, settings.WORKER_SHARED_SECRET}:
        await websocket.close(code=4003, reason="Unauthorized: invalid worker secret")
        return

    await websocket.accept()
    logger.info("Browser worker connected via WebSocket")
    active_relay_tasks: List[asyncio.Task] = []

    try:
        while True:
            raw_msg = await websocket.receive_text()
            try:
                data = json.loads(raw_msg)
            except Exception:
                data = {"raw": raw_msg}

            msg_type = data.get("type", "")
            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong", "timestamp": time.time()}))

            elif msg_type == "ready":
                await websocket.send_text(json.dumps({"type": "acknowledged", "status": "idle"}))

            elif msg_type == "worker_register":
                worker_id = data.get("worker_id", "unknown")
                logger.info("Worker registered: %s", worker_id)
                await websocket.send_text(json.dumps({
                    "type": "worker_registered",
                    "worker_id": worker_id,
                    "timestamp": time.time()
                }))

            elif msg_type == "challenge_required":
                task_id = data.get("task_id", "")
                kind = data.get("kind", "otp")
                prompt = data.get("prompt", "Challenge input required")
                challenge_data_b64 = data.get("challenge_data_b64")

                # Decode and store ephemeral CAPTCHA image in RAM
                if challenge_data_b64:
                    try:
                        raw_bytes = base64.b64decode(challenge_data_b64)
                        challenge_broker.store_captcha(task_id, raw_bytes)
                    except Exception as e:
                        logger.warning("Failed to decode CAPTCHA screenshot: %s", str(e))

                # Compute TTL
                now = time.time()
                expires_at = data.get("expires_at", now + 180)
                ttl = max(int(expires_at - now), 10)

                # Register challenge future in ChallengeBroker
                broker_fut = challenge_broker.register_challenge(
                    task_id=task_id,
                    kind=kind,
                    prompt=prompt,
                    ttl_seconds=ttl,
                    attempts=data.get("attempts_left", 3)
                )

                # Transition task state to WAITING_FOR_USER via deterministic state machine
                with store._lock:
                    if task_id in store.tasks:
                        task = store.tasks[task_id]
                        cur_status = task.get("status")
                        if cur_status not in {s.value for s in TERMINAL_STATES}:
                            if cur_status != TaskState.WAITING_FOR_USER.value:
                                if cur_status == TaskState.RECEIVED.value:
                                    transition(task, TaskState.VALIDATING, actor="system")
                                    transition(task, TaskState.PLANNING, actor="system")
                                    transition(task, TaskState.WAITING_FOR_USER, actor="orchestrator")
                                elif cur_status == TaskState.VALIDATING.value:
                                    transition(task, TaskState.PLANNING, actor="system")
                                    transition(task, TaskState.WAITING_FOR_USER, actor="orchestrator")
                                elif cur_status in {TaskState.PLANNING.value, TaskState.RUNNING.value, TaskState.AUTHENTICATING.value}:
                                    transition(task, TaskState.WAITING_FOR_USER, actor="orchestrator")
                            task["pending_input"] = kind

                # Background relay watcher: when citizen submits input, relay to worker
                async def _relay_future_to_worker(fut: asyncio.Future, t_id: str, k: str, ws: WebSocket):
                    try:
                        secret_val = await fut
                        val_str = secret_val.get_secret_value() if hasattr(secret_val, "get_secret_value") else str(secret_val)
                        await ws.send_text(json.dumps({
                            "type": "relay_input",
                            "task_id": t_id,
                            "kind": k,
                            "value": val_str,
                        }))
                        del val_str  # Zero-persistence guarantee
                    except asyncio.CancelledError:
                        pass
                    except Exception as exc:
                        logger.warning("Error relaying user response to worker for task %s: %s", t_id, str(exc))

                watcher_task = asyncio.create_task(_relay_future_to_worker(broker_fut, task_id, kind, websocket))
                active_relay_tasks.append(watcher_task)

                await websocket.send_text(json.dumps({
                    "type": "challenge_registered",
                    "task_id": task_id,
                    "kind": kind,
                    "timestamp": time.time()
                }))

            elif msg_type == "task_progress":
                task_id = data.get("task_id")
                if task_id:
                    with store._lock:
                        if task_id in store.tasks:
                            task = store.tasks[task_id]
                            if "progress" in data:
                                task["progress"] = data["progress"]
                            if "message" in data:
                                task["progress_message"] = data["message"]
                            req_status = data.get("status")
                            cur_status = task.get("status")
                            # Progress updates cannot transition to terminal states (handled by dedicated frames)
                            if req_status and req_status not in {s.value for s in TERMINAL_STATES} and req_status != cur_status and cur_status not in {s.value for s in TERMINAL_STATES}:
                                if can_transition(cur_status, req_status, actor="worker"):
                                    transition(task, req_status, actor="worker")
                                elif cur_status == TaskState.RECEIVED.value and req_status == TaskState.RUNNING.value:
                                    transition(task, TaskState.VALIDATING, actor="system")
                                    transition(task, TaskState.PLANNING, actor="system")
                                    transition(task, TaskState.RUNNING, actor="worker")
                                elif cur_status == TaskState.VALIDATING.value and req_status == TaskState.RUNNING.value:
                                    transition(task, TaskState.PLANNING, actor="system")
                                    transition(task, TaskState.RUNNING, actor="worker")
                await websocket.send_text(json.dumps({"type": "progress_ack", "task_id": task_id}))

            elif msg_type == "task_completed":
                task_id = data.get("task_id")
                if task_id:
                    with store._lock:
                        if task_id in store.tasks:
                            task = store.tasks[task_id]
                            cur_status = task.get("status")
                            if cur_status not in {s.value for s in TERMINAL_STATES}:
                                # Advance task to VERIFYING state prior to verifier completion gate
                                if cur_status == TaskState.WAITING_FOR_USER.value:
                                    transition(task, TaskState.RUNNING, actor="orchestrator")
                                    transition(task, TaskState.DOWNLOADING, actor="orchestrator")
                                    transition(task, TaskState.VERIFYING, actor="orchestrator")
                                elif cur_status in {TaskState.RUNNING.value, TaskState.AUTHENTICATING.value}:
                                    transition(task, TaskState.DOWNLOADING, actor="orchestrator")
                                    transition(task, TaskState.VERIFYING, actor="orchestrator")
                                elif cur_status == TaskState.DOWNLOADING.value:
                                    transition(task, TaskState.VERIFYING, actor="orchestrator")
                                elif cur_status != TaskState.VERIFYING.value:
                                    if cur_status == TaskState.RECEIVED.value:
                                        transition(task, TaskState.VALIDATING, actor="system")
                                        transition(task, TaskState.PLANNING, actor="system")
                                    elif cur_status == TaskState.VALIDATING.value:
                                        transition(task, TaskState.PLANNING, actor="system")
                                    transition(task, TaskState.RUNNING, actor="system")
                                    transition(task, TaskState.DOWNLOADING, actor="system")
                                    transition(task, TaskState.VERIFYING, actor="orchestrator")

                                # Task is in VERIFYING state; enforce Rule 2 Verifier-Only Completion Gate
                                transition(task, TaskState.COMPLETED, actor="verifier")
                                task["pending_input"] = None
                                if "document_id" in data:
                                    task["document_id"] = data["document_id"]
                                if "storage_path" in data:
                                    task["storage_path"] = data["storage_path"]
                                user_id = task.get("user_id")
                                if user_id and store.active_workflows.get(user_id) == task_id:
                                    del store.active_workflows[user_id]
                await websocket.send_text(json.dumps({"type": "completed_ack", "task_id": task_id}))

            elif msg_type == "task_failed":
                task_id = data.get("task_id")
                error_code = data.get("error_code") or "WORKER_AUTOMATION_FAILED"
                error_message = data.get("error_message")
                if task_id:
                    with store._lock:
                        if task_id in store.tasks:
                            task = store.tasks[task_id]
                            cur_status = task.get("status")
                            if cur_status not in {s.value for s in TERMINAL_STATES}:
                                transition(task, TaskState.FAILED, actor="orchestrator", reason=error_code)
                                task["error_code"] = error_code
                                if error_message:
                                    task["error_message"] = error_message
                                task["pending_input"] = None
                                user_id = task.get("user_id")
                                if user_id and store.active_workflows.get(user_id) == task_id:
                                    del store.active_workflows[user_id]
                await websocket.send_text(json.dumps({"type": "failed_ack", "task_id": task_id}))

            elif msg_type == "refresh_captcha":
                task_id = data.get("task_id")
                await websocket.send_text(json.dumps({"type": "refresh_captcha", "task_id": task_id}))

            else:
                await websocket.send_text(json.dumps({"type": "received", "data": data}))

    except WebSocketDisconnect:
        logger.info("Browser worker disconnected")
    except Exception as e:
        logger.warning("Worker WebSocket error: %s", str(e))
    finally:
        for t in active_relay_tasks:
            if not t.done():
                t.cancel()
