# Saral AI — Milestone 1 (M1) DDL, Constraints & Triggers Specification

**Author:** `explorer_m1_1` (M1 DDL & Constraints Explorer)  
**Date:** 2026-10-13  
**Working Directory:** `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\explorer_m1_1\`  
**Target Migration:** `supabase/migrations/0001_init.sql`  
**Authoritative References:**
- `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\ORIGINAL_REQUEST.md` (R4, Lines 55–64)
- `d:\Startup\Saral Ai\Saral_app\PROJECT.md` (Features 1–3, Lines 170–173)
- `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\SCOPE_M1.md` (Lines 8–17, 32–34)
- `d:\Startup\Saral Ai\Saral_app\SARAL_AI_IMPLEMENTATION_PLAN.md` (Section 4, Lines 92–169, 198–202)

---

## 1. Executive Summary

Milestone 1 establishes the database foundation for the entire Saral AI system on Supabase PostgreSQL. This document provides the authoritative SQL design for the DDL, foreign key cascade semantics, performance and partial unique indexes, idempotency constraints, and the automated user profile trigger.

The database model is designed around three architectural pillars:
1. **Zero-Trust User Data Isolation:** Every operational entity references `auth.users(id)` directly, ensuring clean cascade deletions upon account termination (complying with Indian DPDP Act right to erasure) and enabling low-overhead Row Level Security (RLS) evaluation without relational joins.
2. **Deterministic Task Concurrency & Idempotency:** The task engine enforces strict single-active-workflow guarantees via a PostgreSQL partial unique index, alongside per-user idempotency keys that protect against network retries and duplicate task dispatches.
3. **Auditability & Zero-Persistence Invariants:** Tasks and documents record structural metadata and integrity hashes (SHA-256), while strictly prohibiting raw biometric credentials, OTPs, or CAPTCHA values from database persistence.

---

## 2. Complete SQL DDL Specification (`0001_init.sql` Core Schema)

Below is the exact SQL implementation recommended for the schema, tables, constraints, indexes, and triggers in `supabase/migrations/0001_init.sql`.

```sql
-- ============================================================================
-- Saral AI: Database Migration 0001_init.sql
-- Core Schema: Extensions, Tables, Constraints, Indexes & Triggers
-- ============================================================================

-- 0. Extensions
create extension if not exists pgcrypto;

-- ============================================================================
-- 1. Table: public.profiles
-- User profile metadata linked 1:1 with auth.users
-- ============================================================================
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  created_at timestamptz not null default now()
);

comment on table public.profiles is 'User profile metadata linked 1:1 to Supabase Auth';

-- ============================================================================
-- 2. Table: public.conversations
-- Chat sessions displayed in the mobile app History Drawer
-- ============================================================================
create table public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null default 'New chat',
  archived boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.conversations is 'Chat sessions grouped in History Drawer';

-- Index: Fast retrieval of active conversations sorted by most recently updated
create index conversations_user_id_updated_at_idx 
  on public.conversations (user_id, updated_at desc);

-- ============================================================================
-- 3. Table: public.tasks
-- Background automation tasks managed by FastAPI state machine & worker
-- Note: Defined before public.messages to support optional FK references
-- ============================================================================
create table public.tasks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  conversation_id uuid references public.conversations(id) on delete set null,
  workflow text not null,
  status text not null default 'RECEIVED' check (status in (
    'RECEIVED',
    'VALIDATING',
    'PLANNING',
    'RUNNING',
    'WAITING_FOR_USER',
    'AUTHENTICATING',
    'DOWNLOADING',
    'VERIFYING',
    'COMPLETED',
    'FAILED',
    'CANCELLED',
    'EXPIRED'
  )),
  request_text text,
  idempotency_key text not null,
  pending_input jsonb,
  error_code text,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  finished_at timestamptz,
  constraint tasks_user_id_idempotency_key_key unique (user_id, idempotency_key)
);

comment on table public.tasks is 'Automation task tracking with 12-state deterministic state machine';
comment on column public.tasks.pending_input is 'Transient challenge prompt metadata {kind, prompt, expires_at, attempts_left} - NEVER raw secrets';

