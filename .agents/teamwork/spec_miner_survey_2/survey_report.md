# Specification Report: Mock Government Portal & Playwright Automation Worker

**Document:** `survey_report.md`  
**Version:** 1.0  
**Author:** spec_miner_survey_2 (Worker & Mock Portal Spec Miner)  
**Date:** 2026-10-13  
**Status:** Completed  
**Sources:** `ORIGINAL_REQUEST.md`, `SARAL_AI_IMPLEMENTATION_PLAN.md` (Sections 1–8, 11, 14, 16, 17), `rules.md` (R-SEC, R-ARCH, R-TEST, R-REAL).

---

## 1. Executive Summary

This report establishes the authoritative, production-grade specification for two critical subsystems of the **Saral AI** architecture:
1. **Mock Government Portal (`mock_portal/`)**: A self-contained, deterministic FastAPI web application designed to simulate official Indian government identity portals (specifically modeling the UIDAI e-Aadhaar download journey). It replicates the multi-step identity verification flow (Aadhaar/VID input → dynamic CAPTCHA challenge → 6-digit OTP verification → PDF generation) and provides simulation switches for ten discrete failure modes without incurring costs, legal risks, or rate limits against real public infrastructure.
2. **Playwright Headless Browser Worker (`backend/app/worker/` or `worker/`)**: An isolated, hardened Python automation daemon utilizing Playwright with headless Chromium. The worker connects outbound to the FastAPI backend via an authenticated WebSocket (`WS /internal/worker`), enforces strict network route-level domain allowlisting, isolates each browser context in ephemeral storage, executes deterministic DOM interactions, relays sensitive inputs (CAPTCHA images and OTP secrets) purely in memory, intercepts downloads, subjects files to a 5-point document security verification pipeline, and uploads verified documents to private Supabase Storage.

---

## 2. Component Specification: Mock Government Portal (`mock_portal/`)

### 2.1 Architectural Context & Purpose
- **Root Directory:** `d:\Startup\Saral Ai\Saral_app\mock_portal/`
- **Runtime:** Python 3.12, FastAPI, Uvicorn, Jinja2, Pillow (PIL), ReportLab / PyMuPDF.
- **Port & Host:** Default `http://127.0.0.1:8001` (configurable via `MOCK_PORTAL_PORT` and `MOCK_PORTAL_HOST`).
- **Core Strategy:** Under Section 1 & Section 14 (Rule 9) of `SARAL_AI_IMPLEMENTATION_PLAN.md`, all automated development, CI pipelines, and end-to-end integration tests must target `mock_portal/` prior to any real portal feasibility gate.

### 2.2 Portal State Machine & Session Lifecycle
The mock portal maintains ephemeral session state in memory (keyed by `session_id` UUID or cryptographically signed session cookie).

```
   [GET /] ───────► (STATE: LANDING)
                           │
       Submit UID + CAPTCHA│
                           ▼
                 [Valid CAPTCHA & UID?]
                     ├── NO  ──► Re-render Landing with error, increment captcha_attempts
                     └── YES ──► (STATE: OTP_SENT)
                                       │
                         Submit 6-digit OTP
                                       ▼
                             [Valid & Non-Expired?]
                                 ├── Wrong (<3 attempts) ──► Re-render OTP page with error
                                 ├── Wrong (>=3 attempts) ─► (STATE: LOCKED / FAILED)
                                 ├── Expired (>180s) ──────► (STATE: EXPIRED)
                                 └── Correct ──────────────► (STATE: AUTHENTICATED)
                                                                   │
                                                            Download PDF
                                                                   ▼
                                                          (STATE: COMPLETED)
```

### 2.3 HTTP Endpoints & API Contract

| Route | Method | Content-Type | Parameters / Body | Description & Contract |
|---|---|---|---|---|
| `/` | `GET` | `text/html` | Query: `test_mode` (optional) | Renders the initial Login / Aadhaar entry page. Issues a unique `session_id`. |
| `/captcha` | `GET` | `image/png` | Query: `session_id` | Generates a distorted 6-character alphanumeric image. Headers: `Cache-Control: no-store, no-cache, must-revalidate`. |
| `/login` | `POST` | `application/x-www-form-urlencoded` or `multipart/form-data` | Body: `uid` (12-digit Aadhaar / 16-digit VID), `captcha` (text), `session_id` | Validates UID and CAPTCHA. On success, transitions session to `OTP_SENT` and redirects to `/verify-otp`. |
| `/verify-otp` | `GET` | `text/html` | Query: `session_id` | Renders the OTP verification screen displaying masked recipient phone number (`******1234`) and countdown timer. |
| `/verify-otp` | `POST` | `application/x-www-form-urlencoded` | Body: `otp` (6 digits), `session_id` | Validates OTP. On success, redirects to `/download` or triggers PDF attachment response. On failure, returns error message and attempt counter. |
| `/resend-otp` | `POST` | `application/x-www-form-urlencoded` | Body: `session_id` | Invalidates old OTP, issues new 6-digit OTP, resets 180-second countdown. |
| `/download` | `GET` | `application/pdf` | Query: `session_id` | Streams the generated PDF file. Headers: `Content-Disposition: attachment; filename="eaadhaar_<masked_uid>.pdf"`. |
| `/health` | `GET` | `application/json` | None | Returns `{"status": "ok", "service": "mock_portal"}`. |

### 2.4 HTML DOM Structure & Stable Selectors
To guarantee deterministic Playwright automation and fulfill Section 16/19 requirements ("Selectors centralised per workflow; fail loudly on change"), the mock portal provides stable semantic DOM IDs:

1. **Login Page (`/`):**
   - `<input id="uid_input" name="uid" type="text" maxlength="16" placeholder="Enter Aadhaar Number / VID" required />`
   - `<img id="captcha_img" src="/captcha?session_id=..." alt="CAPTCHA Challenge" />`
   - `<button id="btn_refresh_captcha" type="button">Refresh</button>`
   - `<input id="captcha_input" name="captcha" type="text" maxlength="6" autocomplete="off" required />`
   - `<button id="btn_send_otp" type="submit">Send OTP</button>`
   - `<div id="error_msg" class="alert-error" role="alert">...</div>` (rendered conditionally on error)

2. **OTP Verification Page (`/verify-otp`):**
   - `<span id="masked_phone_hint">******1234</span>`
   - `<input id="otp_input" name="otp" type="password" inputmode="numeric" maxlength="6" autocomplete="off" required />`
   - `<button id="btn_verify_download" type="submit">Verify & Download</button>`
   - `<button id="btn_resend_otp" type="button">Resend OTP</button>`
   - `<span id="timer_countdown">180</span>`
   - `<div id="error_msg" class="alert-error" role="alert">...</div>`

### 2.5 CAPTCHA Generation Engine
- **Character Set:** Uppercase letters (`A-Z`) and digits (`0-9`), excluding ambiguous glyphs (`O`, `0`, `I`, `1`) to avoid optical recognition confusion: `23456789ABCDEFGHJKLMNPQRSTUVWXYZ`.
- **Length:** Exactly 6 characters.
- **Visual Distortions:**
  - Background noise: random color arcs, lines, and salt-and-pepper noise points.
  - Character jitter: random rotation (-25° to +25°), randomized font sizing, and vertical baseline offsets.
  - Distortion wave: sine wave displacement applied across horizontal slices.
- **Storage:** Plaintext answer stored in `session_store[session_id].captcha_solution`.
- **Expiry:** Re-generated on every GET request to `/captcha` or upon 3 consecutive invalid entries.

### 2.6 OTP Lifecycle & Retry Engine
- **Format:** Exactly 6 numeric digits (`^\d{6}$`).
- **Default Deterministic Mock OTP:** `123456` (or randomly generated 6-digit integer when `MOCK_RANDOM_OTP=true`).
- **TTL (Time to Live):** 180 seconds (3 minutes) from issuance timestamp.
- **Max Retry Budget:** Exactly 3 attempts (`otp_attempts = 0`, incremented per invalid attempt).
- **Behavior Matrix:**
  - `otp_attempts = 1` or `2`: Returns HTTP 200 with `<div id="error_msg">Invalid OTP. Attempt {n} of 3.</div>`.
  - `otp_attempts >= 3`: Transitions session to `LOCKED`. Returns HTTP 400/403 with `<div id="error_msg">Maximum OTP attempts exceeded. Session locked.</div>`.
  - `now() > otp_expires_at`: Returns HTTP 400 with `<div id="error_msg">OTP has expired. Please request a new OTP.</div>`.

### 2.7 Failure Mode Simulation Engine
The mock portal incorporates deterministic failure switches via **Special UID Values** or **HTTP Query Parameters / Headers** (`X-Mock-Mode`):

| Test Mode ID | Trigger Mechanism (UID / Query) | Portal Behavior & Failure Simulation | Expected System Consequence |
|---|---|---|---|
| `HAPPY_PATH` | Normal 12-digit UID (e.g. `123456789012`) | Standard successful flow: CAPTCHA passes, OTP `123456` passes, valid password-protected PDF returned. | Task transitions `DOWNLOADING → VERIFYING → COMPLETED`. |
| `WRONG_CAPTCHA` | `uid="000000000001"` or `?mode=wrong_captcha` | Rejects submitted CAPTCHA regardless of input. Shows `#error_msg`. | Worker retries CAPTCHA up to 3 times before failing task. |
| `EXPIRED_OTP` | `uid="000000000002"` or `?mode=expired_otp` | Issues OTP with `otp_expires_at = now() - 1s`. Any OTP input results in "OTP has expired". | Worker reports `EXPIRED`. Task transitions to `EXPIRED`. |
| `WRONG_OTP_RETRY` | Standard UID + incorrect OTP input | Shows attempt warning. On 3rd failure locks session. | Worker relays attempt count back to user; on 3rd failure transitions to `FAILED`. |
| `CORRUPT_PDF` | `uid="000000000003"` or `?mode=corrupt_pdf` | Streams invalid payload: header has random garbage or truncated xref table. | Document verifier catches corruption with `pypdf.errors.PdfStreamError`; task transitions to `FAILED`. |
| `HTML_AS_PDF` | `uid="000000000004"` or `?mode=html_as_pdf` | Returns `Content-Type: application/pdf`, but response body is `<html><body>Server Error 500</body></html>`. | Document verifier rejects missing `%PDF-` header; task transitions to `FAILED`. |
| `OVERSIZE_PDF` | `uid="000000000005"` or `?mode=oversize_pdf` | Streams generated PDF padded with zero-byte bloat to 12 MB (> 5 MB limit). | Document verifier rejects file size exceeding 5 MB limit; task transitions to `FAILED`. |
| `MALICIOUS_PDF` | `uid="000000000006"` or `?mode=malicious_pdf` | Injects `/JavaScript` or `/Launch` action dictionary into PDF catalog. | Document verifier detects forbidden active code; raises security exception; task transitions to `FAILED`. |
| `PAGE_TIMEOUT` | `uid="000000000007"` or `?mode=timeout` | Endpoint sleeps for 45 seconds before responding. | Playwright worker hits 30s navigation/element timeout; triggers bounded retry (max 2 retries) then `FAILED`. |
| `CHANGED_SELECTOR`| `uid="000000000008"` or `?mode=broken_dom` | Renders OTP page with `<input id="unexpected_otp_field">` instead of `#otp_input`. | Playwright locator times out; worker logs descriptive DOM selector mismatch error; task fails cleanly. |
| `FOREIGN_REDIRECT`| `uid="000000000009"` or `?mode=foreign_redirect` | Page sends HTTP 302 redirect to `https://evil-unauthorized-tracker.com`. | Route allowlist interceptor detects non-allowlisted host and immediately aborts navigation. |

