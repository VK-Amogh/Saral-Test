# Handoff Report — spec_miner_survey_3 (Flutter App & Schema Spec Miner)

**Date:** 2026-10-13T06:25:00Z  
**Author:** `spec_miner_survey_3`  
**Recipient / Parent:** `b5871ec8-28ec-4ff6-821a-198f59d99e91` (Teamwork Orchestrator)  
**Deliverable Path:** `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_3\survey_report.md`

---

## 1. Observation

Direct observations from inspecting authoritative specification files in the workspace:

1. **`ORIGINAL_REQUEST.md` (lines 44–63):**
   > "R3. Flutter Mobile Application (`app/`): Implement the Flutter Android app following `rules.md` (monochrome theme, strictly black `#000000`, white `#FFFFFF`, and dark grey `#1A1A1A` with zero accent hues, glass surfaces with blur, Arapey typography for headings/wordmark, Inter for UI)... State management using `flutter_riverpod` and routing via `go_router`... Strict UI Input Masking & Security: 12-digit Aadhaar/VID inputs use visual masking (`XXXX-XXXX-1234`), 6-digit OTP input with countdown ring, `FLAG_SECURE` enabled on sensitive screens, `autocorrect: false`, `enableSuggestions: false`, no clipboard exposure... R4. Supabase Schema, Security & Operations: Database migrations in `supabase/migrations/0001_init.sql` matching Section 4 of `SARAL_AI_IMPLEMENTATION_PLAN.md`... Full Row Level Security (RLS) policies... Private Supabase Storage bucket `documents` with user isolation... GitHub Actions workflows: CI (`ci.yml`), Supabase keep-alive ping (`keepalive.yml`), hourly document cleanup sweep (`cleanup.yml`)."

2. **`SARAL_AI_IMPLEMENTATION_PLAN.md` (Section 4, lines 92–203):**
   - Exact SQL table schema definitions:
     - `profiles`: `id uuid primary key references auth.users(id) on delete cascade`, `display_name text`, `created_at timestamptz not null default now()`.
     - `conversations`: `id uuid primary key default gen_random_uuid()`, `user_id uuid not null references auth.users(id) on delete cascade`, `title text not null default 'New chat'`, `archived boolean not null default false`, index on `(user_id, updated_at desc)`.
     - `messages`: `role in ('user','assistant','system','task')`, `content text not null` (PII scrubbed), `task_id uuid`, index on `(conversation_id, created_at)`.
     - `tasks`: 12 legal statuses (`RECEIVED`, `VALIDATING`, `PLANNING`, `RUNNING`, `WAITING_FOR_USER`, `AUTHENTICATING`, `DOWNLOADING`, `VERIFYING`, `COMPLETED`, `FAILED`, `CANCELLED`, `EXPIRED`). Unique constraint on `(user_id, idempotency_key)`. Partial unique index `one_active_task_per_workflow on public.tasks (user_id, workflow) where status not in ('COMPLETED','FAILED','CANCELLED','EXPIRED')`. `pending_input jsonb` holds metadata only, never values.
     - `task_events`: `id bigint generated always as identity`, `progress smallint check (progress between 0 and 100)`.
     - `documents`: `storage_path text not null unique` (convention `<user_id>/<task_id>.pdf`), `sha256 text not null`, `pdf_encrypted boolean not null default false`, `delete_after timestamptz not null`.
     - RLS: client has read-only `SELECT` using `auth.uid() = user_id` on `messages`, `tasks`, `task_events`, and `documents`; backend service key writes.
     - Storage: bucket `documents` (private), RLS on `storage.objects` allows select where `(storage.foldername(name))[1] = auth.uid()::text`.
     - Realtime: `alter publication supabase_realtime add table public.tasks, public.task_events, public.messages;`.
     - Trigger: `handle_new_user()` security definer function and `on_auth_user_created` trigger on `auth.users`.

3. **`SARAL_AI_IMPLEMENTATION_PLAN.md` (Section 10, lines 312–408):**
   - Monochrome color tokens: `AppColors.black = Color(0xFF000000)`, `AppColors.ink = Color(0xFF0A0A0A)`, `AppColors.graphite = Color(0xFF141414)`, `glassFill([.06])`, `glassStroke([.10])`, `textHigh = 100%`, `textMid = 64%`, `textLow = 38%`.
   - Motion tokens: `fast (120ms)`, `base (240ms)`, `slow (420ms)`, curves `Curves.easeOutCubic`, `Curves.easeInOutCubicEmphasized`.
   - `GlassSurface` widget code structure with `RepaintBoundary`, `ClipRRect`, `BackdropFilter`, and white linear gradient border.
   - Glass performance limits: at most 3 blurred surfaces on screen simultaneously; message bubbles use translucent fill without `BackdropFilter`; wrap each blurred surface in `RepaintBoundary`; `lowPowerGlass` fallback.
   - Typography: Arapey for wordmark, screen titles, greeting, key assistant lines; Inter for UI, body, inputs. Bundled locally in `pubspec.yaml`.

