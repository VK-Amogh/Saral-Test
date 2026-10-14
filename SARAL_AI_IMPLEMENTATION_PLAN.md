# Saral AI — End-to-End Implementation Plan (Free-Tier Edition)

**Version:** 1.0 · **Date:** 13 Oct 2026 · **Target:** Flutter Android app + FastAPI backend + Playwright worker, built at ₹0 using free tiers.

> **How to use this file**
> - **You (human):** do the account/key checklist in Section 13, then hand this file to your coding agents.
> - **Coding agents:** read Section 14 (`AGENTS.md`) first, then execute Section 12 phase by phase. Do not skip a phase's acceptance criteria.

---

## 1. Decisions at a glance

| Layer | Choice | Cost | Notes |
|---|---|---|---|
| Mobile app | Flutter (Android only), Riverpod, go_router | ₹0 | Chat UI, history, document vault |
| Auth, DB, file storage, realtime | **Supabase Free** | ₹0 | Email+password auth, Postgres, private Storage, Realtime |
| API server | **FastAPI on Render Free** | ₹0 | **No browser on this server** (see Section 2) |
| Browser worker | Playwright + Chromium **on your own machine** (Docker) | ₹0 | Moves to a bigger host only when needed |
| Job queue | Postgres table (`FOR UPDATE SKIP LOCKED`) | ₹0 | Replaces Redis for the MVP |
| Chat LLM | Google Gemini free tier (AI Studio key) | ₹0 | Model name lives in env, never hard-coded |
| Structured decisions | Rules first; **Jev (TypeSafe)** optional behind an interface | ~₹0 | Early-access model, see Section 9 |
| CI, keep-alive, cleanup cron | GitHub Actions | ₹0 | Free allowance applies |
| Safe test target | **Mock government portal** in the repo | ₹0 | Build and test everything without touching a real portal |

**Core strategy:** build the entire pipeline (chat → task → browser → CAPTCHA/OTP pause → download → validation → private delivery) against a **mock portal first**. Then run a **gated feasibility spike** on the real Aadhaar workflow. The architecture stays workflow-agnostic.

---

## 2. Reality check — what changes versus your spec

These were verified in October 2026. Re-check anything marked ⚠ before relying on it.

