# Saral AI — Backend & AI Engine Specification Survey Report

**Author:** `spec_miner_survey_1` (Backend & AI Engine Spec Miner)  
**Date:** 2026-10-13  
**Status:** Completed  
**Target Systems:** FastAPI Backend Core, Supabase Auth/RBAC, PII & Biometric Scrubber, Groq LLM AI Engine, Deterministic State Machine, Postgres Job Queue, Challenge Broker, Internal Worker & Cleanup APIs.

---

## Executive Summary & Specification Sources

This specification report documents the authoritative requirements, interface contracts, state transitions, security constraints, and failure modes for the Backend and AI Engine of Saral AI.

### Authoritative Specification Sources Analyzed:
1. `ORIGINAL_REQUEST.md`: System mission, credentials, Groq model constraints, acceptance criteria, zero-persistence mandates.
2. `SARAL_AI_IMPLEMENTATION_PLAN.md`:
   - Section 1: Architectural decisions & free-tier constraints.
   - Section 2: Reality check (ephemeral filesystems, Render sleep, memory limits).
   - Section 3: High-level architecture & deployment topology.
   - Section 4: Data model, tables, RLS policies, indexes, and Realtime publications.
   - Section 5: API route table, authentication headers, rate limits, cross-cutting rules.
   - Section 6: Deterministic state machine, transition matrix, timeouts, and actors.
   - Section 7: Secure input handling (OTP and CAPTCHA in-memory relay).
   - Section 8: Workflow registry, download validation (`%PDF-`, pypdf structure, security checks), delivery signed URLs.
   - Section 9: AI Layer (PII scrubber, IntentClassifier interface, Groq/Gemini fallbacks).
   - Section 11: Repository layout (`backend/`).
   - Section 14: `AGENTS.md` hard rules (never break).
   - Section 16: Comprehensive test matrix.
   - Section 18: Render deployment configuration (`render.yaml`) & operational crons.
3. `rules.md`: Production engineering guidelines, zero-dummy-bypass rules, error handling, strict security bounds.

---