---

## 3. Component Specification: Playwright Headless Browser Worker

### 3.1 Architectural Context & Topology
- **Location:** `backend/app/worker/` (or dedicated `worker/` service root).
- **Execution Environment:** Host machine or dedicated Docker container running Python 3.12 + Playwright + Chromium.
- **Connection Type:** **Outbound Persistent WebSocket** connection initiated by the Worker to the FastAPI backend at `wss://<backend>/internal/worker` (or `ws://127.0.0.1:8000/internal/worker` locally).
- **Authentication:** Authenticated via pre-shared secret: `X-Worker-Secret: <WORKER_SHARED_SECRET>` or `Authorization: Bearer <WORKER_SHARED_SECRET>`.
- **Rationale for Outbound Architecture:**
  1. The worker operates behind NAT / firewalls without requiring exposed public inbound ports.
  2. Free cloud hosting tiers (e.g. Render Free, 512 MB RAM) crash under Chromium execution. Decoupled worker runs on client hardware or dedicated compute while backend remains lightweight.
  3. No task polling required: backend pushes tasks immediately over the open WebSocket.

### 3.2 WebSocket Protocol Specification (`WS /internal/worker`)

All frames transmitted across the internal WebSocket use JSON encoding.

```
Worker                               Backend (/internal/worker)
  │                                               │
  ├─── WS Handshake (Bearer WORKER_SHARED_SECRET) ─►
  ◄─── Handshake Accepted (Connection Registered)─┤
  │                                               │
  │    (Worker awaits job assignments)            │
  ◄─── {"type": "assign_task", "task_id": "...",  │
  │     "workflow": "aadhaar_download", ...} ─────┤
  │                                               │
  ├─── {"type": "task_progress", "progress": 10} ─►
  │                                               │
  ├─── {"type": "challenge_required",             │
  │     "kind": "captcha", "b64_image": ...} ────►
  │                                               │
  ◄─── {"type": "relay_input",                    │
  │     "kind": "captcha", "value": "A1B2C3"} ────┤
  │                                               │
  ├─── {"type": "challenge_required",             │
  │     "kind": "otp", "attempts_left": 3} ──────►
  │                                               │
  ◄─── {"type": "relay_input",                    │
  │     "kind": "otp", "value": "123456"} ────────┤
  │                                               │
  ├─── {"type": "task_progress", "progress": 85} ─►
  │                                               │
  ├─── {"type": "task_completed",                 │
  │     "document_id": "...", "sha256": ...} ────►
  │                                               │
```

#### Message Schemas:

1. **`worker_connect` (Worker → Backend Handshake):**
   ```json
   {
     "type": "worker_register",
     "worker_id": "worker-pc-01",
     "timestamp": "2026-10-13T06:30:00Z",
     "capabilities": ["aadhaar_download", "mock_portal"]
   }
   ```

2. **`assign_task` (Backend → Worker):**
   ```json
   {
     "type": "assign_task",
     "task_id": "b3e34b9e-64d8-4f9e-a89b-89d2d0b51234",
     "user_id": "550e8400-e29b-41d4-a716-446655440000",
     "workflow": "aadhaar_download",
     "parameters": {
       "uid": "123456789012",
       "portal_url": "http://127.0.0.1:8001"
     }
   }
   ```

3. **`task_progress` (Worker → Backend):**
   ```json
   {
     "type": "task_progress",
     "task_id": "b3e34b9e-64d8-4f9e-a89b-89d2d0b51234",
     "status": "RUNNING",
     "message": "Navigating to portal...",
     "progress": 15
   }
   ```

4. **`challenge_required` (Worker → Backend):**
   ```json
   {
     "type": "challenge_required",
     "task_id": "b3e34b9e-64d8-4f9e-a89b-89d2d0b51234",
     "kind": "captcha",
     "prompt": "Enter the characters shown in the image",
     "challenge_data_b64": "iVBORw0KGgoAAAANSUhEUgAA...",
     "expires_at": "2026-10-13T06:33:00Z",
     "attempts_left": 3
   }
   ```

5. **`relay_input` (Backend → Worker):**
   ```json
   {
     "type": "relay_input",
     "task_id": "b3e34b9e-64d8-4f9e-a89b-89d2d0b51234",
     "kind": "captcha",
     "value": "WXYZ89"
   }
   ```

6. **`task_completed` (Worker → Backend):**
   ```json
   {
     "type": "task_completed",
     "task_id": "b3e34b9e-64d8-4f9e-a89b-89d2d0b51234",
     "document_id": "8fa8169e-d31a-42c2-843e-a8bf3df01234",
     "storage_path": "550e8400-e29b-41d4-a716-446655440000/b3e34b9e-64d8-4f9e-a89b-89d2d0b51234.pdf",
     "file_name": "eaadhaar_1234.pdf",
     "size_bytes": 1048576,
     "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
     "pdf_encrypted": true
   }
   ```

7. **`task_failed` (Worker → Backend):**
   ```json
   {
     "type": "task_failed",
     "task_id": "b3e34b9e-64d8-4f9e-a89b-89d2d0b51234",
     "error_code": "WRONG_OTP_LIMIT_EXCEEDED",
     "error_message": "Maximum OTP verification attempts (3) exceeded."
   }
   ```

8. **`cancel_task` (Backend → Worker):**
   ```json
   {
     "type": "cancel_task",
     "task_id": "b3e34b9e-64d8-4f9e-a89b-89d2d0b51234",
     "reason": "User cancelled via application"
   }
   ```

### 3.3 Browser Sandbox & Context Isolation

