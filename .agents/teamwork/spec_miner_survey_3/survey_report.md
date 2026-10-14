# Saral AI — Flutter Mobile App, Supabase Database & Operations Specification Report

**Document Version:** 1.0  
**Date:** 13 October 2026  
**Author:** `spec_miner_survey_3` (Flutter App & Schema Spec Miner)  
**Target Project:** Saral AI Android Application, Supabase Backend, and Cloud Operations  
**Authoritative Sources:**
- `d:\Startup\Saral Ai\Saral_app\ORIGINAL_REQUEST.md`
- `d:\Startup\Saral Ai\Saral_app\SARAL_AI_IMPLEMENTATION_PLAN.md` (Sections 1–20, specifically Sections 4, 10, 11, 14, 18)
- `d:\Startup\Saral Ai\Saral_app\rules.md` (Engineering rules, R-ARCH, R-PERF, R-UI, R-SEC, R-REAL, R-VIS)

---

## 1. Executive Summary & Architecture Overview

Saral AI is an outcome-oriented, zero-cost (free-tier optimized) mobile assistance system for Indian citizens interacting with official government services. The architecture decouples the lightweight mobile presentation layer, serverless database/storage backend, API orchestration engine, and isolated browser automation workers:

```
┌─────────────────────────────────────────────────────────────┐
│                 Flutter Android App (app/)                  │
│  - Strict monochrome design (#000000, #0A0A0A, #141414)     │
│  - Arapey & Inter typography; GlassSurface (<=3 blurred)     │
│  - State management: flutter_riverpod; Router: go_router   │
│  - Direct Supabase Realtime subscription (tasks, events)    │
│  - FLAG_SECURE & visual masking for Aadhaar/VID & OTP       │
└──────────────┬───────────────────────────────┬──────────────┘
               │ HTTPS + SSE                   │ Supabase Auth & Realtime
               ▼                               ▼
┌───────────────────────────────┐  ┌───────────────────────────┐
│ FastAPI API (Render Free)     │  │ Supabase (Free Tier)      │
│  - JWT verification           │  │  - Auth (Email/Pass)      │
│  - PII Scrubber               │  │  - Postgres with RLS      │
│  - Intent Classifier          │  │  - Private Storage Bucket │
│  - In-memory challenge broker │  │  - Realtime Publications  │
└──────────────┬────────────────┘  └─────────────▲─────────────┘
               │ Outbound WebSocket (WSS)        │ Direct Upload
               ▼                                 │ (Service Key)
┌────────────────────────────────────────────────┴─────────────┐
│ Playwright Worker (Isolated Docker / PC)                    │
│  - Headless Chromium with strict domain allowlist           │
│  - Challenge extraction & fill; PDF validation & SHA-256    │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Supabase Database Schema & Storage (`supabase/migrations/0001_init.sql`)

### 2.1 Complete SQL DDL Specification

```sql
-- Extension
create extension if not exists pgcrypto;

-- 1. Profiles
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  created_at timestamptz not null default now()
);

-- 2. Conversations
create table public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null default 'New chat',
  archived boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on public.conversations (user_id, updated_at desc);

-- 3. Messages
create table public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('user','assistant','system','task')),
  content text not null,              -- PII-scrubbed before storage
  task_id uuid,
  created_at timestamptz not null default now()
);
create index on public.messages (conversation_id, created_at);

-- 4. Tasks
create table public.tasks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  conversation_id uuid references public.conversations(id) on delete set null,
  workflow text not null,
  status text not null default 'RECEIVED' check (status in
    ('RECEIVED','VALIDATING','PLANNING','RUNNING','WAITING_FOR_USER','AUTHENTICATING',
     'DOWNLOADING','VERIFYING','COMPLETED','FAILED','CANCELLED','EXPIRED')),
  request_text text,                  -- scrubbed
  idempotency_key text not null,
  pending_input jsonb,                -- {kind, prompt, expires_at, attempts_left} — NEVER values
  error_code text,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  finished_at timestamptz,
  unique (user_id, idempotency_key)
);
-- Duplicate-execution protection: exactly one active task per user per workflow
create unique index one_active_task_per_workflow on public.tasks (user_id, workflow)
  where status not in ('COMPLETED','FAILED','CANCELLED','EXPIRED');

-- 5. Task Events
create table public.task_events (
  id bigint generated always as identity primary key,
  task_id uuid not null references public.tasks(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  status text not null,
  message text not null,
  progress smallint check (progress between 0 and 100),
  created_at timestamptz not null default now()
);
create index on public.task_events (task_id, id);

-- 6. Documents
create table public.documents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  task_id uuid references public.tasks(id) on delete set null,
  doc_type text not null,
  file_name text not null,
  storage_path text not null unique,  -- '<user_id>/<task_id>.pdf'
  size_bytes integer not null,
  sha256 text not null,
  pdf_encrypted boolean not null default false,
  created_at timestamptz not null default now(),
  delete_after timestamptz not null   -- retention deadline
);
create index on public.documents (user_id, created_at desc);

-- 7. Row Level Security (RLS)
alter table public.profiles      enable row level security;
alter table public.conversations enable row level security;
alter table public.messages      enable row level security;
alter table public.tasks         enable row level security;
alter table public.task_events   enable row level security;
alter table public.documents     enable row level security;

