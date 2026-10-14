# Handoff Report — Backend & AI Engine Spec Mining (Hard Handoff)

**Agent ID:** `spec_miner_survey_1`  
**Parent Agent ID:** `b5871ec8-28ec-4ff6-821a-198f59d99e91`  
**Date:** 2026-10-13  
**Artifacts Produced:**  
- `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_1\survey_report.md`  
- `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_1\BRIEFING.md`  
- `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_1\progress.md`  
- `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_1\DISPATCH.md`  

---

## 1. Observation

Direct observations from the authoritative specifications:

1. **`ORIGINAL_REQUEST.md` (lines 10-18, 24-32, 68-73):**
   - Supabase project URL: `https://rsftbslckmdkynprmpin.supabase.co`
   - LLM Provider: Groq API key `gsk_mock_saral_groq_api_key_for_testing`, default model `llama-3.3-70b-versatile` via `LLM_MODEL`.
   - Backend Core (FastAPI): Supabase JWT token verification, streaming SSE via Groq, endpoints `GET /health`, `POST /api/v1/chat`, `POST /api/v1/tasks`, `GET /api/v1/tasks/{id}`, `POST /api/v1/tasks/{id}/input` (using `SecretStr`), `GET /api/v1/tasks/{id}/challenge`, `POST /api/v1/tasks/{id}/cancel`, `GET /api/v1/tasks/{id}/download` (signed URL), `DELETE /api/v1/documents/{id}`, `WS /internal/worker`, `POST /internal/cleanup`.
   - Strict PII & Biometric Scrubber: Masks 12-digit Aadhaar/VID numbers (regex + Verhoeff validation), phone numbers, emails, biometric mentions, and OTPs. All application logs pass through custom redacting log filters.
   - Deterministic state machine (`transition()` function) with Postgres job queue using `FOR UPDATE SKIP LOCKED`.
   - Strict zero-persistence policy for OTP and CAPTCHA values.

2. **`SARAL_AI_IMPLEMENTATION_PLAN.md`:**
   - **Section 4 (lines 92-203):** Data model with tables `profiles`, `conversations`, `messages`, `tasks`, `task_events`, `documents`.
     - `tasks` status enum: `'RECEIVED','VALIDATING','PLANNING','RUNNING','WAITING_FOR_USER','AUTHENTICATING','DOWNLOADING','VERIFYING','COMPLETED','FAILED','CANCELLED','EXPIRED'`.
     - Unique constraints: `unique (user_id, idempotency_key)`, partial index `create unique index one_active_task_per_workflow on public.tasks (user_id, workflow) where status not in ('COMPLETED','FAILED','CANCELLED','EXPIRED')`.
     - Private Supabase Storage bucket `documents` with path convention `<user_id>/<task_id>.pdf`.
   - **Section 5 (lines 209-228):** API route table, Supabase JWT verification on every route, Pydantic v2 validation, `SecretStr` for input values, 60-second signed download URLs, per-user rate limits (`slowapi`), ownership checks on every `task_id`/`document_id`.
   - **Section 6 (lines 231-248):** Task state machine transition matrix:
     - Only verifier can move `VERIFYING -> COMPLETED`.
     - Timeouts: pending user input expires after 3 minutes; whole task after 10 minutes; max 3 OTP attempts and 3 CAPTCHA attempts; bounded retries (2) for page-load failures only.
   - **Section 7 (lines 251-263):** Challenge broker: In-memory relay only; worker reaches challenge -> orchestrator sets `WAITING_FOR_USER` with `pending_input = {kind, prompt, expires_at, attempts_left}`; values never touch Postgres, logs, Realtime, or LLM prompts.
   - **Section 8 (lines 265-285):** Download validation: Starts with `%PDF-`, size within range, no `/JavaScript` or `/Launch` actions, SHA-256 computed, temp dirs deleted in `finally`.
   - **Section 9 (lines 293-310):** AI layer: PII scrubber -> IntentClassifier (`RuleBasedClassifier` -> Groq `llama-3.3-70b-versatile` tool calling/JSON schema fallback with confidence gating ≥ 0.8).
   - **Section 11 (lines 419-422):** Repository layout for `backend/app/` (`main.py`, `api/`, `core/`, `chat/`, `orchestrator/`, `policy/`, `ai/`, `workflows/`, `worker/`, `db/`).
   - **Section 18 (lines 570-602):** `render.yaml` with Python 3.12.7, uvicorn entry point, environment variables.

