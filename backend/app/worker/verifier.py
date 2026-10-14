"""
Saral AI — 5-Point Document Security Verifier
File: backend/app/worker/verifier.py

Validates intercepted documents prior to storage and completion:
1. Header: starts with %PDF-
2. Size: between 100 bytes and 5 MB
3. Structure: valid %%EOF marker and pypdf page/trailer validation
4. Security: zero /JavaScript, /JS, or /Launch actions
5. Integrity: SHA-256 cryptographic digest calculation and encryption check
"""

from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
from typing import Optional, Union

try:
    import pypdf
    from pypdf.generic import DictionaryObject
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False


@dataclass
class VerifierResult:
    """Outcome of 5-point document security inspection."""
    is_valid: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    sha256: Optional[str] = None
    size_bytes: int = 0
    pdf_encrypted: bool = False


class DocumentValidationError(Exception):
    """Raised when a document fails security or structural verification."""
    def __init__(self, error_code: str, message: str, size_bytes: int = 0):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.size_bytes = size_bytes


def verify_document_security(
    content: bytes,
    min_size_bytes: int = 100,
    max_size_mb: int = 5
) -> VerifierResult:
    """Execute 5-point document security verification on in-memory bytes.

    Args:
        content: Raw binary payload of the downloaded document.
        min_size_bytes: Minimum permissible file size (default 100 bytes).
        max_size_mb: Maximum permissible file size in megabytes (default 5 MB).

    Returns:
        VerifierResult: Structured result indicating validation success or failure reason.
    """
    size = len(content)

    # Stage 1: %PDF- Magic Byte Header Check
    if not content.startswith(b"%PDF-"):
        return VerifierResult(
            is_valid=False,
            error_code="INVALID_PDF_HEADER",
            error_message="Payload does not start with %PDF- header",
            size_bytes=size
        )

    # Stage 2: Size Limits (min_size_bytes to max_size_mb)
    if size < min_size_bytes:
        return VerifierResult(
            is_valid=False,
            error_code="TRUNCATED_PDF",
            error_message=f"PDF payload is too small or truncated ({size} bytes < {min_size_bytes} bytes)",
            size_bytes=size
        )

    max_bytes = max_size_mb * 1024 * 1024
    if size > max_bytes:
        return VerifierResult(
            is_valid=False,
            error_code="OVERSIZE_PDF",
            error_message=f"PDF size {size} exceeds max threshold {max_size_mb}MB",
            size_bytes=size
        )

    # Stage 3: PDF trailer/xref marker and structural syntax
    if b"%%EOF" not in content:
        return VerifierResult(
            is_valid=False,
            error_code="MALFORMED_PDF_TRAILER",
            error_message="Missing %%EOF marker in PDF payload",
            size_bytes=size
        )

    is_encrypted = b"/Encrypt" in content

    if PYPDF_AVAILABLE:
        try:
            reader = pypdf.PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                is_encrypted = True
            else:
                if len(reader.pages) < 1:
                    return VerifierResult(
                        is_valid=False,
                        error_code="EMPTY_PDF_DOCUMENT",
                        error_message="PDF contains 0 valid renderable pages",
                        size_bytes=size
                    )
        except Exception as e:
            # If structural parsing fails completely
            return VerifierResult(
                is_valid=False,
                error_code="MALFORMED_PDF_STRUCTURE",
                error_message=f"Corrupt or unreadable PDF structure: {str(e)}",
                size_bytes=size
            )

    # Stage 4: Malicious Action Checks (/JavaScript, /JS, /Launch)
    if b"/JavaScript" in content or b"/JS" in content:
        return VerifierResult(
            is_valid=False,
            error_code="MALICIOUS_PDF_JAVASCRIPT",
            error_message="Forbidden /JavaScript action dictionary detected",
            size_bytes=size
        )

    if b"/Launch" in content:
        return VerifierResult(
            is_valid=False,
            error_code="MALICIOUS_PDF_LAUNCH",
            error_message="Forbidden /Launch action dictionary detected",
            size_bytes=size
        )

    # Stage 5: Hash & Encryption Determination
    digest = hashlib.sha256(content).hexdigest()

    return VerifierResult(
        is_valid=True,
        sha256=digest,
        size_bytes=size,
        pdf_encrypted=is_encrypted
    )


class DocumentVerifier:
    """High-level document verifier class for file paths or binary streams."""

    def __init__(self, min_size_bytes: int = 100, max_size_mb: int = 5):
        self.min_size_bytes = min_size_bytes
        self.max_size_mb = max_size_mb

    def verify_file(self, file_path: Union[str, Path]) -> VerifierResult:
        """Verify document stored at local filesystem path."""
        path = Path(file_path)
        if not path.is_file():
            return VerifierResult(
                is_valid=False,
                error_code="FILE_NOT_FOUND",
                error_message=f"File at {file_path} does not exist"
            )
        content = path.read_bytes()
        return verify_document_security(content, self.min_size_bytes, self.max_size_mb)

    def verify(self, target: Union[bytes, str, Path]) -> VerifierResult:
        """Verify binary bytes or file path."""
        if isinstance(target, bytes):
            return verify_document_security(target, self.min_size_bytes, self.max_size_mb)
        return self.verify_file(target)