-- Critical Partial Unique Index: Exactly one active task per user per workflow
create unique index one_active_task_per_workflow 
  on public.tasks (user_id, workflow)
  where status not in ('COMPLETED', 'FAILED', 'CANCELLED', 'EXPIRED');

-- Operational Index: Postgres Queue Dequeue via FOR UPDATE SKIP LOCKED
create index tasks_queue_dequeue_idx 
  on public.tasks (created_at asc)
  where status in ('RECEIVED', 'RUNNING');

-- ============================================================================
-- 4. Table: public.messages
-- Chat message history (PII scrubbed before insertion)
-- ============================================================================
create table public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('user', 'assistant', 'system', 'task')),
  content text not null,
  task_id uuid references public.tasks(id) on delete set null,
  created_at timestamptz not null default now()
);

comment on table public.messages is 'Chat messages scrubbed of PII before persistence';

-- Index: Chronological conversation message streaming and pagination
create index messages_conversation_id_created_at_idx 
  on public.messages (conversation_id, created_at);

-- ============================================================================
-- 5. Table: public.task_events
-- Chronological event log driving the Flutter TaskStepperCard in Realtime
-- ============================================================================
create table public.task_events (
  id bigint generated always as identity primary key,
  task_id uuid not null references public.tasks(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  status text not null,
  message text not null,
  progress smallint check (progress between 0 and 100),
  created_at timestamptz not null default now()
);

comment on table public.task_events is 'Monotonic telemetry events driving client Realtime stepper';

-- Index: Event history playback by task ordered monotonically by sequence id
create index task_events_task_id_id_idx 
  on public.task_events (task_id, id);

-- ============================================================================
-- 6. Table: public.documents
-- Metadata for verified artifacts deposited in Supabase Storage
-- ============================================================================
create table public.documents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  task_id uuid references public.tasks(id) on delete set null,
  doc_type text not null,
  file_name text not null,
  storage_path text not null unique,
  size_bytes integer not null,
  sha256 text not null,
  pdf_encrypted boolean not null default false,
  created_at timestamptz not null default now(),
  delete_after timestamptz not null
);

comment on table public.documents is 'Verified document vault records subject to automated retention deletion';

-- Index: User document vault listing ordered chronologically descending
create index documents_user_id_created_at_idx 
  on public.documents (user_id, created_at desc);

-- Operational Index: Hourly retention cleanup sweep
create index documents_delete_after_idx 
  on public.documents (delete_after);

