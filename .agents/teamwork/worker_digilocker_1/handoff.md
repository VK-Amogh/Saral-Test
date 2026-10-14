# Handoff Report: DigiLocker OAuth2 / IndiaStack Fallback Route (M2_DIGILOCKER)

**Agent**: `worker_digilocker_1`  
**Date**: 2026-10-13  
**Status**: Completed  
**Artifact Path**: `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\worker_digilocker_1\handoff.md`  

---

## 1. Observation

### 1.1 Requirements & Scope
The assignment specified implementing the official DigiLocker OAuth2 fallback route for e-Aadhaar document retrieval within the Saral AI FastAPI backend:
1. `backend/app/services/digilocker_service.py`:
   - Generate OAuth2 consent URL with client ID, redirect URI, scope (`read`), and HMAC-SHA256 signed state token embedding `task_id`, `user_id`, and `expires_at` (180s TTL).
   - Validate HMAC signature and TTL expiration on callback state tokens.
   - Exchange authorization code for access token via `httpx` async client.
   - Stream e-Aadhaar PDF bytes directly into memory without disk persistence.
   - Pass retrieved bytes to `verify_document_security()` (`backend/app/worker/verifier.py`).
   - Upload verified bytes to private Supabase Storage `documents/{user_id}/{task_id}.pdf` via service-role client, insert record into `public.documents`, and transition task to `COMPLETED` strictly with `actor="verifier"`.
2. `backend/app/api/digilocker.py`:
   - `GET /api/v1/digilocker/authorize/{task_id}`: Returns consent URL for the citizen.
   - `GET /api/v1/digilocker/callback`: Validates state HMAC, executes token exchange, document retrieval, 5-point verification, storage upload, and task completion.
   - Register router in `backend/app/main.py` under prefix `/api/v1/digilocker`.
3. `backend/app/api/tasks.py`:
   - When `workflow == "aadhaar_digilocker"`, initialize task in `RECEIVED` -> `VALIDATING` -> `PLANNING` -> `WAITING_FOR_USER` with `pending_input` metadata exposing `kind="oauth_consent"` and `auth_url`.
4. `backend/tests/test_digilocker.py`:
   - Comprehensive test suite covering consent generation, tampered/expired state rejection, mocked token/file APIs, 5-point verification, storage upload, and verifier-only gate.

### 1.2 Implemented Changes
- **`backend/app/services/digilocker_service.py`**:
  - Implemented `generate_digilocker_state(task_id, user_id, secret, ttl_seconds=180)`: generates `{b64_payload}.{hmac_sha256_hex}`.
  - Implemented `verify_digilocker_state(state, secret)`: validates HMAC-SHA256 signature using `hmac.compare_digest` and verifies `time.time() <= expires_at`. Raises `DigiLockerStateInvalidError` on tampering/corruption and `DigiLockerStateExpiredError` on expired tokens.
  - Implemented `DigiLockerService.generate_consent_url()`: constructs DigiLocker OAuth2 consent URL with `response_type=code`, `client_id`, `redirect_uri`, `scope=read`, and signed `state`.
  - Implemented `DigiLockerService.exchange_code_for_token()`: async POST to DigiLocker token endpoint returning `SecretStr` encapsulated access token.
  - Implemented `DigiLockerService.fetch_eaadhaar_document()`: async GET to DigiLocker file API streaming binary PDF payload into memory.
  - Implemented `DigiLockerService.verify_document()`: invokes 5-point security inspection via `DocumentVerifier(min_size_bytes=100, max_size_mb=5)`.
  - Implemented `DigiLockerService.upload_and_save_document()`: stores file bytes into `store.storage_objects[f"{user_id}/{task_id}.pdf"]`, records document in `store.documents[doc_id]`, and triggers Supabase Storage REST upload if remote URL is configured.
  - Implemented `DigiLockerService.process_callback()`: orchestrates transitions `WAITING_FOR_USER` -> `RUNNING` -> `DOWNLOADING` -> `VERIFYING` -> `COMPLETED`, strictly enforcing `actor="verifier"` on completion transition.
- **`backend/app/api/digilocker.py`**:
  - `GET /authorize/{task_id}`: enforces Bearer token authentication (`get_current_user`), ownership validation, status transition to `WAITING_FOR_USER`, and returns `{task_id, auth_url, status, expires_in}`.
  - `GET /callback`: accepts `code` and `state`, validates HMAC and TTL (returns HTTP 400 on invalid/expired), processes token exchange and document retrieval, executes 5-point inspection, and returns `{status: "COMPLETED", task_id, document_id, sha256, pdf_encrypted}`.
- **`backend/app/main.py`**:
  - Imported `digilocker_router` and registered with `app.include_router(digilocker_router, prefix="/api/v1/digilocker")`.
- **`backend/app/api/tasks.py`**:
  - Updated `create_task()`: when `workflow == "aadhaar_digilocker"`, transitions task from `RECEIVED` -> `VALIDATING` -> `PLANNING` -> `WAITING_FOR_USER` and attaches `pending_input` metadata with `kind="oauth_consent"` and `auth_url`.
