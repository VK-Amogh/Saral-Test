## 2026-10-13T14:36:29Z
Your identity: worker_digilocker_1
Your working directory: d:\Startup\Saral Ai\Saral_app\.agents\teamwork\worker_digilocker_1\
Original request path (MANDATORY TO READ FIRST): d:\Startup\Saral Ai\Saral_app\.agents\teamwork\ORIGINAL_REQUEST.md
Scope path: d:\Startup\Saral Ai\Saral_app\.agents\teamwork\teamwork_preview_orchestrator_2\SCOPE.md
Investigation blueprint: d:\Startup\Saral Ai\Saral_app\.agents\teamwork\explorer_survey_2_2\handoff.md

DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Exclusively Owned Files:
- backend/app/api/digilocker.py
- backend/app/services/digilocker_service.py
- backend/app/api/tasks.py
- backend/app/main.py
- backend/tests/test_digilocker.py

Mission & Tasks:
1. Implement `backend/app/services/digilocker_service.py`:
   - DigiLocker OAuth2 consent URL generation with client ID, redirect URI, scope (`read`), and HMAC-SHA256 signed state token embedding `task_id`, `user_id`, and `expires_at`.
   - HMAC state validation verifying signature and timestamp expiration (180s TTL).
   - DigiLocker token exchange (exchange authorization code for access token via `httpx` async client).
   - DigiLocker document fetch: streams e-Aadhaar PDF bytes directly into memory without disk storage.
   - Verification invocation: passes bytes to `verify_document_security()` from `backend/app/worker/verifier.py`.
   - Upload verified bytes to private Supabase Storage `documents/{user_id}/{task_id}.pdf` via service-role client, insert record into `public.documents`, and transition task to `COMPLETED` strictly with `actor="verifier"`.
2. Implement `backend/app/api/digilocker.py`:
   - `GET /api/v1/digilocker/authorize/{task_id}`: Returns DigiLocker consent URL for the citizen.
   - `GET /api/v1/digilocker/callback`: Callback endpoint receiving `code` and `state`, validating HMAC, executing token exchange, document retrieval, verification, storage upload, and task completion.
   - Include router in `backend/app/main.py` under prefix `/api/v1/digilocker`.
3. Support DigiLocker workflow in `backend/app/api/tasks.py`:
   - When `workflow == "aadhaar_digilocker"`, task initializes in `RECEIVED` -> `VALIDATING` -> `PLANNING` -> `WAITING_FOR_USER` with `pending_input` metadata exposing `kind="oauth_consent"` and `auth_url`.
4. Write tests in `backend/tests/test_digilocker.py`:
   - Test consent URL generation and valid HMAC state.
   - Test tampered / expired state rejection (HTTP 400).
   - Test authorization callback with mocked DigiLocker token & file API, verifying full 5-point verification, Supabase storage upload, and verifier-only completion gate.
5. Run tests:
   `uv run --with pytest pytest backend/tests/test_digilocker.py -v`
   `uv run --with pytest pytest backend/tests/ -v`
   Ensure all tests pass without errors.
6. Write your handoff report to:
   `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\worker_digilocker_1\handoff.md`
Then send a brief message with your handoff path.
