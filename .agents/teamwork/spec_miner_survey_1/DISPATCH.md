## 2026-10-13T06:17:21Z
You are spec_miner_survey_1 (Backend & AI Engine Spec Miner).
Working directory: d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_1\
Project root: d:\Startup\Saral Ai\Saral_app\

Authoritative specifications to read:
- d:\Startup\Saral Ai\Saral_app\.agents\teamwork\ORIGINAL_REQUEST.md
- d:\Startup\Saral Ai\Saral_app\SARAL_AI_IMPLEMENTATION_PLAN.md (Sections 5, 6, 7, 9, 11, 14, 16)
- d:\Startup\Saral Ai\Saral_app\rules.md

Your Mission:
Mine, extract, and document all precise requirements, feature inventory items, constraints, API contracts, and failure modes for:
1. Backend Core (FastAPI on Python 3.12, requirements, architecture).
2. Supabase JWT Authentication & RBAC/ownership checks for every protected endpoint.
3. PII & Biometric Scrubber: regex + Verhoeff algorithm for 12-digit Aadhaar/VID numbers, Indian phone numbers, emails, biometric mentions, OTP strings, redacting log filter.
4. AI Layer / Groq LLM Provider: Groq API (`llama-3.3-70b-versatile`), streaming SSE (`POST /api/v1/chat`), tool calling/intent classification (Rule-based, IntentClassifier interface, fallback handling, rate limits).
5. Deterministic State Machine: `transition()` function, strict allowed state matrix, Postgres job queue (`FOR UPDATE SKIP LOCKED`), idempotent task creation.
6. Challenge Broker: In-memory relay for OTP & CAPTCHA (SecretStr, zero persistence to DB, logs, or Realtime).
7. All Backend endpoints & contracts:
   - `GET /health`
   - `POST /api/v1/chat` (SSE streaming & task intent)
   - `POST /api/v1/tasks`
   - `GET /api/v1/tasks/{id}`
   - `POST /api/v1/tasks/{id}/input`
   - `GET /api/v1/tasks/{id}/challenge`
   - `POST /api/v1/tasks/{id}/cancel`
   - `GET /api/v1/tasks/{id}/download` (signed URL)
   - `DELETE /api/v1/documents/{id}`
   - `WS /internal/worker` (authenticated with WORKER_SHARED_SECRET)
   - `POST /internal/cleanup` (authenticated with CLEANUP_SECRET)

Output requirements:
- Write your comprehensive specification report to: `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_1\survey_report.md`
- Write your handoff report to: `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_1\handoff.md`
- Once complete, notify the orchestrator (caller) using send_message with a summary and file paths.

DO NOT write source code or run builds. You are an exploratory spec miner.