## 1. Features Discovered

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|----------|---------|-------------|--------|---------|----------------|----------------|
| 1 | Backend Core | FastAPI Application Lifespan & Config | Initializes async connection pools, loads settings via Pydantic BaseSettings, attaches redacting logger filter | Environment variables (`SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `GROQ_API_KEY`, etc.) | App startup context, database pools, Groq client | Startup failure with clear log on missing required secrets | Plan §5, §11, §18; ORIGINAL_REQUEST.md |
| 2 | Backend Core | Public Health Check (`GET /health`) | Unauthenticated health probe for Render monitoring and mobile warm-up | HTTP GET | `{"status": "ok", "version": "1.0.0", "timestamp": "..."}` | 503 if database connection is completely dead | Plan §5; ORIGINAL_REQUEST.md R1 |
| 3 | Auth & RBAC | Supabase JWT Verification Dependency | Validates Supabase JWT on all protected routes via JWKS / Supabase Auth API; extracts `sub`, `email`, `role` | `Authorization: Bearer <token>` | `AuthenticatedUser(id: UUID, email: str, role: str)` | 401 Unauthorized (`detail`: "Invalid or expired token") | Plan §5, §14; rules.md §12 |
| 4 | Auth & RBAC | Resource Ownership Gate | Enforces that task/document belongs to the authenticated user ID | `user_id` from token, resource `id` | Resource entity or allows action | 404 Not Found (or 403 Forbidden) if resource is owned by another user | Plan §5, §16; rules.md §12 |
| 5 | PII Scrubber | Aadhaar / VID Masking with Verhoeff | Scans text for 12-digit Aadhaar / 16-digit VID candidate numbers and validates Verhoeff checksum; masks to `[REDACTED_AADHAAR]` | Raw string | Sanitized string with masked Aadhaar numbers | Non-matching numbers untouched; invalid checksums matching regex masked as `[REDACTED_ID_NUMBER]` | Plan §9, §14; ORIGINAL_REQUEST.md R1 |
| 6 | PII Scrubber | Indian Phone Number Masking | Regex detection of 10-digit Indian mobile numbers (+91, 0, or raw 6-9 prefix); masks to `[REDACTED_PHONE]` | Raw string | Sanitized string | Does not redact standard integers (dates, counts) outside phone regex | Plan §9; ORIGINAL_REQUEST.md R1 |
| 7 | PII Scrubber | Email Address Masking | Detects standard email address formats; masks to `[REDACTED_EMAIL]` | Raw string | Sanitized string | False positive prevention on URL paths | Plan §9; ORIGINAL_REQUEST.md R1 |
| 8 | PII Scrubber | Biometric Term Scrubbing | Detects keywords referring to biometric data (fingerprint, iris, retina, minutiae); sanitizes context | Raw string | Sanitized string | Retains grammatical flow | Plan §9; ORIGINAL_REQUEST.md R1 |
| 9 | PII Scrubber | OTP String Masking | Detects 4/6/8-digit numeric codes in proximity to auth keywords; masks to `[REDACTED_OTP]` | Raw string | Sanitized string | Standalone numbers outside auth context preserved | Plan §7, §9; ORIGINAL_REQUEST.md R1 |
| 10 | Security / Logging | Redacting Logging Filter | Custom `logging.Filter` applied to all Python loggers; redacts OTPs, Aadhaar, tokens, Bearer headers, and base64 buffers | LogRecord | Redacted LogRecord | Never raises exceptions that crash logging | Plan §5, §7, §14; ORIGINAL_REQUEST.md R1 |
| 11 | AI Engine | Groq LLM Provider (`llama-3.3-70b-versatile`) | Async client wrapper implementing `LLMProvider` interface; handles streaming generation and system prompts | Messages list, temperature, max_tokens | Async token generator (`AsyncIterator[str]`) | Groq API rate limit (429) triggers friendly chat message; 500 triggers fallback | ORIGINAL_REQUEST.md R1; Plan §9 |
| 12 | AI Engine | Chat Streaming SSE (`POST /api/v1/chat`) | Streams assistant message tokens over Server-Sent Events (`text/event-stream`); persists conversation & messages | `conversation_id`, `text`, `Idempotency-Key` header | SSE stream of tokens or task detection event | 400 Bad Request, 429 Rate Limit, 500 Provider Error | Plan §5, §9; ORIGINAL_REQUEST.md R1 |
| 13 | AI Engine | Rule-Based Intent Classifier | Regex/keyword classifier detecting high-confidence task triggers (e.g. "download aadhaar") with zero latency | PII-scrubbed message string | `IntentResult(workflow, confidence, is_task)` | Returns `is_task=False` if no pattern matches | Plan §9; ORIGINAL_REQUEST.md R1 |
| 14 | AI Engine | LLM / Tool Calling Intent Classifier | Secondary classifier using Groq structured function calling or JSON output schema for ambiguous queries | Message history + system prompt | `IntentResult` with extracted entities | Fallback to general chat if confidence < 0.8 | Plan §9; ORIGINAL_REQUEST.md R1 |
| 15 | State Machine | Deterministic State Transition (`transition()`) | Enforces valid state machine edges; logs transition to `task_events`; verifies actor permissions | `(task, new_status, actor, message)` | Updated `Task` instance | Raises `InvalidStateTransitionError` on illegal edges | Plan §6; ORIGINAL_REQUEST.md R1 |
| 16 | State Machine | Verifier Completion Gate | Enforces that only the verifier actor can move a task from `VERIFYING` to `COMPLETED` | `actor == "verifier"`, valid PDF verified | Status `COMPLETED` | 400/InvalidStateTransitionError if actor != "verifier" | Plan §6, §14; rules.md R-OUT-2 |
| 17 | State Machine | Timeout & Attempt Watchdog | Checks task age, pending input duration, and OTP/CAPTCHA attempt counts | Task state and timestamps | Transitions task to `EXPIRED` or `FAILED` | Graceful expiry; informs user via task events | Plan §6; ORIGINAL_REQUEST.md R1 |
| 18 | Job Queue | Postgres Queue (`FOR UPDATE SKIP LOCKED`) | Concurrency-safe job polling from `public.tasks` table using SQL locking | Polling query: status `RECEIVED` | Locked task row for worker assignment | Returns empty if queue is empty without blocking other workers | Plan §1, §3, §4; ORIGINAL_REQUEST.md R1 |
| 19 | Job Queue | Idempotent Task Creation | Prevents duplicate task executions via `(user_id, idempotency_key)` and `one_active_task_per_workflow` index | `idempotency_key`, `workflow`, `user_id` | Created `Task` or existing task | 409 Conflict if active task exists; returns existing task on idempotency replay | Plan §4, §5; ORIGINAL_REQUEST.md R1 |
| 20 | Challenge Broker | In-Memory CAPTCHA Storage | Holds raw CAPTCHA image bytes in transient Python memory keyed by `task_id`; zero persistence | `task_id`, `image_bytes`, `mime_type` | In-memory challenge record | Overwrites previous unconsumed CAPTCHA; expires after 3 mins | Plan §7; ORIGINAL_REQUEST.md R1 |
| 21 | Challenge Broker | In-Memory OTP/CAPTCHA Relay | Uses `asyncio.Future` to route user input to worker WebSocket without writing to DB, logs, or Realtime | `task_id`, `SecretStr(value)` | Resolved future delivered to worker | 400 if input expired, invalid format, or future already cancelled | Plan §7, §14; ORIGINAL_REQUEST.md R1 |
| 22 | API Endpoint | Direct Task Creation (`POST /api/v1/tasks`) | Explicit task creation endpoint for guided flow or retry actions | `{workflow, idempotency_key}` | `TaskResponse` (`id`, `status`, `workflow`) | 409 Conflict if duplicate active task; 422 if invalid workflow | Plan §5; ORIGINAL_REQUEST.md R1 |
| 23 | API Endpoint | Task Status Query (`GET /api/v1/tasks/{id}`) | Returns sanitized task state, progress, and `pending_input` metadata (NO values) | `task_id` in path | `TaskDetailResponse` | 404 Not Found if missing or not owner | Plan §5; ORIGINAL_REQUEST.md R1 |
| 24 | API Endpoint | Secure Input Submission (`POST /api/v1/tasks/{id}/input`) | Accepts OTP, CAPTCHA solution, or approval; strictly validates format; forwards to Challenge Broker | `task_id`, `{input_id, value: SecretStr}` | `{"status": "accepted"}` | 400 Bad Request (format mismatch, expired), 404 Not Found | Plan §5, §7; ORIGINAL_REQUEST.md R1 |
| 25 | API Endpoint | Challenge CAPTCHA Image (`GET /api/v1/tasks/{id}/challenge`) | Returns raw image bytes from in-memory challenge broker with `Cache-Control: no-store` | `task_id` in path | `Response(content=bytes, media_type="image/png")` | 404 Not Found if no active challenge or challenge expired | Plan §5, §7; ORIGINAL_REQUEST.md R1 |
| 26 | API Endpoint | Task Cancellation (`POST /api/v1/tasks/{id}/cancel`) | Cooperative cancellation of an ongoing task; signals worker to abort Playwright context | `task_id` in path | `{"status": "cancelled"}` | 400 if already terminal (`COMPLETED`, `FAILED`, `EXPIRED`) | Plan §5, §6; ORIGINAL_REQUEST.md R1 |
| 27 | API Endpoint | Document Download Signed URL (`GET /api/v1/tasks/{id}/download`) | Generates a 60-second Supabase Storage signed download URL for verified documents | `task_id` in path | `{"download_url": "...", "expires_in": 60}` | 404 Not Found if no document exists or verification incomplete | Plan §5, §8.3; ORIGINAL_REQUEST.md R1 |
| 28 | API Endpoint | Document Deletion (`DELETE /api/v1/documents/{id}`) | Deletes document record from Postgres AND deletes file object from Supabase Storage bucket | `document_id` in path | `{"status": "deleted"}` | 404 Not Found if missing or not owner | Plan §5; ORIGINAL_REQUEST.md R1 |
| 29 | Internal Worker | Worker WebSocket Link (`WS /internal/worker`) | Long-lived WebSocket for Playwright worker automation; authenticated via `WORKER_SHARED_SECRET` | Header/query `WORKER_SHARED_SECRET`, WS messages | Bidirectional task dispatch, challenge relay, and event updates | 403 / WS 1008 Policy Violation on invalid secret | Plan §3, §5; ORIGINAL_REQUEST.md R1 |
| 30 | Internal Ops | Retention Sweep (`POST /internal/cleanup`) | Cron endpoint triggered by GitHub Actions with `CLEANUP_SECRET` to purge expired documents | `X-Cleanup-Secret: <CLEANUP_SECRET>` | `{"deleted_documents_count": N, "cleaned_storage_objects": N}` | 401/403 if invalid cleanup secret | Plan §5, §18; ORIGINAL_REQUEST.md R1 |
| 31 | Policy Engine | Workflow Policy & Domain Allowlist | Checks workflow parameters against allowed domain list; worker strictly blocks unlisted URLs | Workflow configuration (`ALLOWED_DOMAINS`) | Approved workflow plan | Aborts navigation if domain not allowlisted | Plan §8.1; ORIGINAL_REQUEST.md R2 |
| 32 | Rate Limiting | Per-User Request Throttling | Limits endpoint usage via `slowapi` with in-memory or Redis key tracking | Client IP / Supabase User ID | Passes or returns 429 | 429 Too Many Requests (`Retry-After` header) | Plan §5, §17; rules.md §12 |

---

## 2. Detailed Technical Specifications

### 2.1 Backend Core & Architecture

#### Architecture Stack
- **Framework:** FastAPI running on **Python 3.12.7**
- **ASGI Server:** Uvicorn (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`)
- **Package Management:** `uv` / `pip` with pinned `requirements.txt`
- **Data Validation:** Pydantic v2 (`BaseModel`, `Field`, `SecretStr`, `ConfigDict`)
- **Settings Management:** `pydantic-settings` (`BaseSettings`)
- **Async HTTP:** `httpx.AsyncClient`
- **Database Client:** Supabase Python SDK (`supabase-py`) initialized with `SUPABASE_SECRET_KEY` (service role) for privileged operations; direct `asyncpg` connection for `FOR UPDATE SKIP LOCKED` transaction semantics.
- **Log Management:** Standard library `logging` with structured JSON formatting and custom `RedactingLogFilter`.

