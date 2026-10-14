"""PostgreSQL Job Queue with FOR UPDATE SKIP LOCKED logic and in-memory fallback."""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class JobQueue:
    """Task queue supporting PostgreSQL FOR UPDATE SKIP LOCKED with in-memory fallback."""

    def __init__(self, db_pool: Optional[Any] = None):
        self._pool = db_pool
        self._lock = asyncio.Lock()
        self._in_memory_queue: List[Dict[str, Any]] = []
        self._processing: Dict[str, Dict[str, Any]] = {}

    def set_pool(self, db_pool: Any) -> None:
        """Set the asyncpg database connection pool."""
        self._pool = db_pool

    async def enqueue(
        self,
        task_id: str,
        workflow: str,
        user_id: str,
        request_text: Optional[str] = None
    ) -> None:
        """Enqueue a new task for processing."""
        item = {
            "id": task_id,
            "task_id": task_id,
            "workflow": workflow,
            "user_id": user_id,
            "request_text": request_text,
            "status": "RECEIVED",
            "enqueued_at": time.time(),
        }

        if self._pool is not None:
            try:
                async with self._pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO tasks (id, workflow, user_id, request_text, status)
                        VALUES ($1, $2, $3, $4, 'RECEIVED')
                        ON CONFLICT (id) DO UPDATE SET status = 'RECEIVED'
                        """,
                        task_id, workflow, user_id, request_text
                    )
                    return
            except Exception as e:
                logger.warning("Postgres enqueue failed, falling back to in-memory queue: %s", str(e))

        async with self._lock:
            self._in_memory_queue.append(item)

    async def dequeue(self) -> Optional[Dict[str, Any]]:
        """Fetch the next available task using FOR UPDATE SKIP LOCKED, or in-memory FIFO."""
        if self._pool is not None:
            try:
                async with self._pool.acquire() as conn:
                    async with conn.transaction():
                        row = await conn.fetchrow(
                            """
                            SELECT id, workflow, user_id, request_text
                            FROM tasks
                            WHERE status = 'RECEIVED'
                            ORDER BY created_at ASC
                            LIMIT 1
                            FOR UPDATE SKIP LOCKED
                            """
                        )
                        if row:
                            task_id = str(row["id"])
                            await conn.execute(
                                "UPDATE tasks SET status = 'VALIDATING' WHERE id = $1",
                                row["id"]
                            )
                            return {
                                "id": task_id,
                                "task_id": task_id,
                                "workflow": row["workflow"],
                                "user_id": str(row["user_id"]),
                                "request_text": row["request_text"],
                                "status": "VALIDATING",
                            }
                        return None
            except Exception as e:
                logger.warning("Postgres dequeue failed, checking in-memory queue: %s", str(e))

        async with self._lock:
            if not self._in_memory_queue:
                return None
            task = self._in_memory_queue.pop(0)
            task["status"] = "VALIDATING"
            self._processing[task["id"]] = task
            return dict(task)

    async def ack(self, task_id: str) -> None:
        """Acknowledge successful completion of a task."""
        if self._pool is not None:
            try:
                async with self._pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE tasks SET finished_at = NOW() WHERE id = $1",
                        task_id
                    )
                    return
            except Exception as e:
                logger.warning("Postgres ack failed: %s", str(e))

        async with self._lock:
            self._processing.pop(task_id, None)

    async def nack(self, task_id: str) -> None:
        """Return an unacknowledged task back to the queue for retry."""
        async with self._lock:
            task = self._processing.pop(task_id, None)
            if task:
                task["status"] = "RECEIVED"
                self._in_memory_queue.append(task)

    async def size(self) -> int:
        """Return the number of items currently pending in the queue."""
        if self._pool is not None:
            try:
                async with self._pool.acquire() as conn:
                    val = await conn.fetchval(
                        "SELECT COUNT(*) FROM tasks WHERE status = 'RECEIVED'"
                    )
                    return int(val)
            except Exception:
                pass

        async with self._lock:
            return len(self._in_memory_queue)

    async def clear(self) -> None:
        """Clear all tasks from the queue."""
        async with self._lock:
            self._in_memory_queue.clear()
            self._processing.clear()


# Global queue singleton
job_queue = JobQueue()
