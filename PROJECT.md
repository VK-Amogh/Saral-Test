# Project: Saral AI

## Architecture
Saral AI is an outcome-oriented, zero-cost (free-tier optimized) system for Indian citizens interacting with official government services.
- **Flutter Android App (`app/`)**: Strict monochrome design system, Riverpod state management, GoRouter, local Arapey/Inter typography, GlassSurface with performance safeguards, direct Supabase Auth & Realtime connection, SSE streaming chat consumer, secure input sheets with `FLAG_SECURE` and visual masking (`XXXX-XXXX-1234`), on-device document vault.
- **FastAPI Backend (`backend/`)**: Render Free-compatible lightweight API. Verifies Supabase JWTs on all protected routes, scrubs PII/biometrics using regex + Verhoeff dihedral D5 algorithm, streams chat via Groq API (`llama-3.3-70b-versatile`), enforces deterministic task state machine (`transition()`), manages Postgres queue with `FOR UPDATE SKIP LOCKED`, brokers OTP/CAPTCHA in memory with zero persistence, serves WebSocket for browser automation workers, and coordinates signed document downloads.
- **Mock Government Portal (`mock_portal/`)**: Standalone FastAPI service replicating the multi-step identity verification flow (UID entry → CAPTCHA → OTP → PDF generation) with 10 deterministic failure simulations for comprehensive E2E testing without touching public government portals.
- **Playwright Automation Worker (`backend/app/worker/`)**: Headless Chromium runner on host/Docker. Outbound WebSocket connection to `/internal/worker`, isolated ephemeral browser contexts, route-level domain allowlisting, in-memory challenge relay, download interception, 5-point document security verification (`%PDF-`, size, pypdf structure, no `/JavaScript`/`/Launch`, SHA-256), private Supabase Storage upload, and guaranteed temp directory cleanup.
- **Supabase Cloud (Postgres, Auth, Storage, Realtime)**: Tables with strict RLS (client read-only for operational tables, backend writes with service key), private `documents` bucket, and Realtime publications.
- **GitHub Actions & Cloud Operations**: CI for Flutter and pytest, daily keepalive ping, hourly cleanup sweep, and Render service manifest.