#### Directory Layout (`backend/`)
```text
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                          # FastAPI app instantiation, lifespan, middleware
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                    # Settings (Pydantic BaseSettings)
│   │   ├── logging.py                   # RedactingLogFilter, log configuration
│   │   ├── security.py                  # Supabase JWT decoding, ownership checks
│   │   ├── rate_limit.py                # slowapi limiter setup
│   │   └── exceptions.py                # Custom exceptions and global error handlers
│   ├── db/
│   │   ├── __init__.py
│   │   ├── supabase.py                  # Client with SUPABASE_SECRET_KEY
│   │   └── session.py                   # Async connection pool for queue transactions
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py                      # FastAPI dependencies (get_current_user, get_db)
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py                # v1 router aggregator
│   │       ├── health.py                # GET /health
│   │       ├── chat.py                  # POST /api/v1/chat (SSE streaming)
│   │       ├── tasks.py                 # Task CRUD, input, challenge, cancel, download
│   │       └── documents.py             # DELETE /api/v1/documents/{id}
│   ├── internal/
│   │   ├── __init__.py
│   │   ├── worker_ws.py                 # WS /internal/worker
│   │   └── cleanup.py                   # POST /internal/cleanup
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── state_machine.py             # transition(), state matrix, actor validation
│   │   ├── queue.py                     # Postgres job queue (FOR UPDATE SKIP LOCKED)
│   │   ├── challenge_broker.py          # In-memory OTP & CAPTCHA relay
│   │   └── task_service.py              # Orchestration & lifecycle management
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── provider.py                  # LLMProvider abstract interface
│   │   ├── groq_provider.py             # Groq SDK implementation (llama-3.3-70b-versatile)
│   │   ├── classifier.py                # IntentClassifier interface & IntentResult model
│   │   ├── rules_classifier.py          # Fast regex & keyword classifier
│   │   └── pii_scrubber.py              # Verhoeff algorithm + regex for PII/biometrics
│   ├── policy/
│   │   ├── __init__.py
│   │   ├── domain_allowlist.py          # Workflow domain checking
│   │   └── approval_gates.py            # Financial/irreversible action gates
│   └── workflows/
│       ├── __init__.py
│       ├── base.py                      # Workflow definition interface
│       ├── registry.py                  # Supported workflow registry
│       └── aadhaar_download.py          # Aadhaar download workflow metadata
├── tests/
│   ├── conftest.py
│   ├── test_state_machine.py
│   ├── test_pii_scrubber.py
│   ├── test_auth.py
│   ├── test_chat_sse.py
│   ├── test_challenge_broker.py
│   ├── test_queue.py
│   └── test_api_endpoints.py
├── requirements.txt
└── pyproject.toml
```

---

### 2.2 Supabase JWT Authentication & RBAC / Ownership

#### Token Structure & Verification Protocol
1. **Header Requirement:**
   `Authorization: Bearer <Supabase access_token>` on every protected route.
2. **Verification Logic:**
   - The token is a JWT signed by Supabase Auth using either asymmetric RSA/ECDSA (JWKS) or symmetric HMAC-SHA256 (project JWT secret).
   - Backend decodes and verifies the token against the Supabase project configuration (`https://<project_id>.supabase.co/auth/v1/.well-known/jwks.json` or fallback via Supabase client `supabase.auth.get_user(token)`).
   - Validates standard claims:
     - `exp`: Reject if `current_time > exp`.
     - `iss`: Must match Supabase auth issuer URL.
     - `aud`: Must be `authenticated`.
     - `sub`: Must be a valid UUID representing `user_id`.
3. **Data Model for Authenticated User:**
   ```python
   class AuthenticatedUser(BaseModel):
       id: UUID
       email: str | None = None
       role: str = "authenticated"
   ```
4. **Ownership Verification Protocol:**
   For any operation accessing a resource by ID (`task_id`, `document_id`, `conversation_id`):
   - Query resource from Supabase using service-role key.
   - If not found: return HTTP `404 Not Found` with `{"detail": "Resource not found"}`.
   - If `resource.user_id != authenticated_user.id`: return HTTP `403 Forbidden` with `{"detail": "Access forbidden: resource does not belong to the authenticated user"}`.

#### Internal Authentication Mechanisms
1. **Worker WebSocket (`WS /internal/worker`):**
   - Must present `WORKER_SHARED_SECRET`.
   - Supplied via HTTP Header `X-Worker-Secret` or query parameter `?secret=<WORKER_SHARED_SECRET>`.
   - If secret does not match constant-time comparison `hmac.compare_digest(provided, config.WORKER_SHARED_SECRET)`:
     - For WebSocket: close with code `1008 (Policy Violation)`.
