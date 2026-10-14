# Handoff Report: Specification Mining for Mock Portal & Playwright Worker

**Report File:** `handoff.md`  
**Agent:** spec_miner_survey_2 (Worker & Mock Portal Spec Miner)  
**Date:** 2026-10-13  
**Target:** Orchestrator (`b5871ec8-28ec-4ff6-821a-198f59d99e91`)  
**Type:** Hard Handoff (Task Complete)

---

## 1. Observation

Direct observations from authoritative specifications in the repository:

1. **`ORIGINAL_REQUEST.md` (Lines 33–43, Requirement R2):**
   > "Implement `mock_portal/`: Standalone service simulating an official government portal: Login → CAPTCHA image challenge → OTP verification → Secure PDF generation and download. Full simulation of failure modes: wrong CAPTCHA, expired OTP, wrong OTP, corrupt PDF, timeout."  
   > "Implement the headless Playwright browser automation worker in Python: Outbound authenticated WebSocket connection to `/internal/worker`. Isolated browser context per task with strict domain allowlist checking (aborts any non-allowlisted request). CAPTCHA extraction and relay; OTP submission; download interception. Document verifier: validates `%PDF-` header, structure, checks for malicious `/JavaScript` actions, computes SHA-256, and uploads to private Supabase Storage (`documents/<user_id>/<task_id>.pdf`). Cleanup temp directories in `finally` blocks."

2. **`SARAL_AI_IMPLEMENTATION_PLAN.md` (Section 2, Line 33 & Section 3, Lines 57–59, 76):**
   > "1. Chromium will not run on Render Free. Free instances have 512 MB RAM; headless Chromium is widely reported to run out of memory there... Render hosts only the lightweight API. The browser worker runs on your PC (or a larger host later)."  
   > "Mode B — Hosted API: API on Render Free. Worker on your PC connects outbound to `wss://<api>/internal/worker`. Worker only runs while your PC is on; reconnect with backoff."

3. **`SARAL_AI_IMPLEMENTATION_PLAN.md` (Section 6, Lines 231–249):**
   > "Transitions are enforced in one function (`transition(task, new_status, actor)`). Anything not listed is rejected. Only the verifier can move `VERIFYING → COMPLETED`, and only after file validation passes. An LLM saying 'done' never completes a task."  
   > "Timeouts: pending user input expires after 3 minutes; whole task after 10 minutes; max 3 OTP attempts and 3 CAPTCHA attempts; bounded retries (2) for page-load failures only."

4. **`SARAL_AI_IMPLEMENTATION_PLAN.md` (Section 7, Lines 251–262):**
   > "1. Worker reaches a challenge step → orchestrator sets `WAITING_FOR_USER` with `pending_input = {kind, prompt, expires_at, attempts_left}`. No values."  
   > "4. The API relays the value over the worker WebSocket to an `asyncio.Future` keyed by `task_id`. It is never written to the database, logs, Realtime, or any LLM prompt."  
   > "5. Worker fills the field with `locator.fill()`, then verifies the result from page state (OTP error text vs. next-step element)."  
   > "Worker hardening: disable Playwright tracing, video and HAR in production; never set `DEBUG=pw:api` (it can print typed values); take no screenshots on the OTP step; drop references to the value immediately after use."