## Code Layout
```text
saral-ai/
├── AGENTS.md                                   # Root agent operational constraints
├── render.yaml                                 # Render Free deployment descriptor
├── .env.example                                # Environment variable templates
├── supabase/
│   └── migrations/
│       └── 0001_init.sql                       # Complete schema, RLS, storage, realtime
├── backend/
│   ├── app/
│   │   ├── main.py                             # Lifespan, middlewares, router inclusion
│   │   ├── core/
│   │   │   ├── config.py                       # Pydantic BaseSettings
│   │   │   ├── logging.py                      # RedactingLogFilter, structured logging
│   │   │   ├── security.py                     # Supabase JWT validation, ownership checks
│   │   │   ├── rate_limit.py                   # slowapi rate limiter
│   │   │   └── exceptions.py                   # Domain exceptions & error handlers
│   │   ├── db/
│   │   │   ├── supabase.py                     # Supabase service role client
│   │   │   └── session.py                      # asyncpg queue pool for SKIP LOCKED
│   │   ├── api/
│   │   │   ├── deps.py                         # Auth & DB dependencies
│   │   │   └── v1/
│   │   │       ├── router.py                   # Aggregator router
│   │   │       ├── health.py                   # GET /health
│   │   │       ├── chat.py                     # POST /api/v1/chat (SSE streaming)
│   │   │       ├── tasks.py                    # Task endpoints (CRUD, input, challenge, cancel, download)
│   │   │       └── documents.py                # DELETE /api/v1/documents/{id}
│   │   ├── internal/
│   │   │   ├── worker_ws.py                    # WS /internal/worker
│   │   │   └── cleanup.py                      # POST /internal/cleanup
│   │   ├── orchestrator/
│   │   │   ├── state_machine.py                # transition(), state matrix, verifier gate
│   │   │   ├── queue.py                        # Postgres FOR UPDATE SKIP LOCKED queue
│   │   │   ├── challenge_broker.py             # In-memory OTP & CAPTCHA relay
│   │   │   └── task_service.py                 # Task lifecycle & orchestration
│   │   ├── ai/
│   │   │   ├── provider.py                     # LLMProvider abstract interface
│   │   │   ├── groq_provider.py                # Groq SDK provider (llama-3.3-70b-versatile)
│   │   │   ├── classifier.py                   # IntentClassifier interface & models
│   │   │   ├── rules_classifier.py             # Regex & keyword intent router
│   │   │   └── pii_scrubber.py                 # Verhoeff algorithm + regex scrubber
│   │   ├── policy/
│   │   │   ├── domain_allowlist.py             # Route allowlist configuration
│   │   │   └── approval_gates.py               # Sensitive action checks
│   │   ├── workflows/
│   │   │   ├── base.py                         # Workflow contract
│   │   │   ├── registry.py                     # Workflow registry
│   │   │   └── aadhaar_download.py             # Aadhaar download workflow spec
│   │   └── worker/
│   │       ├── main.py                         # Worker entrypoint, WS client
│   │       ├── browser.py                      # Playwright Chromium context manager
│   │       ├── runner.py                       # DOM automation & challenge scraper
│   │       └── verifier.py                     # 5-stage document security verifier
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_state_machine.py
│   │   ├── test_pii_scrubber.py
│   │   ├── test_auth.py
│   │   ├── test_chat_sse.py
│   │   ├── test_challenge_broker.py
│   │   ├── test_queue.py
│   │   └── test_api_endpoints.py
│   ├── requirements.txt
│   └── pyproject.toml
├── mock_portal/
│   ├── app/
│   │   ├── main.py                             # Mock portal app, routes, failure switches
│   │   ├── captcha.py                          # Distorted 6-char CAPTCHA generator
│   │   ├── otp.py                              # OTP lifecycle, TTL, attempts tracker
│   │   └── pdf.py                              # Test PDF generator (valid, corrupt, malicious, etc.)
│   ├── templates/
│   │   ├── index.html                          # UID + CAPTCHA login page
│   │   └── verify_otp.html                     # OTP verification page
│   ├── tests/
│   │   └── test_mock_portal.py
│   ├── requirements.txt
│   └── run.py
├── app/
│   ├── pubspec.yaml                            # Dependencies & font asset declarations
│   ├── assets/
│   │   └── fonts/
│   │       ├── arapey/                         # Arapey Regular & Italic
│   │       └── inter/                          # Inter Regular, Medium, SemiBold, Bold
│   ├── lib/
│   │   ├── main.dart                           # Entrypoint, orientation, warm-up
│   │   ├── core/
│   │   │   ├── theme/
│   │   │   │   ├── tokens.dart                 # Monochrome colors, curves, typography
│   │   │   │   └── app_theme.dart              # ThemeData
│   │   │   ├── widgets/
│   │   │   │   ├── glass_surface.dart          # BackdropFilter with RepaintBoundary & lowPowerGlass
│   │   │   │   ├── arapey_text.dart            # Typography helper
│   │   │   │   └── shimmer_loading.dart        # Monochrome loading indicator
│   │   │   ├── net/
│   │   │   │   ├── api_client.dart             # Dio HTTP client, JWT injection, SSE client
│   │   │   │   └── supabase_client.dart        # Supabase client singleton
│   │   │   ├── router/
│   │   │   │   └── app_router.dart             # GoRouter configuration
│   │   │   └── security/
│   │   │       └── screen_security.dart        # FLAG_SECURE platform channel wrapper
│   │   └── features/
│   │       ├── splash/
│   │       │   └── splash_screen.dart          # Wordmark fade, session check, /health warm-up
│   │       ├── auth/
│   │       │   ├── presentation/
│   │       │   │   ├── auth_screen.dart        # Glass card Sign In / Sign Up / Reset
│   │       │   │   └── auth_controller.dart    # Riverpod auth state notifier
│   │       │   └── data/
│   │       │       └── auth_repository.dart    # Supabase Auth wrapper
│   │       ├── chat/
│   │       │   ├── presentation/
│   │       │   │   ├── chat_screen.dart        # Greeting, suggestions, composer pill, SSE stream
│   │       │   │   ├── chat_controller.dart    # Riverpod chat controller
│   │       │   │   └── widgets/
│   │       │   │       ├── message_bubble.dart # Glass/translucent bubble, Arapey/Inter
│   │       │   │       ├── composer_pill.dart  # Rounded pill composer, send button morph
│   │       │   │       └── waking_shimmer.dart # Quiet server warm-up line
│   │       ├── tasks/
│   │       │   ├── presentation/
│   │       │   │   ├── widgets/
│   │       │   │   │   ├── task_stepper_card.dart # Animated stepper driven by Realtime task_events
│   │       │   │   │   └── secure_input_sheet.dart# Visual masked UID, 6-box OTP ring, CAPTCHA
│   │       │   │   └── tasks_controller.dart   # Realtime subscription controller
│   │       │   └── data/
│   │       │       └── task_repository.dart    # Task actions, inputs, cancellation
│   │       ├── vault/
│   │       │   ├── presentation/
│   │       │   │   ├── vault_screen.dart       # Document list, expiry countdown, view/share/delete
│   │       │   │   └── vault_controller.dart   # Vault controller
│   │       │   └── data/
│   │       │       └── vault_repository.dart   # Download with signed URL, local storage
│   │       ├── history/
│   │       │   └── presentation/
│   │       │       └── history_drawer.dart     # Today/Yesterday/Older drawer, search, delete
│   │       └── settings/
│   │           └── presentation/
│   │               └── settings_screen.dart    # Retention settings, sign out, delete account
│   └── test/
│       ├── core/
│       │   └── glass_surface_test.dart
│       ├── features/
│       │   ├── auth_widget_test.dart
│       │   ├── chat_widget_test.dart
│       │   ├── task_stepper_widget_test.dart
│       │   └── secure_input_sheet_widget_test.dart
│       └── mocks/
│           └── mock_supabase.dart
└── .github/
    └── workflows/
        ├── ci.yml                              # Flutter analyze & test + pytest
        ├── keepalive.yml                       # Supabase keepalive ping
        └── cleanup.yml                         # Hourly retention cleanup sweep
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Supabase Schema & Tables | Full DDL for profiles, conversations, messages, tasks, task_events, documents | M1 | Survey 3 |
| 2 | Table Constraints & Indexes | Foreign key cascades, composite unique (user_id, idempotency_key), partial index one_active_task_per_workflow | M1 | Survey 3 |
| 3 | Supabase Profiles Trigger | `handle_new_user()` security definer trigger on auth.users | M1 | Survey 3 |
| 4 | Supabase Row Level Security | Client read-only policies on operational tables; backend writes via secret key | M1 | Survey 3 |
| 5 | Supabase Storage Policies | Private `documents` bucket, `<user_id>/<task_id>.pdf` path folder isolation | M1 | Survey 3 |
| 6 | Supabase Realtime Publications | Realtime enabled for tasks, task_events, messages | M1 | Survey 3 |
| 7 | Backend App Lifespan & Config | FastAPI startup lifespan, Pydantic BaseSettings, connection pools | M2 | Survey 1 |
| 8 | Public Health Check | `GET /health` unauthenticated warm-up and probe | M2 | Survey 1 |
| 9 | Supabase JWT Auth Dependency | JWT verification on protected routes, extract user claims | M2 | Survey 1 |
| 10 | Resource Ownership Gate | Strict authorization check ensuring user owns target task/document | M2 | Survey 1 |
| 11 | Aadhaar / VID Masking (Verhoeff) | Regex + dihedral group D5 Verhoeff checksum algorithm for 12/16 digit IDs | M2 | Survey 1 |
| 12 | Phone Number Masking | Detects +91, 0, or 10-digit Indian phone numbers; masks to `[REDACTED_PHONE]` | M2 | Survey 1 |
| 13 | Email Address Masking | Detects emails; masks to `[REDACTED_EMAIL]` | M2 | Survey 1 |
| 14 | Biometric Mention Scrubbing | Detects biometric terms (fingerprint, iris, retina); redacts context | M2 | Survey 1 |
| 15 | OTP String Masking | Detects 4/6/8-digit numeric codes near auth terms; masks to `[REDACTED_OTP]` | M2 | Survey 1 |
| 16 | Redacting Logging Filter | Custom logging.Filter masking OTPs, Aadhaar, tokens, Bearer headers | M2 | Survey 1 |
| 17 | Groq LLM Provider | Groq API async client (`llama-3.3-70b-versatile`) with streaming generation | M2 | Survey 1 |
| 18 | Chat Streaming SSE Endpoint | `POST /api/v1/chat` streaming Server-Sent Events, message persistence | M2 | Survey 1 |
| 19 | Rule-Based Intent Classifier | Regex/keyword fast classifier for task intent | M2 | Survey 1 |
| 20 | LLM Intent Classifier Fallback | Groq-based structured tool calling / schema intent extraction | M2 | Survey 1 |
| 21 | Deterministic State Machine | `transition()` enforcing 12-state transition matrix and actor checks | M2 | Survey 1 |
| 22 | Verifier Completion Gate | Strictly requires actor="verifier" to advance VERIFYING → COMPLETED | M2 | Survey 1 |
| 23 | Timeout & Attempt Watchdog | Task timeout (10m), input timeout (3m), OTP attempts budget (3) | M2 | Survey 1 |
| 24 | Postgres Job Queue | Concurrency-safe task dequeue via `FOR UPDATE SKIP LOCKED` | M2 | Survey 1 |
| 25 | Idempotent Task Creation | Prevents duplicate task executions via idempotency key and DB index | M2 | Survey 1 |
| 26 | Challenge Broker CAPTCHA Storage | In-memory transient buffer for CAPTCHA image bytes; no persistence | M2 | Survey 1 |
| 27 | Challenge Broker OTP Relay | In-memory `asyncio.Future` and `SecretStr` relay to worker WebSocket | M2 | Survey 1 |
| 28 | Direct Task Creation Endpoint | `POST /api/v1/tasks` for guided/retry task initiation | M2 | Survey 1 |
| 29 | Task Status Query Endpoint | `GET /api/v1/tasks/{id}` returning sanitized state and input prompts | M2 | Survey 1 |
| 30 | Secure Input Submission Endpoint | `POST /api/v1/tasks/{id}/input` accepting OTP/CAPTCHA into Challenge Broker | M2 | Survey 1 |
| 31 | Challenge Image Endpoint | `GET /api/v1/tasks/{id}/challenge` serving in-memory CAPTCHA (`no-store`) | M2 | Survey 1 |
| 32 | Task Cancellation Endpoint | `POST /api/v1/tasks/{id}/cancel` cooperative task abort | M2 | Survey 1 |
| 33 | Document Download Signed URL | `GET /api/v1/tasks/{id}/download` generating 60-second signed URL | M2 | Survey 1 |
| 34 | Document Deletion Endpoint | `DELETE /api/v1/documents/{id}` deleting database row and Storage object | M2 | Survey 1 |
| 35 | Worker WebSocket Endpoint | `WS /internal/worker` authenticated via `WORKER_SHARED_SECRET` | M2 | Survey 1 |
| 36 | Retention Cleanup Endpoint | `POST /internal/cleanup` authenticated via `CLEANUP_SECRET` | M2 | Survey 1 |
| 37 | Policy Engine & Domain Allowlist | Route allowlisting checks on workflow execution | M2 | Survey 1 |
| 38 | Rate Limiting Middleware | `slowapi` rate limiter on all endpoints, strict on `/input` | M2 | Survey 1 |
| 39 | Mock Portal Login & Landing | `GET /` and `POST /login` with UID & CAPTCHA validation | M3 | Survey 2 |
| 40 | Mock Portal CAPTCHA Generator | `GET /captcha` producing distorted 6-char PNG challenge | M3 | Survey 2 |
| 41 | Mock Portal OTP Screen & Verification | `GET /verify-otp` and `POST /verify-otp` with attempt limits | M3 | Survey 2 |
| 42 | Mock Portal OTP Resend | `POST /resend-otp` resetting 180s countdown and issuing new code | M3 | Survey 2 |
| 43 | Mock Portal PDF Stream | `GET /download` streaming password-protected e-Aadhaar PDF | M3 | Survey 2 |
| 44 | Mock Portal Health Endpoint | `GET /health` probe returning status ok | M3 | Survey 2 |
| 45 | Stable Semantic DOM Selectors | Semantic IDs (`#uid_input`, `#captcha_img`, `#otp_input`, etc.) | M3 | Survey 2 |
| 46 | Mock Failure Mode: Wrong CAPTCHA | Deterministic failure switch rejecting CAPTCHA input | M3 | Survey 2 |
| 47 | Mock Failure Mode: Expired OTP | Deterministic failure switch simulating expired OTP | M3 | Survey 2 |
| 48 | Mock Failure Mode: Wrong OTP (3x) | Deterministic failure switch locking session after 3 invalid attempts | M3 | Survey 2 |
| 49 | Mock Failure Mode: Corrupt PDF | Streams truncated or invalid PDF xref payload | M3 | Survey 2 |
| 50 | Mock Failure Mode: HTML as PDF | Returns 500 HTML body with application/pdf header | M3 | Survey 2 |
| 51 | Mock Failure Mode: Oversize PDF | Returns 12 MB bloated PDF exceeding 5 MB threshold | M3 | Survey 2 |
| 52 | Mock Failure Mode: Malicious PDF | Injects forbidden `/JavaScript` or `/Launch` action dictionary | M3 | Survey 2 |
| 53 | Mock Failure Mode: Page Timeout | Sleeps 45s simulating unresponsive upstream portal | M3 | Survey 2 |
| 54 | Mock Failure Mode: Changed Selectors | Renders broken DOM IDs simulating unannounced portal changes | M3 | Survey 2 |
| 55 | Mock Failure Mode: Foreign Redirect | Redirects to unauthorized external domain | M3 | Survey 2 |
| 56 | Worker Outbound WebSocket Client | Connects outbound to `WS /internal/worker` with retry backoff | M3 | Survey 2 |
| 57 | Worker Ephemeral Browser Context | Isolated Playwright Chromium context wiped on task completion | M3 | Survey 2 |
| 58 | Worker Route Interception Allowlist | Aborts any request outside `ALLOWED_DOMAINS` | M3 | Survey 2 |
| 59 | Worker In-Memory CAPTCHA Scraper | Takes screenshot of `#captcha_img` element and sends via WS | M3 | Survey 2 |
| 60 | Worker Zero-Persistence OTP Fill | Fills `#otp_input` via `locator.fill()`, no traces/video/HAR | M3 | Survey 2 |
| 61 | Worker Download Interception | Listens for `page.expect_download()` and stores in temp directory | M3 | Survey 2 |
| 62 | 5-Point Document Security Verifier | Validates `%PDF-`, size, pypdf syntax, no `/JavaScript`/`/Launch`, SHA-256 | M3 | Survey 2 |
| 63 | Storage Upload & Documents Insert | Uploads verified PDF to `documents/<user_id>/<task_id>.pdf` | M3 | Survey 2 |
| 64 | Worker Ephemeral Temp Cleanup | Guarantees deletion of temporary download directory in `finally` | M3 | Survey 2 |
| 65 | Worker Bounded Navigation Retries | Bounded retries (max 2) on network/navigation failures | M3 | Survey 2 |
| 66 | Flutter Clean Architecture & Riverpod | Feature-first layering with Riverpod providers | M4 | Survey 3 |
| 67 | Flutter Declarative GoRouter | Centrally configured routes with auth state redirect | M4 | Survey 3 |
| 68 | Monochrome Theme Tokens | Strictly `#000000`, `#0A0A0A`, `#141414`, `#1A1A1A`, zero accent hues | M4 | Survey 3 |
| 69 | Local Bundled Typography | Arapey (headings/greeting) and Inter (body/inputs) fonts as assets | M4 | Survey 3 |
| 70 | GlassSurface Component | BackdropFilter with blur, RepaintBoundary, max 3 blurred surfaces | M4 | Survey 3 |
| 71 | Splash Screen & Warm-up | Arapey wordmark fade-in, session check, background `/health` warm-up | M4 | Survey 3 |
| 72 | Supabase Auth Screen | Sign In, Sign Up, Reset Password glass card with validation | M4 | Survey 3 |
| 73 | Home Chat Screen | Arapey greeting, glass suggestion chips, pill composer | M4 | Survey 3 |
| 74 | SSE Chat Streaming Consumer | Streams tokens into chat with soft fade animation | M4 | Survey 3 |
| 75 | Waking-Server Indicator | Subtle shimmer indicator above composer when server is waking | M4 | Survey 3 |
| 76 | Inline Task Stepper Card | Realtime-driven animated stepper reflecting `task_events` | M4 | Survey 3 |
| 77 | Secure Input Sheet (UID Masking) | Visual masking (`XXXX-XXXX-1234`), autofocus, clear prompt | M4 | Survey 3 |
| 78 | Secure Input Sheet (OTP Countdown) | 6-box OTP entry with animated countdown ring & attempts left | M4 | Survey 3 |
| 79 | Secure Input Sheet (CAPTCHA) | In-memory CAPTCHA image display with refresh button | M4 | Survey 3 |
| 80 | Android `FLAG_SECURE` Platform Channel | Prevents screenshots, screen recording, and task switcher previews | M4 | Survey 3 |
| 81 | Secure Input Keyboard Hardening | `enableSuggestions: false`, `autocorrect: false`, no autofill | M4 | Survey 3 |
| 82 | Document Vault Screen | Listing of downloaded files with expiry countdown & delete | M4 | Survey 3 |
| 83 | Document Local Password Helper | On-device password construction hint (first 4 caps + birth year) | M4 | Survey 3 |
| 84 | Document Actions (Open, Share) | `open_filex` and `share_plus` integration | M4 | Survey 3 |
| 85 | History Drawer | Grouped by Today / Yesterday / Older with search & swipe-to-delete | M4 | Survey 3 |
| 86 | Settings Screen | Retention preferences, sign out, data deletion action | M4 | Survey 3 |
| 87 | GitHub Actions CI Workflow | `.github/workflows/ci.yml` running Flutter analyze & test + pytest | M5 | Survey 3 |
| 88 | GitHub Actions Supabase Keep-Alive | `.github/workflows/keepalive.yml` daily REST ping to Supabase | M5 | Survey 3 |
| 89 | GitHub Actions Cleanup Sweep | `.github/workflows/cleanup.yml` hourly sweep calling `/internal/cleanup` | M5 | Survey 3 |
| 90 | Render Deployment Descriptor | `render.yaml` configuring FastAPI free tier web service | M5 | Survey 3 |
| 91 | Environment Templates & AGENTS.md | `.env.example` with required keys and root `AGENTS.md` hard rules | M5 | Survey 3 |
| 92 | E2E Opaque-Box Test Suite | Comprehensive 4-tier E2E test suite covering full requirements | M6 | Survey 1,2,3 |
| 93 | Adversarial Coverage Hardening | White-box stress testing, gap analysis, and security fuzzing | M6 | Survey 1,2,3 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Supabase Database Schema, Migrations & Security | Features 1–6 (`supabase/migrations/0001_init.sql`, RLS policies, Storage buckets, Realtime publications) | none | PLANNED |
| M2 | FastAPI Backend Core & AI Engine | Features 7–38 (`backend/app/`, JWT auth, PII/Verhoeff scrubber, Groq LLM SSE, state machine, queue, challenge broker, all REST/WS endpoints) | M1 | PLANNED |
| M3 | Mock Government Portal & Automation Worker | Features 39–65 (`mock_portal/`, `backend/app/worker/`, Playwright worker, 10 failure modes, document verifier, storage upload) | M1, M2 | PLANNED |
| M4 | Flutter Mobile Application | Features 66–86 (`app/`, Riverpod, GoRouter, monochrome tokens, Arapey/Inter, GlassSurface, Supabase auth, SSE chat, stepper, secure sheets, vault, FLAG_SECURE) | M1, M2 | PLANNED |
| M5 | Cloud Operations, CI/CD & Production Configs | Features 87–91 (`.github/workflows/`, `render.yaml`, `.env.example`, `AGENTS.md`) | M1, M2, M3, M4 | PLANNED |
| M6 | Final Milestone: E2E Integration & Adversarial Hardening | Features 92–93 (Pass 100% E2E test suite Tiers 1-4, execute Tier 5 Adversarial Coverage Hardening, Victory Audit) | M1, M2, M3, M4, M5, TEST_READY.md | PLANNED |