2. **Cleanup Endpoint (`POST /internal/cleanup`):**
   - Must present `CLEANUP_SECRET`.
   - Supplied via HTTP Header `X-Cleanup-Secret: <CLEANUP_SECRET>`.
   - If secret does not match: return HTTP `401 Unauthorized` or `403 Forbidden`.

---

### 2.3 Strict PII & Biometric Scrubber Specification

#### Mandate
All user inputs MUST be scrubbed before:
1. Passing to any LLM prompt (Groq or Gemini).
2. Persisting into Postgres database (`messages.content`, `tasks.request_text`).
3. Emitting to log outputs or third-party monitoring.

#### Mathematical Definition: Verhoeff Algorithm for Aadhaar & VID
Aadhaar numbers are 12 digits ($a_1 a_2 \dots a_{12}$), where $a_{12}$ is the Verhoeff checksum digit. VIDs are 16 digits.
The Verhoeff algorithm operates on the dihedral group $D_5$ using three lookup tables:
1. **Multiplication table $d[10][10]$:**
   ```text
   d[i][j] = [
     [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
     [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
     [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
     [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
     [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
     [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
     [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
     [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
     [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
     [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
   ]
   ```
2. **Permutation table $p[8][10]$:**
   ```text
   p[i][j] = [
     [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
     [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
     [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
     [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
     [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
     [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
     [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
     [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]
   ]
   ```
3. **Inverse table $inv[10]$:**
   `inv = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]`

#### Verification Algorithm:
Given a number string $S$, remove spaces and hyphens:
```python
def validate_verhoeff(num_str: str) -> bool:
    if not num_str.isdigit():
        return False
    c = 0
    # Process digits in reverse order (0-indexed from right)
    for i, digit in enumerate(reversed(num_str)):
        c = d[c][p[i % 8][int(digit)]]
    return c == 0
```

#### Scrubbing Patterns & Transformation Matrix
| PII / Sensitive Element | Detection Regex / Validation Logic | Replacement Token |
|---|---|---|
| **Aadhaar Number (12 digits)** | `\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b` + `validate_verhoeff()` | `[REDACTED_AADHAAR]` |
| **Aadhaar Candidate (12 digits, unverified)** | `\b\d{4}[ -]?\d{4}[ -]?\d{4}\b` | `[REDACTED_ID_NUMBER]` |
| **Virtual ID / VID (16 digits)** | `\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b` | `[REDACTED_VID]` |
| **Indian Mobile Number** | `(?:(?:\+91[\-\s]?)|(?:\b0))?[6-9]\d{9}\b` | `[REDACTED_PHONE]` |
| **Email Address** | `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b` | `[REDACTED_EMAIL]` |
| **Biometric Keywords** | `\b(?:fingerprints?|thumbprints?|iris(?:es)?|retina(?:s)?|biometrics?|minutiae|biometric[ -]data)\b` (case-insensitive) | `[REDACTED_BIOMETRIC_DATA]` |
| **OTP / Auth Codes** | `(?i)(?:otp|code|one[ -]time[ -]password|pin|verification[ -]code)[\s:=]+(\d{4,8})\b` or standalone 6-digit near auth keywords `\b\d{6}\b` | `[REDACTED_OTP]` |

#### Redacting Log Filter
A dedicated Python logging filter:
```python
class RedactingLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = scrub_pii(record.msg)
        if record.args:
            # Recursively scrub arguments if tuple or dict
            record.args = scrub_args(record.args)
        return True
```
Must be attached to all handlers on root logger, `uvicorn`, `uvicorn.access`, `fastapi`, and worker loggers.

---

### 2.4 AI Layer & Groq LLM Provider

#### Groq Client Specification
- **SDK:** `groq` Python library (`from groq import AsyncGroq`)
- **Key:** `GROQ_API_KEY` (configured via environment)
- **Model:** `llama-3.3-70b-versatile` (configurable via `LLM_MODEL`)
- **Architecture Abstraction:**
  ```python
  class LLMProvider(ABC):
      @abstractmethod
      async def stream_chat(
          self,
          messages: list[dict[str, str]],
          system_prompt: str | None = None
      ) -> AsyncIterator[str]:
          pass

      @abstractmethod
      async def classify_intent(
          self,
          text: str,
          tools_or_schema: dict[str, Any]
      ) -> dict[str, Any]:
          pass
  ```

#### Multi-Tier Intent Classification Pipeline
```text
User Message Text
       │
       ▼
 [PII Scrubber] (Masks Aadhaar, Phone, Email, OTP)
       │
       ▼
 [RuleBasedClassifier] ──── High confidence match (confidence=1.0) ────► Task Execution
       │ (No match or low confidence)
       ▼
 [Groq LLM Tool/JSON Classifier] (`llama-3.3-70b-versatile`)
       │
       ├─ Confidence ≥ 0.8 ──► Task Orchestrator (workflow="aadhaar_download")
       │
       └─ Confidence < 0.8 ──► General Conversational Chat (Stream SSE)
```

#### Rule-Based Classifier Keyword Matrix
- Keywords: `download aadhaar`, `aadhaar card`, `get aadhaar`, `eaadhaar`, `e-aadhaar`, `uidai download`, `download my aadhaar`, `aadhaar pdf`.
- Negative Keywords: `what is aadhaar`, `how to apply for aadhaar`, `who made aadhaar`.
- If match: return `IntentResult(workflow="aadhaar_download", confidence=1.0, is_task=True)`.

#### Rate Limiting & Fallback Responses
- Rate Limit Policy:
  - Chat streaming: 15 requests per minute per authenticated user.
  - Task creation: 5 requests per minute per authenticated user.
- On HTTP 429 from Groq API:
  - Do NOT crash or display stack trace.
  - Return friendly, graceful streaming chunk:
    `"I am currently handling high traffic. Please give me a brief moment and try your request again."`

---

### 2.5 Deterministic State Machine & Postgres Job Queue