-- Client permissions
create policy "own profile"       on public.profiles      for all    using (id = auth.uid()) with check (id = auth.uid());
create policy "own conversations" on public.conversations for all    using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Read-only client policies (Backend writes with secret service_role key)
create policy "read own messages"  on public.messages    for select using (user_id = auth.uid());
create policy "read own tasks"     on public.tasks       for select using (user_id = auth.uid());
create policy "read own events"    on public.task_events for select using (user_id = auth.uid());
create policy "read own documents" on public.documents   for select using (user_id = auth.uid());

-- 8. Storage Configuration & Storage RLS
insert into storage.buckets (id, name, public) values ('documents','documents', false)
  on conflict (id) do nothing;

create policy "read own files" on storage.objects for select to authenticated
  using (bucket_id = 'documents' and (storage.foldername(name))[1] = auth.uid()::text);

-- 9. Realtime Publication
alter publication supabase_realtime add table public.tasks, public.task_events, public.messages;

-- 10. Automated Profile Creation Trigger
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.profiles (id) values (new.id);
  return new;
end;
$$;

create or replace trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
```

### 2.2 Security, Cascades & RLS Invariants

| Invariant / Mechanism | Specification & Behavioral Contract | Authoritative Source |
|---|---|---|
| **Foreign Key Cascades** | `user_id` deletion in `auth.users` cascades to `profiles`, `conversations`, `messages`, `tasks`, `task_events`, and `documents`. Deleting a conversation cascades to messages. Deleting a task cascades to `task_events` and sets `task_id` to `NULL` in `messages` and `documents`. | Section 4 DDL |
| **Client Read-Only Enforcement** | Clients possessing only the `publishable` key can **never** insert, update, or delete rows in `messages`, `tasks`, `task_events`, or `documents`. All writes must originate from the FastAPI backend using `service_role` (secret key). | Section 4, 14 (Rule 1) |
| **Storage User Isolation** | Bucket `documents` is private (`public = false`). Direct client downloads verify `(storage.foldername(name))[1] = auth.uid()::text`. No client insert/update/delete policies exist. | Section 4 Storage Policy |
| **Idempotency Protection** | Unique constraint on `(user_id, idempotency_key)` in `tasks`. | Section 4 DDL |
| **Concurrency Protection** | Partial unique index `one_active_task_per_workflow` on `tasks(user_id, workflow)` where `status not in ('COMPLETED', 'FAILED', 'CANCELLED', 'EXPIRED')`. Prevents concurrent tasks for the same workflow. | Section 4 DDL |
| **Zero-Persistence Policy** | `tasks.pending_input` stores ONLY metadata (`kind`, `prompt`, `expires_at`, `attempts_left`). Raw OTPs, CAPTCHAs, and Aadhaar numbers are **strictly forbidden** from database columns, Realtime events, or logs. | Section 4, 7, 14 (Rule 2) |
| **Retention Enforcement** | `documents.delete_after` records retention deadline (default 24 hours, max 30 days). Expired records and associated storage objects are swept hourly by `/internal/cleanup`. | Section 4, 8.2, 18 |

---

## 3. Flutter Mobile Application Specification (`app/`)

### 3.1 Architectural Foundation & Code Organization

The Flutter application strictly adheres to Clean Modular Architecture (`rules.md` R-ARCH and R-FILE) and the technical requirements of `SARAL_AI_IMPLEMENTATION_PLAN.md` Section 10:

```
app/
├── lib/
│   ├── app/
│   │   ├── app.dart                   # Root MaterialApp with theme & router wiring
│   │   ├── bootstrap.dart             # Async initialization & binding
│   │   └── router.dart                # Central go_router configuration
│   ├── core/
│   │   ├── constants/                 # Route names, asset paths
│   │   ├── errors/                    # Result and Failure domain models
│   │   ├── net/                       # Dio client with JWT interceptor & SSE reader
│   │   ├── platform/                  # FLAG_SECURE platform channel wrapper
│   │   ├── theme/
│   │   │   ├── app_colors.dart        # Monochrome tokens (#000000, #0A0A0A, #141414)
│   │   │   ├── motion.dart            # Duration and curve tokens
│   │   │   ├── typography.dart        # Arapey & Inter TextStyle definitions
│   │   │   └── app_theme.dart         # Dark ThemeData configuration
│   │   └── widgets/
│   │       ├── glass_surface.dart     # GlassSurface with BackdropFilter & RepaintBoundary
│   │       ├── pill_button.dart       # Rounded interactive button
│   │       ├── shimmer_skeleton.dart  # Monochrome loading placeholders
│   │       └── waving_shimmer.dart    # Waking-server indicator
│   └── features/
│       ├── auth/
│       │   ├── presentation/          # AuthScreen, sign_in_form, sign_up_form, reset_form
│       │   └── state/                 # auth_controller_provider, auth_state
│       ├── chat/
│       │   ├── presentation/          # ChatScreen, message_bubble, composer_pill, suggestion_chip
│       │   └── state/                 # chat_messages_provider, chat_stream_provider
│       ├── tasks/
│       │   ├── presentation/          # TaskStepperCard, secure_input_sheet, otp_boxes, captcha_box
│       │   └── state/                 # task_realtime_provider, secure_input_controller
│       ├── vault/
│       │   ├── presentation/          # VaultScreen, document_card, document_viewer_modal
│       │   └── state/                 # vault_documents_provider, download_controller
│       ├── history/
│       │   ├── presentation/          # HistoryDrawer, history_group_tile, search_bar
│       │   └── state/                 # history_provider
│       └── settings/
│           ├── presentation/          # SettingsScreen, retention_picker
│           └── state/                 # settings_provider (lowPowerGlass flag)
```

**State Management & Routing Principles:**
- State Management: `flutter_riverpod` (Notifiers and AsyncNotifiers). No business logic inside widgets. Screen-scoped notifiers auto-disposed (`AutoDisposeNotifier`).
- Navigation: `go_router` declarative routing. Routes:
  - `/splash` (`SplashScreen`)
  - `/auth` (`AuthScreen`)
  - `/chat` (`ChatScreen` with drawer)
  - `/vault` (`VaultScreen`)
  - `/settings` (`SettingsScreen`)
- Configuration: `--dart-define` exclusively (`SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `API_BASE_URL`). No committed secrets or hardcoded endpoints.