1. **Chromium will not run on Render Free.** Free instances have 512 MB RAM; headless Chromium is widely reported to run out of memory there (Render's own Playwright example uses the 2 GB Standard plan). **Fix:** Render hosts only the lightweight API. The browser worker runs on your PC (or a larger host later).
2. **Render Free sleeps.** It spins down after 15 minutes without inbound traffic and takes about a minute to wake. 750 free instance hours per workspace per month. Filesystem is ephemeral. **Fix:** a "waking server" UX state in the app and a `/health` warm-up call at launch.
3. **Supabase Free pauses after 1 week of inactivity.** Limits: 500 MB database, 1 GB file storage, 50k monthly active users, 2 free projects. **Fix:** a daily GitHub Actions ping. (Free Render Postgres expires after 30 days, which is why this plan uses Supabase for the database.)
4. **Aadhaar download is not a pure one-shot automation.** The official flow needs an Aadhaar number or VID, a **CAPTCHA**, and an **OTP**. The e-Aadhaar PDF comes **password-protected**. Your spec forbids bypassing CAPTCHA, so CAPTCHA becomes a second user-input pause, same as OTP.
5. **Legal/permission gate.** The UIDAI terms I found prohibit misusing or compromising the portals but do not explicitly grant permission for third-party automation. The consent-based official route (DigiLocker via API Setu, or via an aggregator) needs partner/business onboarding, so it is not a free individual option. Handling Aadhaar data on your servers also brings privacy-law obligations (India's DPDP Act). **I am not a lawyer — get advice before you ship this to real users.** The plan therefore has a **Guided Mode** fallback (Section 8.4).
6. **Free Gemini tier is not private.** Google may use free-tier inputs/outputs to improve its products. Limits are per project, not published in one table, and community numbers conflict (about 20 to 1,500 requests/day depending on model). Model names also churn (Gemini 3.x deprecations in October 2026). **Fix:** scrub PII before any LLM call, rate-limit per user, keep a provider interface.
7. **Jev is early access and is not a chat model.** It returns typed answers (choice, score, yes/no probability) with confidence, not text, and has no streaming. Listed price is about $0.042 per million input tokens, with free output. ⚠ Check console.typesafe.ai for free credits or limits. Use it for routing and gating only.

---

## 3. Architecture

```
Flutter (Android)
  │  Supabase Auth (email+password)         ← login, session
  │  Supabase Realtime (RLS-protected)      ← task progress, history updates
  │  HTTPS + SSE to FastAPI                 ← chat tokens, task actions, OTP/CAPTCHA input
  ▼
FastAPI (Render Free)  ── verifies Supabase JWT on every request
  ├─ Chat service ──► PII scrubber ──► Intent router (rules → Jev → Gemini)
  ├─ Task orchestrator + state machine (backend-validated transitions)
  ├─ Policy engine (domain allowlist, approval gates, rate limits)
  └─ Challenge broker (in-memory only: OTP/CAPTCHA relay, never persisted)
        ▲
        │ outbound authenticated WebSocket (worker → API)
        ▼
Browser worker (your PC / Docker)
  Playwright + Chromium, one isolated context per task
  ├─ Deterministic workflow code (per portal)
  ├─ Download capture → validation → upload to private Storage
  └─ Temp-file cleanup in `finally`
        ▼
Official portal (or the Mock Portal during development)

Supabase: Auth · Postgres (tasks, events, chats, documents) · private Storage bucket
GitHub Actions: CI · keep-alive pings · retention cleanup
```

### Deployment modes

| Mode | When | How |
|---|---|---|
| **A — Local** | Phases 1–6 | API and worker on your PC. Phone reaches the API over your LAN or a free tunnel (e.g. `cloudflared tunnel`). Android blocks plain HTTP by default, so use the tunnel's HTTPS, or allow cleartext in the **debug** manifest only. |
| **B — Hosted API** | Phase 9 | API on Render Free. Worker on your PC connects **outbound** to `wss://<api>/internal/worker`. Worker only runs while your PC is on; reconnect with backoff. |
| **C — Always-on** | After validation | Needs a separate cost assessment: a 2 GB host for Chromium (Render Standard is about $25/month) or another VM. ⚠ Free VM offers exist but were not verified. |

Do **not** rely on an open WebSocket keeping Render Free awake; that was not verified.

### Why Postgres as the queue and Realtime for progress
- Fewer moving parts and no Redis to host.
- Flutter subscribes straight to Supabase Realtime for `tasks` and `task_events` under RLS, so progress streaming does not depend on a sleeping Render server.
- FastAPI still streams chat tokens over **SSE** (low latency, simple).
- **Exception:** OTP and CAPTCHA values never touch Postgres or Realtime. They go app → API (HTTPS) → worker (in-memory over the WebSocket) → portal.

---
## 4. Data model (Supabase)

Put this in `supabase/migrations/0001_init.sql` and apply with the Supabase CLI (`supabase link`, `supabase db push`).

```sql
create extension if not exists pgcrypto;

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  created_at timestamptz not null default now()
);

create table public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null default 'New chat',
  archived boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on public.conversations (user_id, updated_at desc);

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
-- duplicate-execution protection: one active task per user per workflow
create unique index one_active_task_per_workflow on public.tasks (user_id, workflow)
  where status not in ('COMPLETED','FAILED','CANCELLED','EXPIRED');

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

-- Row Level Security
alter table public.profiles      enable row level security;
alter table public.conversations enable row level security;
alter table public.messages      enable row level security;
alter table public.tasks         enable row level security;
alter table public.task_events   enable row level security;
alter table public.documents     enable row level security;

create policy "own profile"       on public.profiles      for all    using (id = auth.uid()) with check (id = auth.uid());
create policy "own conversations" on public.conversations for all    using (user_id = auth.uid()) with check (user_id = auth.uid());
-- messages, tasks, events, documents: users can READ only. The backend (secret key) writes them,
-- so a client can never forge assistant messages, task states, or documents.
create policy "read own messages"  on public.messages    for select using (user_id = auth.uid());
create policy "read own tasks"     on public.tasks       for select using (user_id = auth.uid());
create policy "read own events"    on public.task_events for select using (user_id = auth.uid());
create policy "read own documents" on public.documents   for select using (user_id = auth.uid());

-- Private bucket; path convention '<user_id>/<file>'
insert into storage.buckets (id, name, public) values ('documents','documents', false)
  on conflict (id) do nothing;
create policy "read own files" on storage.objects for select to authenticated
  using (bucket_id = 'documents' and (storage.foldername(name))[1] = auth.uid()::text);
-- No insert/update/delete policies for users: only the backend writes or deletes files.

-- Realtime for live progress and history
alter publication supabase_realtime add table public.tasks, public.task_events, public.messages;

-- Profile row on signup
create function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = '' as $$
begin insert into public.profiles (id) values (new.id); return new; end $$;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();
```

**Keys (important):** Flutter gets only the **publishable** key (formerly "anon"). The **secret** key (formerly "service_role") lives only in the backend and worker environments. ⚠ Confirm the naming in your project's API Keys settings.

---

## 5. API

All routes require `Authorization: Bearer <Supabase access token>`, verified in FastAPI (prefer the project's JWKS endpoint; fallback: Supabase `auth.get_user`). ⚠ Check Project Settings → JWT Keys for your project's signing method.

| Route | Purpose |
|---|---|
| `GET /health` | Public health check. Used for warm-up and Render's health check. |
| `POST /api/v1/chat` | Body `{conversation_id?, text}`. Scrubs PII, stores the user message, routes intent. General chat streams via **SSE**. Task intent creates a task and returns `{task_id}`. Requires `Idempotency-Key` header. |
| `POST /api/v1/tasks` | Creates a task directly (used by the Guided/retry UI). |
| `GET /api/v1/tasks/{id}` | Safe state and progress for the owner only. |
| `POST /api/v1/tasks/{id}/input` | Body `{input_id, value}`. Used for OTP, CAPTCHA text, and approvals. `value` is a `SecretStr`. |
| `GET /api/v1/tasks/{id}/challenge` | Returns the current CAPTCHA image bytes from memory (`Cache-Control: no-store`). Never stored. |
| `POST /api/v1/tasks/{id}/cancel` | Cooperative cancellation. |
| `GET /api/v1/tasks/{id}/download` | Verified documents only. Returns a signed URL that lives about 60 seconds. |
| `DELETE /api/v1/documents/{id}` | Deletes the row **and** the Storage object. |
| `WS /internal/worker` | Worker connection, authenticated with `WORKER_SHARED_SECRET`. Not exposed to the app. |
| `POST /internal/cleanup` | Retention sweep, called by GitHub Actions with `CLEANUP_SECRET`. |

**Cross-cutting rules:** Pydantic v2 validation on every body; per-user rate limits (e.g. `slowapi`); ownership check on every `task_id`/`document_id`; a log filter that redacts OTP, CAPTCHA, Aadhaar-like 12-digit numbers, tokens and `Authorization` headers.

---

## 6. Task state machine

Transitions are enforced in one function (`transition(task, new_status, actor)`). Anything not listed is rejected. **Only the verifier can move `VERIFYING → COMPLETED`**, and only after file validation passes. An LLM saying "done" never completes a task.

| From | Allowed next states |
|---|---|
| `RECEIVED` | `VALIDATING`, `FAILED`, `CANCELLED` |
| `VALIDATING` | `PLANNING`, `FAILED`, `CANCELLED` |
| `PLANNING` | `RUNNING`, `WAITING_FOR_USER`, `FAILED`, `CANCELLED` |
| `RUNNING` | `WAITING_FOR_USER`, `AUTHENTICATING`, `DOWNLOADING`, `FAILED`, `CANCELLED`, `EXPIRED` |
| `WAITING_FOR_USER` | `RUNNING`, `AUTHENTICATING`, `FAILED`, `CANCELLED`, `EXPIRED` |
| `AUTHENTICATING` | `RUNNING`, `WAITING_FOR_USER` (wrong OTP, retry), `DOWNLOADING`, `FAILED`, `CANCELLED` |
| `DOWNLOADING` | `VERIFYING`, `FAILED`, `CANCELLED` |
| `VERIFYING` | `COMPLETED`, `FAILED` |
| `COMPLETED`, `FAILED`, `CANCELLED`, `EXPIRED` | terminal |

Timeouts: pending user input expires after 3 minutes; whole task after 10 minutes; max 3 OTP attempts and 3 CAPTCHA attempts; bounded retries (2) for page-load failures only.

---

## 7. Secure input handling (OTP and CAPTCHA)

1. Worker reaches a challenge step → orchestrator sets `WAITING_FOR_USER` with `pending_input = {kind, prompt, expires_at, attempts_left}`. **No values.**
2. Flutter sees the Realtime update and opens the secure input sheet. For CAPTCHA it fetches the image from `/challenge` and shows it in memory only.
3. User submits → `POST /input` over HTTPS. The API checks owner, task state, expiry and format (`^\d{6}$` for OTP) and rejects replays.
4. The API relays the value over the worker WebSocket to an `asyncio.Future` keyed by `task_id`. **It is never written to the database, logs, Realtime, or any LLM prompt.**
5. Worker fills the field with `locator.fill()`, then verifies the result from page state (OTP error text vs. next-step element).

**Worker hardening:** disable Playwright tracing, video and HAR in production; never set `DEBUG=pw:api` (it can print typed values); take no screenshots on the OTP step; drop references to the value immediately after use.

**Flutter hardening:** enable `FLAG_SECURE` on OTP and document screens (platform channel, or a maintained package such as `screen_protector` — ⚠ check it is maintained); `enableSuggestions: false`, `autocorrect: false`, no autofill hints; **never** use SMS auto-read/retriever APIs (your spec forbids reading OTP messages).

---

## 8. Workflows, documents and delivery

### 8.1 Workflow registry
Each supported workflow is a declarative definition: `id`, allowed domains, required inputs, steps, expected output type and size range, whether it needs user approval before irreversible actions. The policy engine enforces it:
- Playwright `context.route("**/*")` **aborts any request whose host is not in the workflow's allowlist.**
- Only one expected download is accepted; anything else is discarded and the task fails.
- Payments and irreversible submissions require an explicit in-app approval step (not needed for the first workflow).

### 8.2 Download validation (before `COMPLETED`)
1. Starts with `%PDF-`, size within the workflow's range (e.g. 10 KB to 5 MB), filename matches the expected pattern.
2. Parses with `pypdf`: if **not** encrypted, at least 1 page; if encrypted (expected for e-Aadhaar), structure and trailer are valid and `pdf_encrypted = true`.
3. No `/JavaScript` or `/Launch` actions.
4. Compute SHA-256; upload to `documents/<user_id>/<task_id>.pdf` with the secret key; insert the `documents` row with `delete_after` (default 24 hours; the user can choose "keep in vault" up to 30 days).
5. Delete the local temp directory in a `finally` block.

> Because the e-Aadhaar PDF is password-protected, the server can only validate structure, not read it. The app asks the user for the password **locally** (the portal's documented rule at time of writing is first four letters of the name in capitals plus birth year — ⚠ verify on the portal) and never sends it to the server.

### 8.3 Delivery
Flutter calls `/download`, gets a ~60-second signed URL, downloads with Dio into app-private storage, and offers **Open** (`open_filex`), **Save to Downloads** (scoped storage), and **Share**. The vault screen lists documents with an expiry countdown and a delete action.

### 8.4 Two modes for the real Aadhaar workflow
- **Mode 1 — Automated (only if the Phase 7 gate passes):** worker drives the portal; user supplies VID/Aadhaar number (encourage **VID**), CAPTCHA and OTP through the secure sheets.
- **Mode 2 — Guided (recommended default fallback):** the app opens the official portal in an in-app WebView restricted to allowlisted hosts (`flutter_inappwebview` exposes download events), overlays a step checklist, and saves the downloaded PDF into the on-device vault. **No Aadhaar number, OTP or document ever reaches your servers.** ⚠ Verify the portal works inside a WebView.

Both modes share the same chat UI, task states, history and vault.

---

## 9. AI layer

**Principle:** AI decides *what* workflow is needed; ordinary code decides *what is permitted*.

```
user text → PII scrubber → IntentClassifier (interface)
              ├─ RuleBasedClassifier   (keywords/regex; ship first, ₹0)
              ├─ JevClassifier         (optional; confidence-gated)
              └─ GeminiClassifier      (fallback; JSON-schema output)
         → policy engine (allowlist, approvals) → orchestrator
```

- **PII scrubber:** masks 12-digit Aadhaar-like numbers, phone numbers, emails and OTP-looking strings **before** any LLM/Jev call and before storing messages. Unit-test it heavily.
- **Jev (optional):** `POST https://api.typesafe.ai/v1/systemone`, Bearer key, model `jev-latest` (alias moves; **pin `jev-1.13.0`** for reproducible tests). Python SDK: `pip install typesafe-sdk` (Python 3.10+), exports `TypeSafeClient`, `Choice`, `Noul`, `Score`. Example questions: a `Choice` over `{aadhaar_download, unsupported_service, general_chat}` and a `Noul` for "user is asking to act on a government portal". Use **confidence-gated routing**: confidence ≥ 0.8 accept, otherwise fall back to Gemini or ask the user. Ask several questions in one call. Jev accepts text only and returns no rationale.
  Agent skill for your coding agents: `npx skills add typesafe-ai/skills --skill typesafe-ai` (or the Claude Code plugin from the TypeSafe docs).
- **Gemini (chat + fallback):** official `google-genai` SDK, key from Google AI Studio, `LLM_MODEL` in env. ⚠ Check `aistudio.google.com/rate-limit` for your project's real limits. Handle HTTP 429 with a friendly in-chat message, cache routing results, keep prompts short, and keep a second free provider behind the same `LLMProvider` interface.
- **Never** send documents, OTPs, CAPTCHAs, raw credentials or unscrubbed text to any model.

---
## 10. Flutter app and design system

### 10.1 Screens
| Screen | Notes |
|---|---|
| Splash | Arapey wordmark fades in; session check; `/health` warm-up fires in the background. |
| Auth | Sign in, sign up, reset password. One glass card on a dark canvas. |
| Chat (home) | Opens straight to chat like ChatGPT/Claude. Empty state: Arapey italic greeting plus glass suggestion chips. Composer is a rounded pill. |
| History drawer | Blurred drawer, search, grouped by Today / Yesterday / Previous 7 days / Older, swipe to rename or delete, "New chat" at top, "Documents" and "Settings" entries at the bottom. |
| Task card (inline in chat) | Animated stepper driven by `task_events`; Cancel button; becomes the result card on completion. |
| Secure input sheet | 6-box OTP with expiry countdown ring; CAPTCHA image plus text field; attempts left. `FLAG_SECURE` on. |
| Document result and Vault | Open / Save / Share / Delete, expiry countdown, empty state. |
| Settings | Retention preference, sign out, delete my data. |
| Waking-server state | A quiet shimmer line above the composer ("Waking the server…") when the first call takes over 2 seconds. |

### 10.2 Visual language (strictly black, white and darkest grey)
- **Canvas:** `#000000` base, `#0A0A0A` and `#141414` for raised areas. **No accent colours.** Errors, success and warnings are expressed with icons, wording, weight and motion, not colour.
- **Glass:** white fill at 3–9% opacity, 1 px white stroke at 10%, blur sigma 16–28, soft top-left highlight gradient. Glass only reads if something sits behind it, so give the canvas a few very low-contrast monochrome radial gradients or slow-drifting blurred shapes.
- **Text hierarchy:** white 100% / 64% / 38%.
- **Fonts:** **Arapey** for the wordmark, screen titles, greeting and key assistant lines; **Inter** for all UI, body and input text. Arapey ships only Regular and Italic (no bold), so create emphasis with size, italics and letter-spacing. Bundle both as assets in `pubspec.yaml` (no runtime font fetch; both are open-licence fonts on Google Fonts).
- **Shapes:** composer radius 28 (pill when single line, softly rounded when expanded), cards 24, sheets 32 on top corners, buttons fully rounded.

```dart
// lib/core/theme/tokens.dart
import 'dart:ui';
import 'package:flutter/material.dart';

class AppColors {
  static const black = Color(0xFF000000);
  static const ink = Color(0xFF0A0A0A);
  static const graphite = Color(0xFF141414);
  static Color glassFill([double a = .06]) => Colors.white.withValues(alpha: a);
  static Color glassStroke([double a = .10]) => Colors.white.withValues(alpha: a);
  static Color textHigh = Colors.white;
  static Color textMid = Colors.white.withValues(alpha: .64);
  static Color textLow = Colors.white.withValues(alpha: .38);
}

class Motion {
  static const fast = Duration(milliseconds: 120);
  static const base = Duration(milliseconds: 240);
  static const slow = Duration(milliseconds: 420);
  static const enter = Curves.easeOutCubic;
  static const emphasized = Curves.easeInOutCubicEmphasized;
}

class GlassSurface extends StatelessWidget {
  const GlassSurface({super.key, required this.child, this.radius = 28, this.blur = 24, this.padding});
  final Widget child; final double radius, blur; final EdgeInsetsGeometry? padding;

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
              border: Border.all(color: AppColors.glassStroke()),
              gradient: LinearGradient(
                begin: Alignment.topLeft, end: Alignment.bottomRight,
                colors: [AppColors.glassFill(.09), AppColors.glassFill(.03)]),
            ),
            child: child,
          ),
        ),
      ),
    );
  }
}
```

### 10.3 Motion and micro-interactions
Use `flutter_animate` plus implicit animations; one set of duration/curve tokens (above).
- **Messages:** fade + 8 px upward slide on arrival; assistant tokens appear with a soft fade, not letter-by-letter jitter.
- **Typing indicator:** three dots with staggered opacity pulse.
- **Send button:** morphs from mic-less idle outline to filled white circle as text appears; spring scale on press; light haptic.
- **Composer:** height animates smoothly as lines are added; border brightens on focus.
- **Task stepper:** the connecting line draws between steps as states advance; active step has a slow breathing glow (opacity, not colour).
- **OTP boxes:** digit scales in; shake and soft haptic on a wrong code; ring countdown shrinks.
- **Page transitions:** shared-axis fade/slide; `Hero` from result card to document viewer.
- **Drawer:** slides with a background blur ramp tied to drag progress.
- **Loading:** monochrome shimmer skeletons, never spinners alone.
- Respect `MediaQuery.disableAnimations` (reduce motion).

### 10.4 Performance rules for glass on Android
- At most **3 blurred surfaces on screen** (e.g. composer, app bar, drawer). Message bubbles use translucent fill **without** `BackdropFilter`.
- Wrap each blurred surface in `RepaintBoundary`; never blur per list item.
- Profile on a real mid-range phone with `flutter run --profile`. If frames drop, a `lowPowerGlass` flag swaps blur for an 85%-opaque grey fill.

### 10.5 Packages (add with `flutter pub add`, so you get current versions)
`supabase_flutter`, `flutter_riverpod`, `go_router`, `dio`, `flutter_animate`, `flutter_markdown`, `open_filex`, `path_provider`, `share_plus`, `flutter_secure_storage`, `connectivity_plus`, `intl`, `flutter_inappwebview` (Guided Mode), `screen_protector` (⚠ check maintenance). Config comes from `--dart-define` values, never from committed files.

---

## 11. Repository layout

```
saral-ai/
├─ AGENTS.md                     # Section 14, verbatim
├─ docs/PLAN.md                  # this file
├─ app/                          # Flutter
│  └─ lib/{core/{theme,widgets,net},features/{auth,chat,history,tasks,vault,settings}}
├─ backend/
│  ├─ app/{main.py,api/,core/,chat/,orchestrator/,policy/,ai/,workflows/,worker/,db/}
│  ├─ tests/
│  └─ requirements.txt
├─ mock_portal/                  # tiny FastAPI site: login → CAPTCHA → OTP → PDF (incl. failure modes)
├─ supabase/migrations/
└─ .github/workflows/{ci.yml,keepalive.yml,cleanup.yml}
```

---

## 12. Phased plan

Sizes are relative: **S** (hours to a day), **M** (a few days), **L** (a week or more).

| # | Phase | Size | Deliverables | Done when |
|---|---|---|---|---|
| 1 | **Foundations** | S | GitHub repo, `AGENTS.md`, Supabase project, migration applied, auth settings, env templates | You can sign up a user in the Supabase dashboard and the RLS tests in `supabase/tests` pass |
| 2 | **Flutter shell and design system** | M | Theme tokens, glass widgets, fonts, auth screens, chat screen, history drawer, vault screen, secure sheet (all against fake data) | Sign up/in/out works on a physical phone; UI matches Section 10; 60 fps on a mid-range device in profile mode |
| 3 | **Backend core and chat** | M | FastAPI skeleton, JWT verification, `/health`, `/chat` with SSE, PII scrubber, `LLMProvider` (Gemini), persistence of conversations/messages | Chat streams end-to-end; history survives app restart; scrubber tests pass |
| 4 | **Task engine, mock portal, worker** | L | State machine, orchestrator, Postgres job queue, worker with Playwright, workflow registry, domain allowlist, download validation, mock portal with CAPTCHA/OTP/PDF | A task completes against the mock portal; every failure mode in Section 16 is reproduced and reported accurately |
| 5 | **AI routing** | S | `IntentClassifier` interface; rules implementation; Jev and Gemini implementations with confidence gating | ≥ 95% routing accuracy on a 50-prompt local test set; Jev optional |
| 6 | **End-to-end integration** | M | Realtime progress in Flutter, secure OTP/CAPTCHA handoff, download delivery, vault, cancel, history of tasks | Full mock flow works on a physical phone; OTP never appears in any log, row or prompt (automated check) |
| 7 | **Real-workflow feasibility gate (Aadhaar)** | M | Written findings on portal flow, permitted automation, legal review outcome. Then **Mode 1** (automated) *or* **Mode 2** (guided WebView) | A documented go/no-go. Do not ship Mode 1 without it |
| 8 | **Security hardening and tests** | M | Cross-user isolation tests, rate limits, redaction audit, retention job, dependency audit | All items in Sections 16 and 17 pass in CI |
| 9 | **Deploy and operate** | S | Render deploy, GitHub Actions cron jobs, release APK, device test, monitoring | Complete flow verified on the hosted API from a physical phone |

**Gate rule:** no phase starts until the previous phase's "Done when" is demonstrated, with test output attached to the pull request.

---

## 13. Human checklist (accounts, keys, one-time setup)

1. **GitHub:** create a private repo `saral-ai`; enable Actions.
2. **Supabase:** create a project (pick the Mumbai region for latency if offered). Then:
   - Auth → Email provider on. Minimum password length 8 or more. Confirm-email **off in dev, on in prod**.
   - Auth → URL configuration: add a deep link redirect such as `saral://auth-callback`; add the matching Android intent filter.
   - Supabase's built-in email sender is for testing only (tight rate limits and restrictions). Before real users, connect a custom SMTP provider. ⚠ Check any provider's free quota.
   - Copy: Project URL, **publishable** key, **secret** key.
3. **Google AI Studio:** create a Gemini API key. Check your project's limits at `aistudio.google.com/rate-limit`.
4. **TypeSafe (optional):** create a key at `console.typesafe.ai`; check free credits and rate limits.
5. **Render:** create an account (no card needed for Free). Connect the GitHub repo in Phase 9.
6. **Local machine:** Flutter (stable), Android Studio or SDK, Python 3.12, `uv` or `pip`, Docker Desktop, Supabase CLI, `cloudflared` (optional).
7. **Secrets:** never commit them. Use `.env` (gitignored) locally and Render/GitHub secrets in the cloud.

| Variable | Where | Purpose |
|---|---|---|
| `SUPABASE_URL` | backend, worker | Project URL |
| `SUPABASE_SECRET_KEY` | backend, worker **only** | Server-side DB/Storage writes |
| `GEMINI_API_KEY`, `LLM_MODEL` | backend | Chat LLM; model name is configurable |
| `TYPESAFE_API_KEY`, `JEV_MODEL` | backend | Optional; pin `jev-1.13.0` |
| `WORKER_SHARED_SECRET` | backend, worker | Authenticates `/internal/worker` |
| `CLEANUP_SECRET` | backend, GitHub secret | Authenticates `/internal/cleanup` |
| `ALLOWED_DOMAINS` | backend, worker | Per-workflow host allowlist |
| `APP_ENV`, `LOG_LEVEL` | backend, worker | `dev`/`prod`; never `DEBUG` in prod |
| Flutter `--dart-define` | app | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `API_BASE_URL` |

---

## 14. `AGENTS.md` (copy this into the repo root)

```markdown
# Saral AI — rules for coding agents

## Mission
Outcome-oriented agent app: user asks in chat, backend executes a supported government-service workflow,
pauses for user CAPTCHA/OTP, verifies the result, delivers the file privately. Read docs/PLAN.md first.

## Hard rules (never break)
1. No secrets in the Flutter app or git. Only the Supabase *publishable* key is allowed in the app.
2. OTP and CAPTCHA values: never log, persist, send to Supabase Realtime, or put in any LLM/Jev prompt.
   Use pydantic SecretStr and the redacting log filter. Playwright tracing/video/HAR stay OFF in prod.
3. Never auto-read SMS. Never bypass CAPTCHA/OTP. Only allowlisted domains (route-level enforcement).
4. A task becomes COMPLETED only through the verifier after file validation. Never because an LLM says so.
5. All state transitions go through `transition()`; add a test for every new edge.
6. Every endpoint: JWT auth, ownership check, input validation, rate limit.
7. Scrub PII before any model call or message storage.
8. UI: only black / white / greys, Arapey + Inter, glass components, ≤3 blurred surfaces per screen.
9. Do not touch the real UIDAI portal until Phase 7's gate is signed off. Develop against mock_portal/.

## Working style
- One phase at a time, from docs/PLAN.md. Small PRs. Tests included. Update docs when behaviour changes.
- Before using any external API/package, check its current docs (names and limits change). Do not guess.
- Keep AI providers behind interfaces (LLMProvider, IntentClassifier). Model names come from env.
- Ask the human only for things in "Human checklist"; otherwise decide, document, and proceed.

## Commands
- Backend: `cd backend && uv sync && uv run pytest && uv run uvicorn app.main:app --reload`
- Worker: `cd backend && uv run python -m app.worker.main` (needs `playwright install chromium`)
- App: `cd app && flutter pub get && flutter analyze && flutter test && flutter run --dart-define-from-file=env.json`
- DB: `supabase db push`

## Definition of done (every PR)
Tests pass; analyzers clean; no secrets; redaction test updated if new data flows; screenshots for UI changes.
```

---

## 15. Phase prompts for your agents

Give each agent `AGENTS.md` plus `docs/PLAN.md`. Run phases in order; sequential agents on one branch per phase is simplest. If you run parallel agents, split by folder (`app/`, `backend/`, `mock_portal/`) to avoid conflicts.

- **Phase 1:** "Initialise the repo per Section 11. Create `supabase/migrations/0001_init.sql` from Section 4, add RLS tests proving user A cannot read user B's rows or files, add `.env.example`, CI skeleton, and `AGENTS.md`."
- **Phase 2:** "Build the Flutter shell per Section 10: tokens, `GlassSurface`, fonts as assets, Supabase email/password auth, chat screen, history drawer, vault, and secure OTP sheet using fake data. Add widget tests and a profile-mode performance note."
- **Phase 3:** "Build the FastAPI core per Sections 5 and 9: JWT verification, `/health`, `/chat` with SSE, PII scrubber with tests, `LLMProvider` with a Gemini implementation, message persistence via the secret key."
- **Phase 4:** "Implement the state machine (Section 6), Postgres job queue, worker with Playwright, workflow registry, route-level domain allowlist, download validation (Section 8.2), and a `mock_portal` with CAPTCHA, OTP, PDF download and failure modes (wrong OTP, expired OTP, corrupt PDF, wrong file type, slow page, changed selector)."
- **Phase 5:** "Add `IntentClassifier` with rule-based, Jev and Gemini implementations plus confidence gating. Use the TypeSafe skill for Jev. Build a 50-prompt test set."
- **Phase 6:** "Wire Flutter to Supabase Realtime for task progress, the secure input sheets, `/input` and `/challenge` flows, download and vault. Add an automated test that greps logs, DB rows and recorded prompts for the test OTP and fails if found."
- **Phase 7:** "Write `docs/AADHAAR_FEASIBILITY.md` from manual observation of the current portal flow and its terms. Do not automate yet. Then implement the mode chosen by the human."
- **Phase 8:** "Run the full Section 16 matrix, add rate limits and the retention job, audit dependencies, fix gaps."
- **Phase 9:** "Create `render.yaml`, GitHub Actions for keep-alive and cleanup, release build instructions, and a deployment verification checklist."

---

## 16. Test plan

| Area | Tests |
|---|---|
| State machine | Every legal edge passes; every illegal edge is rejected; terminal states are final; only the verifier completes |
| Auth and isolation | No token → 401; user A cannot read, cancel, download or delete user B's task, message or document (API **and** direct Supabase queries); Storage paths are isolated |
| Redaction | Fake OTP, CAPTCHA, Aadhaar-like numbers and tokens never appear in logs, DB rows, Realtime payloads, prompts, error messages or crash reports |
| Mock-portal E2E | Happy path; wrong OTP then correct; 3 wrong OTPs → `FAILED`; OTP expiry → `EXPIRED`; wrong CAPTCHA retry; user cancels mid-run; duplicate request (same idempotency key and second active task) rejected; corrupt PDF; HTML masquerading as PDF; oversize file; unexpected second download; page timeout; changed selector → clear failure message, never fake success |
| Policy | Request to a non-allowlisted host is aborted; redirect to a foreign host is aborted |
| Cleanup | Temp directory removed on success, failure and cancel; expired documents deleted from Storage **and** table |
| AI | Scrubber unit tests; routing accuracy; low-confidence → fallback; LLM 429 → friendly message; kill-switch if provider unavailable |
| Flutter | Widget tests for auth, composer, stepper, OTP sheet; golden tests for key glass components; physical-device smoke test per release |

---

## 17. Security and compliance checklist

- [ ] HTTPS everywhere; no cleartext in release builds.
- [ ] JWT verified server-side on every route; ownership checks tested.
- [ ] Secret key never in the app; secrets only in env/secret stores.
- [ ] RLS enabled on every table; Storage bucket private; signed URLs ≈ 60 seconds.
- [ ] Domain allowlist enforced at network-route level.
- [ ] OTP/CAPTCHA/Aadhaar-number redaction verified by automated test.
- [ ] Browser contexts isolated per task; worker runs as non-root with a temp directory wiped in `finally`.
- [ ] Retention: documents auto-delete by `delete_after`; task history keeps no sensitive payloads.
- [ ] User can delete a document and all their data from Settings.
- [ ] Rate limits on all routes; extra-strict on `/input`.
- [ ] Prefer VID over Aadhaar number in prompts and UI copy.
- [ ] Legal review before real users: DPDP obligations (consent, purpose limitation, deletion), UIDAI terms, privacy policy, and who counts as the data controller. *(I am not a lawyer.)*
- [ ] Never claim success without verification; every failure shows a safe next step (retry, guided mode, or official support).

---

## 18. Deployment and operations

**Render (API only):**

```yaml
# render.yaml
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
      - key: GEMINI_API_KEY
        sync: false
      - key: LLM_MODEL
        sync: false
      - key: WORKER_SHARED_SECRET
        sync: false
      - key: CLEANUP_SECRET
        sync: false
```

**GitHub Actions:**
- `ci.yml`: `flutter analyze && flutter test`; `pytest` including mock-portal E2E (installs Chromium in the runner).
- `keepalive.yml`: daily call to your Supabase REST endpoint (prevents the 1-week pause). Optionally ping the Render `/health` every 10 minutes if you want to avoid sleep; one always-awake free service fits inside the 750-hour allowance, but all free services in the workspace share it. GitHub may disable scheduled workflows in repos with no recent activity, so check them monthly.
- `cleanup.yml`: hourly `POST /internal/cleanup` (the backend removes expired Storage objects and rows; deleting Storage rows through SQL does not remove the files, so use the API).

**Android release:** `flutter build apk --release` with a signing keystore kept **outside** git; install with `adb install`. Play Store publishing is not needed for the MVP.

**Monitoring on a ₹0 budget:** structured, redacted logs; a `task_metrics` view (success rate, time per state, failure codes); measure LLM latency, navigation, browser actions and download time, as your spec requires.

---

## 19. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Portal forbids or blocks automation | Mode 1 impossible | Phase 7 gate; Guided Mode; consent-based DigiLocker route via a registered partner if you later become one |
| Portal UI changes | Workflow breaks | Selectors centralised per workflow; fail loudly; scheduled canary against the mock only; manual real-portal check before releases |
| Free-tier limits (Gemini, Supabase, Render) | Throttling, pauses, cold starts | Rules-first routing, caching, per-user limits, keep-alive jobs, warm-up UX, provider interfaces |
| Free LLM data use | Privacy exposure | Scrub PII; send no documents or secrets; consider a paid no-training tier before launch |
| Worker only runs while your PC is on | Tasks stall | Queue with timeouts and clear "worker offline" message; plan Mode C after validation |
| Storing identity documents | Legal and breach risk | Short retention, private bucket, signed URLs, user deletion, or Guided Mode with on-device-only storage |
| Jev is early access | API or behaviour changes | Optional, pinned model version, confidence gating, rule/Gemini fallbacks |
| Glass UI jank on low-end phones | Poor feel | ≤3 blur surfaces, `RepaintBoundary`, `lowPowerGlass` fallback |

---

## 20. Sources and what to re-check

Figures above came from these (several are third-party summaries, so confirm on the primary pages):

- Render: free-tier behaviour and plans — `render.com/docs/free`, `render.com/pricing`; summaries at temps.sh/blog/render-pricing-2026 and jwatte.com/blog/render-com-platform-review. Playwright memory: `github.com/render-examples/playwright-mcp-render` and the Render community thread on Playwright crashes.
- Supabase: `supabase.com/pricing` (free limits and 1-week pause).
- TypeSafe Jev: `docs.typesafe.ai` (introduction, quick start, API reference, `llms.txt`), promptfoo's TypeSafe page (pricing), LiteLLM's TypeSafe pass-through page, llmreference.com (release date).
- Gemini: `ai.google.dev/gemini-api/docs/pricing`, `ai.google.dev/gemini-api/docs/rate-limits`, `aistudio.google.com/rate-limit`; free-tier data-use note via geotoolbox.ai/blog/gemini-api-pricing.
- Aadhaar: `uidai.gov.in` terms and website policies; step-by-step flow summaries at surepass.io and taxtmi.com; DigiLocker partner flow at `docs.setu.co/data/digilocker` and the DigiLocker partner onboarding FAQ (`digilocker.gov.in`).

**Before Phase 3:** verify Gemini model names and limits. **Before Phase 7:** read the live UIDAI terms and portal flow yourself, and consult a lawyer. **Before Phase 9:** re-check Render and Supabase free-tier terms.