#### State Definitions
1. `RECEIVED`: Task created and queued.
2. `VALIDATING`: Validating request schemas, parameters, and domain policy.
3. `PLANNING`: Determining execution steps and worker assignment.
4. `RUNNING`: Playwright worker actively executing browser steps.
5. `WAITING_FOR_USER`: Paused for user challenge input (OTP, CAPTCHA, or approval).
6. `AUTHENTICATING`: Submitting user credentials/OTP to target portal.
7. `DOWNLOADING`: Intercepting file download stream from portal.
8. `VERIFYING`: Validating downloaded document structure, headers, and security checks.
9. `COMPLETED`: Terminal Success. **Only transitionable from `VERIFYING` after verifier approval.**
10. `FAILED`: Terminal Failure. Contains `error_code` and `error_message`.
11. `CANCELLED`: Terminal Cancellation. Cooperative cancellation initiated by user or orchestrator.
12. `EXPIRED`: Terminal Timeout. User challenge timed out (3 mins) or total task duration timed out (10 mins).

#### Complete Allowed State Transition Matrix
| Current State (`From`) | Allowed Next States (`To`) | Permitted Actors | Conditions / Invariants |
|---|---|---|---|
| `RECEIVED` | `VALIDATING`, `FAILED`, `CANCELLED` | `system`, `orchestrator`, `user` | Initial state; user may cancel immediately |
| `VALIDATING` | `PLANNING`, `FAILED`, `CANCELLED` | `orchestrator`, `user` | Validation passed -> `PLANNING`; policy rejection -> `FAILED` |
| `PLANNING` | `RUNNING`, `WAITING_FOR_USER`, `FAILED`, `CANCELLED` | `orchestrator`, `user` | Worker allocated -> `RUNNING` or `WAITING_FOR_USER` if initial credentials needed |
| `RUNNING` | `WAITING_FOR_USER`, `AUTHENTICATING`, `DOWNLOADING`, `FAILED`, `CANCELLED`, `EXPIRED` | `worker`, `orchestrator`, `system`, `user` | Worker encounters challenge -> `WAITING_FOR_USER`; download triggered -> `DOWNLOADING` |
| `WAITING_FOR_USER` | `RUNNING`, `AUTHENTICATING`, `FAILED`, `CANCELLED`, `EXPIRED` | `orchestrator`, `system`, `user` | User inputs OTP/CAPTCHA -> `AUTHENTICATING`; timeout (3m) -> `EXPIRED`; user cancels -> `CANCELLED` |
| `AUTHENTICATING` | `RUNNING`, `WAITING_FOR_USER`, `DOWNLOADING`, `FAILED`, `CANCELLED` | `worker`, `orchestrator`, `user` | Wrong OTP/CAPTCHA (attempts left > 0) -> `WAITING_FOR_USER`; max attempts (3) -> `FAILED`; auth success -> `DOWNLOADING` |
| `DOWNLOADING` | `VERIFYING`, `FAILED`, `CANCELLED` | `worker`, `orchestrator`, `user` | Download intercepted -> `VERIFYING`; timeout/network disconnect -> `FAILED` |
| `VERIFYING` | `COMPLETED`, `FAILED` | `verifier` ONLY | Valid PDF + SHA-256 computed + stored -> `COMPLETED`; corrupt/malicious PDF -> `FAILED` |
| `COMPLETED` | (None) | Terminal | Immutable state |
| `FAILED` | (None) | Terminal | Immutable state |
| `CANCELLED` | (None) | Terminal | Immutable state |
| `EXPIRED` | (None) | Terminal | Immutable state |

#### Implementation of `transition()` Function
```python
class InvalidStateTransitionError(Exception):
    def __init__(self, from_state: str, to_state: str, actor: str):
        super().__init__(f"Illegal transition from '{from_state}' to '{to_state}' by actor '{actor}'")

async def transition(
    task: Task,
    new_status: TaskStatus,
    actor: str,
    event_message: str,
    progress: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    db_session: Any = None
) -> Task:
    # 1. Check if current state is terminal
    if task.status in TERMINAL_STATES:
        raise InvalidStateTransitionError(task.status, new_status, actor)
    
    # 2. Check transition matrix
    allowed = ALLOWED_TRANSITIONS.get(task.status, set())
    if new_status not in allowed:
        raise InvalidStateTransitionError(task.status, new_status, actor)
        
    # 3. Special actor guard: Only verifier can transition VERIFYING -> COMPLETED
    if task.status == TaskStatus.VERIFYING and new_status == TaskStatus.COMPLETED:
        if actor != "verifier":
            raise InvalidStateTransitionError(task.status, new_status, actor)

    # 4. Update task record
    task.status = new_status
    task.updated_at = datetime.now(timezone.utc)
    if new_status in TERMINAL_STATES:
        task.finished_at = datetime.now(timezone.utc)
    if error_code:
        task.error_code = error_code
        task.error_message = error_message

    # 5. Insert task_event for Realtime audit & UI stepper
    await insert_task_event(
        task_id=task.id,
        user_id=task.user_id,
        status=new_status.value,
        message=event_message,
        progress=progress
    )
    return task
```

#### Postgres Job Queue (`FOR UPDATE SKIP LOCKED`)
Workers or orchestrator background tasks fetch pending work directly from Postgres without Redis:
```sql
BEGIN;
SELECT id, user_id, workflow, request_text, idempotency_key
FROM public.tasks
WHERE status = 'RECEIVED'
ORDER BY created_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED;

-- Upon selecting row:
UPDATE public.tasks
SET status = 'VALIDATING', updated_at = now()
WHERE id = :selected_task_id;

COMMIT;
```
This guarantees concurrency safety across multiple API/worker instances without duplicate assignments or race conditions.

#### Idempotency & Duplicate Execution Protection
1. **Per-user Idempotency Key:**
   Database table `tasks` has `unique (user_id, idempotency_key)`.
   If a client resubmits a request with the same `Idempotency-Key` header, the existing task is returned immediately with HTTP 200 rather than creating a duplicate.
2. **One Active Task Per Workflow Rule:**
   Partial unique index:
   ```sql
   create unique index one_active_task_per_workflow on public.tasks (user_id, workflow)
     where status not in ('COMPLETED','FAILED','CANCELLED','EXPIRED');
   ```
   If a user attempts to spawn a second concurrent task for the same workflow while one is active, the database raises a unique constraint violation and the API responds with HTTP 409 Conflict:
   `{"detail": "An active task for workflow 'aadhaar_download' is already in progress. Please complete or cancel it first."}`

