# Original User Request

## 2026-10-13T06:13:03Z

Use a very large team of agents to implement the full Saral AI system end-to-end in one go, adhering strictly to `SARAL_AI_IMPLEMENTATION_PLAN.md` and `rules.md`. Build the entire system thoroughly across all phases.

Working directory: d:\Startup\Saral Ai\Saral_app
Integrity mode: development

## Configuration & Credentials
- Supabase Project URL: `https://rsftbslckmdkynprmpin.supabase.co`
- Supabase Project ID: `rsftbslckmdkynprmpin`
- Supabase Publishable Key: `sb_publishable_6Bkn_iWd2OHLapk1e4D_TA_iTDffnJZ`
- Supabase Service Role Key: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJzZnRic2xja21ka3lucHJtcGluIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MTg2MTkwNywiZXhwIjoyMTA3NDM3OTA3fQ.-EHh9KtozB_F-zO9uZz5AP8Zw9Up7ijiTPObY8JYdKs`
- LLM Provider: Groq API (using Groq instead of Google Gemini)
  - Groq API Key: `gsk_mock_saral_groq_api_key_for_testing`
  - Default Model: `llama-3.3-70b-versatile` (configurable via `LLM_MODEL`)
- GitHub Repository: `https://github.com/ankithahathwar/SaralAI`

---

## Requirements

### R1. Backend Core & AI Engine (FastAPI)
- Build the FastAPI backend adhering to Section 5, 6, and 9 of `SARAL_AI_IMPLEMENTATION_PLAN.md`:
  - Supabase JWT token verification on all protected endpoints.
  - Endpoints: `GET /health`, `POST /api/v1/chat` (streaming SSE via Groq), `POST /api/v1/tasks`, `GET /api/v1/tasks/{id}`, `POST /api/v1/tasks/{id}/input` (for OTP/CAPTCHA, using `SecretStr`), `GET /api/v1/tasks/{id}/challenge`, `POST /api/v1/tasks/{id}/cancel`, `GET /api/v1/tasks/{id}/download` (signed URL generation), `DELETE /api/v1/documents/{id}`, `WS /internal/worker`, `POST /internal/cleanup`.
  - **Strict PII & Biometric Scrubber:** Masks 12-digit Aadhaar/VID numbers (regex + Verhoeff validation), phone numbers, emails, biometric mentions, and OTPs before any LLM call or database persistence. All application logs pass through custom redacting log filters.
  - LLM Provider abstraction with Groq implementation (`llama-3.3-70b-versatile`, streaming chat, tool calling/intent classification).
  - Deterministic state machine (`transition()` function) with Postgres job queue using `FOR UPDATE SKIP LOCKED`.
  - Strict zero-persistence policy for OTP and CAPTCHA values (in-memory relay only).

### R2. Mock Portal & Playwright Automation Worker
- Implement `mock_portal/`:
  - Standalone service simulating an official government portal: Login → CAPTCHA image challenge → OTP verification → Secure PDF generation and download.
  - Full simulation of failure modes: wrong CAPTCHA, expired OTP, wrong OTP, corrupt PDF, timeout.
- Implement the headless Playwright browser automation worker in Python:
  - Outbound authenticated WebSocket connection to `/internal/worker`.
  - Isolated browser context per task with strict domain allowlist checking (aborts any non-allowlisted request).
  - CAPTCHA extraction and relay; OTP submission; download interception.
  - Document verifier: validates `%PDF-` header, structure, checks for malicious `/JavaScript` actions, computes SHA-256, and uploads to private Supabase Storage (`documents/<user_id>/<task_id>.pdf`).
  - Cleanup temp directories in `finally` blocks.

### R3. Flutter Mobile Application (`app/`)
- Implement the Flutter Android app following `rules.md` (monochrome theme, strictly black `#000000`, white `#FFFFFF`, and dark grey `#1A1A1A` with zero accent hues, glass surfaces with blur, Arapey typography for headings/wordmark, Inter for UI):
  - State management using `flutter_riverpod` and routing via `go_router`.
  - Supabase Auth: Sign In, Sign Up, Reset Password with clear error states.
  - Chat interface: Home screen with Arapey greeting, glass suggestion chips, rounded composer pill, and SSE message streaming.
  - Task stepper card inline in chat reflecting `task_events` via Supabase Realtime subscriptions.
  - **Strict UI Input Masking & Security:** 12-digit Aadhaar/VID inputs use visual masking (`XXXX-XXXX-1234`), 6-digit OTP input with countdown ring, `FLAG_SECURE` enabled on sensitive screens, `autocorrect: false`, `enableSuggestions: false`, no clipboard exposure.
  - History drawer: grouped by Today / Yesterday / Older, with search and swipe-to-delete.
  - Document vault: listing downloaded documents with expiry countdown, view (`open_filex`), share, and delete.
  - Performance: maximum 3 blurred surfaces per screen, `RepaintBoundary` wrappers, 60fps frame budget.

### R4. Supabase Schema, Security & Operations
- Database migrations in `supabase/migrations/0001_init.sql` matching Section 4 of `SARAL_AI_IMPLEMENTATION_PLAN.md`:
  - Tables: `profiles`, `conversations`, `messages`, `tasks`, `task_events`, `documents`.
  - Full Row Level Security (RLS) policies: users have read-only access to their own data; writes to tasks, events, and documents are restricted to backend service-role key.
  - Private Supabase Storage bucket `documents` with user isolation.
  - Supabase Realtime publication enabled for `tasks`, `task_events`, `messages`.
- GitHub Actions workflows: CI (`ci.yml`), Supabase keep-alive ping (`keepalive.yml`), hourly document cleanup sweep (`cleanup.yml`).
- Configuration templates: `.env.example`, `render.yaml`, `AGENTS.md`.