- **Process-Level Singleton:** Single Playwright Chromium browser instance initialized at worker boot:
  ```python
  browser = await playwright.chromium.launch(
      headless=True,
      args=[
          "--no-sandbox",
          "--disable-setuid-sandbox",
          "--disable-dev-shm-usage",
          "--disable-gpu",
          "--no-first-run",
          "--no-default-browser-check"
      ]
  )
  ```
- **Context-Level Isolation:** Every assigned task creates a strictly isolated `BrowserContext`:
  ```python
  task_temp_dir = tempfile.mkdtemp(prefix=f"saral_task_{task_id}_")
  context = await browser.new_context(
      accept_downloads=True,
      ignore_https_errors=False,  # Set True only in local dev test against mock
      viewport={"width": 1280, "height": 800},
      user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
  )
  ```
- **Zero Cross-Contamination:** No shared cookies, localStorage, indexedDB, cache, or authentication sessions between tasks.
- **Teardown Contract:** In the mandatory `finally` block:
  1. `await page.close()`
  2. `await context.close()`
  3. `shutil.rmtree(task_temp_dir, ignore_errors=True)`
  4. Nullify memory references to in-flight buffers.

### 3.4 Network Route Filtering & Domain Allowlisting

Under Section 8.1 and Section 14 (Rule 3) of `SARAL_AI_IMPLEMENTATION_PLAN.md`, the worker must enforce domain allowlisting at the Playwright network routing layer.

- **Route Hook:**
  ```python
  await context.route("**/*", handle_route)
  ```
- **Enforcement Logic:**
  ```python
  ALLOWED_DOMAINS = ["localhost", "127.0.0.1", "uidai.gov.in", "myaadhaar.uidai.gov.in"]

  async def handle_route(route: Route, request: Request):
      parsed = urlparse(request.url)
      hostname = parsed.hostname
      
      # Match exact domain or wildcard subdomain
      is_allowed = any(
          hostname == allowed or hostname.endswith("." + allowed)
          for allowed in ALLOWED_DOMAINS
      )
      
      if is_allowed:
          await route.continue_()
      else:
          logger.warning("Blocked outbound request to non-allowlisted host: %s", hostname)
          await route.abort("blockedbyclient")
  ```
- **Protection Scope:**
  - Prevents automated browsers from following malicious 302 redirects to phishing/foreign domains.
  - Blocks telemetry scripts, third-party CDNs, ad trackers, and malicious embedded assets.

### 3.5 Automated Interaction Lifecycle: Aadhaar Download Journey

1. **Step 1: Portal Navigation:**
   - Worker navigates to portal entry point: `await page.goto(portal_url, timeout=30000, wait_until="networkidle")`.
   - Bounded retries: Up to 2 retries on connection reset or transient 502/504 errors.
2. **Step 2: Credential Entry & CAPTCHA Extraction:**
   - Worker types UID: `await page.locator("#uid_input").fill(uid)`.
   - Worker locates CAPTCHA element: `captcha_elem = page.locator("#captcha_img")`.
   - **Crucial Invariant:** Worker takes a direct element screenshot:
     ```python
     captcha_bytes = await captcha_elem.screenshot(type="png")
     ```
     *(Note: Worker does NOT make a secondary GET request to `/captcha`, as secondary HTTP fetches regenerate the image on stateful portals and desynchronize the solution).*
   - Worker encodes image to Base64 and dispatches `challenge_required` message over WebSocket.
3. **Step 3: Awaiting & Relaying CAPTCHA Input:**
   - Worker creates an `asyncio.Future` associated with `(task_id, "captcha")`.
   - Waits up to 180 seconds (`timeout=180.0`).
   - On receiving `relay_input`:
     ```python
     await page.locator("#captcha_input").fill(captcha_text)
     del captcha_text  # Immediately delete reference
     await page.locator("#btn_send_otp").click()
     ```
4. **Step 4: Error Detection vs. Transition to OTP:**
   - Worker performs raced wait for `#error_msg` vs `#otp_input`:
     - If `#error_msg` displays "Invalid Captcha":
       - Decrements attempts remaining.
       - If `attempts_left > 0`: takes new screenshot of refreshed `#captcha_img` and repeats `challenge_required`.
       - If `attempts_left <= 0`: reports `task_failed` (`CAPTCHA_ATTEMPTS_EXCEEDED`).
     - If `#otp_input` becomes visible: proceeds to Step 5.
5. **Step 5: OTP Challenge & Submission:**
   - Worker dispatches `challenge_required` for OTP:
     ```json
     {"type": "challenge_required", "kind": "otp", "attempts_left": attempts_left}
     ```
   - Awaits `relay_input` future for OTP.
   - On reception:
     ```python
     await page.locator("#otp_input").fill(otp_value)
     del otp_value  # Immediate scrub
     ```
   - Worker hardening:
     - Tracing, HAR recording, and video recording MUST be disabled.
     - `DEBUG=pw:api` environment variable MUST NOT be set.
     - Worker MUST NOT take screenshots on the OTP screen.
     - OTP is NEVER passed to loggers.
6. **Step 6: OTP Submission & Download Interception:**
   - Worker triggers download via `expect_download`:
     ```python
     async with page.expect_download(timeout=30000) as download_info:
         await page.locator("#btn_verify_download").click()
     download = await download_info.value
     download_target = os.path.join(task_temp_dir, download.suggested_filename)
     await download.save_as(download_target)
     ```
   - If `#error_msg` appears instead of download:
     - Check error text for "Invalid OTP" or "OTP Expired".
     - If retryable: dispatch updated `challenge_required` with decremented attempts.
     - If terminal: dispatch `task_failed`.
   - **Single Download Guarantee:** Any secondary download event triggered is immediately aborted and discarded.

### 3.6 Document Verifier Specification (`DocumentVerifier`)

Section 8.2 of `SARAL_AI_IMPLEMENTATION_PLAN.md` states: *"Only the verifier can move VERIFYING → COMPLETED, and only after file validation passes. An LLM saying 'done' never completes a task."*