---

### 2.6 Challenge Broker (Zero-Persistence In-Memory Relay)

#### Zero-Persistence Mandates
- OTP codes and CAPTCHA answers represent transient authorization credentials.
- **NEVER** write OTP or CAPTCHA values to:
  - Database tables (`tasks`, `task_events`, `messages`, `profiles`).
  - Application logs (`RedactingLogFilter` scrubs any accidental leakage).
  - Supabase Realtime payloads (`pending_input` contains only `{kind, prompt, expires_at, attempts_left}`).
  - LLM prompts.
- All values MUST be wrapped in Pydantic `SecretStr` in memory and dereferenced only at the moment of forwarding over the WebSocket to the worker.

#### Architecture of Challenge Broker
```python
@dataclass
class ActiveChallenge:
    task_id: UUID
    input_id: str
    kind: Literal["CAPTCHA", "OTP", "APPROVAL"]
    prompt: str
    expires_at: datetime
    attempts_left: int
    image_bytes: bytes | None = None  # Populated only for CAPTCHA
    future: asyncio.Future[SecretStr] = field(default_factory=asyncio.Future)

class ChallengeBroker:
    def __init__(self):
        self._challenges: dict[UUID, ActiveChallenge] = {}

    def register_challenge(self, task_id: UUID, kind: str, prompt: str, image_bytes: bytes | None = None) -> ActiveChallenge:
        # Create challenge with 3-minute expiry and 3 attempts
        ...
        
    async def submit_input(self, task_id: UUID, input_id: str, value: SecretStr) -> bool:
        challenge = self._challenges.get(task_id)
        if not challenge or challenge.input_id != input_id or datetime.now(timezone.utc) > challenge.expires_at:
            return False
        if not challenge.future.done():
            challenge.future.set_result(value)
        return True

    def get_challenge_image(self, task_id: UUID) -> bytes | None:
        challenge = self._challenges.get(task_id)
        return challenge.image_bytes if challenge else None

    def clear(self, task_id: UUID):
        self._challenges.pop(task_id, None)
```

#### Step-by-Step Challenge Flow:
1. **Worker pauses at CAPTCHA/OTP:**
   - Worker sends WebSocket message: `{"type": "challenge_needed", "task_id": "...", "kind": "CAPTCHA", "image_base64": "..."}`.
   - Broker stores image in memory.
   - Backend transitions task to `WAITING_FOR_USER` with `pending_input = {"kind": "CAPTCHA", "input_id": "...", "expires_at": "...", "attempts_left": 3}`.
2. **Flutter retrieves CAPTCHA image:**
   - `GET /api/v1/tasks/{id}/challenge` returns raw binary PNG with headers:
     - `Content-Type: image/png`
     - `Cache-Control: no-store, no-cache, must-revalidate, max-age=0`
     - `Pragma: no-cache`
3. **User submits solution:**
   - `POST /api/v1/tasks/{id}/input` with `{input_id: "...", value: "ABC12"}` (parsed as `SecretStr`).
   - Broker resolves `challenge.future`.
   - Backend relays payload over WebSocket to worker: `{"type": "challenge_response", "task_id": "...", "value": "ABC12"}`.
   - Memory reference in broker is cleared immediately.

---

### 2.7 Complete Backend API Endpoints & Contracts

#### 1. `GET /health`
- **Authentication:** Public (no auth required)
- **Purpose:** Render health check probe & client warm-up trigger
- **Request:** None
- **Response (200 OK):**
  ```json
  {
    "status": "healthy",
    "version": "1.0.0",
    "environment": "development",
    "timestamp": "2026-10-13T06:30:00Z"
  }
  ```
- **Error Codes:** 503 Service Unavailable (if internal database is unreachable)

---

#### 2. `POST /api/v1/chat`
- **Authentication:** `Authorization: Bearer <token>`
- **Headers Required:** `Idempotency-Key: <unique-string>`
- **Rate Limit:** 15 requests / minute
- **Request Body (`ChatRequest`):**
  ```json
  {
    "conversation_id": "123e4567-e89b-12d3-a456-426614174000",
    "text": "Please help me download my Aadhaar card"
  }
  ```
  *(Note: `conversation_id` is optional; if omitted, a new conversation is created).*
- **Processing Pipeline:**
  1. Verify token & get user.
  2. Scrub PII from `text`.
  3. Store user message in `public.messages` (PII-scrubbed).
  4. Run `IntentClassifier`.
  5. If `is_task` (e.g. `aadhaar_download`):
     - Create task record in `public.tasks` with status `RECEIVED`.
     - Return SSE event with task detection metadata.
  6. If general chat:
     - Stream assistant response tokens from Groq API via SSE.
     - Store assistant message in `public.messages`.
- **Response:** `Content-Type: text/event-stream`
  **SSE Event Examples:**
  - Token chunk:
    ```text
    event: token
    data: {"text": "I can help "}

    event: token
    data: {"text": "you download your Aadhaar."}
    ```
  - Task triggered:
    ```text
    event: task_created
    data: {"task_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "workflow": "aadhaar_download", "status": "RECEIVED"}
    ```
  - Completion:
    ```text
    event: done
    data: {"message_id": "8fa85f64-5717-4562-b3fc-2c963f66afb7"}
    ```
- **Error Responses:**
  - 400 Bad Request: Missing text or invalid parameters.
  - 401 Unauthorized: Invalid/missing token.
  - 429 Too Many Requests: Rate limit exceeded.

---

#### 3. `POST /api/v1/tasks`
- **Authentication:** `Authorization: Bearer <token>`
- **Headers Required:** `Idempotency-Key: <string>`
- **Request Body (`CreateTaskRequest`):**
  ```json
  {
    "workflow": "aadhaar_download",
    "request_text": "Download Aadhaar with VID"
  }
  ```
- **Response (201 Created) (`TaskResponse`):**
  ```json
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "user_id": "123e4567-e89b-12d3-a456-426614174000",
    "workflow": "aadhaar_download",
    "status": "RECEIVED",
    "created_at": "2026-10-13T06:30:00Z"
  }
  ```
- **Error Responses:**
  - 400 Bad Request: Unsupported workflow.
  - 409 Conflict: An active task for this workflow is already running.

---