## Interface Contracts

### 1. Flutter Mobile App ↔ FastAPI Backend (`app` ↔ `backend`)
- **Authentication:** All requests (except `GET /health`) send `Authorization: Bearer <Supabase_Access_Token>`.
- **Chat Streaming:** `POST /api/v1/chat`
  - Headers: `Authorization: Bearer <jwt>`, `Idempotency-Key: <uuid>`, `Accept: text/event-stream`
  - Body: `{"conversation_id": "<uuid | null>", "text": "<string>"}`
  - Response: Server-Sent Events stream (`data: {"token": "..."}`, `data: {"task_id": "...", "status": "RECEIVED"}`)
- **Task Input (OTP/CAPTCHA):** `POST /api/v1/tasks/{id}/input`
  - Body: `{"input_id": "<string>", "value": "<string>"}` (OTP must match `^\d{6}$`)
  - Response: `{"status": "accepted"}`
- **CAPTCHA Challenge Image:** `GET /api/v1/tasks/{id}/challenge`
  - Response: `image/png` with `Cache-Control: no-store`
- **Document Download:** `GET /api/v1/tasks/{id}/download`
  - Response: `{"download_url": "<signed_supabase_url>", "expires_in": 60}`

### 2. FastAPI Backend ↔ Playwright Worker (`backend` ↔ `worker`)
- **Transport:** WebSocket `WS /internal/worker`
- **Authentication:** `X-Worker-Secret: <WORKER_SHARED_SECRET>` or query parameter
- **Messages (Backend → Worker):**
  - `{"type": "TASK_DISPATCH", "task_id": "<uuid>", "workflow": "aadhaar_download", "params": {"uid": "<masked_uid>"}}`
  - `{"type": "INPUT_RESPONSE", "task_id": "<uuid>", "kind": "OTP"|"CAPTCHA", "value": "<secret_str>"}`
  - `{"type": "TASK_CANCEL", "task_id": "<uuid>"}`
