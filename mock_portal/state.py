"""
Saral AI — Mock Portal State Engine
File: mock_portal/state.py

Manages in-memory portal sessions, 3-attempt OTP countdown timers,
and 10 deterministic failure simulation switches.
"""

import threading
import time
import uuid
from typing import Any, Dict, Optional, Tuple


class MockPortalState:
    """Thread-safe state container for mock UIDAI portal sessions and failure switches."""

    # 10 Deterministic failure modes specified in SARAL_AI_IMPLEMENTATION_PLAN §16
    FAILURE_SWITCHES = [
        "wrong_captcha",
        "expired_otp",
        "wrong_otp_3x",
        "corrupt_pdf",
        "html_as_pdf",
        "oversize_pdf",
        "malicious_pdf",
        "timeout",
        "changed_selectors",
        "foreign_redirect",
    ]

    # Special UID triggers mapping to deterministic failure switches
    SPECIAL_UID_MAP = {
        "000000000001": "wrong_captcha",
        "000000000002": "expired_otp",
        "000000000003": "corrupt_pdf",
        "000000000004": "html_as_pdf",
        "000000000005": "oversize_pdf",
        "000000000006": "malicious_pdf",
        "000000000007": "timeout",
        "000000000008": "changed_selectors",
        "000000000009": "foreign_redirect",
    }

    def __init__(self):
        self._lock = threading.Lock()
        self.failure_switches: Dict[str, bool] = {k: False for k in self.FAILURE_SWITCHES}
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.otp_attempts: Dict[str, int] = {}
        self.otp_timer: Dict[str, float] = {}

    def reset(self) -> None:
        """Reset all failure switches, sessions, and timers to pristine state."""
        with self._lock:
            for k in self.failure_switches:
                self.failure_switches[k] = False
            self.sessions.clear()
            self.otp_attempts.clear()
            self.otp_timer.clear()

    def set_switch(self, switch_name: str, enabled: bool = True) -> bool:
        """Set state of a deterministic failure switch."""
        with self._lock:
            # Handle aliases
            canonical = switch_name.lower().replace("-", "_")
            if canonical == "page_timeout":
                canonical = "timeout"
            elif canonical in {"broken_dom", "changed_selector"}:
                canonical = "changed_selectors"

            if canonical in self.failure_switches:
                self.failure_switches[canonical] = enabled
                return True
            return False

    def is_switch_active(
        self,
        switch_name: str,
        uid: Optional[str] = None,
        header_mode: Optional[str] = None,
        query_mode: Optional[str] = None
    ) -> bool:
        """Evaluate if a failure switch is active via global switch, UID, header, or query."""
        with self._lock:
            canonical = switch_name.lower().replace("-", "_")
            if canonical == "page_timeout":
                canonical = "timeout"
            elif canonical in {"broken_dom", "changed_selector"}:
                canonical = "changed_selectors"

            # 1. Global switch active
            if self.failure_switches.get(canonical, False):
                return True

            # 2. Check UID trigger
            if uid and self.SPECIAL_UID_MAP.get(uid) == canonical:
                return True

            # 3. Check X-Mock-Mode header or query
            active_mode = (header_mode or query_mode or "").lower().replace("-", "_")
            if active_mode == canonical:
                return True
            if active_mode == "page_timeout" and canonical == "timeout":
                return True
            if active_mode in {"broken_dom", "changed_selector"} and canonical == "changed_selectors":
                return True

            return False

    def create_session(
        self,
        uid: Optional[str] = None,
        captcha_solution: str = "VALID_CAP",
        otp_code: str = "123456",
        ttl_seconds: int = 180
    ) -> Dict[str, Any]:
        """Create a new portal session with 180s OTP countdown and 3 attempts."""
        session_id = str(uuid.uuid4())
        now = time.time()
        expires_at = now + ttl_seconds

        session_data = {
            "session_id": session_id,
            "uid": uid or "",
            "captcha_solution": captcha_solution,
            "stage": "LANDING",
            "otp": otp_code,
            "otp_attempts_left": 3,
            "otp_issued_at": now,
            "otp_expires_at": expires_at,
            "authenticated": False,
            "download_token": None,
            "created_at": now,
        }

        with self._lock:
            self.sessions[session_id] = session_data
            self.otp_attempts[session_id] = 3
            self.otp_timer[session_id] = now

        return session_data

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve session record by session_id."""
        with self._lock:
            return self.sessions.get(session_id)

    def verify_captcha(self, session_id: str, submitted_captcha: str) -> bool:
        """Case-insensitive verification of submitted CAPTCHA solution."""
        session = self.get_session(session_id)
        if not session:
            return False
        expected = session.get("captcha_solution", "VALID_CAP").strip().upper()
        actual = (submitted_captcha or "").strip().upper()
        # Accept if matches expected solution, or standard universal test token 'VALID_CAP'
        return actual == expected or actual == "VALID_CAP" or actual == "K7M9P2" or actual == "WXYZ12"

    def advance_to_otp(self, session_id: str, uid: str) -> Optional[Dict[str, Any]]:
        """Transition session to OTP_SENT stage."""
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return None
            now = time.time()
            session["uid"] = uid
            session["stage"] = "OTP_SENT"
            session["otp_issued_at"] = now
            session["otp_expires_at"] = now + 180
            session["otp_attempts_left"] = 3
            self.otp_attempts[session_id] = 3
            self.otp_timer[session_id] = now
            return session

    def verify_otp(
        self,
        session_id: str,
        submitted_otp: str
    ) -> Tuple[str, int]:
        """Validate submitted OTP against session.

        Returns:
            Tuple[str, int]: (result_status, attempts_left)
            Status can be 'AUTHENTICATED', 'INVALID', 'LOCKED', 'EXPIRED', or 'SESSION_NOT_FOUND'.
        """
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return "SESSION_NOT_FOUND", 0

            # 1. Check expiration switch or timestamp
            if self.failure_switches.get("expired_otp", False):
                return "EXPIRED", 0

            now = time.time()
            if now > session.get("otp_expires_at", 0):
                return "EXPIRED", 0

            # 2. Check 3x wrong failure switch or incorrect OTP
            expected_otp = session.get("otp", "123456")
            is_wrong = self.failure_switches.get("wrong_otp_3x", False) or (submitted_otp != expected_otp)

            if is_wrong:
                current_attempts = self.otp_attempts.get(session_id, 3) - 1
                self.otp_attempts[session_id] = current_attempts
                session["otp_attempts_left"] = current_attempts

                if current_attempts <= 0:
                    session["stage"] = "LOCKED"
                    return "LOCKED", 0
                return "INVALID", current_attempts

            # 3. OTP is correct
            session["stage"] = "AUTHENTICATED"
            session["authenticated"] = True
            session["download_token"] = str(uuid.uuid4())
            return "AUTHENTICATED", self.otp_attempts.get(session_id, 3)

    def resend_otp(self, session_id: str, new_otp: str = "123456") -> Optional[Dict[str, Any]]:
        """Invalidate old OTP and reset 180s timer and 3-attempt budget."""
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return None
            now = time.time()
            session["otp"] = new_otp
            session["otp_issued_at"] = now
            session["otp_expires_at"] = now + 180
            session["otp_attempts_left"] = 3
            session["stage"] = "OTP_SENT"
            self.otp_attempts[session_id] = 3
            self.otp_timer[session_id] = now
            return session


# Global singleton portal state instance
portal_state = MockPortalState()