#### 4. `GET /api/v1/tasks/{id}`
- **Authentication:** `Authorization: Bearer <token>`
- **Request:** Path parameter `id` (UUID)
- **Response (200 OK) (`TaskDetailResponse`):**
  ```json
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "workflow": "aadhaar_download",
    "status": "WAITING_FOR_USER",
    "pending_input": {
      "kind": "OTP",
      "prompt": "Enter the 6-digit OTP sent to your registered mobile",
      "expires_at": "2026-10-13T06:33:00Z",
      "attempts_left": 3
    },
    "error_code": null,
    "error_message": null,
    "created_at": "2026-10-13T06:30:00Z",
    "updated_at": "2026-10-13T06:31:00Z",
    "finished_at": null
  }
  ```
- **Error Responses:**
  - 401 Unauthorized
  - 403 Forbidden (task belongs to another user)
  - 404 Not Found

---

#### 5. `POST /api/v1/tasks/{id}/input`
- **Authentication:** `Authorization: Bearer <token>`
- **Request Body (`TaskInputSubmission`):**
  ```json
  {
    "input_id": "inp_987654321",
    "value": "123456"
  }
  ```
  *(Note: Model definition uses `value: SecretStr`).*
- **Validation Rules:**
  - If challenge `kind == "OTP"`: `value` MUST match `^\d{6}$`.
  - If challenge `kind == "CAPTCHA"`: `value` MUST match `^[A-Za-z0-9]{4,8}$`.
  - Rejects submissions if task is not in `WAITING_FOR_USER`.
  - Rejects submissions if expired (`current_time > expires_at`).
- **Response (200 OK):**
  ```json
  {
    "status": "accepted",
    "message": "Input received and relayed to worker"
  }
  ```
- **Error Responses:**
  - 400 Bad Request: Invalid format, invalid task state, or expired challenge.
  - 403 Forbidden: Ownership mismatch.
  - 404 Not Found: Task or input ID not found.

---

#### 6. `GET /api/v1/tasks/{id}/challenge`
- **Authentication:** `Authorization: Bearer <token>`
- **Purpose:** Fetches current CAPTCHA image bytes directly from in-memory challenge broker.
- **Response (200 OK):**
  - Content-Type: `image/png` or `image/jpeg`
  - Headers:
    - `Cache-Control: no-store, no-cache, must-revalidate, max-age=0`
    - `Pragma: no-cache`
  - Body: Binary image bytes.
- **Error Responses:**
  - 404 Not Found: No active CAPTCHA challenge found for this task.

---

#### 7. `POST /api/v1/tasks/{id}/cancel`
- **Authentication:** `Authorization: Bearer <token>`
- **Purpose:** Cooperatively cancel an ongoing task.
- **Response (200 OK):**
  ```json
  {
    "status": "cancelled",
    "task_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
  }
  ```
- **Error Responses:**
  - 400 Bad Request: Task is already in terminal state (`COMPLETED`, `FAILED`, `EXPIRED`).
  - 403 Forbidden: Ownership mismatch.
  - 404 Not Found.

---

#### 8. `GET /api/v1/tasks/{id}/download`
- **Authentication:** `Authorization: Bearer <token>`
- **Purpose:** Generate temporary signed URL for verified document.
- **Response (200 OK):**
  ```json
  {
    "download_url": "https://rsftbslckmdkynprmpin.supabase.co/storage/v1/object/sign/documents/123e4567/3fa85f64.pdf?token=...",
    "expires_in_seconds": 60,
    "file_name": "eaadhaar.pdf",
    "size_bytes": 145020,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  }
  ```
- **Error Responses:**
  - 400 Bad Request: Task has not completed or verified document does not exist.
  - 403 Forbidden: Ownership mismatch.
  - 404 Not Found.

---

#### 9. `DELETE /api/v1/documents/{id}`
- **Authentication:** `Authorization: Bearer <token>`
- **Purpose:** Delete document record from Postgres AND delete binary object from Supabase Storage bucket.
- **Response (200 OK):**
  ```json
  {
    "status": "deleted",
    "document_id": "d123e456-e89b-12d3-a456-426614174000"
  }
  ```
- **Error Responses:**
  - 403 Forbidden: Ownership mismatch.
  - 404 Not Found: Document not found.

---

#### 10. `WS /internal/worker`
- **Authentication:** `X-Worker-Secret` header or `?secret=<WORKER_SHARED_SECRET>`
- **Protocol:** WebSocket (JSON message framing)
- **Message Types (Worker -> Backend):**
  - `{"type": "worker_ready", "worker_id": "w1"}`
  - `{"type": "task_progress", "task_id": "...", "status": "RUNNING", "message": "Navigating to portal", "progress": 25}`
  - `{"type": "challenge_created", "task_id": "...", "kind": "CAPTCHA", "image_base64": "..."}`
  - `{"type": "challenge_created", "task_id": "...", "kind": "OTP"}`
  - `{"type": "challenge_rejected", "task_id": "...", "reason": "WRONG_OTP", "attempts_left": 2}`
  - `{"type": "download_completed", "task_id": "...", "temp_path": "...", "file_bytes": "..."}`
  - `{"type": "task_failed", "task_id": "...", "error_code": "PORTAL_TIMEOUT", "error_message": "..."}`
- **Message Types (Backend -> Worker):**
  - `{"type": "task_assigned", "task": { ... }}`
  - `{"type": "challenge_input", "task_id": "...", "kind": "OTP", "value": "123456"}`
  - `{"type": "task_cancel", "task_id": "..."}`
- **Error / Disconnect Behavior:**
  - Invalid secret -> Close connection with code 1008.
  - Worker disconnect -> Backend marks in-flight task as `FAILED` (or retries if within retry budget).

---

#### 11. `POST /internal/cleanup`
- **Authentication:** `X-Cleanup-Secret: <CLEANUP_SECRET>`
- **Purpose:** Trigger retention sweep (called hourly by GitHub Actions `cleanup.yml`).
- **Processing Logic:**
  1. Find documents where `delete_after <= now()`.
  2. For each document: delete object from Supabase Storage bucket `documents`.
  3. Delete rows from `public.documents`.
  4. Find tasks in terminal states older than retention period (e.g. 30 days) and archive/clean.
- **Response (200 OK):**
  ```json
  {
    "status": "completed",
    "deleted_documents": 4,
    "deleted_storage_objects": 4,
    "timestamp": "2026-10-13T06:30:00Z"
  }
  ```
