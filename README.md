# Saral AI — Outcome-Oriented Civic Assistant (Zero-Cost Free-Tier Edition)

[![CI/CD Pipeline](https://github.com/ankithahathwar/SaralAI/actions/workflows/ci.yml/badge.svg)](https://github.com/ankithahathwar/SaralAI/actions/workflows/ci.yml)
[![Supabase Keepalive](https://github.com/ankithahathwar/SaralAI/actions/workflows/keepalive.yml/badge.svg)](https://github.com/ankithahathwar/SaralAI/actions/workflows/keepalive.yml)
[![Document Retention Cleanup](https://github.com/ankithahathwar/SaralAI/actions/workflows/cleanup.yml/badge.svg)](https://github.com/ankithahathwar/SaralAI/actions/workflows/cleanup.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg)](LICENSE)
[![Flutter](https://img.shields.io/badge/Flutter-3.22+-black.svg?logo=flutter)](https://flutter.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-black.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL%20%2B%20Auth-black.svg?logo=supabase)](https://supabase.com)
[![Groq](https://img.shields.io/badge/LLM-Groq%20Llama%203.3%2070B-black.svg)](https://groq.com)

---

## 1. Overview

**Saral AI** is an outcome-oriented, zero-cost civic assistant designed for Indian citizens. Instead of requiring users to navigate complex, fragmented government portals, Saral AI allows citizens to state their goal in conversational natural language (e.g., *"Download my Aadhaar card"*). 

The system orchestrates a deterministic browser automation worker, securely pauses for required citizen inputs (CAPTCHA challenge text and 6-digit OTP), verifies the downloaded payload against a 5-point document security inspection, and delivers the encrypted official PDF directly to a secure on-device document vault.

### Core Cost & Architecture Strategy
- **Infrastructure Cost:** **₹0 / month** using free tiers (Supabase Free, Render Free, Groq API Free Tier, GitHub Actions free runner allowance).
- **Separation of Concerns:** Headless Chromium **never** runs on Render Free (preventing OOM errors on 512 MB instances). The browser automation worker runs locally or on a dedicated host, connecting **outbound** to the FastAPI backend via an authenticated WebSocket.
- **Queue & Realtime:** Supabase PostgreSQL acts as the persistent job queue using `FOR UPDATE SKIP LOCKED`. Task events stream to the mobile app via native Supabase Realtime subscriptions under Row Level Security.

---

## 2. System Architecture

```mermaid
flowchart TD
    subgraph MobileApp["Flutter Android Client (app/)"]
        AuthUI["Supabase Auth (Email + Password)"]
        ChatUI["Chat UI (SSE Streaming Tokens)"]
        SecureSheet["Secure Input Sheet (FLAG_SECURE)"]
        VaultUI["Document Vault (Local Storage)"]
    end

    subgraph BackendAPI["FastAPI Backend (backend/ on Render Free)"]
        JWT["JWT Auth & Ownership Check"]
        Scrubber["PII & Biometric Scrubber (Verhoeff D5)"]
        Router["Intent Classifier (Rules + Groq LLM)"]
        StateMachine["12-State Task Machine & Queue"]
        ChallengeBroker["In-Memory Challenge Broker (SecretStr)"]
        CleanupCron["POST /internal/cleanup"]
    end

    subgraph CloudServices["Supabase Cloud Infrastructure"]
        SupaAuth["Supabase Auth"]
        SupaDB[("PostgreSQL Database\n- profiles\n- tasks\n- task_events\n- documents")]
        SupaStorage[("Private Storage Bucket\n/documents/{user_id}/")]
        SupaRealtime["Supabase Realtime Engine"]
    end

    subgraph AutomationWorker["Browser Worker (Playwright / Chromium)"]
        WSClient["Outbound WebSocket Client"]
        DomainPolicy["Route Allowlist Enforcer"]
        PageAutomation["Headless Page Automation"]
        DocVerifier["5-Point Document Verifier"]
    end

    subgraph TargetPortals["Official Portals & Test Harness"]
        MockPortal["Mock Government Portal (mock_portal/)"]
        UIDAIPortal["Official UIDAI myAadhaar Portal"]
    end

    %% Mobile Connections
    AuthUI -->|Sign In / Sign Up| SupaAuth
    ChatUI -->|POST /api/v1/chat (SSE)| BackendAPI
    SecureSheet -->|POST /api/v1/tasks/{id}/input| ChallengeBroker
    SupaRealtime -.->|task_events updates| MobileApp
    VaultUI -->|GET /api/v1/tasks/{id}/download| BackendAPI

    %% Backend Connections
    BackendAPI -->|JWT Validation & RLS| SupaDB
    BackendAPI -->|Chat Tokens / Tools| GroqLLM["Groq Cloud API (Llama 3.3 70B)"]
    ChallengeBroker <==>|In-Memory WS Relay| WSClient

    %% Worker Connections
    WSClient --> PageAutomation
    DomainPolicy -->|Route Filter| PageAutomation
    PageAutomation --> MockPortal
    PageAutomation -.-> UIDAIPortal
    PageAutomation --> DocVerifier
    DocVerifier -->|Encrypted Upload| SupaStorage
```

---

## 3. Security & Non-Negotiable Invariants

Saral AI is built under rigorous cryptographic and data privacy constraints:

1. **Zero Persistence of Sensitive Verification Credentials:**
   - OTP and CAPTCHA inputs exist **strictly in-memory** (`pydantic.SecretStr`).
   - They are **never** persisted to PostgreSQL, written to application logs, broadcasted via Supabase Realtime, or injected into any LLM prompt.
   - Values are relayed across ephemeral `asyncio.Future` buffers and wiped immediately after DOM injection.
2. **Verifier-Only Completion Gate:**
   - A task can **only** advance from `VERIFYING` to `COMPLETED` when executed by `actor="verifier"`.
   - LLMs can never mark tasks as complete, regardless of prompt output or generated tokens.
3. **PII & Biometric Scrubbing with Verhoeff Checksum ($D_5$):**
   - 12-digit Aadhaar / VID numbers matching the dihedral group $D_5$ Verhoeff checksum are masked to visual format `XXXX-XXXX-1234`.
   - Indian phone numbers (`[REDACTED_PHONE]`), email addresses (`[REDACTED_EMAIL]`), biometric mentions (`[REDACTED_BIOMETRIC]`), and verification codes (`[REDACTED_OTP]`) are scrubbed before storage or model dispatch.
4. **Route-Level Domain Allowlisting:**
   - The browser worker enforces network interception (`context.route`). Any request targeting a domain outside `ALLOWED_DOMAINS` is instantly aborted.
5. **Multi-Tenant Row Level Security (RLS):**
   - All tables enforce strict Postgres RLS. Operational tables (`tasks`, `task_events`, `documents`, `messages`) are read-only for authenticated clients; writes are restricted exclusively to the backend service role key.
   - User B is cryptographically prevented from querying, canceling, or downloading User A's tasks or documents.
6. **5-Point Document Verifier:**
   - Verifies magic `%PDF-` header bytes.
   - Enforces payload bounds (10 KB minimum to 5 MB maximum).
   - Validates structural trailers and xref tables using `pypdf`.
   - Strictly scans for and rejects files with malicious `/JavaScript` or `/Launch` action dictionaries.
   - Computes SHA-256 integrity hash and confirms document encryption status.
7. **Mobile Client Window Protection (`FLAG_SECURE`):**
   - The Flutter mobile client enforces Android `FLAG_SECURE` on sensitive screens to prevent screenshots, screen recordings, and Android Recents task-switcher previews.

---

## 4. Repository Structure

```text
saral-ai/
├── .github/
│   └── workflows/
│       ├── ci.yml                     # Multi-job CI: Backend, Mock Portal, E2E, Flutter
│       ├── keepalive.yml              # Daily keepalive ping to Supabase free tier
│       └── cleanup.yml                # Hourly document retention cleanup sweep
├── AGENTS.md                          # Multi-agent architecture, state machine, and hard rules
├── render.yaml                        # Render Infrastructure as Code Blueprint
├── .env.example                       # Production configuration template
├── README.md                          # Comprehensive documentation
├── run_e2e_tests.py                   # Standalone 4-tier E2E test runner (84 tests)
├── supabase/
│   ├── migrations/
│   │   └── 0001_init.sql              # Supabase tables, RLS policies, storage bucket, triggers
│   └── tests/
│       ├── test_0001_init.sql         # SQL RLS and security verification tests
│       ├── test_schema.py             # Pytest schema verification suite
│       └── verify_schema.py           # Automated schema integrity verification runner
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI application lifespan & middleware
│   │   ├── config.py                  # Pydantic BaseSettings environment loader
│   │   ├── auth.py                    # Supabase JWT bearer authentication & ownership check
│   │   ├── scrubber.py                # Verhoeff dihedral D5 checksum + PII scrubber
│   │   ├── llm.py                     # Groq LLM client & SSE token streaming
│   │   ├── state_machine.py           # Deterministic 12-state task engine & verifier gate
│   │   ├── queue.py                   # PostgreSQL FOR UPDATE SKIP LOCKED job queue
│   │   ├── broker.py                  # In-memory transient CAPTCHA & OTP challenge broker
│   │   ├── store.py                   # In-memory and Postgres document storage interface
│   │   ├── api/                       # REST endpoints (health, chat, tasks, docs, internal)
│   │   └── worker/                    # Playwright automation worker & document verifier
│   ├── tests/                         # Backend unit & integration test suites
│   ├── requirements.txt
│   └── pyproject.toml
├── mock_portal/                       # Mock Government Portal for offline E2E validation
│   ├── app/
│   │   ├── main.py                    # Standalone FastAPI portal with 10 failure switches
│   │   ├── captcha.py                 # Distorted PNG CAPTCHA challenge generator
│   │   ├── otp.py                     # OTP lifecycle, retry limits, and countdown timers
│   │   └── pdf.py                     # Sample PDF generator (valid, corrupt, malicious)
│   ├── templates/                     # Portal HTML templates (UID entry, OTP validation)
│   └── tests/                         # Mock portal contract tests
├── tests/
│   └── e2e/                           # Comprehensive 4-Tier E2E test suite (84 tests)
│       ├── conftest.py                # Oracle harness & live server fixtures
│       ├── test_tier1_feature_coverage.py
│       ├── test_tier2_boundaries_and_corners.py
│       ├── test_tier3_pairwise_combinations.py
│       └── test_tier4_real_world_scenarios.py
└── app/                               # Flutter Android Application
    ├── lib/
    │   ├── main.dart                  # Flutter entrypoint & initialization
    │   ├── core/                      # Monochrome tokens, Arapey/Inter typography, GlassSurface
    │   └── features/
    │       ├── auth/                  # Supabase Auth screens (Sign In, Sign Up, Password Reset)
    │       ├── chat/                  # Chat interface with SSE message streaming & task stepper
    │       ├── tasks/                 # Task stepper card & secure masked input sheets
    │       ├── vault/                 # Document vault with expiry countdown & local actions
    │       └── history/               # Conversation history drawer (Today/Yesterday/Older)
    └── test/                          # Flutter widget & unit test suite
```

---

## 5. Quickstart Guide (Local Development)

### Prerequisites
- **Python 3.12+**
- **Flutter 3.22+** with Android SDK
- **Supabase CLI** (optional for local DB, or use cloud Supabase)
- **Groq API Key** (from [console.groq.com](https://console.groq.com))

### Step 1: Environment Setup
```bash
# Clone the repository
git clone https://github.com/ankithahathwar/SaralAI.git
cd SaralAI

# Copy environment template
cp .env.example .env
```
Fill in `.env` with your Supabase URL, keys, and Groq API key.

### Step 2: Supabase Database Migration
Apply the database schema and RLS policies:
```bash
# Link to your Supabase project
supabase link --project-ref <your-project-id>

# Push the migration
supabase db push
```

### Step 3: Run the FastAPI Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Test health probe: `curl http://127.0.0.1:8000/health` → `{"status": "ok", "service": "saral-api"}`

### Step 4: Run the Mock Government Portal
```bash
cd mock_portal
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```
Access the mock portal at `http://127.0.0.1:8001`.

### Step 5: Run the Playwright Automation Worker
```bash
cd backend
playwright install chromium
python -m app.worker.main
```

### Step 6: Run the Flutter Mobile App
```bash
cd app
flutter pub get
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000 \
            --dart-define=SUPABASE_URL=https://<your-project>.supabase.co \
            --dart-define=SUPABASE_PUBLISHABLE_KEY=<your-anon-key>
```
*(Note: `10.0.2.2` routes to host localhost in Android Emulator).*

---

## 6. Testing & Quality Assurance

Saral AI maintains a comprehensive multi-tier test suite with 100% verification coverage.

### 1. Comprehensive 4-Tier E2E Test Suite (84 Tests)
```bash
# Run all 84 E2E tests across 4 tiers
uv run --with pytest python run_e2e_tests.py

# Run specific tiers
python run_e2e_tests.py --tier 1   # Category-Partition Feature Coverage (47 tests)
python run_e2e_tests.py --tier 2   # Boundary Value Analysis & Corners (21 tests)
python run_e2e_tests.py --tier 3   # Pairwise Subsystem Integrations (10 tests)
python run_e2e_tests.py --tier 4   # Real-World Workflows & Recovery (6 tests)
```

### 2. Supabase Schema & Security Tests
```bash
# Verify schema tables, constraints, RLS policies, and triggers
python supabase/tests/verify_schema.py

# Run database tests with pytest
pytest supabase/tests/ -v
```

### 3. Flutter Static Analysis & Widget Tests
```bash
cd app
# Static analysis (Enforces 0 errors and 0 warnings)
flutter analyze

# Widget & unit tests
flutter test
```

---

## 7. REST & WebSocket API Specification

All protected endpoints require `Authorization: Bearer <Supabase_JWT>`.

| Method | Endpoint | Auth | Purpose | Request Body / Query | Response |
|---|---|---|---|---|---|
| `GET` | `/health` | Public | Warm-up probe & health check | None | `{"status": "ok", "service": "saral-api"}` |
| `POST` | `/api/v1/chat` | JWT | PII-scrubbed SSE chat stream | `{"conversation_id": "...", "text": "..."}` | `text/event-stream` tokens / task events |
| `POST` | `/api/v1/tasks` | JWT | Direct task creation | `{"workflow": "aadhaar_download"}` | `{"id": "...", "status": "RECEIVED"}` |
| `GET` | `/api/v1/tasks/{id}` | JWT | Task status & pending challenges | None | `{"id": "...", "status": "...", "pending_input": {...}}` |
| `POST` | `/api/v1/tasks/{id}/input` | JWT | Submit OTP or CAPTCHA text | `{"input_id": "...", "value": "123456"}` | `{"status": "accepted"}` |
| `GET` | `/api/v1/tasks/{id}/challenge` | JWT | In-memory CAPTCHA PNG bytes | None | `image/png` (`Cache-Control: no-store`) |
| `POST` | `/api/v1/tasks/{id}/cancel` | JWT | Cooperative task cancellation | None | `{"status": "cancelled"}` |
| `GET` | `/api/v1/tasks/{id}/download` | JWT | Generate 60-second signed URL | None | `{"download_url": "...", "expires_in": 60}` |
| `DELETE` | `/api/v1/documents/{id}` | JWT | Delete document row and storage | None | `{"status": "deleted"}` |
| `WS` | `/internal/worker` | Secret | Browser worker bidirectional link | Header: `X-Worker-Secret` | Bidirectional JSON event stream |
| `POST` | `/internal/cleanup` | Secret | Retention sweep cron endpoint | Header: `X-Cleanup-Secret` | `{"status": "ok", "cleaned_documents": N}` |

---

## 8. Production Deployment Guide

### Deploying API & Mock Portal to Render Free
1. Connect your GitHub repository to [Render](https://render.com).
2. Create a new **Blueprint Instance** pointing to `render.yaml`.
3. Configure the required environment variables in Render Dashboard:
   - `SUPABASE_URL`
   - `SUPABASE_PUBLISHABLE_KEY`
   - `SUPABASE_SECRET_KEY`
   - `SUPABASE_JWT_SECRET`
   - `DATABASE_URL`
   - `GROQ_API_KEY`
4. Render will automatically spin up:
   - `saral-backend` (`https://saral-backend.onrender.com`)
   - `saral-mock-portal` (`https://saral-mock-portal.onrender.com`)

### GitHub Actions Secrets Configuration
In your GitHub Repository Settings → **Secrets and variables** → **Actions**, add:

| Secret Name | Description |
|---|---|
| `SUPABASE_URL` | Your Supabase project URL (`https://<project>.supabase.co`) |
| `SUPABASE_PUBLISHABLE_KEY` | Supabase anon/publishable key |
| `BACKEND_API_URL` | Hosted FastAPI backend URL (`https://saral-backend.onrender.com`) |
| `CLEANUP_SECRET` | Secret token matching `CLEANUP_SECRET` in backend `.env` |

### Automated Maintenance Jobs
- **Daily Supabase Keepalive (`keepalive.yml`):** Runs daily at `04:00 UTC` to send REST and Auth queries to Supabase, preventing free-tier projects from pausing after 7 days of inactivity.
- **Hourly Document Retention Cleanup (`cleanup.yml`):** Runs hourly (`0 * * * *`) calling `POST /internal/cleanup` to sweep expired documents from the Postgres database and Supabase Storage.

### Building Release Android APK
```bash
cd app
flutter build apk --release \
  --dart-define=API_BASE_URL=https://saral-backend.onrender.com \
  --dart-define=SUPABASE_URL=https://<your-project>.supabase.co \
  --dart-define=SUPABASE_PUBLISHABLE_KEY=<your-anon-key>
```
The production APK is generated at `app/build/app/outputs/flutter-apk/app-release.apk`.