-- ============================================================================
-- 7. Trigger: Automated Profile Creation on User Signup
-- ============================================================================
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, display_name)
  values (
    new.id,
    coalesce(
      new.raw_user_meta_data->>'display_name',
      new.raw_user_meta_data->>'full_name',
      split_part(new.email, '@', 1)
    )
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

comment on function public.handle_new_user() is 'Creates 1:1 public.profiles row automatically upon auth.users signup';

drop trigger if exists on_auth_user_created on auth.users;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
```

---

## 3. Deep-Dive: Column Specifications & Rationale

| Table | Column | Type | Constraints / Default | Rationale & Architectural Rule |
|---|---|---|---|---|
| `profiles` | `id` | `uuid` | `primary key references auth.users(id) on delete cascade` | Strict 1:1 binding to Supabase Auth identity. Cascade ensures zero orphaned profile records. |
| `profiles` | `display_name` | `text` | nullable | Populated via trigger from user signup metadata or edited later. |
| `profiles` | `created_at` | `timestamptz` | `not null default now()` | Audit timestamp. |
| `conversations` | `id` | `uuid` | `primary key default gen_random_uuid()` | Standard UUID primary key. |
| `conversations` | `user_id` | `uuid` | `not null references auth.users(id) on delete cascade` | Mandatory ownership reference. Cascade deletes conversations when account is erased. |
| `conversations` | `title` | `text` | `not null default 'New chat'` | Fits Flutter chat drawer UI requirements. |
| `conversations` | `archived` | `boolean` | `not null default false` | Enables soft-hiding older chats in Flutter drawer. |
| `conversations` | `updated_at` | `timestamptz` | `not null default now()` | Used for sorting drawer groups (Today, Yesterday, Older). |
| `tasks` | `id` | `uuid` | `primary key default gen_random_uuid()` | Globally unique task identifier. |
| `tasks` | `user_id` | `uuid` | `not null references auth.users(id) on delete cascade` | Enforces ownership and RLS scoping. |
| `tasks` | `conversation_id` | `uuid` | `references public.conversations(id) on delete set null` | **Architectural Invariant:** Deleting a chat conversation must NOT abort or destroy background tasks or document access. |
| `tasks` | `workflow` | `text` | `not null` | Workflow key (e.g., `'aadhaar_download'`). |
| `tasks` | `status` | `text` | `not null default 'RECEIVED' check (...)` | Strict CHECK constraint across exactly 12 states defined in Section 6 state machine. |
| `tasks` | `request_text` | `text` | nullable | Scrubbed initial user prompt initiating the task. |
| `tasks` | `idempotency_key`| `text` | `not null` | Provided by client header `Idempotency-Key` or generated UUID. |
| `tasks` | `pending_input` | `jsonb`| nullable | **Zero-Persistence Rule:** Stores only `{kind, prompt, expires_at, attempts_left}`. Never contains raw OTPs or CAPTCHAs. |
| `tasks` | `error_code` | `text` | nullable | Machine-readable failure reason (e.g. `PORTAL_TIMEOUT`, `INVALID_OTP`). |
| `tasks` | `error_message` | `text` | nullable | Sanitized, user-facing error message. |
| `tasks` | `finished_at` | `timestamptz`| nullable | Set when status reaches `COMPLETED`, `FAILED`, `CANCELLED`, or `EXPIRED`. |
| `messages` | `id` | `uuid` | `primary key default gen_random_uuid()` | Unique message ID. |
| `messages` | `conversation_id`| `uuid`| `not null references public.conversations(id) on delete cascade` | Deleting a conversation wipes all associated chat bubbles. |
| `messages` | `user_id` | `uuid` | `not null references auth.users(id) on delete cascade` | Stored directly on message to allow direct `user_id = auth.uid()` RLS without subquery joins. |
| `messages` | `role` | `text` | `not null check (role in ('user','assistant','system','task'))` | Restricts roles to the four supported system actors. |
| `messages` | `content` | `text` | `not null` | Scrubbed text content. |
| `messages` | `task_id` | `uuid` | `references public.tasks(id) on delete set null` | Optional link to inline task card in chat. |
| `task_events` | `id` | `bigint`| `generated always as identity primary key` | Monotonically increasing 64-bit sequence guarantees strict event ordering. |
| `task_events` | `task_id` | `uuid` | `not null references public.tasks(id) on delete cascade` | Deleting a task deletes all associated event telemetry. |
| `task_events` | `user_id` | `uuid` | `not null references auth.users(id) on delete cascade` | Allows direct RLS filtering and Realtime broadcast authorization. |
| `task_events` | `progress` | `smallint`| `check (progress between 0 and 100)` | Progress percentage for Flutter TaskStepperCard. |
| `documents` | `id` | `uuid` | `primary key default gen_random_uuid()` | Unique document ID. |
| `documents` | `user_id` | `uuid` | `not null references auth.users(id) on delete cascade` | Owner user ID. |
| `documents` | `task_id` | `uuid` | `references public.tasks(id) on delete set null` | Deleting a task preserves the document row in vault. |
| `documents` | `storage_path` | `text` | `not null unique` | Path pattern `'<user_id>/<task_id>.pdf'`. Unique constraint prevents file collisions. |
| `documents` | `size_bytes` | `integer`| `not null` | File size in bytes (verified within workflow limits). |
| `documents` | `sha256` | `text` | `not null` | Cryptographic SHA-256 hash verifying download integrity. |
| `documents` | `pdf_encrypted`| `boolean`| `not null default false` | Flag indicating password-protected e-Aadhaar. |
| `documents` | `delete_after` | `timestamptz`| `not null` | Retention deadline (24 hours default, up to 30 days vault). |

---

## 4. Foreign Key Cascade Semantics & Reference Hierarchy

### 4.1 Dependency Hierarchy (Creation Order)

To eliminate foreign key circularity and forward-reference compilation errors in PostgreSQL, the tables MUST be created in the following order:

```
[auth.users] (Supabase system schema)
   │
   ├──► public.profiles          (FK -> auth.users ON DELETE CASCADE)
   ├──► public.conversations     (FK -> auth.users ON DELETE CASCADE)
   │       │
   │       ├────────────────────────┐
   │       ▼                        ▼
   ├──► public.tasks             (FK -> auth.users ON DELETE CASCADE, FK -> conversations ON DELETE SET NULL)
   │       │                        │
   │       ├──────────────┬─────────┤
   │       ▼              ▼         ▼
   ├──► public.messages   (FK -> conversations ON DELETE CASCADE, FK -> auth.users ON DELETE CASCADE, FK -> tasks ON DELETE SET NULL)
   ├──► public.task_events(FK -> tasks ON DELETE CASCADE, FK -> auth.users ON DELETE CASCADE)
   └──► public.documents  (FK -> tasks ON DELETE SET NULL, FK -> auth.users ON DELETE CASCADE)
```

### 4.2 Cascade Invariant Matrix

| Trigger Event | Target Table & Relationship | Action Taken | Architectural Rationale |
|---|---|---|---|
| **User Account Deletion** (`DELETE FROM auth.users WHERE id = $1`) | `profiles.id` | `CASCADE` | User profile removed immediately. |
| | `conversations.user_id` | `CASCADE` | All conversations for the user are purged. |
| | `messages.user_id` | `CASCADE` | All messages belonging to the user are purged. |
| | `tasks.user_id` | `CASCADE` | All tasks for the user are purged. |
| | `task_events.user_id` | `CASCADE` | All event telemetry is purged. |
| | `documents.user_id` | `CASCADE` | All document records are purged. |
| **Conversation Deletion** (`DELETE FROM conversations WHERE id = $1`) | `messages.conversation_id` | `CASCADE` | Chat history inside that conversation is deleted. |
| | `tasks.conversation_id` | `SET NULL` | **Critical:** Active tasks or finished task results are **preserved**. The user deleting a chat thread does not abort a running automation or delete their downloaded document. |
| **Task Deletion** (`DELETE FROM tasks WHERE id = $1`) | `task_events.task_id` | `CASCADE` | Event logs are tightly coupled to the task lifecycle and are purged. |
| | `messages.task_id` | `SET NULL` | The chat message referencing the task remains readable without a broken foreign key. |
| | `documents.task_id` | `SET NULL` | **Critical:** Document in vault remains downloadable/viewable even if task record is pruned. |

---

## 5. Index Design & Performance Analysis

### 5.1 Primary Specification Indexes

1. **`conversations_user_id_updated_at_idx`** on `public.conversations (user_id, updated_at desc)`
   - *Query Pattern:* `SELECT * FROM conversations WHERE user_id = auth.uid() ORDER BY updated_at DESC;`
   - *Analysis:* Perfectly satisfies index-only or bitmap index scan for the Flutter History Drawer. The compound index filters on equality `user_id` and sorts immediately on `updated_at DESC` without an in-memory sort node (`SortMethod: quicksort`).
2. **`messages_conversation_id_created_at_idx`** on `public.messages (conversation_id, created_at)`
   - *Query Pattern:* `SELECT * FROM messages WHERE conversation_id = $1 ORDER BY created_at ASC;`
   - *Analysis:* Enables lightning-fast paginated message loading for chat threads. Chronological order (`created_at ASC`) aligns with natural forward index scans.
3. **`task_events_task_id_id_idx`** on `public.task_events (task_id, id)`
   - *Query Pattern:* `SELECT * FROM task_events WHERE task_id = $1 ORDER BY id ASC;`
   - *Analysis:* Uses the monotonic 64-bit sequence `id` to guarantee strictly ordered event delivery to the Flutter TaskStepperCard. Eliminates clock skew and timestamp collision issues.
4. **`documents_user_id_created_at_idx`** on `public.documents (user_id, created_at desc)`
   - *Query Pattern:* `SELECT * FROM documents WHERE user_id = auth.uid() ORDER BY created_at DESC;`
   - *Analysis:* Powers the on-device Document Vault screen, sorting the user's downloaded PDFs with newest files first.

### 5.2 Recommended Operational Indexes

In addition to the core specification indexes, two high-value operational indexes are recommended:

1. **`tasks_queue_dequeue_idx`** on `public.tasks (created_at asc) WHERE status in ('RECEIVED', 'RUNNING')`
   - *Query Pattern:* `SELECT * FROM tasks WHERE status = 'RECEIVED' ORDER BY created_at ASC FOR UPDATE SKIP LOCKED LIMIT 1;`
   - *Rationale:* Feature 24 (`Postgres Job Queue`) implements worker dequeuing via `FOR UPDATE SKIP LOCKED`. A partial B-tree index indexing only pending tasks (`'RECEIVED'` / `'RUNNING'`) avoids scanning thousands of historical completed/failed tasks.
2. **`documents_delete_after_idx`** on `public.documents (delete_after)`
   - *Query Pattern:* `DELETE FROM documents WHERE delete_after <= NOW();`
   - *Rationale:* Feature 36 / 89 (`Hourly Retention Sweep`) executes periodic batch deletions of expired documents. Without this index, the hourly sweep triggers a full sequential scan on `public.documents`.

---

## 6. Composite Unique Constraint `(user_id, idempotency_key)`

### 6.1 Architectural Rationale

In `public.tasks`:
```sql
constraint tasks_user_id_idempotency_key_key unique (user_id, idempotency_key)
```

1. **Mobile Network Resiliency:** Mobile clients in low-connectivity environments frequently retry `POST /api/v1/chat` or `POST /api/v1/tasks` if the network drops before an HTTP response is acknowledged. The client attaches an `Idempotency-Key: <uuid>`.
2. **Tenant Scoping:** By combining `user_id` with `idempotency_key`, the constraint guarantees that two independent users generating identical UUIDs (or predictable retry tokens) do not collide.
3. **API Handling:** If a client re-submits a request with the same key, PostgreSQL throws `23505` (`unique_violation`). The FastAPI backend catches this exception and returns the already-created task object with HTTP `200 OK`, avoiding duplicate task creation.

---

## 7. Partial Unique Index: `one_active_task_per_workflow`

### 7.1 Detailed Mechanics

```sql
create unique index one_active_task_per_workflow on public.tasks (user_id, workflow)
  where status not in ('COMPLETED', 'FAILED', 'CANCELLED', 'EXPIRED');
```

### 7.2 State Partitioning

The state machine defines 12 distinct status values:

| Category | States Count | Status Values | In Partial Index? |
|---|---|---|---|
| **Active States** | 8 | `'RECEIVED'`, `'VALIDATING'`, `'PLANNING'`, `'RUNNING'`, `'WAITING_FOR_USER'`, `'AUTHENTICATING'`, `'DOWNLOADING'`, `'VERIFYING'` | **YES** (Index entry exists) |
| **Terminal States** | 4 | `'COMPLETED'`, `'FAILED'`, `'CANCELLED'`, `'EXPIRED'` | **NO** (Filtered out by WHERE) |

### 7.3 Concurrency & Invariant Enforcement

1. **Single-Flight Invariant:** For any given `(user_id, workflow)` tuple, there can be at most **one** task whose status is in the active set.
2. **Immediate Race Condition Serialization:** Even under high concurrency (e.g. user rapid-taps "Download Aadhaar" in chat, causing 2 simultaneous HTTP requests to different FastAPI worker threads), PostgreSQL's index b-tree lock forces one transaction to commit and the second transaction to abort immediately with:
   ```
   ERROR: duplicate key value violates unique constraint "one_active_task_per_workflow"
   DETAIL: Key (user_id, workflow)=(<uuid>, aadhaar_download) already exists.
   ```
3. **HTTP 409 Conflict Mapping:** FastAPI catches `one_active_task_per_workflow` violations and translates them to HTTP `409 Conflict` with a user-friendly message: `"A task for this workflow is already in progress."`
4. **Historical Multiplicity:** As soon as an active task transitions to a terminal state (`status = 'COMPLETED'`), the row is excluded from the index. A user can accumulate hundreds of historical completed/failed tasks without ever violating this constraint.

---

## 8. Security Definer Trigger: `handle_new_user()`

### 8.1 Implementation & Security Hardening

```sql
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, display_name)
  values (
    new.id,
    coalesce(
      new.raw_user_meta_data->>'display_name',
      new.raw_user_meta_data->>'full_name',
      split_part(new.email, '@', 1)
    )
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
```

### 8.2 Security Checklist Analysis

1. **`security definer` Necessity:**
   - `public.profiles` has RLS enabled with `USING (id = auth.uid())`.
   - When a user signs up, the row is inserted into `auth.users` by the internal Supabase auth daemon. At that instant, no authenticated JWT session is active in the PostgreSQL session context (`auth.uid()` evaluates to `NULL`).
   - Running the trigger as `security definer` executes the insert under the database owner (`postgres` or `supabase_admin`), bypassing RLS and ensuring profile row creation never fails due to security policies.
2. **`set search_path = ''` Hardening:**
   - Required by PostgreSQL security standards and Supabase database linter (`function_search_path_mutable`).
   - Prevents search path manipulation vulnerabilities where an attacker could inject a fake `profiles` table in a custom schema.
   - All object references (`public.profiles`) are explicitly schema-qualified.
3. **`on conflict (id) do nothing` Idempotency:**
   - Guarantees that if a signup transaction is retried or if a user ID is pre-seeded in a test environment, the trigger will not throw a primary key violation.
4. **Metadata Extraction:**
   - Intelligently extracts `display_name` from `raw_user_meta_data` if supplied during signup, falling back to the email local part.

---

## 9. Comprehensive SQL Verification Suite

Below is the verification test script (`supabase/tests/0001_init_test.sql`) that can be executed to independently verify all DDL, cascade, index, constraint, and trigger behaviors:

```sql
-- ============================================================================
-- Saral AI: M1 Verification Test Suite
-- ============================================================================

begin;

-- 1. Verify Extension
do $$
begin
  assert (select count(*) from pg_extension where extname = 'pgcrypto') = 1,
    'Extension pgcrypto is missing';
end $$;

-- 2. Verify Table Existence
do $$
declare
  t text;
  tables text[] := array['profiles', 'conversations', 'tasks', 'messages', 'task_events', 'documents'];
begin
  foreach t in array tables loop
    assert exists (
      select 1 from information_schema.tables 
      where table_schema = 'public' and table_name = t
    ), format('Table public.%s does not exist', t);
  end loop;
end $$;

-- 3. Verify Trigger and Profile Creation
do $$
declare
  test_user_id uuid := gen_random_uuid();
begin
  -- Simulate user signup
  insert into auth.users (id, email, raw_user_meta_data)
  values (test_user_id, 'tester@example.com', '{"display_name": "Test Citizen"}'::jsonb);

  -- Assert profile was created automatically
  assert exists (
    select 1 from public.profiles where id = test_user_id and display_name = 'Test Citizen'
  ), 'handle_new_user trigger failed to create profile';
end $$;

-- 4. Verify Composite Unique Constraint (user_id, idempotency_key)
do $$
declare
  u1 uuid := gen_random_uuid();
  u2 uuid := gen_random_uuid();
begin
  insert into auth.users (id, email) values (u1, 'u1@example.com'), (u2, 'u2@example.com');

  -- Task 1 with idempotency_key 'k1'
  insert into public.tasks (user_id, workflow, idempotency_key, status)
  values (u1, 'aadhaar_download', 'k1', 'COMPLETED');

  -- Task 2 with same idempotency_key for DIFFERENT user -> MUST SUCCEED
  insert into public.tasks (user_id, workflow, idempotency_key, status)
  values (u2, 'aadhaar_download', 'k1', 'COMPLETED');

  -- Task 3 with SAME user and SAME idempotency_key -> MUST FAIL
  begin
    insert into public.tasks (user_id, workflow, idempotency_key, status)
    values (u1, 'aadhaar_download', 'k1', 'COMPLETED');
    raise exception 'Expected duplicate idempotency_key error, but insert succeeded';
  exception
    when unique_violation then
      null; -- Expected behavior
  end;
end $$;

-- 5. Verify Partial Unique Index: one_active_task_per_workflow
do $$
declare
  u uuid := gen_random_uuid();
  t1_id uuid;
begin
  insert into auth.users (id, email) values (u, 'active_tester@example.com');

  -- First active task (RUNNING) -> MUST SUCCEED
  insert into public.tasks (user_id, workflow, idempotency_key, status)
  values (u, 'aadhaar_download', 'req-1', 'RUNNING')
  returning id into t1_id;

  -- Second active task (same user, same workflow, status WAITING_FOR_USER) -> MUST FAIL
  begin
    insert into public.tasks (user_id, workflow, idempotency_key, status)
    values (u, 'aadhaar_download', 'req-2', 'WAITING_FOR_USER');
    raise exception 'Expected one_active_task_per_workflow violation, but insert succeeded';
  exception
    when unique_violation then
      null; -- Expected behavior
  end;

  -- Active task for a DIFFERENT workflow -> MUST SUCCEED
  insert into public.tasks (user_id, workflow, idempotency_key, status)
  values (u, 'pan_download', 'req-3', 'RUNNING');

  -- Transition t1 to terminal state COMPLETED
  update public.tasks set status = 'COMPLETED' where id = t1_id;

  -- Now insert new active task for aadhaar_download -> MUST SUCCEED
  insert into public.tasks (user_id, workflow, idempotency_key, status)
  values (u, 'aadhaar_download', 'req-4', 'RECEIVED');

  -- Multiple terminal tasks for aadhaar_download -> MUST SUCCEED
  insert into public.tasks (user_id, workflow, idempotency_key, status)
  values (u, 'aadhaar_download', 'req-5', 'FAILED');

  insert into public.tasks (user_id, workflow, idempotency_key, status)
  values (u, 'aadhaar_download', 'req-6', 'CANCELLED');
end $$;

-- 6. Verify Foreign Key Cascade Semantics
do $$
declare
  u uuid := gen_random_uuid();
  c_id uuid;
  t_id uuid;
  m_id uuid;
  e_id bigint;
  d_id uuid;
begin
  insert into auth.users (id, email) values (u, 'cascade_tester@example.com');

  insert into public.conversations (user_id, title) values (u, 'Test Conversation')
  returning id into c_id;

  insert into public.tasks (user_id, conversation_id, workflow, idempotency_key, status)
  values (u, c_id, 'aadhaar_download', 'idem-c', 'COMPLETED')
  returning id into t_id;

  insert into public.messages (conversation_id, user_id, role, content, task_id)
  values (c_id, u, 'user', 'Download my card', t_id)
  returning id into m_id;

  insert into public.task_events (task_id, user_id, status, message, progress)
  values (t_id, u, 'COMPLETED', 'Done', 100)
  returning id into e_id;

  insert into public.documents (user_id, task_id, doc_type, file_name, storage_path, size_bytes, sha256, delete_after)
  values (u, t_id, 'aadhaar', 'card.pdf', u::text || '/test.pdf', 1024, 'abc123sha', now() + interval '1 day')
  returning id into d_id;

  -- Test 6a: Deleting conversation cascades messages, but SET NULL on tasks.conversation_id
  delete from public.conversations where id = c_id;
  assert not exists (select 1 from public.messages where id = m_id), 'Message was not cascaded on conversation delete';
  assert (select conversation_id from public.tasks where id = t_id) is null, 'Task conversation_id was not set to null';

  -- Test 6b: Deleting task cascades task_events, but SET NULL on documents.task_id
  delete from public.tasks where id = t_id;
  assert not exists (select 1 from public.task_events where id = e_id), 'Task event was not cascaded on task delete';
  assert (select task_id from public.documents where id = d_id) is null, 'Document task_id was not set to null';

  -- Test 6c: Deleting user cascades all remaining entities
  delete from auth.users where id = u;
  assert not exists (select 1 from public.profiles where id = u), 'Profile was not cascaded on user delete';
  assert not exists (select 1 from public.documents where id = d_id), 'Document was not cascaded on user delete';
end $$;

rollback; -- Verification test clean rollback
```