- **Messages (Worker → Backend):**
  - `{"type": "WORKER_READY", "worker_id": "<id>", "capabilities": ["headless_chromium"]}`
  - `{"type": "CHALLENGE_REQUEST", "task_id": "<uuid>", "kind": "CAPTCHA", "image_base64": "<b64>", "prompt": "Enter CAPTCHA"}`
  - `{"type": "CHALLENGE_REQUEST", "task_id": "<uuid>", "kind": "OTP", "prompt": "Enter 6-digit OTP", "expires_in": 180, "attempts_left": 3}`
  - `{"type": "TASK_EVENT", "task_id": "<uuid>", "status": "<STATUS>", "message": "<msg>", "progress": 0..100}`
  - `{"type": "TASK_COMPLETE", "task_id": "<uuid>", "document": {"file_name": "...", "size_bytes": 1234, "sha256": "...", "storage_path": "..."}}`
  - `{"type": "TASK_FAIL", "task_id": "<uuid>", "error_code": "...", "error_message": "..."}`

### 3. Flutter Mobile App ↔ Supabase Backend (`app` ↔ `supabase`)
- **Auth:** Standard Supabase Auth (Sign in with password, Sign up with password, Reset password).
- **Realtime:** Subscribes to channels:
  - `postgres_changes` on `tasks` (filter: `user_id=eq.<uid>`)
  - `postgres_changes` on `task_events` (filter: `user_id=eq.<uid>`)
  - `postgres_changes` on `messages` (filter: `user_id=eq.<uid>`)
- **Direct Reads:** Read `conversations`, `messages`, `tasks`, `task_events`, `documents` under RLS.