### 3.2 Strict Monochrome Visual Design System (R-VIS & Section 10.2)

1. **Strict Palette:**
   - Base Canvas: Black `#000000` (`AppColors.black`)
   - Raised Areas / Elevation 1: Ink `#0A0A0A` (`AppColors.ink`)
   - Card Surfaces / Elevation 2: Graphite `#141414` (`AppColors.graphite`)
   - Interactive Elements (Buttons, Sheets, Boxes): Dark Grey `#1A1A1A`
   - **Zero Accent Hues:** No blue, green, red, amber, or colored tints. Errors, warnings, and success must be communicated strictly through icon glyphs, text copy, layout weight, and motion.
2. **Text Hierarchy (White Opacity):**
   - High Emphasis (Headings, primary body): White 100% (`#FFFFFF`, `AppColors.textHigh`)
   - Mid Emphasis (Secondary labels, metadata): White 64% (`AppColors.textMid`)
   - Low Emphasis (Placeholders, disabled states): White 38% (`AppColors.textLow`)
3. **Typography Standards:**
   - **Arapey** (Google Font, bundled locally in `pubspec.yaml`): Wordmark, screen titles, greetings, key assistant highlight phrases. Arapey ships Regular and Italic styles; emphasis is achieved through font size, italics, and letter spacing. Section headings remain upright per R-PHX.
   - **Inter** (Google Font, bundled locally in `pubspec.yaml`): All UI elements, body copy, input text, buttons, stepper labels, and metadata.
4. **Shapes & Radii:**
   - Composer: Radius 28 dp (pill when single-line, softly rounded when multi-line)
   - Cards & Steppers: Radius 24 dp
   - Bottom Sheets: Radius 32 dp (top-left and top-right corners)
   - Buttons: Fully rounded (pill shape)

### 3.3 Glassmorphic UI Engineering (`GlassSurface`)

```dart
// lib/core/widgets/glass_surface.dart
import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:saral_app/core/theme/app_colors.dart';

class GlassSurface extends StatelessWidget {
  const GlassSurface({
    super.key,
    required this.child,
    this.radius = 28,
    this.blur = 24,
    this.padding,
    this.borderWidth = 1.0,
  });

  final Widget child;
  final double radius;
  final double blur;
  final EdgeInsetsGeometry? padding;
  final double borderWidth;

  @override
  Widget build(BuildContext context) {
    final r = BorderRadius.circular(radius);
    return RepaintBoundary(
      child: ClipRRect(
        borderRadius: r,
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: blur, sigmaY: blur),
          child: Container(
            padding: padding,
            decoration: BoxDecoration(
              borderRadius: r,
              border: Border.all(
                color: AppColors.glassStroke(),
                width: borderWidth,
              ),
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [
                  AppColors.glassFill(0.09),
                  AppColors.glassFill(0.03),
                ],
              ),
            ),
            child: child,
          ),
        ),
      ),
    );
  }
}
```

**Android Glass Performance Invariants (Section 10.4):**
- Maximum **3 blurred surfaces simultaneously active** on any screen (e.g., composer pill, app bar, history drawer).
- Message bubbles use translucent monochrome fill **without** `BackdropFilter` to avoid raster thread overload.
- Every `GlassSurface` is wrapped in a `RepaintBoundary`.
- `lowPowerGlass` Fallback: User toggle / device profile flag that dynamically swaps `BackdropFilter` for an 85% opaque `#1A1A1A` solid container fill.

### 3.4 Motion & Micro-Interactions (Section 10.3)

