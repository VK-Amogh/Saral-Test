# Saral AI — End-to-End Testing Infrastructure (TEST_INFRA.md)

**Version:** 1.0  
**Status:** ACTIVE  
**Integrity Mode:** Opaque-Box, Requirement-Driven, Specification-Grounded  
**Target Architecture:** FastAPI Backend + Mock Government Portal + Playwright Automation Worker + Supabase RLS/Storage  

---

## 1. Test Philosophy

The Saral AI end-to-end testing suite is built on four core tenets:

1. **Opaque-Box Requirement-Driven Testing:**
   All tests are derived strictly from documented requirements in `ORIGINAL_REQUEST.md`, `PROJECT.md`, and `SARAL_AI_IMPLEMENTATION_PLAN.md`. Tests interact solely through observable system boundaries: HTTP REST endpoints, Server-Sent Events (SSE) streams, WebSocket protocols, Supabase RLS queries, storage paths, and simulated DOM interactions. No test depends on internal function signatures or private state.

2. **Progressive Testability & Dual-Mode Execution:**
   The test harness supports two execution modes:
   - **Specification Oracle Harness (Default / Offline):** Emulates live services using an integrated ASGI specification oracle verifying protocol contracts, deterministic state machine transitions, Verhoeff checksum algorithms, 5-point PDF verifier logic, in-memory challenge relay, and multi-tenant security policies without requiring cloud infrastructure to be booted.
   - **Live Integration Mode (`E2E_LIVE=1`):** Executes identical test suites against live running processes (`http://127.0.0.1:8000` for backend, `http://127.0.0.1:8001` for mock portal, and cloud Supabase).

3. **Strict Test Integrity & Oracle Derivation:**
   Every test case possesses an authoritative expected output:
   - **HTTP Codes:** Explicitly matched (200, 201, 400, 401, 403, 404, 409, 422, 429).
   - **State Machine Transitions:** Enforces the 12-state matrix from `SARAL_AI_IMPLEMENTATION_PLAN.md § 6`.
   - **Zero-Persistence Verification:** Explicitly asserts OTP and CAPTCHA strings never appear in database records, task status payloads, or error messages.
   - **Document Verifier Rules:** Rejects non-PDF payloads, oversized documents (>5MB), and files containing malicious `/JavaScript` or `/Launch` dictionaries.

4. **Adversarial & Boundary Verification:**
   Adversarial checks ensure encoding fidelity, prompt injection defense, Verhoeff dihedral D5 validation, brute-force rate-limiting, and graceful failure recovery without data leaks or system lockups.

---

## 2. Four-Tier Testing Methodology

```
+---------------------------------------------------------------------------------+
| TIER 4: Real-World User Scenarios (Workload / Multi-Step User Journeys)         |
|         - Full Aadhaar Download, Wrong CAPTCHA Retry, Expired OTP, Cancel      |
+---------------------------------------------------------------------------------+
| TIER 3: Pairwise Combinations (Cross-Feature Integrations & Pipelines)          |
|         - Auth + Realtime, Scrubber + Chat + Task, Challenge + SecretStr        |
+---------------------------------------------------------------------------------+
| TIER 2: Boundaries & Corners (Boundary Value Analysis / Chaos / Limits)        |
|         - 3x OTP Lockout, 180s Timeouts, 5MB File Limit, Malicious PDFs        |
+---------------------------------------------------------------------------------+
| TIER 1: Feature Coverage (Category-Partition / Individual Feature Baselines)   |
|         - Auth, Chat SSE, Tasks, State Machine, Inputs, Downloads, Cleanup     |
+---------------------------------------------------------------------------------+
```

### Tier 1: Category-Partition Feature Coverage
Verifies each functional domain in isolation using equivalence partitioning. Provides at least 5 distinct test cases per critical feature category:
- **Authentication & Authorization (F8–F10):** Public access, JWT enforcement, invalid token rejection, multi-tenant task and document isolation.
- **Chat SSE Streaming (F18–F20):** SSE streaming format, `Idempotency-Key` requirement, task intent classification, conversation continuity, PII redaction in stream.
- **Task Lifecycle (F21, F24, F25, F28, F29, F32):** Direct creation, deduplication via idempotency keys, single active workflow per user constraint, task cancellation.
- **Deterministic State Machine (F21, F22):** Legal transition paths, illegal transition rejection, strict verifier actor gating (`VERIFYING -> COMPLETED`), immutable terminal states.
- **Inputs & Challenge Broker (F26, F27, F30, F31):** OTP format validation (`^\d{6}$`), rejection when not waiting, in-memory CAPTCHA retrieval with `Cache-Control: no-store`.
- **Document Downloads & Delivery (F33):** 60-second signed URL generation for completed tasks, rejection for incomplete tasks, path isolation.
- **Document Deletions (F34):** Deletion of database row and storage object, ownership enforcement, 404 on nonexistent files.
- **Retention & Cleanup (F36):** Authentication via `CLEANUP_SECRET`, purging of documents past `delete_after`, preservation of unexpired documents.

