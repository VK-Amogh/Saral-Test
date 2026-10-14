## 2026-10-13T06:17:21Z

You are spec_miner_survey_3 (Flutter App & Schema Spec Miner).
Working directory: d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_3\
Project root: d:\Startup\Saral Ai\Saral_app\

Authoritative specifications to read:
- d:\Startup\Saral Ai\Saral_app\.agents\teamwork\ORIGINAL_REQUEST.md
- d:\Startup\Saral Ai\Saral_app\SARAL_AI_IMPLEMENTATION_PLAN.md (Sections 4, 10, 11, 14, 18)
- d:\Startup\Saral Ai\Saral_app\rules.md

Your Mission:
Mine, extract, and document all precise requirements, feature inventory items, constraints, UI/UX contracts, and schema definitions for:
1. Supabase Database Schema & Storage:
   - `supabase/migrations/0001_init.sql` schema: `profiles`, `conversations`, `messages`, `tasks`, `task_events`, `documents`.
   - Foreign keys, cascades, indexes, constraints, `handle_new_user()` trigger on auth.users.
   - Full RLS policies for each table (read-only for clients on tasks/events/docs/messages, backend writes with secret key).
   - Private Supabase Storage bucket `documents` with user isolation RLS.
   - Supabase Realtime publication configuration for `tasks`, `task_events`, `messages`.
2. Flutter Mobile Application (`app/`):
   - Architecture: Riverpod state management, GoRouter, clean modular structure following `rules.md`.
   - Strict monochrome design system: black (`#000000`), ink (`#0A0A0A`), graphite (`#141414`), white text hierarchy (100%, 64%, 38%), zero accent hues.
   - Typography: Arapey for headings/wordmark/greeting, Inter for body/inputs (bundled local assets).
   - Glassmorphic UI: `GlassSurface` widget with blur, maximum 3 blurred surfaces per screen, `RepaintBoundary` wrappers.
   - Screens: Splash (warm-up `/health`), Auth (Sign in, Sign up, Reset password), Chat (greeting, suggestion chips, pill composer, SSE streaming), Task Stepper Card inline in chat driven by Realtime `task_events`, Secure Input Sheet with visual masking (`XXXX-XXXX-1234`), 6-digit OTP countdown ring, `FLAG_SECURE` platform channel, Document Vault with expiry countdown and view/share/delete actions, History Drawer (Today/Yesterday/Older).
3. Operations & CI/CD:
   - GitHub Actions workflows: `ci.yml` (Flutter analyze/test, pytest), `keepalive.yml` (Supabase ping), `cleanup.yml` (hourly retention sweep).
   - Render deployment (`render.yaml`) and `.env.example`.

Output requirements:
- Write your comprehensive specification report to: `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_3\survey_report.md`
- Write your handoff report to: `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\spec_miner_survey_3\handoff.md`
- Once complete, notify the orchestrator (caller) using send_message with a summary and file paths.

DO NOT write source code or run builds. You are an exploratory spec miner.