3. **`rules.md` (lines 1-440):**
   - Zero-dummy-bypass rules, deterministic state models, typed error handling, strict validation, no mocks in shipped code, least privilege.

---

## 2. Logic Chain

1. **Premise 1:** The user request mandates building the complete Saral AI backend in FastAPI (Python 3.12) adhering to Sections 5, 6, 7, 9, 11, 14, 16 of `SARAL_AI_IMPLEMENTATION_PLAN.md` and `ORIGINAL_REQUEST.md`.
2. **Premise 2:** Authentication and authorization require Supabase JWT verification on all client routes and explicit user ownership checks (`resource.user_id == current_user.id`) to prevent broken object-level authorization (BOLA/IDOR).
3. **Premise 3:** Privacy laws (India's DPDP Act) and project constraints require zero-leakage of Aadhaar numbers, biometrics, OTPs, and CAPTCHAs. Therefore:
   - Aadhaar numbers must be identified via regex and validated via the Verhoeff algorithm ($D_5$ group permutations) to avoid both false positives and unmasked leakage.
   - In-memory challenge brokerage using `asyncio.Future` and `SecretStr` isolates OTP/CAPTCHA values completely from DB rows, console logs (via `RedactingLogFilter`), Supabase Realtime payloads, and LLM prompts.
4. **Premise 4:** The AI engine requires high responsiveness and cost efficiency on free-tier infrastructure. Implementing a multi-tier intent pipeline (Rule-Based -> Groq `llama-3.3-70b-versatile` tool calling fallback) ensures zero latency for common workflows, while SSE streaming ensures immediate token feedback to the Flutter client.
5. **Premise 5:** Task execution must be reliable and concurrency-safe without Redis. A deterministic state machine (`transition()` function) coupled with Postgres `FOR UPDATE SKIP LOCKED` on the `tasks` table guarantees that worker assignments are mutually exclusive, idempotent, and provably resilient to race conditions.
6. **Premise 6:** Verification before delivery is non-negotiable. Only the verifier actor can trigger the terminal `COMPLETED` state after cryptographically validating the `%PDF-` header, trailer, size, absence of malicious JavaScript, and calculating SHA-256.

---

## 3. Caveats

- **Caveat 1:** The implementation plan references optional Jev (TypeSafe) classifier; however, `ORIGINAL_REQUEST.md` specifies Groq API (`llama-3.3-70b-versatile`) as the primary AI engine. The design specifies the `IntentClassifier` interface with Rule-Based as primary and Groq tool calling/JSON schema as secondary.
- **Caveat 2:** Real portal automation is subject to a Phase 7 feasibility gate (Mode 1 automated vs Mode 2 guided WebView). The backend architecture is completely workflow-agnostic and tested against `mock_portal`.
- **Caveat 3:** Free-tier Render containers sleep after 15 minutes of inactivity; `GET /health` is specified as a warm-up probe.

---

## 4. Conclusion

All specifications, interface contracts, state transitions, PII scrubbing logic, AI engine interfaces, challenge broker protocols, and API endpoint schemas have been comprehensively mined, analyzed, and documented in `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_1\survey_report.md`.

The downstream implementation teams (M1 Supabase, M2 Backend Core & AI Engine, M3 Mock Portal & Worker, M4 Flutter App) now have an unambiguous blueprint with exact contracts, database constraints, mathematical tables, and failure behaviors.

---

## 5. Verification Method

To independently verify the findings in this report:

1. **Verify Report Integrity:**
   - Inspect `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_1\survey_report.md` for completeness across all 32 discovered features and 23 edge cases.
2. **Verify Against Authoritative Specs:**
   - Cross-check route definitions against `SARAL_AI_IMPLEMENTATION_PLAN.md` Section 5.
   - Cross-check state matrix against Section 6.
   - Cross-check zero-persistence and challenge handling against Section 7.
   - Cross-check Verhoeff algorithm and PII scrubber requirements against `ORIGINAL_REQUEST.md` R1 and Plan Section 9.
3. **Invalidation Conditions:**
   - If UIDAI introduces a different checksum algorithm than Verhoeff.
   - If Supabase alters JWT claim structure (`sub`, `iss`, `aud`).
   - If Groq API changes the model name from `llama-3.3-70b-versatile`.
