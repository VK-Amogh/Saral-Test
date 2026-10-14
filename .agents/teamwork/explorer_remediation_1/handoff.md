# Handoff Report: Investigation and Surgical Remediation for Finding 1 (Allowlist Scheme Validation)

**Agent Identity:** `explorer_remediation_1`  
**Working Directory:** `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\explorer_remediation_1\`  
**Target:** Finding 1 from `reviewer_gate_2` — SSRF & Protocol Smuggling via Missing Scheme Validation in `backend/app/worker/allowlist.py`  
**Date:** 2026-10-13  
**Status:** COMPLETE (Ready for Implementer)  

---

## 1. Observation

1. **Vulnerability in `backend/app/worker/allowlist.py` (Lines 52–71):**
   ```python
   # backend/app/worker/allowlist.py: lines 52-71
   url_lower = url.lower()
   if url_lower.startswith("data:") or url_lower.startswith("blob:") or url_lower.startswith("about:"):
       return True

   try:
       parsed = urlparse(url)
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
   ```
   Direct observation: `is_url_allowed` parses `url` using `urlparse(url)` and immediately checks `parsed.hostname` against `self.allowed_domains` without verifying `parsed.scheme`.

2. **Reproduction Command & Output:**
   Command executed:
   ```bash
   uv run python -c "from backend.app.worker.allowlist import DomainAllowlistInterceptor; i = DomainAllowlistInterceptor(); print(i.is_url_allowed('gopher://127.0.0.1:6379/_flushall'))"
   ```
   Output:
   ```text
   True
   ```
   For `gopher://127.0.0.1:6379/_flushall`:
   - `parsed.scheme` is `"gopher"`
   - `parsed.hostname` is `"127.0.0.1"`
   Because `"127.0.0.1"` is an allowlisted domain in `DEFAULT_ALLOWED_DOMAINS`, `is_url_allowed()` erroneously evaluates to `True`.
   Similarly:
   - `file://127.0.0.1/etc/passwd` evaluates to `True`
   - `ftp://127.0.0.1/upload` evaluates to `True`
   - `dict://127.0.0.1:11211/stat` evaluates to `True`

3. **Current Test Coverage in `backend/app/worker/test_worker.py` (Lines 158–198):**
   Existing allowlist unit tests verify exact domains (`https://uidai.gov.in/ecosystem`, `http://localhost:8001/login`, `http://127.0.0.1:8000/health`), genuine subdomains (`https://myaadhaar.uidai.gov.in/portal`), unauthorized external domains (`https://evil-unauthorized-tracker.com/phishing`), phishing subdomain deceptions (`https://uidai.gov.in.evilattacker.com/steal`), and internal browser schemes (`data:`, `blob:`).
   There is currently **zero test coverage** asserting that non-HTTP schemes targeting allowlisted hosts (`127.0.0.1` or `localhost`) are blocked.

4. **Baseline Test Suite Status:**
   - `uv run --with pytest pytest backend/app/worker/test_worker.py -v`: 28 passed in 1.46s.
   - `uv run --with pytest pytest backend/tests/test_adversarial_challenges.py -v`: 89 passed in 0.18s.
   - `uv run python run_e2e_tests.py`: All 84 tests across 4 tiers passed in 4.51s.

---

## 2. Logic Chain

1. **Attack Vector Analysis:**
   - In automated Playwright Chromium instances, route interception (`context.route("**/*")`) captures all browser network events.
   - If a malicious page, redirect, or SSRF payload triggers navigation or resource loading targeting `gopher://127.0.0.1:6379/...` or `file://127.0.0.1/...`, the allowlist checks `parsed.hostname`. Because `127.0.0.1` and `localhost` are permitted (necessary for local backend and mock portal communication), the request is continued rather than aborted.
   - This creates an SSRF and protocol smuggling risk where Chromium can be leveraged to interact with internal services or read local files.