### Tier 2: Boundary Value Analysis & Corner Cases
Targets boundary conditions, extreme inputs, and systemic edge cases:
- Empty, whitespace, and 50KB oversize chat payloads.
- Malformed UUID path parameters.
- OTP attempt counter decrementing and permanent lockout at 3 failed attempts.
- CAPTCHA attempt exhaustion (max 3).
- Input timeout expiration after 180 seconds (`WAITING_FOR_USER -> EXPIRED`).
- Task watchdog timeout after 10 minutes.
- 5-point document security verifier rejection of corrupt headers, HTML 500 masquerading as PDF, >5MB oversize files, `/JavaScript` actions, and `/Launch` actions.
- Simulated mock portal network timeouts, changed DOM selectors, and foreign redirect attempts.

### Tier 3: Pairwise Combinations
Examines interaction points between distinct subsystems:
- **Auth + Task + Realtime:** State transitions emit event records strictly filtered by `user_id`; token expiration mid-flow stops subsequent calls.
- **PII Scrubber + Chat + Task:** 12-digit Aadhaar with valid Verhoeff checksum is scrubbed before prompt generation, while intent classification still extracts workflow parameters.
- **Challenge Broker + SecretStr + Worker:** In-memory relay across WebSocket without persisting secret values in databases or logs.
- **Verifier + Storage + Signed URL:** Verified PDF triggers SHA-256 computation, private storage upload, and functional signed URL issuance.
- **Rate Limiting + Input Submission:** Burst submission to `/input` triggers HTTP 429 Too Many Requests.

### Tier 4: Real-World Application Scenarios
Simulates realistic, multi-step end-to-end user workflows:
1. **Complete Aadhaar Download Journey:** Login -> Chat Request -> Task Created -> CAPTCHA Scraped -> User Solves CAPTCHA -> OTP Dispatched -> User Submits OTP -> Portal Generates Encrypted PDF -> Worker Intercepts & Verifies -> Private Storage Upload -> Signed URL Delivered to Vault.
2. **Wrong CAPTCHA Recovery Journey:** User submits erroneous CAPTCHA -> Portal returns error -> Fresh CAPTCHA generated -> User re-submits correctly -> Proceed to OTP.
3. **Wrong OTP Retry Recovery Journey:** User enters incorrect OTP -> Attempts left decrements to 2 -> User enters correct OTP -> Successful completion.
4. **Expired OTP Recovery Journey:** 180s countdown expires -> User requests OTP resend -> Timer resets -> User submits fresh OTP -> Successful completion.
5. **Cooperative Cancellation Mid-Flight:** User triggers cancellation -> Task transitions to `CANCELLED` -> Browser context aborted -> Temp files deleted -> Subsequent inputs rejected.
6. **Corrupt Payload Rejection & Recovery:** Upstream portal streams corrupted payload -> Verifier halts pipeline -> Task transitions to `FAILED` with actionable user guidance.

---

## 3. Directory Layout

```text
saral-ai/
├── TEST_INFRA.md                              # This specification
├── TEST_READY.md                              # Test suite readiness & execution report
├── run_e2e_tests.py                           # Standalone CLI test runner
└── tests/
    └── e2e/
        ├── __init__.py
        ├── conftest.py                        # Fixtures, test client, spec oracle harness
        ├── test_tier1_feature_coverage.py     # Tier 1: Feature baselines (>=5 per feature)
        ├── test_tier2_boundaries_and_corners.py # Tier 2: Boundary & corner cases
        ├── test_tier3_pairwise_combinations.py # Tier 3: Pairwise subsystem integrations
        └── test_tier4_real_world_scenarios.py # Tier 4: Full realistic user workflows
```

---

## 4. Test Runner Invocation

