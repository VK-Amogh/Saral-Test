"""Chat endpoint with SSE streaming, PII scrubbing, and task intent detection."""

import json
import time
import uuid
from typing import AsyncIterator, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..auth import UserContext, get_current_user
from ..broker import challenge_broker
from ..llm import llm_service
from ..queue import job_queue
from ..scrubber import scrub_pii
from ..store import store

router = APIRouter(prefix="/api/v1", tags=["Chat"])


class ChatRequest(BaseModel):
    """Payload for chat endpoint."""
    text: str = Field(..., description="User message text")
    conversation_id: Optional[str] = Field(None, description="Optional conversation UUID")


@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    user: UserContext = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):
    """Chat endpoint supporting SSE token streaming and task creation on citizen intent."""
    # 1. Enforce Idempotency-Key header requirement
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Bad Request", "message": "Idempotency-Key header is strictly required"}
        )

    # 2. Validate text content
    raw_text = request.text.strip()
    if not raw_text:
        raise HTTPException(
            status_code=422,
            detail={"error": "Unprocessable Entity", "message": "Chat text cannot be empty"}
        )

    if len(raw_text) > 50000:
        raise HTTPException(
            status_code=422,
            detail={"error": "Unprocessable Entity", "message": "Chat text exceeds 50000 characters limit"}
        )

    # 3. Scrub PII before LLM or storage processing
    scrubbed_prompt = scrub_pii(raw_text)
    conversation_id = request.conversation_id or str(uuid.uuid4())

    # 4. Intent detection
    intent_data = llm_service.detect_intent(scrubbed_prompt)
    is_task_intent = intent_data.get("requires_task", False)
    task_id: Optional[str] = None

    if is_task_intent:
        workflow = intent_data.get("workflow", "aadhaar_download")
        with store._lock:
            # Enforce single active workflow per user
            existing_task_id = store.active_workflows.get(user.user_id)
            if existing_task_id:
                existing_task = store.tasks.get(existing_task_id)
                if existing_task and existing_task.get("status") not in {"COMPLETED", "FAILED", "CANCELLED", "EXPIRED"}:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "error": "Conflict",
                            "message": f"Active task {existing_task_id} already in progress for this workflow"
                        }
                    )

            task_id = str(uuid.uuid4())
            new_task = {
                "id": task_id,
                "user_id": user.user_id,
                "conversation_id": conversation_id,
                "workflow": workflow,
                "status": "RECEIVED",
                "request_text": scrubbed_prompt,
                "idempotency_key": idempotency_key,
                "pending_input": None,
                "created_at": time.time(),
                "updated_at": time.time(),
                "finished_at": None,
            }
            store.tasks[task_id] = new_task
            store.active_workflows[user.user_id] = task_id

        # Enqueue task for worker processing
        await job_queue.enqueue(task_id, workflow, user.user_id, scrubbed_prompt)

    # 5. Generator for SSE stream
    async def sse_event_stream() -> AsyncIterator[str]:
        if task_id:
            # Emit introductory tokens
            tokens = ["Namaste! ", "Processing ", "your ", "request..."]
            for token in tokens:
                yield f"data: {json.dumps({'token': token})}\n\n"

            # Emit task created event with required fields
            task_event = {
                "task_id": task_id,
                "status": "RECEIVED",
                "workflow": "aadhaar_download"
            }
            yield f"data: {json.dumps(task_event)}\n\n"
        else:
            # Stream general chat tokens from LLM
            messages = [{"role": "user", "content": scrubbed_prompt}]
            async for token in llm_service.stream_chat_completion(messages):
                yield f"data: {json.dumps({'token': token})}\n\n"

        # Emit completion marker
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        sse_event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
