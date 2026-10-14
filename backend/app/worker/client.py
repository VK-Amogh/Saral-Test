"""
Saral AI — Outbound Worker WebSocket Client
File: backend/app/worker/client.py

Maintains authenticated outbound WebSocket connection to the backend (/internal/worker)
with exponential backoff, in-memory challenge relay futures, and lifecycle messaging.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Callable, Coroutine, Dict, Optional, Tuple

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

logger = logging.getLogger(__name__)


class WorkerWebSocketClient:
    """Outbound persistent WebSocket client connecting browser worker to FastAPI backend."""

    def __init__(
        self,
        server_ws_url: str = "ws://127.0.0.1:8000/internal/worker",
        shared_secret: str = "saral_worker_shared_secret_secure_key_9988",
        worker_id: Optional[str] = None,
        max_reconnect_delay: float = 30.0,
    ):
        self.server_ws_url = server_ws_url
        self.shared_secret = shared_secret
        self.worker_id = worker_id or f"worker_{uuid.uuid4().hex[:8]}"
        self.max_reconnect_delay = max_reconnect_delay

        self._ws: Any = None
        self._running = False
        self._connected = asyncio.Event()

        # In-memory Futures keyed by (task_id, kind) -> Future[str]
        self._input_futures: Dict[Tuple[str, str], asyncio.Future[str]] = {}
        # Task cancellation flags keyed by task_id -> Event
        self._cancellation_events: Dict[str, asyncio.Event] = {}
        # Captcha refresh events keyed by task_id -> Event
        self._refresh_events: Dict[str, asyncio.Event] = {}

        # Task assignment handler: Callable[[Dict[str, Any]], Coroutine]
        self._task_handler: Optional[Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]] = None

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is currently open."""
        return self._connected.is_set()

    def set_task_handler(self, handler: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]) -> None:
        """Register handler coroutine for assigned tasks."""
        self._task_handler = handler

    async def connect(self) -> bool:
        """Initiate single connection attempt with authentication handshake."""
        if not WEBSOCKETS_AVAILABLE:
            logger.warning("websockets library not installed; operating in offline mode")
            return False

        # Add secret to URL query parameters
        connector_url = f"{self.server_ws_url}?secret={self.shared_secret}"
        headers = {
            "X-Worker-Secret": self.shared_secret,
            "Authorization": f"Bearer {self.shared_secret}",
        }

        try:
            self._ws = await websockets.connect(
                connector_url,
                extra_headers=headers,
                ping_interval=20,
                ping_timeout=10,
            )
            self._connected.set()

            # Transmit register handshake
            await self.send_message({
                "type": "worker_register",
                "worker_id": self.worker_id,
                "timestamp": time.time(),
                "capabilities": ["aadhaar_download", "mock_portal"],
            })
            logger.info("Worker WebSocket connected to %s", self.server_ws_url)
            return True
        except Exception as e:
            self._connected.clear()
            logger.debug("WebSocket connection attempt failed: %s", str(e))
            return False

    async def run_forever(self) -> None:
        """Maintain persistent connection with exponential backoff reconnect loop."""
        self._running = True
        backoff = 1.0

        while self._running:
            success = await self.connect()
            if success:
                backoff = 1.0
                try:
                    await self._listen_loop()
                except Exception as e:
                    logger.warning("WebSocket listen loop encountered exception: %s", str(e))
                finally:
                    self._connected.clear()
                    if self._ws:
                        try:
                            await self._ws.close()
                        except Exception:
                            pass
                        self._ws = None

            if not self._running:
                break

            logger.info("Reconnecting worker WebSocket in %.1fs...", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, self.max_reconnect_delay)

    async def stop(self) -> None:
        """Gracefully disconnect and terminate."""
        self._running = False
        self._connected.clear()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _listen_loop(self) -> None:
        """Process incoming frames from backend."""
        while self._running and self._ws:
            raw_msg = await self._ws.recv()
            if isinstance(raw_msg, bytes):
                raw_msg = raw_msg.decode("utf-8")

            try:
                data = json.loads(raw_msg)
            except Exception:
                continue

            await self._handle_message(data)

    async def _handle_message(self, message: Dict[str, Any]) -> None:
        """Dispatch backend frame to appropriate local future or handler."""
        msg_type = message.get("type", "")

        if msg_type == "assign_task":
            logger.info("Task assigned: %s", message.get("task_id"))
            task_id = message.get("task_id", "")
            self._cancellation_events[task_id] = asyncio.Event()

            if self._task_handler:
                asyncio.create_task(self._task_handler(message))

        elif msg_type == "relay_input":
            task_id = message.get("task_id", "")
            kind = message.get("kind", "")
            val = message.get("value", "")
            key = (task_id, kind)

            future = self._input_futures.pop(key, None)
            if future and not future.done():
                future.set_result(val)
                logger.info("Input relayed for task %s (kind=%s)", task_id, kind)

        elif msg_type == "cancel_task":
            task_id = message.get("task_id", "")
            if task_id in self._cancellation_events:
                self._cancellation_events[task_id].set()
                logger.info("Task %s cancellation requested by backend", task_id)

            # Cancel any pending input futures for this task
            for (t_id, kind), fut in list(self._input_futures.items()):
                if t_id == task_id and not fut.done():
                    fut.cancel()
                    self._input_futures.pop((t_id, kind), None)

        elif msg_type == "refresh_captcha":
            task_id = message.get("task_id", "")
            ev = self._refresh_events.get(task_id)
            if ev:
                ev.set()
            logger.info("Captcha refresh triggered by backend for task %s", task_id)

        elif msg_type == "ping":
            await self.send_message({"type": "pong", "timestamp": time.time()})

    # -----------------------------------------------------------------------
    # Challenge Future & Cancellation API
    # -----------------------------------------------------------------------

    def register_input_future(self, task_id: str, kind: str) -> asyncio.Future[str]:
        """Create and register an asyncio.Future awaiting user submission."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._input_futures[(task_id, kind)] = future
        return future

    def register_refresh_event(self, task_id: str) -> asyncio.Event:
        """Create and register an asyncio.Event for interactive CAPTCHA refresh."""
        event = asyncio.Event()
        self._refresh_events[task_id] = event
        return event

    def get_refresh_event(self, task_id: str) -> Optional[asyncio.Event]:
        """Retrieve existing refresh event for task_id if any."""
        return self._refresh_events.get(task_id)

    def is_task_cancelled(self, task_id: str) -> bool:
        """Check if task has received a cooperative cancellation signal."""
        event = self._cancellation_events.get(task_id)
        return event.is_set() if event else False

    def clear_task_futures(self, task_id: str) -> None:
        """Purge all in-memory futures and events for task_id."""
        for (t_id, kind), fut in list(self._input_futures.items()):
            if t_id == task_id:
                if not fut.done():
                    fut.cancel()
                self._input_futures.pop((t_id, kind), None)
        self._cancellation_events.pop(task_id, None)
        self._refresh_events.pop(task_id, None)

    # -----------------------------------------------------------------------
    # Outgoing Message API
    # -----------------------------------------------------------------------

    async def send_message(self, message: Dict[str, Any]) -> bool:
        """Transmit JSON message frame over WebSocket."""
        if not self._ws:
            return False
        try:
            await self._ws.send(json.dumps(message))
            return True
        except Exception as e:
            logger.warning("Failed to send WebSocket message: %s", str(e))
            return False

    async def send_task_progress(self, task_id: str, progress: int, status: str = "RUNNING", message: str = "") -> bool:
        """Send task execution progress update."""
        return await self.send_message({
            "type": "task_progress",
            "task_id": task_id,
            "status": status,
            "progress": progress,
            "message": message,
            "timestamp": time.time(),
        })

    async def send_challenge_required(
        self,
        task_id: str,
        kind: str,
        prompt: str = "Challenge input required",
        challenge_data_b64: Optional[str] = None,
        attempts_left: int = 3,
        ttl_seconds: int = 180
    ) -> bool:
        """Notify backend that a user challenge is required (CAPTCHA or OTP)."""
        payload = {
            "type": "challenge_required",
            "task_id": task_id,
            "kind": kind,
            "prompt": prompt,
            "attempts_left": attempts_left,
            "expires_at": time.time() + ttl_seconds,
        }
        if challenge_data_b64:
            payload["challenge_data_b64"] = challenge_data_b64

        return await self.send_message(payload)

    async def send_task_completed(
        self,
        task_id: str,
        document_id: str,
        storage_path: str,
        file_name: str,
        size_bytes: int,
        sha256: str,
        pdf_encrypted: bool = True
    ) -> bool:
        """Signal successful task completion with verified document metadata."""
        return await self.send_message({
            "type": "task_completed",
            "task_id": task_id,
            "document_id": document_id,
            "storage_path": storage_path,
            "file_name": file_name,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "pdf_encrypted": pdf_encrypted,
            "timestamp": time.time(),
        })

    async def send_task_failed(self, task_id: str, error_code: str, error_message: str) -> bool:
        """Signal task failure with descriptive error code."""
        return await self.send_message({
            "type": "task_failed",
            "task_id": task_id,
            "error_code": error_code,
            "error_message": error_message,
            "timestamp": time.time(),
        })