The document validation pipeline executes the following checks in strict sequential order:

```
[Raw File in Temp Dir]
         │
         ▼
[1. File Existence & Size Checks] ───────► Fail if size < 10KB or > 5MB
         │
         ▼
[2. Magic Byte Header Check] ────────────► Fail if header != b"%PDF-"
         │
         ▼
[3. pypdf Structural Validation] ────────► Fail if unreadable, corrupt xref, or 0 pages (if unencrypted)
         │
         ▼
[4. Malicious Action Audit] ─────────────► Fail if /JavaScript, /JS, or /Launch dictionaries present
         │
         ▼
[5. Cryptographic Digest (SHA-256)] ─────► Compute hex digest
         │
         ▼
[VERIFICATION PASSED]
```

#### Detailed Verification Steps:
1. **Size Range Validation:**
   - Minimum: 10,240 bytes (10 KB).
   - Maximum: 5,242,880 bytes (5 MB).
   - If outside bounds: raise `DocumentValidationError(f"File size {size} out of range [10KB, 5MB]")`.
2. **Magic Byte Check:**
   - Read first 1024 bytes: verify file starts with `b"%PDF-"`.
   - Blocks disguised HTML error pages, XML, or binary executables.
3. **Syntax & Structure Parsing (`pypdf`):**
   ```python
   reader = pypdf.PdfReader(file_path)
   is_encrypted = reader.is_encrypted
   if not is_encrypted:
       if len(reader.pages) < 1:
           raise DocumentValidationError("PDF contains 0 pages")
   else:
       # Encrypted PDF (Standard e-Aadhaar)
       # Verify document structure and trailer can be read without crashing
       assert reader.trailer is not None
   ```
4. **Malicious Active Code Audit:**
   - Scan all indirect objects in the PDF for active execution triggers:
     - `/JavaScript` and `/JS` (embedded JavaScript execution).
     - `/Launch` (OS executable launching).
     - `/SubmitForm`, `/ImportData` (data exfiltration).
   ```python
   for obj in reader.objects:
       if isinstance(obj, pypdf.generic.DictionaryObject):
           if "/JavaScript" in obj or "/JS" in obj:
               raise MaliciousContentError("Embedded /JavaScript detected")
           if "/Launch" in obj:
               raise MaliciousContentError("Malicious /Launch action detected")
   ```
5. **SHA-256 Cryptographic Hash:**
   - Stream file in 64 KB blocks and calculate `hashlib.sha256().hexdigest()`.

### 3.7 Private Supabase Storage & Persistence Interface

Once the document passes verification:
1. **Storage Path Convention:**
   `documents/<user_id>/<task_id>.pdf`
2. **Upload Execution:**
   - Worker utilizes `SUPABASE_SECRET_KEY` (service role) to upload the file to Supabase Storage:
     ```python
     with open(download_target, "rb") as f:
         supabase.storage.from_("documents").upload(
             path=f"{user_id}/{task_id}.pdf",
             file=f,
             file_options={"content-type": "application/pdf", "upsert": "false"}
         )
     ```
3. **Database Record Persistence:**
   - Insert row into `public.documents`:
     ```sql
     INSERT INTO public.documents (
         user_id,
         task_id,
         doc_type,
         file_name,
         storage_path,
         size_bytes,
         sha256,
         pdf_encrypted,
         delete_after
     ) VALUES (
         :user_id,
         :task_id,
         'aadhaar',
         :file_name,
         :storage_path,
         :size_bytes,
         :sha256,
         :pdf_encrypted,
         NOW() + INTERVAL '24 hours'
     ) RETURNING id;
     ```
4. **Completion Message:**
   Worker transmits `task_completed` over WebSocket with `document_id`, `sha256`, and `storage_path`.

### 3.8 Production Hardening & Sandbox Cleanup Lifecycle
- **Zero Traces / Video / HAR:**
  In production (`APP_ENV=prod`), Playwright's tracing (`context.tracing`), video recording (`record_video_dir`), and HAR capture (`record_har_path`) are strictly omitted.
- **Log Redaction Filter:**
  Worker uses a dedicated `RedactingFilter` attached to the Python `logging` root:
  - Redacts 12-digit Aadhaar / VID regexes.
  - Redacts 6-digit OTP regexes (`\b\d{6}\b`).
  - Redacts `Bearer` tokens and secrets.
- **Guaranteed Cleanup Hook:**
  Every task execution wraps browser actions in:
  ```python
  try:
      ...
  finally:
      if page and not page.is_closed():
          await page.close()
      if context:
          await context.close()
      if task_temp_dir and os.path.exists(task_temp_dir):
          shutil.rmtree(task_temp_dir, ignore_errors=True)
  ```

---