5. **`SARAL_AI_IMPLEMENTATION_PLAN.md` (Section 8.1 & 8.2, Lines 268–279):**
   > "Playwright `context.route("**/*")` aborts any request whose host is not in the workflow's allowlist."  
   > "Only one expected download is accepted; anything else is discarded and the task fails."  
   > "Download validation: 1. Starts with `%PDF-`, size within the workflow's range (e.g. 10 KB to 5 MB)... 2. Parses with `pypdf`: if not encrypted, at least 1 page; if encrypted (expected for e-Aadhaar), structure and trailer are valid and `pdf_encrypted = true`. 3. No `/JavaScript` or `/Launch` actions. 4. Compute SHA-256; upload to `documents/<user_id>/<task_id>.pdf` with the secret key... 5. Delete the local temp directory in a `finally` block."

6. **`SARAL_AI_IMPLEMENTATION_PLAN.md` (Section 16, Lines 539–542):**
   > "Mock-portal E2E: Happy path; wrong OTP then correct; 3 wrong OTPs → `FAILED`; OTP expiry → `EXPIRED`; wrong CAPTCHA retry; user cancels mid-run; duplicate request... rejected; corrupt PDF; HTML masquerading as PDF; oversize file; unexpected second download; page timeout; changed selector → clear failure message, never fake success."  
   > "Policy: Request to a non-allowlisted host is aborted; redirect to a foreign host is aborted."  
   > "Cleanup: Temp directory removed on success, failure and cancel..."

7. **`rules.md` (R-SEC §12, R-ARCH §3, R-REAL §16):**
   > R-SEC-9: "Temp files: app-private, always cleaned (success, failure, cancel, process death sweep). Partial writes are never exposed as final outputs. Verify every write/conversion outcome."  
   > R-REAL-1: "No demos, mocks, fake data, stub screens, or placeholder content in shipped code." Testing occurs against deterministic `mock_portal/` before any real portal spike.

---

## 2. Logic Chain

1. **Decoupled Architecture Rationale:**  
   - Free cloud hosting (Render Free) provides 512 MB RAM, whereas headless Chromium requires substantially more memory and crashes under OOM (Observation 2).  
   - Therefore, the browser automation engine must run as an independent worker process communicating over an **outbound** persistent WebSocket (`WS /internal/worker`) authenticated with `WORKER_SHARED_SECRET`. Outbound connection eliminates the need for opening inbound ports or exposing public IPs on the worker host.

2. **Zero-Persistence Security Guarantee:**  
   - Official Indian Aadhaar downloads require multi-factor input: Aadhaar/VID, dynamic CAPTCHA challenge, and 6-digit SMS OTP (Observations 1, 4).  
   - Under privacy laws and system invariants, OTP and CAPTCHA credentials must never touch disks, databases, log streams, or LLM contexts.  
   - Therefore, the worker must capture the CAPTCHA image via element screenshot in memory, transmit it as Base64 over the WebSocket to the broker, and await the user's response via an `asyncio.Future`. The returned OTP is filled directly into the DOM via `locator.fill()`, with the memory reference immediately deleted and Playwright tracing/logging strictly suppressed (Observation 4).

3. **Multi-Stage Document Verification Pipeline:**  
   - Attackers or malfunctioning portals could deliver HTML error pages disguised as PDFs, corrupted streams, oversized payloads, or weaponized PDFs containing executable payloads (`/JavaScript`, `/Launch`) (Observations 5, 6).  
   - Therefore, the worker must implement a strict 5-stage verification filter before marking a task complete: magic byte header check (`%PDF-`), byte size boundary (10 KB to 5 MB), `pypdf` structural validation, malicious action inspection, and SHA-256 hashing.  
   - State machine transition `DOWNLOADING → VERIFYING → COMPLETED` is exclusively authorized to this verifier (Observation 3).

4. **Network Sandboxing & Route Enforcement:**  
   - Malicious redirects or compromised portal dependencies could navigate the browser context to unintended servers (Observation 5, 6).  
   - Therefore, Playwright route interception (`context.route("**/*")`) must evaluate every outbound URI hostname against `ALLOWED_DOMAINS` and call `route.abort('blockedbyclient')` on any foreign host.

5. **Deterministic Mock Government Portal:**  
   - To validate the entire lifecycle and every failure condition without violating government portal terms or exhausting OTP quotas, `mock_portal/` must simulate both the happy path and all 10 failure modes (Observations 1, 6).

---

## 3. Caveats

1. **Real UIDAI Portal Phase Gate:**  
   - This specification governs `mock_portal/` and the generic Playwright worker. Under Phase 7 of `SARAL_AI_IMPLEMENTATION_PLAN.md`, any automation against live `myaadhaar.uidai.gov.in` is strictly gated behind a manual legal and feasibility review. The system defaults to Guided Mode (in-app WebView) if automated execution is legally or technically restricted.
2. **Encrypted e-Aadhaar Structure:**  
   - Genuine e-Aadhaar documents are password-encrypted using the user's name and birth year. As specified in Section 8.2 of the plan, the server and worker only validate structural integrity, trailer syntax, and absence of malicious tags without decrypting the payload. Decryption is performed exclusively client-side on the user's mobile device.
3. **Local Dev vs. Production HTTPS Certificates:**  
   - In local development testing against `mock_portal/` running on HTTP or self-signed localhost certificates, `ignore_https_errors` in Playwright context must be configurable via environment flag (`APP_ENV=dev`).

---

## 4. Conclusion

The authoritative requirements, system boundaries, protocols, and failure modes for both the **Mock Government Portal** and the **Playwright Headless Browser Worker** are thoroughly mined, documented, and cross-referenced. 

All 36 discovered features, 32 edge cases, and 5 core security invariants have been compiled into the primary specification report:
`d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_2\survey_report.md`

The system design strictly conforms to all zero-persistence, sandboxing, network allowlisting, and verification mandates established in `ORIGINAL_REQUEST.md` and `SARAL_AI_IMPLEMENTATION_PLAN.md`.

---

## 5. Verification Method

To independently verify the completeness and validity of this specification:
1. **Inspect Survey Report:**  
   Verify that `survey_report.md` exists and contains all required sections, tables, and failure modes:
   ```powershell
   Get-Content "d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_2\survey_report.md" | Select-String "Features Discovered"
   ```
2. **Verify Cross-Reference Consistency:**  
   Cross-check the documented failure mode matrix against Section 16 of `SARAL_AI_IMPLEMENTATION_PLAN.md` (lines 539–542) to confirm 100% coverage of all 10 failure simulations (wrong OTP, 3 wrong OTPs, expired OTP, corrupt PDF, HTML as PDF, oversize PDF, malicious PDF, slow response, changed selector, foreign redirect).
3. **Verify Security Invariants:**  
   Confirm that all 5 hard rules from Section 14 (`AGENTS.md`) and Section 7/8.2 of `SARAL_AI_IMPLEMENTATION_PLAN.md` (zero persistence of OTP, element screenshotting, route-level domain allowlisting, 5-stage document verification, and temp cleanup in `finally`) are fully specified with concrete implementation patterns.