| Component | Micro-Interaction Specification | Tokens & Curves |
|---|---|---|
| **Chat Message Arrival** | Fade-in with 8 dp upward slide. Assistant streaming tokens arrive with soft alpha fade (not character jitter). | Duration: `240ms` (`Motion.base`), Curve: `Curves.easeOutCubic` |
| **Send Button** | Morphs from mic-less outline to filled white circle on input; spring scale on tap; light haptic click. | Duration: `120ms` (`Motion.fast`), Spring Curve |
| **Typing Indicator** | Three dots with staggered opacity pulse (0.38 → 1.00 → 0.38). | Duration: `420ms` loop |
| **Task Stepper Line** | Connecting line draws dynamically between steps as status advances; active step circle has a slow breathing opacity glow. | Duration: `420ms` (`Motion.slow`), Opacity loop `0.5 <-> 1.0` |
| **OTP Input Boxes** | Digit scales in; box shakes horizontally with soft haptic on incorrect code; circular countdown ring shrinks smoothly. | Shake: 3 cycles over `240ms`; Scale: `120ms` |
| **Waking Server** | Subtle horizontal shimmer line above composer ("Waking the server…") if request latency exceeds 2000ms. | Shimmer loop, fading out upon first response chunk. |

### 3.5 Detailed Screen Specifications & Security Workflows

#### 3.5.1 Splash Screen
- **Visuals:** Arapey wordmark ("Saral AI") centered on `#000000` canvas, fading in over 420ms.
- **Operations:**
  1. Calls `supabase.auth.currentSession` to evaluate existing authentication state.
  2. Fires asynchronous background warm-up `GET /health` to wake sleeping Render instance.
  3. Transitions via GoRouter to `/chat` if session valid, or `/auth` if invalid/expired.

#### 3.5.2 Auth Screen
- **Visuals:** Single centered `GlassSurface` card on `#000000` canvas.
- **Features:** Segmented tabs for "Sign In", "Sign Up", and "Reset Password".
- **Fields:** Email and Password (enforces min 8 characters).
- **Error Handling:** Clear inline error messages (e.g., "Invalid email or password", "Network unavailable") with retry buttons. No raw backend stack traces.

#### 3.5.3 Chat Screen (Home)
- **Visuals:** Direct-to-chat layout. Top bar with history drawer hamburger icon and "New Chat" action.
- **Empty State:** Centered Arapey italic greeting (*"How can I assist you with government services today?"*) and 3 horizontal glass suggestion chips (e.g., "Download my e-Aadhaar", "Check task status", "PF claim checklist").
- **Composer Pill:** Bottom-anchored `GlassSurface` pill (radius 28). Auto-expanding up to 5 lines. Send button on right.
- **SSE Message Streaming:** Connects to `POST /api/v1/chat`. Streams response tokens directly into the active assistant message bubble with smooth opacity fade.
- **Task Stepper Injection:** When `POST /api/v1/chat` returns a `task_id`, an inline `TaskStepperCard` replaces the streaming placeholder.

#### 3.5.4 Inline Task Stepper Card
- **Realtime Integration:** Subscribes to `public.task_events` on Supabase Realtime filtering by `task_id = eq.<id>`.
- **States Visualized:**
  1. `RECEIVED`
  2. `VALIDATING`
  3. `PLANNING`
  4. `RUNNING`
  5. `WAITING_FOR_USER` (Triggers Secure Input Sheet)
  6. `AUTHENTICATING`
  7. `DOWNLOADING`
  8. `VERIFYING`
  9. `COMPLETED` (Morphs into Document Delivery Card) / `FAILED` / `CANCELLED`
- **Actions:** Cooperative "Cancel" button triggers `POST /api/v1/tasks/{id}/cancel`.

#### 3.5.5 Secure Input Sheet (OTP, CAPTCHA, Aadhaar/VID)
- **Security Hardening:**
  - Activates `FLAG_SECURE` on Android window via platform channel (`screen_protector`) upon opening; deactivates on dismissal.
  - Text inputs enforce `enableSuggestions: false`, `autocorrect: false`, no autofill hints, and no clipboard copy/paste options.
  - Zero SMS auto-retriever / auto-read permissions.
- **Aadhaar/VID Input Mode:**
  - 12-digit / 16-digit input formatted with visual masking: `XXXX-XXXX-1234`.
  - Client-side Verhoeff algorithm validation verifies checksum before sending.
- **OTP Input Mode:**
  - 6 individual glass input boxes with auto-advance and backspace handling.
  - Visual countdown ring showing 3-minute expiry.
  - Remaining attempts indicator (e.g., "3 attempts remaining").
  - Submits via `POST /api/v1/tasks/{id}/input` using `SecretStr` payload format `{input_id, value}`.
- **CAPTCHA Challenge Mode:**
  - Fetches image bytes via `GET /api/v1/tasks/{id}/challenge` (`Cache-Control: no-store`).
  - Decodes and displays image purely in memory (`Image.memory`); never caches image bytes to disk.
  - Alphanumeric text input field with manual refresh button.

#### 3.5.6 Document Delivery Card & Document Vault
- **Delivery Card:**
  - Displays file name, document type, file size (KB/MB), and verified SHA-256 fingerprint badge.
  - Expiry countdown badge (e.g., "Expires in 23h 45m").
  - Action buttons: "View", "Save to Downloads", "Share", "Delete".
- **Download Action:**
  - Requests ephemeral signed URL via `GET /api/v1/tasks/{id}/download` (valid for 60 seconds).
  - Downloads PDF via `Dio` into app-private isolated storage (`getApplicationDocumentsDirectory()`).