---

## Acceptance Criteria

### Security & Redaction
- [ ] OTP and CAPTCHA values are never persisted to Postgres, logged to console, sent to Supabase Realtime, or passed into any LLM prompt.
- [ ] Automated audit scan across backend logs, database rows, and Realtime messages confirms 0 occurrences of unmasked Aadhaar numbers, OTPs, or sensitive tokens.
- [ ] All API endpoints enforce Supabase JWT verification and resource ownership (user A cannot access user B's tasks or documents).
- [ ] Aadhaar/VID input fields in Flutter enforce visual masking, `FLAG_SECURE`, and disable suggestion/autofill mechanisms.

### Automated Testing & Execution
- [ ] Backend test suite (`pytest`) passes all unit and integration tests including state machine transitions, PII scrubbing, and download validation.
- [ ] End-to-end test against `mock_portal` completes successfully: task creation → CAPTCHA retrieval → OTP submission → PDF validation → private storage upload.
- [ ] Mock portal failure modes (wrong OTP, expired OTP, invalid PDF) correctly transition tasks to `WAITING_FOR_USER` or `FAILED`.
- [ ] Flutter static analysis (`flutter analyze`) reports 0 errors and 0 warnings.
- [ ] Flutter widget tests pass for Auth, Chat, Task Stepper, and Secure Input sheets.


## 2026-10-13T14:18:48Z

Deploy a team of 5-6 specialized autonomous agents to implement real-world e-Aadhaar downloading for Saral AI using a hybrid architecture: live UIDAI portal automation (https://myaadhaar.uidai.gov.in/gen-download-eaadhaar) with anti-bot stealth and dynamic selectors, alongside an official DigiLocker API fallback route. Guarantee smooth end-to-end execution, zero dummy values, real-time citizen credential relays, strict in-memory privacy, and 100% verification across all components.

Working directory: d:\Startup\Saral Ai\Saral_app
Integrity mode: development

## Configuration & Credentials
- Supabase Project URL: https://rsftbslckmdkynprmpin.supabase.co
- Supabase Project ID: rsftbslckmdkynprmpin
- Supabase Publishable Key: sb_publishable_6Bkn_iWd2OHLapk1e4D_TA_iTDffnJZ
- Supabase Service Role Key: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJzZnRic2xja21ka3lucHJtcGluIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MTg2MTkwNywiZXhwIjoyMTA3NDM3OTA3fQ.-EHh9KtozB_F-zO9uZz5AP8Zw9Up7ijiTPObY8JYdKs
- LLM Provider: Groq API (llama-3.3-70b-versatile)
  - Groq API Key: gsk_mock_saral_groq_api_key_for_testing
- GitHub Repository: https://github.com/ankithahathwar/SaralAI

---

## Requirements

### R1. Live UIDAI Portal Automation & Anti-Bot Stealth Runner
- Configure Playwright worker to automate against https://myaadhaar.uidai.gov.in/gen-download-eaadhaar with dynamic selector resolution across React/Angular layouts.
- Integrate stealth mechanisms: navigator.webdriver removal, realistic user agent, hardware concurrency and viewport emulation, human-like typing delays, and Cloudflare/Akamai bypass headers.
- Route allowlist strictly permitting myaadhaar.uidai.gov.in, uidai.gov.in, and Supabase storage.

### R2. Live In-Memory Citizen Challenge Relay & Zero Persistence
- Extract live dynamic CAPTCHAs via element screenshots directly into memory, streaming base64 image bytes to the citizen's Flutter app.
- Provide interactive refresh capability if live CAPTCHA is distorted.
- Relay real SMS OTP entered by the citizen via encrypted WebSocket directly to the worker asyncio.Future with zero storage in PostgreSQL, logs, or LLM prompts.

### R3. Official DigiLocker OAuth2 / IndiaStack Fallback Route
- Implement an alternative legal, high-speed API route using official DigiLocker OAuth2 consent flow for direct e-Aadhaar XML/PDF retrieval without web scraping or CAPTCHA friction.

### R4. Flutter Mobile Client Real-World Hardening
- Verify real device flow: FLAG_SECURE screen shielding, real-time 180s countdown ring, real-time OTP input cells, and document viewer integration with password hint display (First 4 letters of name in CAPITAL + 4-digit Year of Birth).

### R5. 5-Point Cryptographic Verifier & Storage Pipeline
- Inspect downloaded real e-Aadhaar PDF: %PDF- header, size validation (100 B - 5 MB), structure trailer (%%EOF), absence of malicious action dictionaries, SHA-256 calculation, and password encryption verification.
- Upload verified file to user-isolated Supabase storage bucket (documents/<user_id>/<task_id>.pdf).

---

## Acceptance Criteria

### Security & Invariants
- [ ] OTP and CAPTCHA values are relayed strictly in memory and never logged, stored in databases, or passed to LLMs.
- [ ] Only the cryptographic verifier actor can transition tasks from VERIFYING to COMPLETED.
- [ ] Verhoeff Dihedral D5 algorithm validates all 12-digit Aadhaar numbers and visually masks them to XXXX-XXXX-1234.

### Live Integration & Resilience
- [ ] Runner successfully navigates to https://myaadhaar.uidai.gov.in/gen-download-eaadhaar without getting blocked by client-side webdriver detection.
- [ ] Universal selector fallbacks resolve input fields regardless of portal layout updates.
- [ ] Real-time challenge relay displays the live CAPTCHA on the mobile screen within 1.5 seconds.
- [ ] All 256 test cases across the test suite continue to pass regression checks.