2. **Scheme Filtering Design:**
   - Web network traffic to allowlisted domains must strictly use standard HTTP/HTTPS schemes: `parsed.scheme.lower() in ("http", "https")`.
   - Internal browser pseudo-schemes (`data:`, `blob:`, `about:`) are used for in-memory rendering (e.g. CAPTCHA images, generated blobs, empty frames) and do not initiate external network connections; they remain permitted via the existing prefix checks (`url_lower.startswith(...)`).
   - If a URL is not a browser pseudo-scheme, `parsed.scheme.lower()` must be checked before evaluating the hostname:
     ```python
     if parsed.scheme.lower() not in ("http", "https"):
         return False
     ```
   - If `parsed.scheme` is empty (e.g. `""`, `"not_a_valid_url"`, or protocol-relative `"//127.0.0.1"`), it is rejected.
   - If `parsed.scheme` is non-HTTP (e.g. `"gopher"`, `"file"`, `"ftp"`, `"dict"`, `"ldap"`, `"javascript"`), it is rejected immediately, even if `parsed.hostname` is `"127.0.0.1"` or `"localhost"`.

3. **Compatibility Verification:**
   - All genuine application URLs (UIDAI portal, mock portal, Supabase storage, local backend health/task endpoints) use `http://` or `https://`.
   - Case insensitivity is preserved via `.lower()`.
   - In-memory test execution confirmed that 100% of existing test cases continue to pass with this enforcement.

---

## 3. Caveats

- **WebSocket Schemes (`ws://` / `wss://`):** The Playwright route interceptor (`DomainAllowlistInterceptor`) governs browser page network requests. The worker's WebSocket connection to the backend `/internal/worker` is established in Python (`backend/app/worker/client.py`) using `websockets.connect()` and does not traverse the browser route interceptor. Therefore, restricting the interceptor to `("http", "https")` has no impact on WebSocket functionality.
- **Scope Restriction:** As an explorer agent, this report provides read-only analysis and proposed patches. The implementer must apply the patches and verify them against the full test suite.

---

## 4. Conclusion & Recommended Surgical Patches

### Patch 1: `backend/app/worker/allowlist.py`

**Target File:** `backend/app/worker/allowlist.py`  
**Target Lines:** 41–72  
**Action:** Enforce `parsed.scheme.lower() in ("http", "https")` and update docstring.

```python
<<<< BEFORE (lines 41-72)
    def is_url_allowed(self, url: str) -> bool:
        """Check whether a given URL's hostname conforms to the allowlist.

        Permits:
        - Exact host match (e.g. 'localhost', '127.0.0.1', 'uidai.gov.in')
        - Subdomains (e.g. 'myaadhaar.uidai.gov.in' under 'uidai.gov.in')
        - Scheme 'data:' or 'blob:' for internal browser memory rendering
        """
        if not url:
            return False

        url_lower = url.lower()
        if url_lower.startswith("data:") or url_lower.startswith("blob:") or url_lower.startswith("about:"):
            return True

        try:
            parsed = urlparse(url)
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
==== AFTER
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
>>>>
```

---

### Patch 2: `backend/app/worker/test_worker.py`

**Target File:** `backend/app/worker/test_worker.py`  
**Target Lines:** 23 (imports) and line 198 (new unit test function)  
**Action:** Import `SecurityPolicyViolation` and add test `test_allowlist_blocks_non_http_schemes_on_allowlisted_hosts`.

```python
<<<< BEFORE (line 23)
from backend.app.worker.allowlist import DomainAllowlistInterceptor
==== AFTER
from backend.app.worker.allowlist import DomainAllowlistInterceptor, SecurityPolicyViolation
>>>>
```