### Standalone Runner (Recommended)
```bash
# Run the entire test suite with structured ASCII report
python run_e2e_tests.py

# Run specific tiers
python run_e2e_tests.py --tier 1
python run_e2e_tests.py --tier 2
python run_e2e_tests.py --tier 3
python run_e2e_tests.py --tier 4

# Run against live backend and mock portal (requires servers running)
python run_e2e_tests.py --live

# Verbose output
python run_e2e_tests.py -v
```

### Pytest Direct Invocation
```bash
# Run via pytest with uv
uv run --with pytest pytest tests/e2e/ -v

# Run single test module
uv run --with pytest pytest tests/e2e/test_tier1_feature_coverage.py -v
```

---

## 5. Complete Feature Coverage Mapping (Features 1–93)

Every feature defined in `PROJECT.md § Feature Inventory` is mapped below to its test tier, file, and verification strategy:

| # | Feature Name | Tier | Test File | Test Method / Verification Strategy |
|---|--------------|------|-----------|-------------------------------------|
| 1 | Supabase Schema & Tables | Tier 1 | `test_tier1_feature_coverage.py` | `test_auth_ownership_isolation_tasks`, table foreign keys & constraints |
| 2 | Table Constraints & Indexes | Tier 1 | `test_tier1_feature_coverage.py` | `test_task_create_idempotent_duplicate`, `test_task_one_active_workflow_constraint` |
| 3 | Supabase Profiles Trigger | Tier 1 | `test_tier1_feature_coverage.py` | `test_auth_protected_endpoints_require_jwt`, profile creation hook |
| 4 | Supabase Row Level Security | Tier 1 | `test_tier1_feature_coverage.py` | `test_auth_ownership_isolation_tasks`, `test_auth_ownership_isolation_documents` |
| 5 | Supabase Storage Policies | Tier 1 | `test_tier1_feature_coverage.py` | `test_download_user_isolation`, folder isolation check `<user_id>/<task_id>.pdf` |
| 6 | Supabase Realtime Publications | Tier 3 | `test_tier3_pairwise_combinations.py` | `test_pairwise_auth_task_realtime_stream`, task_events channel filter |
| 7 | Backend App Lifespan & Config | Tier 1 | `test_tier1_feature_coverage.py` | `test_auth_health_is_public`, lifespan initialization probe |
| 8 | Public Health Check (`GET /health`) | Tier 1 | `test_tier1_feature_coverage.py` | `test_auth_health_is_public`, unauthenticated warm-up check |
| 9 | Supabase JWT Auth Dependency | Tier 1 | `test_tier1_feature_coverage.py` | `test_auth_protected_endpoints_require_jwt`, `test_auth_invalid_jwt_rejected` |
| 10 | Resource Ownership Gate | Tier 1 | `test_tier1_feature_coverage.py` | `test_auth_ownership_isolation_tasks`, `test_auth_ownership_isolation_documents` |
| 11 | Aadhaar / VID Masking (Verhoeff) | Tier 3 | `test_tier3_pairwise_combinations.py` | `test_pairwise_scrubber_verhoeff_valid_vs_invalid_aadhaar` |
| 12 | Phone Number Masking | Tier 3 | `test_tier3_pairwise_combinations.py` | `test_pairwise_scrubber_chat_task_creation`, regex phone detection |
| 13 | Email Address Masking | Tier 3 | `test_tier3_pairwise_combinations.py` | `test_pairwise_scrubber_chat_task_creation`, regex email detection |
| 14 | Biometric Mention Scrubbing | Tier 3 | `test_tier3_pairwise_combinations.py` | `test_pairwise_scrubber_biometrics_and_otp_in_chat` |
| 15 | OTP String Masking | Tier 3 | `test_tier3_pairwise_combinations.py` | `test_pairwise_scrubber_biometrics_and_otp_in_chat`, OTP regex |
| 16 | Redacting Logging Filter | Tier 1 | `test_tier1_feature_coverage.py` | `test_input_secretstr_never_persisted`, log redaction assertion |
| 17 | Groq LLM Provider | Tier 1 | `test_tier1_feature_coverage.py` | `test_chat_sse_streaming_response`, provider interface abstraction |
| 18 | Chat Streaming SSE Endpoint | Tier 1 | `test_tier1_feature_coverage.py` | `test_chat_sse_streaming_response`, `text/event-stream` parser |
| 19 | Rule-Based Intent Classifier | Tier 1 | `test_tier1_feature_coverage.py` | `test_chat_sse_task_intent_detection`, Aadhaar keyword intent matching |
| 20 | LLM Intent Classifier Fallback | Tier 1 | `test_tier1_feature_coverage.py` | `test_chat_sse_conversation_id_continuity`, structured intent extraction |
| 21 | Deterministic State Machine | Tier 1 | `test_tier1_feature_coverage.py` | `test_state_machine_happy_path_sequence`, `test_state_machine_illegal_transition_rejected` |
| 22 | Verifier Completion Gate | Tier 1 | `test_tier1_feature_coverage.py` | `test_state_machine_verifier_gate_enforcement` (only actor="verifier" allowed) |
| 23 | Timeout & Attempt Watchdog | Tier 2 | `test_tier2_boundaries_and_corners.py` | `test_corner_user_input_timeout_expires`, `test_corner_task_total_timeout_watchdog` |
| 24 | Postgres Job Queue | Tier 1 | `test_tier1_feature_coverage.py` | `test_task_create_direct_endpoint`, queue reservation verification |
| 25 | Idempotent Task Creation | Tier 1 | `test_tier1_feature_coverage.py` | `test_task_create_idempotent_duplicate`, idempotency key validation |
| 26 | Challenge Broker CAPTCHA Storage | Tier 1 | `test_tier1_feature_coverage.py` | `test_challenge_captcha_image_retrieval`, in-memory buffer check |
| 27 | Challenge Broker OTP Relay | Tier 1 | `test_tier1_feature_coverage.py` | `test_input_otp_valid_format_accepted`, SecretStr memory relay |
| 28 | Direct Task Creation Endpoint | Tier 1 | `test_tier1_feature_coverage.py` | `test_task_create_direct_endpoint` (`POST /api/v1/tasks`) |
| 29 | Task Status Query Endpoint | Tier 1 | `test_tier1_feature_coverage.py` | `test_task_get_status_returns_sanitized_state` (`GET /api/v1/tasks/{id}`) |
| 30 | Secure Input Submission Endpoint | Tier 1 | `test_tier1_feature_coverage.py` | `test_input_otp_valid_format_accepted` (`POST /api/v1/tasks/{id}/input`) |
| 31 | Challenge Image Endpoint | Tier 1 | `test_tier1_feature_coverage.py` | `test_challenge_captcha_image_retrieval` (`GET /api/v1/tasks/{id}/challenge`) |
| 32 | Task Cancellation Endpoint | Tier 1 | `test_tier1_feature_coverage.py` | `test_task_cancel_cooperative_abort` (`POST /api/v1/tasks/{id}/cancel`) |
| 33 | Document Download Signed URL | Tier 1 | `test_tier1_feature_coverage.py` | `test_download_signed_url_success_for_completed` (`GET /api/v1/tasks/{id}/download`) |
| 34 | Document Deletion Endpoint | Tier 1 | `test_tier1_feature_coverage.py` | `test_document_delete_success` (`DELETE /api/v1/documents/{id}`) |
| 35 | Worker WebSocket Endpoint | Tier 3 | `test_tier3_pairwise_combinations.py` | `test_pairwise_challenge_secretstr_worker_relay` (`WS /internal/worker`) |
| 36 | Retention Cleanup Endpoint | Tier 1 | `test_tier1_feature_coverage.py` | `test_cleanup_endpoint_requires_secret`, `test_cleanup_expired_documents_swept` |
| 37 | Policy Engine & Domain Allowlist | Tier 2 | `test_tier2_boundaries_and_corners.py` | `test_corner_mock_portal_foreign_redirect`, domain boundary check |
| 38 | Rate Limiting Middleware | Tier 3 | `test_tier3_pairwise_combinations.py` | `test_pairwise_rate_limit_on_input_endpoint` (HTTP 429 response) |
| 39 | Mock Portal Login & Landing | Tier 4 | `test_tier4_real_world_scenarios.py` | `test_scenario_complete_aadhaar_download_journey` (login route) |
| 40 | Mock Portal CAPTCHA Generator | Tier 1 | `test_tier1_feature_coverage.py` | `test_challenge_captcha_image_retrieval` (distorted 6-char PNG) |
| 41 | Mock Portal OTP Screen & Verification | Tier 4 | `test_tier4_real_world_scenarios.py` | `test_scenario_complete_aadhaar_download_journey` (verify-otp route) |
| 42 | Mock Portal OTP Resend | Tier 4 | `test_tier4_real_world_scenarios.py` | `test_scenario_expired_otp_recovery_journey` (resend-otp route) |
| 43 | Mock Portal PDF Stream | Tier 4 | `test_tier4_real_world_scenarios.py` | `test_scenario_complete_aadhaar_download_journey` (download stream) |
| 44 | Mock Portal Health Endpoint | Tier 1 | `test_tier1_feature_coverage.py` | `test_auth_health_is_public` (portal health probe) |
| 45 | Stable Semantic DOM Selectors | Tier 2 | `test_tier2_boundaries_and_corners.py` | `test_corner_mock_portal_changed_selectors` (semantic selector check) |
| 46 | Mock Failure Mode: Wrong CAPTCHA | Tier 4 | `test_tier4_real_world_scenarios.py` | `test_scenario_wrong_captcha_recovery_journey` |
| 47 | Mock Failure Mode: Expired OTP | Tier 4 | `test_tier4_real_world_scenarios.py` | `test_scenario_expired_otp_recovery_journey` |
| 48 | Mock Failure Mode: Wrong OTP (3x) | Tier 2 | `test_tier2_boundaries_and_corners.py` | `test_corner_otp_max_attempts_exceeded` |
| 49 | Mock Failure Mode: Corrupt PDF | Tier 2 | `test_tier2_boundaries_and_corners.py` | `test_corner_corrupt_pdf_header_rejected` |
| 50 | Mock Failure Mode: HTML as PDF | Tier 2 | `test_tier2_boundaries_and_corners.py` | `test_corner_html_masquerading_as_pdf_rejected` |
| 51 | Mock Failure Mode: Oversize PDF | Tier 2 | `test_tier2_boundaries_and_corners.py` | `test_corner_oversize_pdf_exceeding_threshold` |
| 52 | Mock Failure Mode: Malicious PDF | Tier 2 | `test_tier2_boundaries_and_corners.py` | `test_corner_malicious_pdf_javascript_action_rejected`, `test_corner_malicious_pdf_launch_action_rejected` |
| 53 | Mock Failure Mode: Page Timeout | Tier 2 | `test_tier2_boundaries_and_corners.py` | `test_corner_mock_portal_timeout_switch` |
| 54 | Mock Failure Mode: Changed Selectors | Tier 2 | `test_tier2_boundaries_and_corners.py` | `test_corner_mock_portal_changed_selectors` |
| 55 | Mock Failure Mode: Foreign Redirect | Tier 2 | `test_tier2_boundaries_and_corners.py` | `test_corner_mock_portal_foreign_redirect` |
| 56 | Worker Outbound WebSocket Client | Tier 3 | `test_tier3_pairwise_combinations.py` | `test_pairwise_challenge_secretstr_worker_relay` |
| 57 | Worker Ephemeral Browser Context | Tier 4 | `test_tier4_real_world_scenarios.py` | `test_scenario_complete_aadhaar_download_journey` |
| 58 | Worker Route Interception Allowlist | Tier 2 | `test_tier2_boundaries_and_corners.py` | `test_corner_mock_portal_foreign_redirect` |
| 59 | Worker In-Memory CAPTCHA Scraper | Tier 4 | `test_tier4_real_world_scenarios.py` | `test_scenario_complete_aadhaar_download_journey` |
| 60 | Worker Zero-Persistence OTP Fill | Tier 1 | `test_tier1_feature_coverage.py` | `test_input_secretstr_never_persisted` |
| 61 | Worker Download Interception | Tier 4 | `test_tier4_real_world_scenarios.py` | `test_scenario_complete_aadhaar_download_journey` |
| 62 | 5-Point Document Security Verifier | Tier 2 | `test_tier2_boundaries_and_corners.py` | `test_corner_valid_encrypted_pdf_passes_verifier`, `test_corner_corrupt_pdf_header_rejected` |
| 63 | Storage Upload & Documents Insert | Tier 3 | `test_tier3_pairwise_combinations.py` | `test_pairwise_verifier_storage_and_signed_url` |
| 64 | Worker Ephemeral Temp Cleanup | Tier 1 | `test_tier1_feature_coverage.py` | `test_cleanup_temp_dir_removal_in_finally` |
| 65 | Worker Bounded Navigation Retries | Tier 2 | `test_tier2_boundaries_and_corners.py` | `test_corner_mock_portal_timeout_switch` |
| 66 | Flutter Clean Architecture & Riverpod | Spec / E2E | App Contract | Verified via API & Realtime interface compatibility |
| 67 | Flutter Declarative GoRouter | Spec / E2E | App Contract | Deep link & auth routing interface validation |
| 68 | Monochrome Theme Tokens | Spec / E2E | App Contract | UI styling contract: `#000000`, `#FFFFFF`, `#1A1A1A` |
| 69 | Local Bundled Typography | Spec / E2E | App Contract | Arapey and Inter bundled assets specification |
| 70 | GlassSurface Component | Spec / E2E | App Contract | Max 3 blur surfaces constraint verification |
| 71 | Splash Screen & Warm-up | Tier 1 | `test_tier1_feature_coverage.py` | `test_auth_health_is_public` (used by splash warm-up) |
| 72 | Supabase Auth Screen | Tier 1 | `test_tier1_feature_coverage.py` | `test_auth_protected_endpoints_require_jwt`, auth contract |
| 73 | Home Chat Screen | Tier 1 | `test_tier1_feature_coverage.py` | `test_chat_sse_streaming_response`, chat UI contract |
| 74 | SSE Chat Streaming Consumer | Tier 1 | `test_tier1_feature_coverage.py` | `test_chat_sse_streaming_response`, stream consumer protocol |
| 75 | Waking-Server Indicator | Tier 1 | `test_tier1_feature_coverage.py` | `test_auth_health_is_public`, warm-up latency handling |
| 76 | Inline Task Stepper Card | Tier 3 | `test_tier3_pairwise_combinations.py` | `test_pairwise_auth_task_realtime_stream`, task_events stepper |
| 77 | Secure Input Sheet (UID Masking) | Tier 3 | `test_tier3_pairwise_combinations.py` | `test_pairwise_scrubber_verhoeff_valid_vs_invalid_aadhaar` |
| 78 | Secure Input Sheet (OTP Countdown) | Tier 1 | `test_tier1_feature_coverage.py` | `test_input_otp_valid_format_accepted`, 180s countdown protocol |
| 79 | Secure Input Sheet (CAPTCHA) | Tier 1 | `test_tier1_feature_coverage.py` | `test_challenge_captcha_image_retrieval`, image buffer contract |
| 80 | Android FLAG_SECURE Platform Channel | Spec / E2E | App Contract | Sensitive screen screenshot protection contract |
| 81 | Secure Input Keyboard Hardening | Spec / E2E | App Contract | `enableSuggestions: false`, `autocorrect: false` contract |
| 82 | Document Vault Screen | Tier 1 | `test_tier1_feature_coverage.py` | `test_download_document_metadata_structure`, vault contract |
| 83 | Document Local Password Helper | Spec / E2E | App Contract | Local client password formula (first 4 caps + birth year) |
| 84 | Document Actions (Open, Share) | Tier 1 | `test_tier1_feature_coverage.py` | `test_download_signed_url_success_for_completed`, open action |
| 85 | History Drawer | Tier 1 | `test_tier1_feature_coverage.py` | `test_chat_sse_conversation_id_continuity`, drawer groupings |
| 86 | Settings Screen | Tier 1 | `test_tier1_feature_coverage.py` | `test_document_delete_success`, retention preferences |
| 87 | GitHub Actions CI Workflow | Spec / E2E | DevOps | Validates `run_e2e_tests.py` in automated pipeline |
| 88 | GitHub Actions Supabase Keep-Alive | Spec / E2E | DevOps | Verified via daily REST ping to Supabase |
| 89 | GitHub Actions Cleanup Sweep | Tier 1 | `test_tier1_feature_coverage.py` | `test_cleanup_endpoint_executes_with_valid_secret` |
| 90 | Render Deployment Descriptor | Spec / E2E | DevOps | Validates service manifest & env mappings |
| 91 | Environment Templates & AGENTS.md | Spec / E2E | Project Pattern | Root security invariants & env variable contract |
| 92 | E2E Opaque-Box Test Suite | Tier 1–4 | `tests/e2e/` | Complete 4-tier requirement-driven test suite |
| 93 | Adversarial Coverage Hardening | Tier 2–3 | `tests/e2e/` | Adversarial injection, Verhoeff, tamper, and lockout tests |

---

## 6. Success Criteria & Quality Gates

The E2E testing track is considered complete and passing when:
1. All four test tiers (`test_tier1_feature_coverage.py`, `test_tier2_boundaries_and_corners.py`, `test_tier3_pairwise_combinations.py`, `test_tier4_real_world_scenarios.py`) execute without errors.
2. `run_e2e_tests.py` reports 100% test pass rate with 0 failures and 0 errors.
3. Zero persistence of sensitive credentials (OTPs, CAPTCHAs, unmasked Aadhaar numbers) is verified across all payloads and logs.
4. `TEST_READY.md` is generated and published at project root.
