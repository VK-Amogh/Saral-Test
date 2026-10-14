"""PII and Biometric Scrubber with Verhoeff Dihedral D5 algorithm and logging filter."""

import logging
import re
from typing import Any

# ---------------------------------------------------------------------------
# Verhoeff Dihedral D5 Algorithm Implementation
# ---------------------------------------------------------------------------

D_TABLE = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]

P_TABLE = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]

INV_TABLE = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def validate_verhoeff(num_str: str) -> bool:
    """Validate a number string using the Verhoeff Dihedral D5 check digit algorithm."""
    digits = [int(c) for c in num_str if c.isdigit()]
    if not digits:
        return False
    c = 0
    for i, digit in enumerate(reversed(digits)):
        c = D_TABLE[c][P_TABLE[i % 8][digit]]
    return c == 0


def compute_verhoeff_checksum(num_str: str) -> int:
    """Calculate the Verhoeff checksum digit to append to a number string."""
    digits = [int(c) for c in num_str if c.isdigit()]
    c = 0
    for i, digit in enumerate(reversed(digits)):
        c = D_TABLE[c][P_TABLE[(i + 1) % 8][digit]]
    return INV_TABLE[c]


def generate_valid_aadhaar(prefix_11_digits: str = "23456789012") -> str:
    """Generate a syntactically valid 12-digit Aadhaar number using Verhoeff."""
    cs = compute_verhoeff_checksum(prefix_11_digits)
    return f"{prefix_11_digits}{cs}"


# ---------------------------------------------------------------------------
# PII Scrubber
# ---------------------------------------------------------------------------

def scrub_pii(text: str) -> str:
    """Scrub Aadhaar/VID, phone numbers, emails, biometric terms, and OTPs."""
    if not text:
        return ""
    scrubbed = text

    # 1. 16-digit Virtual ID (VID): \d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}
    def vid_replacer(m: re.Match) -> str:
        raw = re.sub(r"[ -]", "", m.group(0))
        if len(raw) == 16:
            return f"XXXX-XXXX-{raw[-4:]}"
        return m.group(0)

    scrubbed = re.sub(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b", vid_replacer, scrubbed)

    # 2. 12-digit Aadhaar numbers: validate with Verhoeff before masking
    def aadhaar_replacer(m: re.Match) -> str:
        raw = re.sub(r"[ -]", "", m.group(0))
        if len(raw) == 12 and validate_verhoeff(raw):
            return f"XXXX-XXXX-{raw[-4:]}"
        return m.group(0)

    scrubbed = re.sub(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b", aadhaar_replacer, scrubbed)

    # 3. Indian Phone numbers (e.g. +91 9876543210, 9876543210)
    scrubbed = re.sub(r"(?:\+91[ -]?)?[6-9]\d{9}\b", "[REDACTED_PHONE]", scrubbed)

    # 4. Email addresses
    scrubbed = re.sub(
        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
        "[REDACTED_EMAIL]",
        scrubbed
    )

    # 5. Biometric references (fingerprint, iris, retina, biometrics)
    scrubbed = re.sub(
        r"\b(fingerprint|iris|retina|biometrics?)\b",
        "[REDACTED_BIOMETRIC]",
        scrubbed,
        flags=re.IGNORECASE
    )

    # 6. OTPs near trigger words (otp, code, pin)
    scrubbed = re.sub(
        r"(?i)\b(otp|code|pin)\b\s*(?:is|:)?\s*(\d{4,8})\b",
        r"\1 [REDACTED_OTP]",
        scrubbed
    )

    return scrubbed


# ---------------------------------------------------------------------------
# Redacting Logging Filter
# ---------------------------------------------------------------------------

class RedactingLogFilter(logging.Filter):
    """Logging filter that scrubs PII, credentials, tokens, and authorization headers from all logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._redact(a) if isinstance(a, str) else a for a in record.args)

        return True

    def _redact(self, message: str) -> str:
        # First apply general PII scrubber
        scrubbed = scrub_pii(message)

        # Redact Authorization Bearer tokens
        scrubbed = re.sub(
            r"(?i)(Bearer\s+)[A-Za-z0-9_\-\.]{10,}",
            r"\1[REDACTED_TOKEN]",
            scrubbed
        )

        # Redact generic authorization / token headers
        scrubbed = re.sub(
            r"(?i)(Authorization:\s*)[^\r\n]+",
            r"\1Bearer [REDACTED_TOKEN]",
            scrubbed
        )

        return scrubbed
