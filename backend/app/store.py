"""State store for tasks, documents, and operational rate limits."""

import threading
import time
from typing import Any, Dict, List, Optional


class AppStore:
    """Thread-safe store for tasks, documents, and mock storage objects."""

    def __init__(self):
        self._lock = threading.Lock()
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.documents: Dict[str, Dict[str, Any]] = {}
        self.storage_objects: Dict[str, bytes] = {}
        self.active_workflows: Dict[str, str] = {}  # user_id -> task_id
        self.rate_limits: Dict[str, List[float]] = {}  # key -> list of timestamps

    def reset(self):
        """Reset all in-memory collections (used primarily for test isolation)."""
        with self._lock:
            self.tasks.clear()
            self.documents.clear()
            self.storage_objects.clear()
            self.active_workflows.clear()
            self.rate_limits.clear()

    def check_rate_limit(self, key: str, max_calls: int = 5, window_seconds: float = 10.0) -> bool:
        """Return True if under rate limit, False if exceeded."""
        with self._lock:
            now = time.time()
            history = self.rate_limits.setdefault(key, [])
            # Filter timestamps outside window
            history = [t for t in history if now - t < window_seconds]
            if len(history) >= max_calls:
                self.rate_limits[key] = history
                return False
            history.append(now)
            self.rate_limits[key] = history
            return True


# Global store singleton
store = AppStore()