- **Error Responses:**
  - 401 / 403: Invalid cleanup secret.

---

## 3. Edge Cases & Observed Failure Behaviors

| # | Feature | Input / Condition | Observed / Required Behavior |
|---|---------|-------------------|-----------------------------|
| 1 | PII Scrubber | Input contains valid Aadhaar number with hyphens (`1234-5678-9012` where Verhoeff passes) | Correctly parses, validates Verhoeff, and masks to `[REDACTED_AADHAAR]`. |
| 2 | PII Scrubber | Input contains 12-digit number that FAILS Verhoeff check (e.g. `123456789013`) | Detected as candidate ID; masked to `[REDACTED_ID_NUMBER]` to ensure zero accidental PII leakage. |
| 3 | PII Scrubber | Indian phone number with spaces and +91 (`+91 98765 43210`) | Regex normalizes spaces and matches prefix; masks to `[REDACTED_PHONE]`. |
| 4 | PII Scrubber | General 6-digit integer in non-auth text ("The population is 450000 people") | Preserved untouched because it is not in OTP context or adjacent to auth trigger keywords. |
| 5 | PII Scrubber | User enters OTP in chat text ("my otp is 987654") | Detected by auth keyword proximity and masked to `"my otp is [REDACTED_OTP]"`; rejected from LLM prompt. |
| 6 | Logging Filter | Code calls `logger.info(f"User OTP: {otp_val}")` | `RedactingLogFilter` intercepts record message; output in console/file is `User OTP: [REDACTED_OTP]`. |
| 7 | Auth Gate | Request with expired Supabase JWT token | Decoded claims show `exp < now()`; endpoint immediately returns HTTP 401 with standard error JSON. |
| 8 | Ownership Gate | User A calls `GET /api/v1/tasks/{user_b_task_id}` | Query resolves task belonging to User B; endpoint denies access with HTTP 403 Forbidden. |
| 9 | State Machine | Client attempts illegal transition: `RECEIVED` -> `COMPLETED` | `transition()` checks allowed transitions matrix; raises `InvalidStateTransitionError`; task remains `RECEIVED`. |
| 10 | State Machine | Orchestrator attempts to transition `VERIFYING` -> `COMPLETED` with actor `"orchestrator"` | Rejected! Only actor `"verifier"` can execute this transition after file integrity checks succeed. |
| 11 | Job Queue | Two worker instances poll `public.tasks` concurrently using `FOR UPDATE SKIP LOCKED` | Postgres locks row for Worker 1; Worker 2 skips the locked row and receives the next available task (or empty). |
| 12 | Task Creation | User submits identical request with same `Idempotency-Key` header | Database unique constraint `(user_id, idempotency_key)` caught; returns original task with HTTP 200 without creating new task. |
| 13 | Task Creation | User submits a new task for `aadhaar_download` while one is already in `RUNNING` status | Partial unique index `one_active_task_per_workflow` triggers unique violation; API returns HTTP 409 Conflict. |
| 14 | Challenge Broker | User submits OTP after 3-minute challenge expiry has elapsed | `POST /input` checks `current_time > expires_at`; returns HTTP 400 Bad Request (`"Challenge expired"`). Task moves to `EXPIRED`. |
| 15 | Challenge Broker | User submits OTP with invalid format (e.g. 5 digits `"12345"` or letters `"12345a"`) | Pydantic regex validator fails; returns HTTP 422 Unprocessable Entity; challenge attempt count is not decremented. |
| 16 | Challenge Broker | Worker reports wrong OTP from portal 3 consecutive times | `attempts_left` decrements from 3 to 0; on 0 attempts remaining, task transitions to `FAILED` with error `EXCEEDED_MAX_OTP_ATTEMPTS`. |
| 17 | Challenge Broker | CAPTCHA image requested via `GET /challenge` after solution was already submitted | Broker cleared in-memory image upon submission; endpoint returns HTTP 404 Not Found. |
| 18 | AI Layer | Groq API responds with HTTP 429 Rate Limit during SSE stream | Caught in generator; yields graceful friendly message (`"High traffic, please wait..."`) and terminates SSE cleanly with `event: done`. |
| 19 | Document Download | Client calls `GET /download` on a task whose status is `DOWNLOADING` or `FAILED` | Check enforces `task.status == COMPLETED` and document exists; returns HTTP 400 Bad Request. |
| 20 | Document Deletion | Storage object deletion succeeds, but DB deletion fails | Handled within transaction / compensation pattern: Storage deletion executed only after verifying row ownership; errors logged. |
| 21 | Internal Worker | Worker connects to `WS /internal/worker` with missing or wrong secret | WebSocket handshake evaluated; connection rejected immediately with WS close code 1008 (Policy Violation). |
| 22 | Internal Cleanup | Cleanup cron called with invalid secret | Returns HTTP 401 Unauthorized; zero database or storage operations executed. |
| 23 | Ephemeral Storage | API restarted on Render (free tier container restart) | In-memory challenge broker resets; active pending tasks in `WAITING_FOR_USER` time out gracefully via Postgres timestamp checks. |

---

## 4. Acceptance Criteria & Verification Matrix

| Area | Requirement | Verification Method |
|---|---|---|
| **Zero-Persistence** | OTP and CAPTCHA never persisted in DB, logs, or Realtime | Automated audit test inspecting database rows, stdout logs, and Realtime messages after test run |
| **Aadhaar Masking** | 12-digit Aadhaar / VID masked in all outbound LLM prompts | Unit test in `test_pii_scrubber.py` with known Verhoeff-valid numbers and invalid permutations |
| **State Machine** | All 12 states adhere strictly to transition matrix | Unit test in `test_state_machine.py` iterating through all permitted and forbidden transition edges |
| **Ownership Isolation** | User A cannot view/cancel/download User B's resources | Integration test in `test_auth.py` creating tasks under User A and querying with User B JWT |
| **Streaming SSE** | `/api/v1/chat` emits proper SSE tokens and task creation events | Integration test in `test_chat_sse.py` testing streaming chunk parsing and JSON deserialization |
| **Postgres Queue** | Concurrency safety via `FOR UPDATE SKIP LOCKED` | Integration test in `test_queue.py` simulating concurrent worker polling |
| **Storage Security** | Document downloads use 60-second signed URLs only | Test in `test_api_endpoints.py` asserting signed URL format and expiration parameter |
