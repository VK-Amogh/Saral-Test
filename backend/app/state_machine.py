"""Deterministic 12-state task lifecycle state machine with verifier gate."""

from enum import Enum
import time
from typing import Any, Dict, Optional, Set, Union


class TaskState(str, Enum):
    """The 12 deterministic task lifecycle states."""
    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    AUTHENTICATING = "AUTHENTICATING"
    DOWNLOADING = "DOWNLOADING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


TERMINAL_STATES: Set[TaskState] = {
    TaskState.COMPLETED,
    TaskState.FAILED,
    TaskState.CANCELLED,
    TaskState.EXPIRED,
}


ALLOWED_TRANSITIONS: Dict[TaskState, Set[TaskState]] = {
    TaskState.RECEIVED: {TaskState.VALIDATING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.VALIDATING: {TaskState.PLANNING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.PLANNING: {TaskState.RUNNING, TaskState.WAITING_FOR_USER, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.RUNNING: {
        TaskState.WAITING_FOR_USER,
        TaskState.AUTHENTICATING,
        TaskState.DOWNLOADING,
        TaskState.FAILED,
        TaskState.CANCELLED,
        TaskState.EXPIRED,
    },
    TaskState.WAITING_FOR_USER: {
        TaskState.RUNNING,
        TaskState.AUTHENTICATING,
        TaskState.FAILED,
        TaskState.CANCELLED,
        TaskState.EXPIRED,
    },
    TaskState.AUTHENTICATING: {
        TaskState.RUNNING,
        TaskState.WAITING_FOR_USER,
        TaskState.DOWNLOADING,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.DOWNLOADING: {TaskState.VERIFYING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.VERIFYING: {TaskState.COMPLETED, TaskState.FAILED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELLED: set(),
    TaskState.EXPIRED: set(),
}


class StateMachineError(ValueError):
    """Base exception for state machine transition violations."""
    pass


class TerminalStateError(StateMachineError):
    """Raised when an attempt is made to transition from a terminal state."""
    pass


class InvalidStateTransitionError(StateMachineError):
    """Raised when a transition is illegal according to the transition matrix."""
    pass


class UnauthorizedActorError(StateMachineError):
    """Raised when an unauthorized actor attempts a privileged transition."""
    pass


def is_terminal(state: Union[TaskState, str]) -> bool:
    """Check if the given state is a terminal state."""
    if isinstance(state, str):
        state = TaskState(state)
    return state in TERMINAL_STATES


def can_transition(
    current: Union[TaskState, str],
    next_state: Union[TaskState, str],
    actor: str = "orchestrator"
) -> bool:
    """Check if a transition from current to next_state by actor is legally permissible."""
    if isinstance(current, str):
        current = TaskState(current)
    if isinstance(next_state, str):
        next_state = TaskState(next_state)

    if current in TERMINAL_STATES:
        return False

    if next_state not in ALLOWED_TRANSITIONS.get(current, set()):
        return False

    if next_state == TaskState.COMPLETED and actor != "verifier":
        return False

    return True


def transition(
    task: Dict[str, Any],
    new_status: Union[TaskState, str],
    actor: str = "orchestrator",
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """Execute a validated state transition on a task dictionary.
    
    Enforces:
    1. Terminal state immutability.
    2. Transition matrix legality.
    3. Strict verifier actor gate for transition to COMPLETED.
    """
    if isinstance(new_status, str):
        try:
            target_state = TaskState(new_status)
        except ValueError:
            raise InvalidStateTransitionError(f"Unknown task state: {new_status}")
    else:
        target_state = new_status

    current_raw = task.get("status", TaskState.RECEIVED)
    current_state = TaskState(current_raw) if isinstance(current_raw, str) else current_raw

    # 1. Guard against transition from terminal states
    if current_state in TERMINAL_STATES:
        raise TerminalStateError(
            f"Terminal state {current_state.value} cannot transition to {target_state.value}"
        )

    # 2. Check transition matrix
    allowed = ALLOWED_TRANSITIONS.get(current_state, set())
    if target_state not in allowed:
        raise InvalidStateTransitionError(
            f"Illegal transition from {current_state.value} to {target_state.value}"
        )

    # 3. Enforce verifier gate
    if target_state == TaskState.COMPLETED and actor != "verifier":
        raise UnauthorizedActorError("Only actor='verifier' can transition to COMPLETED")

    # Apply state update
    task["status"] = target_state.value
    task["updated_at"] = time.time()

    if target_state in TERMINAL_STATES:
        task["finished_at"] = time.time()

    if reason:
        task["status_reason"] = reason

    if "history" in task and isinstance(task["history"], list):
        task["history"].append({
            "from": current_state.value if hasattr(current_state, "value") else current_state,
            "to": target_state.value,
            "timestamp": time.time(),
            "actor": actor,
            "reason": reason,
        })

    return task