4. **`SARAL_AI_IMPLEMENTATION_PLAN.md` (Section 18, lines 566–606):**
   - `render.yaml` specification for FastAPI backend web service (Python 3.12, plan `free`, health check path `/health`, env vars).
   - GitHub Actions workflows: `ci.yml` (Flutter analyze/test + pytest), `keepalive.yml` (daily ping to Supabase REST endpoint), `cleanup.yml` (hourly `POST /internal/cleanup`).

5. **`rules.md` (lines 378–403):**
   - R-REAL (§16): No demos, mocks, fake data in shipped code. Real device verification.
   - R-VIS (§17): Exactly three colours: black `#000000`, white `#FFFFFF`, dark grey `#1A1A1A`. No accent hues. Dark theme only. Spacing rhythm multiples of 4 dp.
   - R-ARCH (§3): Strict package and feature boundaries. Feature isolation.

---

## 2. Logic Chain

1. **Step 1 (Source Extraction):** By inspecting `ORIGINAL_REQUEST.md`, `SARAL_AI_IMPLEMENTATION_PLAN.md`, and `rules.md`, all authoritative requirements for Supabase DB/Storage, Flutter Mobile App, and CI/CD operations were gathered.
2. **Step 2 (Data Layer Synthesis):** Section 4 provides the full, unabridged PostgreSQL migration script. The foreign key cascades and partial unique index `one_active_task_per_workflow` directly solve duplicate task execution. The RLS model guarantees that even with a leaked client anon/publishable key, malicious clients cannot fabricate completed tasks, modify messages, or access other users' private PDFs in storage.
3. **Step 3 (Client Presentation Layer Synthesis):** Section 10 and `rules.md` (R-VIS) together dictate an absolute monochrome design standard with strict performance boundaries (maximum 3 blurred glass surfaces). The combination of Arapey + Inter local asset typography and `FLAG_SECURE` platform channels satisfies both visual luxury and high-assurance banking/government security standards.
4. **Step 4 (Operational Resilience):** Section 18 directly mitigates free-tier constraints (sleeping Render web instances via `/health` warm-up UX and sleeping Supabase instances via `keepalive.yml` daily cron, plus automated retention cleanup via `cleanup.yml`).
5. **Step 5 (Feature & Edge Case Cataloging):** Synthesizing all findings into `survey_report.md` produced 29 distinct features discovered and 16 critical edge cases with concrete observable behaviors.

---

## 3. Caveats

1. **Local vs Remote Supabase CLI Application:** The SQL migration in Section 2.1 is prepared for `supabase db push` or direct execution via Supabase SQL Editor / migration runner. In development, the confirm-email setting should be set to off in the Supabase Dashboard, while in production it must be enabled with custom SMTP.
2. **Platform Channels for `FLAG_SECURE`:** While `screen_protector` is referenced as a popular plugin, custom Kotlin platform channel implementation or verified maintenance check is recommended during the implementation phase to ensure compatibility with modern Android 14/15 window manager flags.
3. **Password Rule for e-Aadhaar:** The default password format for e-Aadhaar PDFs (first 4 letters of name in capitals + 4-digit birth year) is portal-specific and must be verified against current UIDAI guidelines.

---

## 4. Conclusion

The specification mining for Supabase Database & Storage, the Flutter Mobile Application, and Operations / CI/CD is complete and authoritative. All requirements, DDL schemas, RLS policies, visual design tokens, typography specifications, screen component architectures, security channels, and workflow scripts have been extracted and codified in `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_3\survey_report.md`.

---

## 5. Verification Method

To verify these mined specifications:
1. **File Inspection:**
   - Read `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_3\survey_report.md` to review the DDL, Flutter architecture, design system, and CI/CD definitions.
2. **SQL Migration Validation:**
   - Verify SQL DDL against Supabase Postgres 15+ using `pg_dump` or Supabase CLI syntax validator.
3. **Design System & Token Verification:**
   - Compare `AppColors`, `GlassSurface`, and typography contracts against `SARAL_AI_IMPLEMENTATION_PLAN.md` Section 10 and `rules.md` R-VIS.
