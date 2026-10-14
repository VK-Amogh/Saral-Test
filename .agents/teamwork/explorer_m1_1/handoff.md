# Handoff Report: Milestone 1 (M1) DDL, Constraints & Triggers

**Agent:** `explorer_m1_1` (M1 DDL & Constraints Explorer)  
**Date:** 2026-10-13  
**Working Directory:** `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\explorer_m1_1\`  
**Handoff Type:** Hard (Task complete)  
**Primary Deliverable:** `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\explorer_m1_1\analysis.md`

---

## 1. Observation

Direct observations from authoritative project specifications:

1. **Table Inventory & Core DDL**:
   - `SARAL_AI_IMPLEMENTATION_PLAN.md` (Lines 93–169):
     ```sql
     create extension if not exists pgcrypto;
     create table public.profiles (id uuid primary key references auth.users(id) on delete cascade, display_name text, created_at timestamptz not null default now());
     create table public.conversations (id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade, title text not null default 'New chat', archived boolean not null default false, created_at timestamptz not null default now(), updated_at timestamptz not null default now());
     create table public.messages (id uuid primary key default gen_random_uuid(), conversation_id uuid not null references public.conversations(id) on delete cascade, user_id uuid not null references auth.users(id) on delete cascade, role text not null check (role in ('user','assistant','system','task')), content text not null, task_id uuid, created_at timestamptz not null default now());
     create table public.tasks (id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade, conversation_id uuid references public.conversations(id) on delete set null, workflow text not null, status text not null default 'RECEIVED' check (status in ('RECEIVED','VALIDATING','PLANNING','RUNNING','WAITING_FOR_USER','AUTHENTICATING','DOWNLOADING','VERIFYING','COMPLETED','FAILED','CANCELLED','EXPIRED')), request_text text, idempotency_key text not null, pending_input jsonb, error_code text, error_message text, created_at timestamptz not null default now(), updated_at timestamptz not null default now(), finished_at timestamptz, unique (user_id, idempotency_key));
     create table public.task_events (id bigint generated always as identity primary key, task_id uuid not null references public.tasks(id) on delete cascade, user_id uuid not null references auth.users(id) on delete cascade, status text not null, message text not null, progress smallint check (progress between 0 and 100), created_at timestamptz not null default now());
     create table public.documents (id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade, task_id uuid references public.tasks(id) on delete set null, doc_type text not null, file_name text not null, storage_path text not null unique, size_bytes integer not null, sha256 text not null, pdf_encrypted boolean not null default false, created_at timestamptz not null default now(), delete_after timestamptz not null);
     ```
2. **Partial Unique Index**:
   - `SARAL_AI_IMPLEMENTATION_PLAN.md` (Lines 141–142):
     ```sql
     create unique index one_active_task_per_workflow on public.tasks (user_id, workflow)
       where status not in ('COMPLETED','FAILED','CANCELLED','EXPIRED');
     ```
3. **Required Query Indexes**:
   - `SARAL_AI_IMPLEMENTATION_PLAN.md` (Lines 109, 120, 153, 168):
     - `create index on public.conversations (user_id, updated_at desc);`
     - `create index on public.messages (conversation_id, created_at);`
     - `create index on public.task_events (task_id, id);`
     - `create index on public.documents (user_id, created_at desc);`
4. **Trigger Definition**:
   - `SARAL_AI_IMPLEMENTATION_PLAN.md` (Lines 198–202):
     ```sql
     create function public.handle_new_user() returns trigger
     language plpgsql security definer set search_path = '' as $$
     begin insert into public.profiles (id) values (new.id); return new; end $$;
     create trigger on_auth_user_created after insert on auth.users
       for each row execute function public.handle_new_user();
     ```
5. **Project Milestone & Feature Mapping**:
   - `PROJECT.md` Feature Inventory (Lines 170–173):
     - Feature 1: Supabase Schema & Tables (Full DDL for profiles, conversations, messages, tasks, task_events, documents)
     - Feature 2: Table Constraints & Indexes (Foreign key cascades, composite unique `(user_id, idempotency_key)`, partial index `one_active_task_per_workflow`)
     - Feature 3: Supabase Profiles Trigger (`handle_new_user()` security definer trigger on `auth.users`)
6. **Existing Filesystem State**:
   - Directory `supabase/` does not yet exist in project root `d:\Startup\Saral Ai\Saral_app\`. No migration files have been created yet.

---

## 2. Logic Chain

1. **Table Creation Ordering (Resolving Foreign Key References)**:
   - *Observation 1* shows that `messages` has `task_id uuid`, and `tasks` has `conversation_id uuid references public.conversations(id) on delete set null`.
   - In Section 4, `messages` was listed before `tasks`. If `messages.task_id` has an explicit foreign key reference to `public.tasks(id)`, `messages` cannot be created before `tasks` without causing relation lookup errors.
   - *Reasoning*: Moving `tasks` before `messages` in `0001_init.sql` resolves this dependency DAG cleanly. `conversations` is created first, then `tasks` (referencing `conversations`), then `messages` (referencing both `conversations` and `tasks`), then `task_events` and `documents`.
2. **Cascade Deletion Semantics & Architectural Preservation**:
   - *Observation 1* explicitly specifies `on delete set null` for `tasks.conversation_id` and `documents.task_id`.
   - *Reasoning*: Deleting a chat thread from the mobile History Drawer must not cancel or wipe ongoing background tasks or already downloaded PDFs in the document vault. Deleting a task preserves the document row in vault (`task_id` becomes NULL) until explicit deletion or `delete_after` expiration. In contrast, deleting an `auth.users` row cascades across all 6 tables, guaranteeing complete account data erasure in accordance with India's DPDP Act.
3. **Idempotency Scoping**:
   - *Observation 1* specifies `unique (user_id, idempotency_key)` on `public.tasks`.
   - *Reasoning*: Scoping idempotency to `user_id` ensures that independent users cannot block each other if client UUID generation collides or during test suite runs with deterministic keys.
4. **Concurrency Protection via Partial Unique Index**:
   - *Observation 2* defines `one_active_task_per_workflow` with predicate `where status not in ('COMPLETED','FAILED','CANCELLED','EXPIRED')`.
   - *Reasoning*: The task state machine defines 12 states (8 active, 4 terminal). The partial index creates an index entry only for active tasks. When a task transitions to any terminal state (`COMPLETED`, `FAILED`, `CANCELLED`, `EXPIRED`), PostgreSQL automatically excludes the row from the partial index. This guarantees at the database level that exactly one active workflow instance can run per user at any time, serializing rapid UI double-taps and translating concurrent attempts into HTTP 409 Conflict.
5. **Security Definer Function Hardening**:
   - *Observation 4* shows `set search_path = ''` in `handle_new_user()`.
   - *Reasoning*: Supabase linter and PostgreSQL best practices require `security definer` functions to lock `search_path` to avoid search path hijacking. Because `search_path = ''`, all table references in the function must be explicitly schema-qualified as `public.profiles`. Additionally, adding `on conflict (id) do nothing` prevents signup failures if a profile was already provisioned.

---

## 3. Caveats

1. **Row Level Security (RLS) Policies**: RLS policies for client access and read-only enforcement are within the dedicated purview of `explorer_m1_2`. They are excluded from this report's DDL to avoid scope collision, but table-level `alter table public.<name> enable row level security;` is fully compatible with this DDL.
2. **Storage Bucket & Realtime Publication**: The `storage.buckets` insert, storage RLS policies, and `alter publication supabase_realtime add table ...` are within the dedicated purview of `explorer_m1_3`.
3. **Local Testing Without Live Supabase Instance**: Since this investigation is read-only and no local PostgreSQL daemon was active during this turn, SQL queries were verified via syntax and constraint analysis rather than direct `psql` connection. The provided verification test script (`supabase/tests/0001_init_test.sql`) is structured as a self-contained transaction block with assertions for automated execution during CI/migration application.

---

## 4. Conclusion

The exact SQL design for the DDL, foreign keys, indexes, constraints, and triggers is finalized and documented in `analysis.md`. The design fulfills 100% of Milestone 1 requirements for Features 1–3:
- Full DDL for 6 tables (`profiles`, `conversations`, `tasks`, `messages`, `task_events`, `documents`) with correct column nullability, defaults, and CHECK constraints.
- Correct table dependency ordering avoiding circular references.
- Exact cascade semantics: `auth.users` cascades all; `conversations` deletion cascades `messages` but `SET NULL` on `tasks`; `tasks` deletion cascades `task_events` but `SET NULL` on `documents`.
- Compound indexes for fast mobile retrieval: `(user_id, updated_at desc)`, `(conversation_id, created_at)`, `(task_id, id)`, `(user_id, created_at desc)`.
- Operational indexes: `tasks_queue_dequeue_idx` (for `FOR UPDATE SKIP LOCKED`) and `documents_delete_after_idx` (for hourly retention sweep).
- Composite unique constraint `(user_id, idempotency_key)` on `tasks`.
- Critical partial unique index `one_active_task_per_workflow on public.tasks (user_id, workflow) where status not in ('COMPLETED','FAILED','CANCELLED','EXPIRED')`.
- Hardened `handle_new_user()` security definer trigger with `set search_path = ''` and `on conflict (id) do nothing`.

---

## 5. Verification Method

1. **File Inspection**:
   - Inspect `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\explorer_m1_1\analysis.md` for full DDL and column matrix.
2. **Automated Verification Script**:
   - Execute the SQL test suite provided in Section 9 of `analysis.md` using Supabase CLI or `psql`:
     ```bash
     psql -h <host> -U <user> -d <db> -f supabase/tests/0001_init_test.sql
     ```
   - The test script asserts:
     - Extension `pgcrypto` presence.
     - Table existence for all 6 tables.
     - Automated profile creation on `auth.users` insert.
     - Composite unique constraint rejecting duplicate `(user_id, idempotency_key)` while allowing identical keys across different users.
     - Partial unique index rejecting concurrent active tasks for the same workflow, allowing concurrent active tasks for different workflows, and allowing multiple terminal tasks.
     - Cascade deletion behavior across users, conversations, and tasks.
3. **Invalidation Conditions**:
   - Any modification to the 12 task status values in the state machine (`Section 6`) without updating the `tasks.status` check constraint or the `one_active_task_per_workflow` index filter predicate invalidates this schema.
