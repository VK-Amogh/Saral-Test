# Scope: Real-World e-Aadhaar Hybrid Architecture

## Architecture
Hybrid e-Aadhaar acquisition architecture featuring:
1. **Live UIDAI Portal Automation & Anti-Bot Stealth**: Playwright headless browser worker with dynamic multi-tier selectors for React/Angular layouts, stealth patches (navigator.webdriver removal, hardware concurrency, WebGL spoofing, realistic headers/UA, human-like typing delays), route allowlisting (uidai.gov.in subdomains, localhost, Supabase storage), and zero-persistence challenge relay.
2. **Official DigiLocker OAuth2 / IndiaStack Fallback**: Legal, high-speed API route via DigiLocker OAuth2 consent flow for direct e-Aadhaar XML/PDF retrieval, integrating cleanly with the 12-state deterministic task state machine.
3. **Flutter Mobile Client Hardening**: OS-level `FLAG_SECURE` window shielding, real-time 180s countdown ring, real-time OTP cells, base64 CAPTCHA image rendering with interactive refresh, and document vault password hint (First 4 letters CAPITAL + 4-digit Year of Birth).
4. **5-Point Cryptographic Verifier & Storage**: Strict verification (%PDF-, 100B-5MB bounds, %%EOF, no /JavaScript or /Launch, SHA-256 + encryption detection) and user-isolated Supabase storage (`documents/<user_id>/<task_id>.pdf`).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Live UIDAI Dynamic Selectors | Cascading multi-tier selectors, React synthetic event sync via `press_sequentially`, advisory dismiss | M1_WORKER | Survey 1 |
| 2 | Anti-Bot Stealth Runner | `navigator.webdriver` removal, realistic UA, hardware concurrency (8), WebGL spoofing, human typing delays | M1_WORKER | Survey 1 |
| 3 | Route Allowlist & Supabase Inclusion | Allowlist strictly permitting `*.uidai.gov.in`, `localhost`, `mock-portal.local`, and `supabase.co` | M1_WORKER | Survey 1 |
| 4 | Live Challenge Relay & Zero Persistence | Bidirectional WebSocket bridge between worker and ChallengeBroker; ephemeral CAPTCHA base64 streaming & OTP relay | M1_WORKER | Survey 1 |
| 5 | DigiLocker OAuth2 Consent Flow | IndiaStack / DigiLocker OAuth2 consent URL generation, HMAC state token, callback handler, token exchange | M2_DIGILOCKER | Survey 2 |
| 6 | DigiLocker Direct Document Retrieval | Stream e-Aadhaar XML/PDF bytes into memory without web scraping | M2_DIGILOCKER | Survey 2 |
| 7 | DigiLocker State Machine Integration | Native mapping onto `RECEIVED` -> `VALIDATING` -> `PLANNING` -> `WAITING_FOR_USER` -> `RUNNING` -> `DOWNLOADING` -> `VERIFYING` -> `COMPLETED` | M2_DIGILOCKER | Survey 2 |
| 8 | Android FLAG_SECURE Screen Shielding | OS-level window security blocking screenshots, screen recording, and task switcher previews | M3_MOBILE | Survey 3 |
| 9 | Base64 CAPTCHA Rendering & Refresh | Decode base64 image bytes in `SecureInputSheet` with interactive refresh button | M3_MOBILE | Survey 3 |
| 10 | Vault Document Password Hint | UIDAI format banner/modal (First 4 letters in CAPITAL + 4-digit Year of Birth) | M3_MOBILE | Survey 3 |
| 11 | 256-Test Regression Verification | Verify all 256 test cases pass without regressions alongside new tests | M4_VERIFY | Survey 3 |
| 12 | Forensic Integrity Audit | Independent forensic audit ensuring zero dummy values, authentic logic, and zero persistence | M4_VERIFY | Rules |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Live UIDAI Worker & Stealth Runner | Features 1–4 (`backend/app/worker/runner.py`, `allowlist.py`, `backend/app/config.py`, `backend/app/api/internal.py`, `backend/app/worker/client.py`) | none | IN_PROGRESS |
| M2 | DigiLocker OAuth2 Fallback Route | Features 5–7 (`backend/app/api/digilocker.py`, `backend/app/services/digilocker_service.py`, `backend/app/api/tasks.py`) | none | PLANNED |
| M3 | Flutter Mobile Client Hardening | Features 8–10 (`app/android/.../MainActivity.kt`, `app/lib/core/services/screen_security.dart`, `secure_input_sheet.dart`, `vault_screen.dart`) | none | PLANNED |
| M4 | Regression Verification & Audit | Features 11–12 (Full 256+ test pass, review, challenger, forensic audit) | M1, M2, M3 | PLANNED |

## Code Layout & Write Boundaries
- **M1 Worker**:
  - `backend/app/worker/runner.py`
  - `backend/app/worker/allowlist.py`
  - `backend/app/worker/client.py`
  - `backend/app/config.py`
  - `backend/app/api/internal.py`
  - `backend/app/worker/test_worker.py`
- **M2 DigiLocker**:
  - `backend/app/api/digilocker.py`
  - `backend/app/services/digilocker_service.py`
  - `backend/app/api/tasks.py`
  - `backend/app/api/router.py` (or inclusion in main.py)
  - `backend/tests/test_digilocker.py`
- **M3 Mobile**:
  - `app/android/app/src/main/kotlin/com/saralai/app/MainActivity.kt`
  - `app/lib/core/services/screen_security.dart`
  - `app/lib/features/chat/presentation/widgets/secure_input_sheet.dart`
  - `app/lib/features/chat/presentation/widgets/task_stepper_card.dart`
  - `app/lib/features/vault/presentation/vault_screen.dart`
  - `app/test/`
