"""In-memory Challenge Broker for zero-persistence OTP and CAPTCHA relays."""

import asyncio
import logging
import time
from typing import Any, Dict, Optional
from pydantic import SecretStr

logger = logging.getLogger(__name__)


class ChallengeBroker:
    """In-memory broker relaying challenge prompts and secrets via asyncio.Future.
    
    Guarantees:
    - Zero persistence: OTP/CAPTCHA values are never written to disk, database, or logs.
    - SecretStr encapsulation for sensitive payload strings.
    - Isolated futures per task_id with expiration tracking.
    """

    def __init__(self):
        self._futures: Dict[str, asyncio.Future[SecretStr]] = {}
        self._captchas: Dict[str, bytes] = {}
        self._pending_inputs: Dict[str, Dict[str, Any]] = {}
        self._attempts_left: Dict[str, int] = {}
        self._expiry_timestamps: Dict[str, float] = {}

    def register_challenge(
        self,
        task_id: str,
        kind: str = "otp",
        prompt: str = "Enter the verification code",
        ttl_seconds: int = 180,
        attempts: int = 3
    ) -> asyncio.Future[SecretStr]:
        """Register a new challenge and create a Future waiting for user submission."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[SecretStr] = loop.create_future()
        self._futures[task_id] = future
        now = time.time()
        expires_at = now + ttl_seconds

        self._pending_inputs[task_id] = {
            "kind": kind,
            "prompt": prompt,
            "expires_at": expires_at,
            "attempts_left": attempts,
            "input_id": kind,
        }
        self._attempts_left[task_id] = attempts
        self._expiry_timestamps[task_id] = expires_at

        return future

    def has_pending_challenge(self, task_id: str) -> bool:
        """Check if an active challenge is waiting for submission."""
        if task_id not in self._pending_inputs:
            return False
        if time.time() > self._expiry_timestamps.get(task_id, 0):
            self.cancel_challenge(task_id, reason="expired")
            return False
        return True

    def get_pending_input(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Return sanitized challenge metadata (kind, prompt, expires_at, attempts_left)."""
        if not self.has_pending_challenge(task_id):
            return None
        return dict(self._pending_inputs[task_id])

    def resolve_challenge(self, task_id: str, value: SecretStr) -> bool:
        """Resolve the challenge future with the provided SecretStr and clear references."""
        future = self._futures.get(task_id)
        if future and not future.done():
            future.set_result(value)
            self._futures.pop(task_id, None)
            self._pending_inputs.pop(task_id, None)
            self._expiry_timestamps.pop(task_id, None)
            return True
        return False

    def store_captcha(self, task_id: str, image_bytes: bytes) -> None:
        """Store CAPTCHA image bytes in RAM only with no disk persistence."""
        self._captchas[task_id] = image_bytes

    def get_captcha(self, task_id: str) -> Optional[bytes]:
        """Retrieve CAPTCHA image bytes from memory."""
        return self._captchas.get(task_id)

    def clear_captcha(self, task_id: str) -> None:
        """Purge CAPTCHA image bytes from memory."""
        self._captchas.pop(task_id, None)

    def decrement_attempts(self, task_id: str) -> int:
        """Decrement remaining attempts for an active challenge."""
        current = self._attempts_left.get(task_id, 3) - 1
        self._attempts_left[task_id] = current
        if task_id in self._pending_inputs:
            self._pending_inputs[task_id]["attempts_left"] = current
        return current

    def cancel_challenge(self, task_id: str, reason: str = "cancelled") -> None:
        """Cancel the pending challenge future and purge associated state."""
        future = self._futures.pop(task_id, None)
        if future and not future.done():
            future.cancel()
        self._pending_inputs.pop(task_id, None)
        self._attempts_left.pop(task_id, None)
        self._expiry_timestamps.pop(task_id, None)
        self._captchas.pop(task_id, None)

    def cleanup(self, task_id: str) -> None:
        """Purge all challenge data associated with task_id."""
        self.cancel_challenge(task_id)


# Global singleton instance
challenge_broker = ChallengeBroker()
