"""
Saral AI — Domain Allowlist Route Interceptor
File: backend/app/worker/allowlist.py

Intercepts all outbound browser network traffic in Playwright contexts,
strictly aborting any requests targeting non-allowlisted domains.
"""

import logging
from typing import Any, Callable, List, Optional, Set
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_DOMAINS = [
    "localhost",
    "127.0.0.1",
    "mock-portal.local",
    "uidai.gov.in",
    "myaadhaar.uidai.gov.in",
    "supabase.co",
    "rsftbslckmdkynprmpin.supabase.co",
]


class SecurityPolicyViolation(Exception):
    """Raised when an outbound URL fails domain allowlist checks."""
    pass


class DomainAllowlistInterceptor:
    """Route interceptor enforcing domain allowlist policies on Playwright contexts."""

    def __init__(self, allowed_domains: Optional[List[str]] = None):
        self.allowed_domains: List[str] = [
            d.lower().strip() for d in (allowed_domains or DEFAULT_ALLOWED_DOMAINS)
        ]
        self.blocked_urls: List[str] = []
        self.allowed_urls: List[str] = []

    def is_url_allowed(self, url: str) -> bool:
        """Check whether a given URL conforms to the allowlist.

        Permits:
        - Network URLs with scheme 'http' or 'https' whose hostname matches:
          * Exact host match (e.g. 'localhost', '127.0.0.1', 'uidai.gov.in')
          * Subdomains (e.g. 'myaadhaar.uidai.gov.in' under 'uidai.gov.in')
        - Internal browser schemes: 'data:', 'blob:', 'about:'

        Strictly rejects:
        - Non-HTTP schemes (e.g. 'gopher://', 'file://', 'ftp://', 'ldap://')
          even if targeting allowlisted hostnames (SSRF/smuggling defense).
        """
        if not url:
            return False

        url_lower = url.lower()
        if url_lower.startswith("data:") or url_lower.startswith("blob:") or url_lower.startswith("about:"):
            return True

        try:
            parsed = urlparse(url)
            if parsed.scheme.lower() not in ("http", "https"):
                return False

            hostname = parsed.hostname
            if not hostname:
                return False
            hostname = hostname.lower()

            for allowed in self.allowed_domains:
                if hostname == allowed:
                    return True
                if hostname.endswith("." + allowed):
                    return True

            return False
        except Exception:
            return False

    def assert_url_allowed(self, url: str) -> None:
        """Assert that a URL is allowed or raise SecurityPolicyViolation."""
        if not self.is_url_allowed(url):
            raise SecurityPolicyViolation(f"Unauthorized destination: {url}")

    async def handle_route(self, route: Any, request: Any = None) -> None:
        """Handle Playwright route event.

        Args:
            route: Playwright Route object (or duck-typed test route)
            request: Playwright Request object (or route.request)
        """
        req = request or getattr(route, "request", None)
        url = req.url if req else getattr(route, "url", "")

        if self.is_url_allowed(url):
            self.allowed_urls.append(url)
            if hasattr(route, "continue_"):
                await route.continue_()
            elif hasattr(route, "resume"):
                await route.resume()
        else:
            self.blocked_urls.append(url)
            logger.warning("Blocked outbound request to non-allowlisted host: %s", url)
            if hasattr(route, "abort"):
                await route.abort("blockedbyclient")

    async def attach_to_context(self, context: Any) -> None:
        """Attach route handler to a Playwright BrowserContext."""
        if hasattr(context, "route"):
            await context.route("**/*", self.handle_route)
            logger.info("Domain allowlist route interceptor attached for domains: %s", self.allowed_domains)


class DomainAllowlist(DomainAllowlistInterceptor):
    """Alias for DomainAllowlistInterceptor for brevity and backward-compatibility."""
    pass