```python
<<<< BEFORE (after line 197)
def test_allowlist_permits_data_and_blob_urls():
    """Allowlist permits internal browser rendering schemes data: and blob:."""
    interceptor = DomainAllowlistInterceptor(["uidai.gov.in"])
    assert interceptor.is_url_allowed("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA") is True
    assert interceptor.is_url_allowed("blob:http://localhost/1234") is True


@pytest.mark.asyncio
==== AFTER
def test_allowlist_permits_data_and_blob_urls():
    """Allowlist permits internal browser rendering schemes data: and blob:."""
    interceptor = DomainAllowlistInterceptor(["uidai.gov.in"])
    assert interceptor.is_url_allowed("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA") is True
    assert interceptor.is_url_allowed("blob:http://localhost/1234") is True


def test_allowlist_blocks_non_http_schemes_on_allowlisted_hosts():
    """Allowlist strictly blocks non-HTTP/HTTPS schemes even on allowlisted domains (SSRF/smuggling defense)."""
    interceptor = DomainAllowlistInterceptor(["uidai.gov.in", "localhost", "127.0.0.1"])
    # Gopher protocol smuggling targeting local Redis or internal daemons
    assert interceptor.is_url_allowed("gopher://127.0.0.1:6379/_flushall") is False
    assert interceptor.is_url_allowed("gopher://localhost:6379/_flushall") is False

    # File scheme local filesystem reads
    assert interceptor.is_url_allowed("file://127.0.0.1/etc/passwd") is False
    assert interceptor.is_url_allowed("file://localhost/etc/passwd") is False
    assert interceptor.is_url_allowed("file:///etc/passwd") is False

    # FTP, dict, and LDAP protocols
    assert interceptor.is_url_allowed("ftp://127.0.0.1:21/exploit") is False
    assert interceptor.is_url_allowed("ftp://localhost:21/exploit") is False
    assert interceptor.is_url_allowed("dict://127.0.0.1:11211/stat") is False
    assert interceptor.is_url_allowed("ldap://127.0.0.1:389/test") is False

    # Verify assert_url_allowed raises SecurityPolicyViolation
    with pytest.raises(SecurityPolicyViolation):
        interceptor.assert_url_allowed("gopher://127.0.0.1:6379/_flushall")
    with pytest.raises(SecurityPolicyViolation):
        interceptor.assert_url_allowed("file://127.0.0.1/etc/passwd")

    # Legitimate HTTP/HTTPS endpoints remain allowed
    assert interceptor.is_url_allowed("http://127.0.0.1:8000/health") is True
    assert interceptor.is_url_allowed("https://uidai.gov.in/ecosystem") is True


@pytest.mark.asyncio
>>>>
```

---

### Patch 3 (Supplementary): `backend/tests/test_adversarial_challenges.py`

**Target File:** `backend/tests/test_adversarial_challenges.py`  
**Target Lines:** 343–348  
**Action:** Add `gopher://127.0.0.1:6379/_flushall` and `file://127.0.0.1/etc/passwd` to `malicious_url` parametrized test cases.

```python
<<<< BEFORE (lines 343-348)
        # Scheme attacks targeting unauthorized external hosts
        "file:///etc/passwd",
        "file:///C:/Windows/win.ini",
        "gopher://attacker.com:6379/_flushall",
        "ftp://attacker.com/leak",
==== AFTER
        # Scheme attacks targeting unauthorized external hosts
        "file:///etc/passwd",
        "file:///C:/Windows/win.ini",
        "gopher://attacker.com:6379/_flushall",
        "ftp://attacker.com/leak",
        # Scheme attacks targeting allowlisted internal hosts (SSRF defense)
        "gopher://127.0.0.1:6379/_flushall",
        "file://127.0.0.1/etc/passwd",
        "ftp://127.0.0.1/leak",
>>>>
```

---

## 5. Verification Method

Once the implementer applies the patches above, verify using the following commands:

1. **Verify Scheme Rejection Directly in Python:**
   ```bash
   uv run python -c "from backend.app.worker.allowlist import DomainAllowlistInterceptor; i = DomainAllowlistInterceptor(); assert i.is_url_allowed('gopher://127.0.0.1:6379/_flushall') is False; assert i.is_url_allowed('file://127.0.0.1/etc/passwd') is False; assert i.is_url_allowed('http://127.0.0.1:8000/health') is True; assert i.is_url_allowed('https://uidai.gov.in/ecosystem') is True; print('Scheme validation verified!')"
   ```
   **Pass Condition:** Prints `"Scheme validation verified!"` and exits with code 0.

2. **Run Worker Test Suite (including new test):**
   ```bash
   uv run --with pytest pytest backend/app/worker/test_worker.py -v
   ```
   **Pass Condition:** 29 passed in under 2 seconds.

3. **Run Adversarial Security Test Suite:**
   ```bash
   uv run --with pytest pytest backend/tests/test_adversarial_challenges.py -v
   ```
   **Pass Condition:** 92 passed in under 1 second.

4. **Run Standalone E2E Test Suite (All 4 Tiers):**
   ```bash
   uv run python run_e2e_tests.py
   ```
   **Pass Condition:** 84/84 tests passed (100% success rate).