- **View Action:**
  - Invokes `open_filex`. For password-protected e-Aadhaar PDFs, displays a local password helper prompt (*"Default password is first 4 letters of your name in CAPITALS + 4-digit birth year"*). The password is entered locally into the PDF viewer and **never sent to any server**.
- **Save Action:** Saves PDF to device Downloads directory via Scoped Storage.
- **Share Action:** Shares file securely using `share_plus`.
- **Delete Action:** Invokes `DELETE /api/v1/documents/{id}` to remove local file, database record, and Supabase Storage object.
- **Vault Screen:** Dedicated screen listing all active user documents from `public.documents`, sorted by `created_at desc`, with active expiry countdown timers and empty state.

#### 3.5.7 History Drawer
- **Visuals:** Slides from left edge with smooth backdrop blur ramp.
- **Sections:** Grouped chronologically into:
  - "Today"
  - "Yesterday"
  - "Previous 7 Days"
  - "Older"
- **Actions:** "New Chat" button at top; debounced search bar; swipe-to-delete conversation; swipe-to-rename; bottom navigation links to "Document Vault" and "Settings".

---

## 4. Operations, Deployment & CI/CD Specification

### 4.1 GitHub Actions Workflows

#### 4.1.1 Continuous Integration (`.github/workflows/ci.yml`)

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  flutter-test:
    name: Flutter Analyze & Test
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Set up Flutter
        uses: subosito/flutter-action@v2
        with:
          flutter-version: '3.24.x'
          channel: 'stable'
          cache: true

      - name: Install Dependencies
        working-directory: app
        run: flutter pub get

      - name: Run Static Analysis
        working-directory: app
        run: flutter analyze --fatal-infos --fatal-warnings

      - name: Run Flutter Tests
        working-directory: app
        run: flutter test --coverage

  backend-test:
    name: Backend Pytest & E2E Mock Portal
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: Install Dependencies
        working-directory: backend
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest pytest-asyncio

      - name: Install Playwright Browsers
        run: playwright install chromium --with-deps

      - name: Run Pytest Suite
        working-directory: backend
        env:
          APP_ENV: test
          LOG_LEVEL: INFO
          SUPABASE_URL: https://rsftbslckmdkynprmpin.supabase.co
          SUPABASE_SECRET_KEY: fake-test-secret-key
          WORKER_SHARED_SECRET: fake-worker-secret
        run: pytest -v tests/
```

#### 4.1.2 Supabase Keep-Alive (`.github/workflows/keepalive.yml`)

```yaml
name: Supabase Keep-Alive Ping

on:
  schedule:
    # Run once daily at 04:00 UTC (09:30 IST) to prevent 7-day inactivity project pause
    - cron: '0 4 * * *'
  workflow_dispatch:

jobs:
  ping:
    name: Ping Supabase REST API
    runs-on: ubuntu-latest
    steps:
      - name: Ping Supabase Project
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_ANON_KEY: ${{ secrets.SUPABASE_PUBLISHABLE_KEY }}
        run: |
          curl -s -f -o /dev/null -w "%{http_code}" \
            -H "apikey: ${SUPABASE_ANON_KEY}" \
            -H "Authorization: Bearer ${SUPABASE_ANON_KEY}" \
            "${SUPABASE_URL}/rest/v1/" || exit 1
          echo "Supabase keep-alive ping successful."
```

#### 4.1.3 Hourly Document Retention Sweep (`.github/workflows/cleanup.yml`)

```yaml
name: Hourly Retention Cleanup

on:
  schedule:
    # Run every hour on the hour
    - cron: '0 * * * *'
  workflow_dispatch:

jobs:
  cleanup:
    name: Trigger Backend Retention Sweep
    runs-on: ubuntu-latest
    steps:
      - name: Call Cleanup Endpoint
        env:
          API_BASE_URL: ${{ secrets.API_BASE_URL }}
          CLEANUP_SECRET: ${{ secrets.CLEANUP_SECRET }}
        run: |
          curl -s -f -X POST "${API_BASE_URL}/internal/cleanup" \
            -H "X-Cleanup-Secret: ${CLEANUP_SECRET}" \
            -H "Content-Type: application/json" || exit 1
          echo "Retention cleanup sweep triggered successfully."
```

### 4.2 Render Deployment (`render.yaml`)

```yaml
services:
  - type: web
    name: saral-api
    runtime: python
    plan: free
    rootDir: backend
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /health
    envVars:
      - key: PYTHON_VERSION
        value: "3.12.7"
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_SECRET_KEY
        sync: false
      - key: GROQ_API_KEY
        sync: false
      - key: LLM_MODEL
        value: "llama-3.3-70b-versatile"
      - key: WORKER_SHARED_SECRET
        sync: false
      - key: CLEANUP_SECRET
        sync: false
      - key: APP_ENV
        value: "prod"
      - key: LOG_LEVEL
        value: "INFO"
```

### 4.3 Environment Variable Master Specification (`.env.example`)

```ini
# ==============================================================================
# Saral AI - Master Environment Configuration Template
# ==============================================================================