## 4. Features Discovered

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|---|---|---|---|---|---|---|
| 1 | Mock Portal | Portal Landing Page (`GET /`) | Serves login form with Aadhaar/VID input, dynamic CAPTCHA image, and session cookie. | HTTP GET request, query `test_mode` (optional) | HTML page with `#uid_input`, `#captcha_img`, `#btn_send_otp` | Returns 500 on internal template error. | `ORIGINAL_REQUEST.md` R2, Plan §11, §16 |
| 2 | Mock Portal | Dynamic CAPTCHA Generation (`GET /captcha`) | Generates a 6-character distorted PNG CAPTCHA with noise lines and rotation. | `session_id` query param | Image binary (`image/png`), `Cache-Control: no-store` | 400 Bad Request if session is invalid. | Plan §7, §16 |
| 3 | Mock Portal | Credential & CAPTCHA Submission (`POST /login`) | Validates 12-digit UID and CAPTCHA string; initializes OTP generation and 180s timer. | `uid`, `captcha`, `session_id` | 303 Redirect to `/verify-otp` on success | Returns 200 with `#error_msg` if CAPTCHA or UID invalid. | Plan §6, §7, §16 |
| 4 | Mock Portal | OTP Verification Page (`GET /verify-otp`) | Displays OTP input form, masked mobile phone number hint, and timer. | `session_id` | HTML page with `#otp_input`, `#masked_phone_hint`, `#btn_verify_download` | 303 Redirect to `/` if session not in `OTP_SENT` state. | Plan §7, §16 |
| 5 | Mock Portal | OTP Submission & Validation (`POST /verify-otp`) | Validates 6-digit OTP code against session; enforces 3-attempt limit and 180s TTL. | `otp` (6 digits), `session_id` | 303 Redirect to `/download` on success | 200 with `#error_msg` on wrong OTP; 403 on lockout; 400 on expiry. | Plan §6, §7, §16 |
| 6 | Mock Portal | OTP Resend (`POST /resend-otp`) | Invalidates old OTP and generates a fresh 6-digit code with renewed 180s timer. | `session_id` | 303 Redirect back to `/verify-otp` | 400 if session is locked or non-existent. | Plan §16, §17 |
| 7 | Mock Portal | Secure PDF Generation & Serving (`GET /download`) | Streams generated e-Aadhaar PDF with valid header and password protection. | `session_id` | PDF binary (`application/pdf`), `Content-Disposition: attachment` | 403 Forbidden if OTP was not successfully verified. | Plan §8.2, §16 |
| 8 | Mock Portal | Corrupt PDF Simulation | Streams broken PDF payload (corrupt xref or truncated stream) when triggered by test mode. | `uid="000000000003"` or `?mode=corrupt_pdf` | Broken binary payload | Intended failure to test worker verification. | Plan §16 (Mock-portal E2E) |
| 9 | Mock Portal | HTML Masquerading as PDF | Returns HTML error page with `Content-Type: application/pdf`. | `uid="000000000004"` or `?mode=html_as_pdf` | HTML text masquerading as PDF | Intended failure to test worker magic-byte validation. | Plan §16 (Mock-portal E2E) |
| 10 | Mock Portal | Oversize PDF Simulation | Generates oversized PDF payload (> 5 MB, e.g. 12 MB) to trigger size limits. | `uid="000000000005"` or `?mode=oversize_pdf` | Oversized PDF binary | Intended failure to test worker max-size guard. | Plan §16 (Mock-portal E2E) |
| 11 | Mock Portal | Malicious PDF Simulation | Injects active execution dictionaries (`/JavaScript`, `/Launch`) into PDF. | `uid="000000000006"` or `?mode=malicious_pdf` | PDF with active exploit tags | Intended failure to test worker security auditor. | Plan §8.2, §16 |
| 12 | Mock Portal | Slow Response Simulation | Stalls response connection for 45 seconds to trigger worker timeout handling. | `uid="000000000007"` or `?mode=timeout` | Delayed HTTP response | Tests worker timeout and bounded retry handling. | Plan §16 (Mock-portal E2E) |
| 13 | Mock Portal | Changed Selector Simulation | Modifies semantic element IDs on OTP page (e.g. renders `#custom_otp`). | `uid="000000000008"` or `?mode=broken_dom` | HTML with altered DOM selectors | Tests worker error logging and graceful failure on DOM change. | Plan §16, §19 (R-CHROME) |
| 14 | Mock Portal | Foreign Redirect Simulation | Issues HTTP 302 redirect to non-allowlisted third-party domain. | `uid="000000000009"` or `?mode=foreign_redirect` | HTTP 302 Redirect to unauthorized domain | Tests worker route allowlist interception. | Plan §8.1, §16 |
| 15 | Worker | Outbound WebSocket Connection | Connects outbound to `WS /internal/worker` using `WORKER_SHARED_SECRET`. | `WORKER_SHARED_SECRET`, Backend WS URL | Active bi-directional WebSocket session | Backoff reconnection loop on disconnect or server downtime. | ORIGINAL_REQUEST R2, Plan §3, §5 |
| 16 | Worker | Browser Process Initialization | Launches headless Chromium with security flags (`--no-sandbox`, `--disable-gpu`). | Worker startup trigger | Persistent `Browser` instance | Raises `BrowserLaunchError` if Chromium binary missing. | Plan §3, §14 |
| 17 | Worker | Isolated Context per Task | Creates fresh `BrowserContext` with dedicated temp directory per task execution. | `task_id` | Ephemeral `BrowserContext` + temporary directory | Cleans up context and temp directory in `finally`. | ORIGINAL_REQUEST R2, Plan §3, §14 |
| 18 | Worker | Network Route Interception | Intercepts all requests via `context.route("**/*")` to enforce domain allowlist. | Outgoing HTTP/HTTPS requests | Allowed request continuation or `route.abort()` | Aborts unauthorized outbound requests immediately. | Plan §8.1, §16, §17 |
| 19 | Worker | Redirect Abort Protection | Traps and aborts unauthorized HTTP 301/302 redirects to non-allowlisted domains. | Redirect responses | Intercepted & aborted request | Fails task if mandatory portal flow redirects out of allowlist. | Plan §8.1, §16 |
| 20 | Worker | CAPTCHA Element Screenshot | Directly screenshots `#captcha_img` element to capture image bytes in memory. | `#captcha_img` Playwright locator | PNG image bytes (in memory) | Raises `ElementNotFound` if CAPTCHA image fails to load. | Plan §7, §16 |
| 21 | Worker | CAPTCHA Challenge Relay | Transmits Base64 CAPTCHA challenge over WebSocket to broker without persistence. | Image bytes, `task_id` | WS `challenge_required` message | Worker pauses and awaits user input future. | ORIGINAL_REQUEST R2, Plan §7 |
| 22 | Worker | Secure CAPTCHA Fill | Fills `#captcha_input` via `locator.fill()` and immediately discards value reference. | Input value from WebSocket | DOM input filled, value dereferenced | Disables Playwright tracing to prevent leak. | Plan §7, §14 |
| 23 | Worker | OTP Challenge Relay | Dispatches OTP challenge prompt over WebSocket without persisting or logging. | `task_id`, `attempts_left` | WS `challenge_required` message | Pauses worker execution on `asyncio.Future`. | ORIGINAL_REQUEST R2, Plan §7 |
| 24 | Worker | Secure OTP Fill | Injects 6-digit OTP into `#otp_input` via `locator.fill()` and scrubs memory. | 6-digit OTP string | DOM input filled, value dereferenced | Redacting filter ensures OTP never printed to logs. | Plan §7, §14 |
| 25 | Worker | Download Capture Engine | Intercepts single PDF download event via `page.expect_download()` into temp directory. | Download trigger button click | Saved file in `task_temp_dir` | Times out after 30s if download fails to initiate. | ORIGINAL_REQUEST R2, Plan §8.2 |
| 26 | Worker | Single Download Enforcement | Enforces that only one download occurs per task; discards unexpected secondary downloads. | Browser download events | First download retained; extras aborted | Fails task if unexpected secondary download detected. | Plan §8.1, §16 |
| 27 | Worker | Magic Byte Header Check | Verifies file starts with `%PDF-` byte sequence before parsing. | Downloaded file path | Boolean validation result | Raises `DocumentValidationError` on mismatch. | ORIGINAL_REQUEST R2, Plan §8.2 |
| 28 | Worker | Size Boundary Verification | Validates file size is between 10 KB and 5 MB. | File size in bytes | Validation confirmation | Raises `DocumentValidationError` if out of bounds. | Plan §8.2, §16 |
| 29 | Worker | pypdf Structural Parser | Validates PDF trailer, cross-reference table, page count, and encryption state. | File path | Parsed PDF object + `pdf_encrypted` flag | Raises `PdfStreamError` on corrupt structure. | Plan §8.2 |
| 30 | Worker | Malicious Action Scanner | Scans all PDF object dictionaries for forbidden `/JavaScript` or `/Launch` tags. | Parsed `pypdf` objects | Security pass confirmation | Raises `MaliciousContentError` and fails task. | ORIGINAL_REQUEST R2, Plan §8.2 |
| 31 | Worker | SHA-256 Digest Calculation | Computes SHA-256 cryptographic hash of verified PDF stream. | File binary stream | 64-character lowercase hex string | Handled in streaming chunks to conserve RAM. | ORIGINAL_REQUEST R2, Plan §8.2 |
| 32 | Worker | Supabase Storage Uploader | Uploads verified PDF to private bucket `documents/<user_id>/<task_id>.pdf`. | File path, `SUPABASE_SECRET_KEY` | Supabase storage confirmation | Retries on network glitch; fails task on 403/500. | ORIGINAL_REQUEST R2, Plan §4, §8.2 |
| 33 | Worker | Database Document Insertion | Inserts document metadata record into `public.documents` with `delete_after` TTL. | Document metadata dictionary | Newly inserted `document_id` UUID | Rollback / storage deletion if DB write fails. | Plan §4, §8.2 |
| 34 | Worker | Completion State Transition | Triggers backend transition from `VERIFYING` to `COMPLETED` upon verified delivery. | `task_id`, `document_id` | WS `task_completed` message | Terminal state; only verifier can complete. | Plan §6, §8.2 |
| 35 | Worker | Ephemeral Sandbox Cleanup | Recursively deletes `task_temp_dir` and closes browser context in `finally` block. | `task_temp_dir` path | Wiped directory, closed context | Guaranteed execution on success, fail, or cancel. | ORIGINAL_REQUEST R2, Plan §8.2 |
| 36 | Worker | In-Flight Task Cancellation | Handles cooperative `cancel_task` message from backend; terminates browser context. | `task_id`, WS cancel frame | Aborted page action, wiped temp dir | Immediate cleanup; sets task to `CANCELLED`. | Plan §5, §6, §16 |