- **`backend/tests/test_digilocker.py`**:
  - 14 automated unit and integration tests covering all positive and negative pathways.

### 1.3 Test Execution Results
- `uv run --with pytest pytest backend/tests/test_digilocker.py -v`:
  - **14 passed** in 0.18s.
- `uv run --with pytest pytest backend/tests/ -v`:
  - **44 passed** (30 existing + 14 new) in 0.52s.
- `uv run --with pytest pytest backend/app/worker/test_worker.py -v`:
  - **23 passed** in 0.81s.
- `uv run --with pytest python run_e2e_tests.py`:
  - **84 passed** across all 4 tiers in 4.59s.
- Total passed tests: **151 passed, 0 failures**.

---

## 2. Logic Chain

1. **State Machine Compliance**:
   - `TaskState.RECEIVED` -> `TaskState.VALIDATING` -> `TaskState.PLANNING` -> `TaskState.WAITING_FOR_USER` are all permitted consecutive edges in `ALLOWED_TRANSITIONS`.
   - On authorization callback, the task transitions `WAITING_FOR_USER` -> `RUNNING` -> `DOWNLOADING` -> `VERIFYING` -> `COMPLETED`.
   - Every intermediate transition is authorized for `actor="orchestrator"`.
   - Transition from `VERIFYING` to `COMPLETED` is strictly gated to `actor="verifier"`. Calling `transition(task, TaskState.COMPLETED, actor="orchestrator")` raises `UnauthorizedActorError`.
2. **Cryptographic State Security**:
   - The OAuth2 state token embeds `task_id`, `user_id`, `nonce`, and `expires_at` (180s TTL).
   - HMAC-SHA256 signature guarantees tamper resistance: any bit alteration in payload or signature causes `hmac.compare_digest` to return False, immediately raising `DigiLockerStateInvalidError` (HTTP 400).
   - Expiration verification checks `time.time() > expires_at`, raising `DigiLockerStateExpiredError` (HTTP 400).
3. **Zero Persistence & In-Memory Streaming**:
   - DigiLocker access tokens are wrapped in `SecretStr` and never persisted to Postgres, disk, or logs.
   - Streamed e-Aadhaar PDF bytes reside strictly in memory (`bytes` objects) and are validated directly via `verify_document_security()`. No unverified temporary files are written to disk.
4. **Multi-Tenant Isolation**:
   - `GET /api/v1/digilocker/authorize/{task_id}` requires matching authenticated user ID (`task["user_id"] == user.user_id`).
   - State verification embeds the authenticated `user_id`, preventing session swapping or cross-user token reuse.
   - Storage upload path strictly follows `documents/{user_id}/{task_id}.pdf`.

---

## 3. Caveats

- In production environments, official DigiLocker OAuth2 credentials (`DIGILOCKER_CLIENT_ID` and `DIGILOCKER_CLIENT_SECRET`) must be obtained from partners.digilocker.gov.in or IndiaStack API Setu. In local development and automated testing, mock credentials and endpoints are utilized with full HTTP mocks.
- DigiLocker supports both PDF download (`/file/{doc_uri}`) and XML credential download (`/xml/eaadhaar`). The implementation focuses on direct PDF binary retrieval, satisfying the 5-point document security verifier and vault display.

---

## 4. Conclusion

The DigiLocker OAuth2 / IndiaStack fallback route has been fully implemented, integrated, and verified:
- Consent URL generation with HMAC-SHA256 state token is active.
- State tampering and expiration are securely rejected with HTTP 400.
- `POST /api/v1/tasks` with `workflow="aadhaar_digilocker"` transitions directly to `WAITING_FOR_USER` exposing `pending_input` metadata.
- `GET /api/v1/digilocker/authorize/{task_id}` and `GET /api/v1/digilocker/callback` are registered under `/api/v1/digilocker`.
- Streamed PDF bytes pass 5-point document security inspection.
- Tasks transition to `COMPLETED` strictly via `actor="verifier"`.
- 100% of tests pass across `backend/tests/test_digilocker.py`, `backend/tests/test_backend.py`, `backend/app/worker/test_worker.py`, and `run_e2e_tests.py` (151 total tests passed).

---

## 5. Verification Method

To independently reproduce and verify this implementation:

```bash
# 1. Run DigiLocker unit and integration test suite (14 tests)
uv run --with pytest pytest backend/tests/test_digilocker.py -v

# 2. Run full backend test suite (44 tests)
uv run --with pytest pytest backend/tests/ -v

# 3. Run worker test suite (23 tests)
uv run --with pytest pytest backend/app/worker/test_worker.py -v

# 4. Run full E2E 4-tier test runner (84 tests)
uv run --with pytest python run_e2e_tests.py
```

All commands must exit with code 0 and report 100% passing tests.