# ------------------------------------------------------------------------------
# Backend & API Server (Render Free / Local)
# ------------------------------------------------------------------------------
APP_ENV=dev                                     # dev | test | prod
LOG_LEVEL=INFO                                  # DEBUG (local dev only) | INFO | WARN | ERROR
PORT=8000
API_BASE_URL=http://localhost:8000

# Supabase Credentials
SUPABASE_URL=https://rsftbslckmdkynprmpin.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_6Bkn_iWd2OHLapk1e4D_TA_iTDffnJZ
SUPABASE_SECRET_KEY=your_supabase_service_role_secret_key_here

# LLM Provider (Groq API)
GROQ_API_KEY=gsk_your_groq_api_key_here
LLM_MODEL=llama-3.3-70b-versatile

# TypeSafe Jev (Optional structured classifier)
TYPESAFE_API_KEY=
JEV_MODEL=jev-1.13.0

# Internal Shared Secrets
WORKER_SHARED_SECRET=generate_a_random_32_char_hex_for_worker_ws
CLEANUP_SECRET=generate_a_random_32_char_hex_for_cleanup_cron

# Security & Policy Allowlist (Comma-separated hostnames)
ALLOWED_DOMAINS=127.0.0.1,localhost,mock-portal.internal,myaadhaar.uidai.gov.in

# ------------------------------------------------------------------------------
# Browser Worker Configuration
# ------------------------------------------------------------------------------
WORKER_WS_URL=ws://localhost:8000/internal/worker
PLAYWRIGHT_HEADLESS=true
PLAYWRIGHT_TIMEOUT_MS=30000