---

## 5. Edge Cases & Failure Scenarios

| # | Feature | Input / Trigger | Observed & Specified Behavior |
|---|---|---|---|
| 1 | Mock Portal | Aadhaar input with incorrect Verhoeff check digit (e.g. `123456789019`). | Portal rejects submission with `#error_msg`: "Invalid Aadhaar Number. Please check and re-enter." Form does not advance. |
| 2 | Mock Portal | VID input with valid 16 digits. | Portal accepts input identically to 12-digit Aadhaar, advances to CAPTCHA verification. |
| 3 | Mock Portal | CAPTCHA submitted with lowercase characters when portal shows uppercase. | Case-insensitive matching accepts the input (standard UIDAI portal behavior); otherwise displays "Invalid Captcha". |
| 4 | Mock Portal | User clicks "Refresh CAPTCHA" button 5 times in succession. | Old CAPTCHA solutions are immediately discarded; only the latest image and solution are retained in session. |
| 5 | Mock Portal | Session idle for more than 15 minutes. | Session store purges expired session. Any POST returns HTTP 303 redirect to `/` with "Session expired". |
| 6 | Mock Portal | OTP input with non-numeric characters (e.g. `1234AB`). | HTML5 pattern / server validator rejects with 400 or displays `#error_msg`: "OTP must be 6 digits". |
| 7 | Mock Portal | OTP submitted after 181 seconds (> 180s TTL). | Portal returns `#error_msg`: "OTP has expired. Please request a new OTP." Session remains locked until Resend. |
| 8 | Mock Portal | Wrong OTP entered twice, then correct OTP on 3rd attempt. | Attempts 1 and 2 increment attempt counter and display warnings. 3rd attempt succeeds and initiates download. |
| 9 | Mock Portal | Wrong OTP entered 3 consecutive times. | Portal locks session permanently: "Maximum attempts exceeded. Please try again after 24 hours." Further POSTs fail. |
| 10 | Mock Portal | User clicks "Resend OTP" after 30 seconds. | Old OTP is invalidated; new 6-digit OTP generated; 180s timer resets to full duration; attempt counter resets to 0. |
| 11 | Mock Portal | Concurrent requests with same `session_id`. | Fast-locking / atomic transaction prevents race conditions in OTP counter. |
| 12 | Worker | Backend WebSocket server is down when Worker boots up. | Worker catches `ConnectionRefusedError` and enters exponential backoff reconnect loop (1s, 2s, 4s, 8s, max 30s) without crashing. |
| 13 | Worker | WebSocket connection disconnects abruptly during active task execution. | Worker pauses browser, attempts reconnection within 30s grace period; if reconnection fails, terminates browser context, wipes temp dir, and marks task failed. |
| 14 | Worker | Backend sends malformed JSON or unknown message type. | Worker logs warning, drops frame, sends `error` message back over WebSocket, and continues normal operation. |
| 15 | Worker | Portal attempts to load third-party analytics script from `https://www.google-analytics.com/analytics.js`. | Route interception pattern detects non-allowlisted host; immediately executes `route.abort('blockedbyclient')`. |
| 16 | Worker | Portal attempts HTTP 302 redirect to unauthorized external domain. | Route handler catches outbound navigation to foreign host, aborts request, and raises `SecurityNavigationError`. |
| 17 | Worker | CAPTCHA image element fails to render or load within 15 seconds. | Worker catches `TimeoutError`; performs up to 2 page reloads; if still failing, reports `task_failed` (`PORTAL_UNRESPONSIVE`). |
| 18 | Worker | User does not submit CAPTCHA or OTP within 180-second timeout. | `asyncio.wait_for` raises `TimeoutError`; worker closes browser context, wipes temp dir, and notifies backend that input expired. |
| 19 | Worker | User presses "Cancel" in Flutter app while worker is awaiting OTP. | Backend sends `cancel_task` over WebSocket; worker cancels `asyncio.Future`, closes context, wipes temp directory, and exits cleanly. |
| 20 | Worker | Duplicate task assignment received with same `task_id`. | Worker checks in-memory active tasks table; rejects duplicate assignment with warning. |
| 21 | Worker | DOM redesign: Portal renames `#otp_input` to `#txt_verification_code`. | `page.wait_for_selector('#otp_input')` times out after 15s; worker logs clear error message ("Selector #otp_input not found on page"), fails task gracefully. |
| 22 | Worker | Chromium process crashes or is killed by OS Out-Of-Memory (OOM) killer. | Worker catches `TargetClosedError` or process exit signal; restarts browser instance; marks in-flight tasks as `FAILED`. |
| 23 | Worker | Download event times out after 30s (server stalled or hung). | `page.expect_download()` raises `TimeoutError`; worker reports download timeout; task transitions to `FAILED`. |
| 24 | Worker | Portal triggers two simultaneous download popups. | Worker accepts only the first download matching expected PDF naming pattern; immediately aborts and discards secondary download. |
| 25 | Worker | Downloaded PDF is truncated / 0 bytes. | Document verifier checks `size_bytes < 10240`; immediately fails verification; does not upload to Supabase. |
| 26 | Worker | Downloaded file has `.pdf` extension but contains `<html>...</html>`. | Header check detects absence of `%PDF-` magic bytes; raises `DocumentValidationError`; task fails. |
| 27 | Worker | Downloaded PDF contains valid pages but has embedded `/JavaScript` action. | Verifier detects `/JavaScript` dictionary; raises `MaliciousContentError`; deletes temp file immediately; reports security violation. |
| 28 | Worker | Downloaded PDF has embedded `/Launch` action targeting `cmd.exe`. | Verifier detects `/Launch` dictionary; raises `MaliciousContentError`; deletes file; flags security event. |
| 29 | Worker | Downloaded PDF is password-protected e-Aadhaar. | Verifier confirms `reader.is_encrypted == True` and valid PDF trailer; sets `pdf_encrypted = True`; marks validation passed. |
| 30 | Worker | Supabase Storage upload fails with network error or 500 status. | Worker retries upload up to 3 times with exponential backoff; if persistent, fails task and preserves clean local disk. |
| 31 | Worker | Database row insert fails after successful Supabase Storage upload. | Worker catches database error, calls Supabase Storage API to remove uploaded orphan object (`storage.remove([path])`), ensuring zero orphaned storage objects. |
| 32 | Worker | Worker process receives SIGTERM / SIGINT shutdown signal while tasks running. | Signal handler intercepts termination, closes all open browser contexts, deletes all temporary directories, and closes WebSocket before exiting. |

---

## 6. Security Invariants & Redaction Contracts

1. **Zero-Persistence Policy for OTP & CAPTCHA:**
   - OTP values and CAPTCHA answers are NEVER written to PostgreSQL, NEVER published to Supabase Realtime, NEVER included in application logs, and NEVER passed to any LLM prompt.
   - Pydantic models handling inputs must wrap values in `SecretStr`.
   - Python worker must drop variable references (`del otp_value`) immediately after `locator.fill()`.
2. **Browser Sandbox Hardening:**
   - In production (`APP_ENV=prod`), Playwright tracing, video, and HAR recording are strictly disabled.
   - Environment variable `DEBUG=pw:api` must never be enabled.
   - No screenshots permitted on the OTP input step.
3. **Network Isolation:**
   - Outbound browser traffic is restricted strictly to allowlisted domains via Playwright route interception.
4. **Storage Isolation & Retention:**
   - Private Supabase Storage bucket `documents` isolates objects under `<user_id>/<task_id>.pdf`.
   - All documents have an enforced `delete_after` retention deadline (default 24 hours).
5. **Deterministic Verifier Authority:**
   - Only `DocumentVerifier` has authorization to advance a task from `VERIFYING` to `COMPLETED`. An LLM response or user claim never completes a task.
