"""
Playwright Browser Automation Worker Package for Saral AI.
"""

from .verifier import DocumentVerifier, VerifierResult, verify_document_security
from .allowlist import DomainAllowlistInterceptor, DEFAULT_ALLOWED_DOMAINS
from .client import WorkerWebSocketClient
from .runner import AadhaarDownloadAutomationRunner, AutomationTaskError

__version__ = "0.1.0"

__all__ = [
    "DocumentVerifier",
    "VerifierResult",
    "verify_document_security",
    "DomainAllowlistInterceptor",
    "DEFAULT_ALLOWED_DOMAINS",
    "WorkerWebSocketClient",
    "AadhaarDownloadAutomationRunner",
    "AutomationTaskError",
]