# ------------------------------------------------------------------------------
# Flutter App Build Defines (--dart-define)
# ------------------------------------------------------------------------------
# Pass these via --dart-define or --dart-define-from-file=env.json
# SUPABASE_URL=https://rsftbslckmdkynprmpin.supabase.co
# SUPABASE_PUBLISHABLE_KEY=sb_publishable_6Bkn_iWd2OHLapk1e4D_TA_iTDffnJZ
# API_BASE_URL=http://10.0.2.2:8000 (Android Emulator) or https://saral-api.onrender.com
```

---

## 5. Features Discovered

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|----------|---------|-------------|--------|---------|----------------|----------------|
| 1 | Supabase DB | Profile Auto-Provisioning | `handle_new_user()` trigger on `auth.users` creates corresponding row in `public.profiles`. | `new.id` from `auth.users` insertion | New row in `public.profiles` | Fails user creation transaction if trigger fails | Section 4 DDL |
| 2 | Supabase DB | Conversation Archival & Ordering | `conversations` table tracks chat threads with composite index on `(user_id, updated_at desc)`. | User ID, Title, Archived flag | UUID conversation record | Violates FK if user does not exist | Section 4 DDL |
| 3 | Supabase DB | PII-Scrubbed Message Store | `messages` table stores scrubbed messages with role constraint `('user','assistant','system','task')`. | Conversation ID, Role, Scrubbed text | Message UUID, timestamp | Rejects invalid role check; RLS blocks unowned insert | Section 4 DDL |
| 4 | Supabase DB | Task State Tracking | `tasks` table with 12 distinct status states and `idempotency_key` unique per user. | Workflow ID, Idempotency key, scrubbed text | Task UUID, status, timestamps | Rejects unlisted status strings; rejects duplicate key | Section 4 DDL |
| 5 | Supabase DB | Single Active Task Guard | Partial unique index `one_active_task_per_workflow` prevents multiple active tasks per user per workflow. | `user_id`, `workflow`, active status | Unique constraint validation | Raises Postgres duplicate key violation if user attempts 2 concurrent runs | Section 4 DDL |
| 6 | Supabase DB | Realtime Task Event Audit | `task_events` identity table with progress percentage (0–100) and step message. | `task_id`, `status`, `message`, `progress` | Event ID, timestamp | Rejects progress outside 0..100; cascades on task delete | Section 4 DDL |
| 7 | Supabase DB | Document Metadata Registry | `documents` table stores SHA-256 digest, encrypted flag, file size, storage path, and `delete_after` retention deadline. | `task_id`, `doc_type`, `sha256`, `size_bytes`, `delete_after` | Document UUID, storage path | Rejects duplicate storage path; cascades on user delete | Section 4 DDL |
| 8 | Supabase RLS | Client Read-Only Security | Client RLS policies allow authenticated `SELECT` on own rows, but completely deny `INSERT`/`UPDATE`/`DELETE` on `tasks`, `messages`, `task_events`, and `documents`. | Client JWT (`auth.uid()`) | Filtered rows or empty set | Disallows write operations with 42501 (insufficient privilege) | Section 4 RLS |
| 9 | Supabase Storage | Private Document Bucket | Private bucket `documents` with path pattern `<user_id>/<task_id>.pdf`, authenticated SELECT RLS only. | Authenticated JWT and folder path | File byte stream | Blocks access if folder token != `auth.uid()` | Section 4 Storage Policy |
| 10 | Supabase Realtime | Live State Broadcast | Publication `supabase_realtime` enabled for `tasks`, `task_events`, and `messages`. | Realtime subscription filter | WebSocket event payload | Silently filters out rows violating subscriber RLS | Section 4 Publication |
| 11 | Flutter UI | Strict Monochrome Theme | Exact palette: Black `#000000`, Ink `#0A0A0A`, Graphite `#141414`, Grey `#1A1A1A`; white text (100%, 64%, 38%); zero accent hues. | `AppColors` token calls | Monochrome UI components | Build analyzer / test fails on literal `Color()` in features | Section 10.2, rules.md R-VIS |
| 12 | Flutter UI | Bundled Typography | Arapey (titles/wordmark/greeting) and Inter (body/UI) bundled as local assets in `pubspec.yaml`. | Text string, style parameters | Rendered glyphs | Falls back to system font if asset missing; forbidden from network fetch | Section 10.2, rules.md R-PHX |
| 13 | Flutter UI | GlassSurface Widget | Glassmorphic surface combining `RepaintBoundary`, `ClipRRect`, `BackdropFilter`, and white gradient stroke. | Child widget, radius, blur sigma | Blurred glass surface container | Swaps to solid grey fill if `lowPowerGlass` flag active | Section 10.2, 10.4 |
| 14 | Flutter UI | 3-Glass Surface Budget | Performance constraint capping maximum concurrent blurred surfaces at 3 per screen. | Layout tree | Smooth 60fps rendering | Frame drops / jank on low-end Android GPUs if violated | Section 10.4 |
| 15 | Flutter UI | Waking-Server UX | Shimmer horizontal line above composer when API latency > 2000ms. | Timer state (>2s pending) | Subtle animated shimmer bar | Dismisses immediately upon first response token | Section 10.1, 10.3 |
| 16 | Flutter UI | SSE Message Streaming | Chat controller connects to `POST /api/v1/chat` and streams tokens into assistant bubble. | HTTP SSE stream | Real-time text accumulation | Shows retry banner on stream failure or HTTP 429 | Section 5, 10.1 |
| 17 | Flutter UI | Inline Task Stepper | Stepper card in message list subscribing to Supabase Realtime `task_events`. | Realtime event stream | Animated step progress & message | Reverts to failed state with retry button on task failure | Section 10.1, 10.3 |
| 18 | Flutter Security | FLAG_SECURE Protection | Platform channel activates Android `FLAG_SECURE` on sensitive sheets/screens. | Sheet open/close lifecycle event | Blocked screenshots & screen recordings | App switcher preview obscured in OS task list | Section 7, 10.1, rules.md R-SEC |
| 19 | Flutter Security | Aadhaar Visual Masking | Formatter masks 12-digit Aadhaar/VID as `XXXX-XXXX-1234` with client Verhoeff checksum validation. | User digit keystrokes | Masked visual string | Rejects non-digits; highlights invalid Verhoeff checksum | Section 7, 10.1, ORIGINAL_REQUEST R3 |
| 20 | Flutter Security | 6-Digit OTP Countdown Sheet | OTP sheet with 6 individual boxes, 3-minute expiry countdown ring, and attempts counter. | 6-digit text input | Secure submission to `/api/v1/tasks/{id}/input` | Shakes boxes on incorrect OTP; disables on 3 failed attempts | Section 7, 10.1, 10.3 |
| 21 | Flutter Security | In-Memory CAPTCHA Display | CAPTCHA image fetched via `/challenge` displayed strictly from memory without disk caching. | HTTP image bytes | In-memory `Image.memory` | Shows refresh button on load failure; no disk trace | Section 5, 7, 10.1 |
| 22 | Flutter Vault | Document Expiry Countdown | Vault lists downloaded files with real-time countdown badge based on `delete_after`. | `public.documents` rows | Formatted countdown timer | Shows "Expired" badge and triggers deletion when deadline passed | Section 8.3, 10.1 |
| 23 | Flutter Vault | Local Password Prompt | Prompts user locally for e-Aadhaar PDF password (4 letters of name + birth year) without sending to server. | User input | Unlocked PDF render in `open_filex` | Displays password rule hint if decryption fails | Section 8.2, 8.3 |
| 24 | Flutter Vault | Scoped Storage Export | Saves verified PDF to public Downloads directory using Android Scoped Storage. | App-private file handle | File copied to `Download/` | Displays permission error if SAF access denied | Section 8.3, rules.md R-SEC |
| 25 | Flutter Nav | History Drawer Organization | Drawer organizes conversations into Today, Yesterday, Previous 7 Days, Older with search & swipe-delete. | Conversation query stream | Categorized list view | Shows empty state if search query has no match | Section 10.1, 10.3 |
| 26 | CI/CD | GitHub Actions Test Workflow | `ci.yml` runs Flutter analyze/test and Python pytest including mock portal E2E. | Git push / PR | Test status badge & logs | Blocks PR merge on test failure or analyze warning | Section 18 |
| 27 | Operations | Supabase Keep-Alive Ping | `keepalive.yml` runs daily cron cURL to Supabase REST endpoint preventing 7-day project inactivity pause. | Scheduled timer | HTTP 200 ping response | Sends failure notification if endpoint unreachable | Section 18 |
| 28 | Operations | Hourly Retention Cleanup | `cleanup.yml` calls `/internal/cleanup` to sweep expired documents from Storage and Postgres. | Scheduled cron trigger | Purge summary response | Alerts on non-200 cleanup response | Section 18 |
| 29 | Deployment | Render Web Service Spec | `render.yaml` declares Python 3.12 service with `/health` check and env sync flags. | Git commit to main | Deployed web service | Fails build if dependencies or start command fails | Section 18 |

---

## 6. Edge Cases & Boundary Conditions

| # | Feature | Input / Condition | Observed / Documented Specification Behavior |
|---|---------|-------------------|-----------------------------------------------|
| 1 | Supabase DB | Two concurrent task creation requests with identical `idempotency_key` | Postgres raises unique constraint violation on `(user_id, idempotency_key)`. Backend catches exception and returns existing `task_id` without duplicating execution. |
| 2 | Supabase DB | User initiates a second task while previous task for same workflow is in `RUNNING` status | Postgres raises unique constraint violation on partial index `one_active_task_per_workflow`. Backend rejects request with HTTP 409 Conflict. |
| 3 | Supabase DB | Task deleted while associated documents and messages exist | Foreign keys use `ON DELETE SET NULL` for `messages.task_id` and `documents.task_id`. Messages and documents remain preserved in user history. |
| 4 | Supabase RLS | Authenticated client attempts direct `INSERT` into `public.tasks` or `public.messages` | RLS policy denies insert with Postgres error `42501` (insufficient privilege). Clients can only read own data; only backend `service_role` key can write. |
| 5 | Supabase Storage | Authenticated user attempts direct download of another user's file (`documents/<other_uid>/task.pdf`) | RLS policy on `storage.objects` evaluates `(storage.foldername(name))[1] = auth.uid()::text`, which evaluates to false. Returns HTTP 403 Forbidden. |
| 6 | Realtime Publication | Unauthenticated socket or other user attempts to listen to task events | Supabase Realtime evaluates RLS `read own events` before streaming rows. Unauthorized users receive zero broadcast payloads. |
| 7 | Flutter UI | Device with low GPU / low RAM runs multiple blurred glass surfaces | If frame rate drops below 60fps or device flags low RAM, `lowPowerGlass` setting activates, replacing `BackdropFilter` with opaque `#1A1A1A` fill. |
| 8 | Flutter Input | User inputs 12-digit number with invalid Verhoeff checksum into Aadhaar field | Input field displays inline validation warning (*"Invalid Aadhaar number checksum"*), disabling the submit button before network dispatch. |
| 9 | Flutter Security | User attempts screen capture or screen recording while OTP sheet is open | Android OS blocks screenshot with message *"Can't take screenshot due to security policy"* due to `FLAG_SECURE`. Screen recordings render black pixels. |
| 10 | Flutter Input | User inputs incorrect 6-digit OTP code | Backend returns `WAITING_FOR_USER` with `attempts_left = attempts_left - 1`. Flutter shakes OTP boxes with soft haptic and decrements attempts counter. |
| 11 | Flutter Input | 3 consecutive incorrect OTP submissions | Task state machine transitions to `FAILED` with `error_code = 'OTP_MAX_ATTEMPTS'`. Flutter sheet closes and inline card shows failure state. |
| 12 | Flutter Input | User does not submit OTP within 3 minutes | Orchestrator expires pending challenge. Task transitions to `EXPIRED`. Flutter sheet closes with expiration banner and retry button. |
| 13 | Flutter Vault | PDF document reaches `delete_after` retention deadline | Document card displays "Expired" tag. When `/internal/cleanup` runs, file is deleted from Storage and DB. Vault refreshes and removes card. |
| 14 | Flutter Vault | User attempts to open encrypted e-Aadhaar PDF | App shows local password helper dialog. Password is submitted directly into local PDF rendering engine and never sent across the network. |
| 15 | Operations | Render Free tier server sleeps due to 15 minutes of inactivity | Flutter splash screen calls `/health` on warm-up. If chat screen makes call while waking, shimmering "Waking the server…" indicator displays until awake. |
| 16 | Operations | GitHub repository experiences inactivity, risking scheduled workflow pause | `keepalive.yml` daily ping prevents Supabase project suspension. Manual repository check documented in Section 18 for monthly inspection. |

---

## 7. Verification Method & Compliance Checklist

To independently verify all mined specifications against the codebase and implementation:
1. **Schema & Migration Verification:**
   - Inspect `supabase/migrations/0001_init.sql` against Section 2.1 DDL.
   - Run `supabase db push` against local or remote Supabase instance.
   - Execute SQL RLS test proving user A cannot select user B's records, and non-service-role clients cannot insert into `public.tasks`.
2. **Flutter Architecture & Theme Verification:**
   - Verify `pubspec.yaml` bundles `Arapey` and `Inter` fonts under `assets/fonts/`.
   - Run `flutter analyze` ensuring zero warnings and no literal `Color(...)` outside `lib/core/theme/`.
   - Verify that all `GlassSurface` instances are wrapped in `RepaintBoundary` and total concurrent instances on any route do not exceed 3.
3. **Operations & CI/CD Verification:**
   - Inspect `.github/workflows/ci.yml`, `keepalive.yml`, and `cleanup.yml`.
   - Validate `render.yaml` schema with Render CLI or documentation.
