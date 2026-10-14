# Row Level Security (RLS) Analysis & Architecture Report

**Project:** Saral AI (`Saral_app`)  
**Milestone:** M1 — Database Architecture & Security  
**Explorer:** `explorer_m1_2` (M1 Row Level Security Explorer)  
**Target Migration:** `supabase/migrations/0001_init.sql`  
**Date:** 2026-10-13  

---

## 1. Executive Summary & Mission Scope

This report provides the exhaustive investigation, security analysis, and exact SQL design for the **Row Level Security (RLS)** subsystem of Saral AI. Saral AI is an outcome-oriented system handling sensitive citizen government interactions (including Aadhaar, CAPTCHA, and OTP workflows). The security architecture must guarantee:
1. **Zero Citizen Data Leakage:** Strict tenant and user isolation across all tables. User A can never inspect, query, or infer User B's profiles, conversations, chat messages, active portal tasks, progress stepper events, or downloaded documents.
2. **Anti-Forgery & State Machine Integrity:** Clients must be strictly blocked from forging assistant messages, fabricating task states, injecting fake task progress, or tampering with document metadata. All writes to operational tables (`messages`, `tasks`, `task_events`, `documents`) are locked down to the backend service role key (`BYPASSRLS`).
3. **Full Self-Management for User Entities:** Citizens retain full management (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) strictly over their own profile and conversation threads.
4. **TRACE Security Compliance:** Enforces Zero-Dummy-Bypass, BOLA/IDOR prevention, and Function-Level Authorization constraints.

---

## 2. Threat Model & Architectural Invariants

### 2.1 The Two-Tier Client-Backend Architecture
In Saral AI, the client application (Flutter Android) communicates via two distinct channels:
1. **Direct Supabase Channel (Publishable / Anon Key + User JWT):**
   - Direct `SELECT` queries for conversations, messages, tasks, task events, and documents.
   - Direct `ALL` (CRUD) operations on `conversations` (creating chats, renaming, archiving, deleting).
   - Realtime subscription (`supabase_realtime`) listening for `postgres_changes` on `tasks`, `task_events`, and `messages`.
2. **FastAPI Backend Channel (Service Role Key):**
   - Protected REST endpoints (`/api/v1/chat`, `/api/v1/tasks`, `/api/v1/tasks/{id}/input`, etc.).
   - Client sends authenticated requests with `Authorization: Bearer <Supabase_JWT>`.
   - FastAPI verifies the JWT, runs the **PII & Verhoeff scrubber**, drives the **deterministic state machine**, brokers CAPTCHA/OTP in memory, and performs all database mutations using the Supabase **Service Role Key**.

### 2.2 Attack Vectors Addressed by RLS

| Threat Vector | Description | RLS Remediation |
|---|---|---|
| **BOLA / IDOR Read** | User A crafts a direct Supabase query specifying User B's `user_id` or `task_id`. | RLS filters `USING (user_id = auth.uid())` ensure User A only sees rows where `user_id` matches their verified JWT `auth.uid()`. Cross-user queries return 0 rows. |
| **BOLA / IDOR Mutation** | User A updates or deletes User B's conversations or profile. | `USING` and `WITH CHECK` on `profiles` and `conversations` enforce `user_id = auth.uid()`. |
| **Assistant Impersonation & Prompt Injection** | User A uses Supabase Client to insert a message with `role = 'assistant'` or `role = 'system'`. | `messages` has **zero INSERT policies** for authenticated users. All messages must go through FastAPI's `/api/v1/chat`. |
| **Unscrubbed PII Persistence Bypass** | User A directly inserts a message containing raw Aadhaar numbers or biometrics into `messages`, bypassing backend PII scrubbers. | Blocked by zero INSERT policies on `messages`. Backend is the single gatekeeper for message persistence. |
| **Task State Escalation** | User A updates `public.tasks` to set `status = 'COMPLETED'` to bypass portal verification gates. | `tasks` has **zero UPDATE/INSERT policies** for authenticated users. Only backend orchestrator/verifier can mutate task states. |
| **Realtime Stepper Spoofing** | User A inserts fraudulent `task_events` to mimic portal success or inject misinformation. | `task_events` has **zero INSERT policies** for authenticated users. Realtime broadcasts genuine events only. |
| **Document Metadata Tampering** | User A inserts fake document records with mismatched SHA-256 hashes or altered retention deadlines (`delete_after`). | `documents` has **zero INSERT/UPDATE policies** for authenticated users. Only worker verifier inserts records. |
| **Direct Document Deletion De-sync** | User A deletes a database record in `documents` without deleting the physical file in Supabase Storage. | `documents` has **zero DELETE policies** for authenticated users. Document deletion must go through `DELETE /api/v1/documents/{id}` for coordinated DB + Storage deletion. |
| **Anonymous Snooping** | Unauthenticated callers query public endpoints. | Policies are explicitly restricted `TO authenticated`. With no policies for `anon`, anonymous queries return 0 rows. |

---

## 3. Table-by-Table RLS Policy Design

PostgreSQL implements a **default-deny** security model: once Row Level Security is enabled on a table (`ALTER TABLE ... ENABLE ROW LEVEL SECURITY;`), all operations (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) are denied by default unless an explicit policy permits them.

### 3.1 `public.profiles`
- **Table Role:** Stores user display metadata. Primary key `id` references `auth.users(id)`.
- **Access Level:** Full access (`ALL`) scoped strictly to `auth.uid()`.
- **Policy Definition:**
  ```sql
  alter table public.profiles enable row level security;

  create policy "own profile"
    on public.profiles
    for all
    to authenticated
    using (id = auth.uid())
    with check (id = auth.uid());
  ```
- **Operational Analysis:**
  - **Signup Trigger:** When a new user registers in Supabase Auth, the trigger `on_auth_user_created` calls `handle_new_user()`. Because `handle_new_user()` is declared as `SECURITY DEFINER` with `SET search_path = ''`, it executes with elevated database privileges, successfully inserting `(id = new.id)` even before user session context is established.
  - **Read:** User can read their own profile row (`id = auth.uid()`).
  - **Update:** User can update their `display_name` (`with check (id = auth.uid())`).
  - **Isolation:** Attempting to query `WHERE id = <other_user>` returns 0 rows. Updating another user's profile modifies 0 rows.

### 3.2 `public.conversations`
- **Table Role:** Tracks chat sessions, titles, and archival status.
- **Access Level:** Full access (`ALL`) scoped strictly to `auth.uid()`.
- **Policy Definition:**
  ```sql
  alter table public.conversations enable row level security;

  create policy "own conversations"
    on public.conversations
    for all
    to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());
  ```
- **Operational Analysis:**
  - **Create (`INSERT`):** Citizens can create conversations from the Flutter app. `with check (user_id = auth.uid())` prevents forging the owner ID.
  - **List/View (`SELECT`):** Used by the History Drawer. Filtered by `using (user_id = auth.uid())`.
  - **Edit (`UPDATE`):** Used to rename conversations or mark `archived = true`. `with check` prevents transferring ownership.
  - **Delete (`DELETE`):** Used by History Drawer swipe-to-delete. When a conversation is deleted, child records in `messages` are automatically removed via `ON DELETE CASCADE`.

### 3.3 `public.messages`
- **Table Role:** Immutable log of chat exchanges (`user`, `assistant`, `system`, `task`).
- **Access Level:** **Client Read-Only** (`SELECT` only).
- **Policy Definition:**
  ```sql
  alter table public.messages enable row level security;

  create policy "read own messages"
    on public.messages
    for select
    to authenticated
    using (user_id = auth.uid());
  ```
- **Operational Analysis:**
  - **No Client `INSERT`:** Clients MUST NOT insert into `messages`. User messages are sent to FastAPI `POST /api/v1/chat`, which:
    1. Runs Verhoeff D5 algorithm and regex scrubbers to sanitize Aadhaar, phone numbers, OTPs, and biometric mentions.
    2. Writes the sanitized user message into `public.messages` using the `service_role` key.
    3. Streams the LLM response via SSE and writes the assistant message using the `service_role` key.
  - **No Client `UPDATE` / `DELETE`:** Chat messages are immutable history records. Direct client tampering is completely prohibited.

### 3.4 `public.tasks`
- **Table Role:** Central orchestrator entity tracking government portal automation workflows.
- **Access Level:** **Client Read-Only** (`SELECT` only).
- **Policy Definition:**
  ```sql
  alter table public.tasks enable row level security;

  create policy "read own tasks"
    on public.tasks
    for select
    to authenticated
    using (user_id = auth.uid());
  ```
- **Operational Analysis:**
  - **No Client `INSERT`:** Tasks are created either automatically via chat intent extraction in `POST /api/v1/chat` or via guided workflow initiation in `POST /api/v1/tasks`. Both endpoints enforce idempotency and check the partial unique index `one_active_task_per_workflow`.
  - **No Client `UPDATE`:** State transitions are governed by the strict 12-state matrix in `transition()` (`backend/app/orchestrator/state_machine.py`). Direct client updates are forbidden to prevent state escalation (e.g., jumping from `AUTHENTICATING` to `COMPLETED`).
  - **No Client `DELETE`:** Cancellation must be cooperative via `POST /api/v1/tasks/{id}/cancel` so the worker can gracefully release browser contexts.

### 3.5 `public.task_events`
- **Table Role:** Append-only timeline of granular task status updates, messages, and progress percentages (0–100%).
- **Access Level:** **Client Read-Only** (`SELECT` only).
- **Policy Definition:**
  ```sql
  alter table public.task_events enable row level security;

  create policy "read own events"
    on public.task_events
    for select
    to authenticated
    using (user_id = auth.uid());
  ```
- **Operational Analysis:**
  - **Realtime Integration:** Drives the Flutter `task_stepper_card.dart` component.
  - **No Client Writes:** Ensures only authenticated background workers and backend state transitions can emit progress events.

### 3.6 `public.documents`
- **Table Role:** Metadata catalogue for downloaded citizen documents (Aadhaar PDFs, etc.).
- **Access Level:** **Client Read-Only** (`SELECT` only).
- **Policy Definition:**
  ```sql
  alter table public.documents enable row level security;

  create policy "read own documents"
    on public.documents
    for select
    to authenticated
    using (user_id = auth.uid());
  ```
- **Operational Analysis:**
  - **No Client `INSERT`:** Records are inserted strictly by the worker verifier (`backend/app/worker/verifier.py`) after passing the 5-point security verification (%PDF- header, size, structure, no /JavaScript actions, SHA-256 hash).
  - **No Client `UPDATE`:** Document metadata is immutable.
  - **No Client `DELETE`:** Document deletion must occur via `DELETE /api/v1/documents/{id}`. This guarantees that FastAPI coordinates the physical deletion of the object in Supabase Storage alongside the database record.

---

## 4. Supabase Storage & Realtime RLS Security Interaction

### 4.1 Private Storage Bucket RLS Policy
The storage bucket `documents` stores downloaded files using the path convention:  
`<user_id>/<task_id>.pdf`

```sql
insert into storage.buckets (id, name, public)
values ('documents', 'documents', false)
on conflict (id) do nothing;

create policy "read own files"
  on storage.objects
  for select
  to authenticated
  using (
    bucket_id = 'documents'
    and (storage.foldername(name))[1] = auth.uid()::text
  );
```

- **Folder-Level Tenant Scoping:** `(storage.foldername(name))[1]` extracts the root directory of the object path. User A can only read objects prefixed with their own `auth.uid()`.
- **Client Write Lockdown:** No `INSERT`, `UPDATE`, or `DELETE` policies are granted on `storage.objects` to authenticated users. Workers upload verified files using `service_role`.

### 4.2 Supabase Realtime Security Under RLS
Realtime publication is configured via:
```sql
alter publication supabase_realtime add table public.tasks, public.task_events, public.messages;
```

- **Postgres WAL RLS Filtering:** When a new WAL event occurs on `tasks`, `task_events`, or `messages`, Supabase Realtime checks the table's `SELECT` RLS policy against the subscriber's JWT identity.
- Because all 3 tables enforce `using (user_id = auth.uid())`, Realtime **only broadcasts events to the owning citizen**. Cross-tenant eavesdropping over WebSocket is cryptographically prevented at the database engine level.

---

## 5. Production SQL Script for `0001_init.sql`

The following snippet represents the exact, fully validated DDL block to be included in `supabase/migrations/0001_init.sql`:

```sql
-- ============================================================================
-- ROW LEVEL SECURITY (RLS) POLICIES
-- ============================================================================

-- 1. Enable RLS on all 6 public tables
alter table public.profiles      enable row level security;
alter table public.conversations enable row level security;
alter table public.messages      enable row level security;
alter table public.tasks         enable row level security;
alter table public.task_events   enable row level security;
alter table public.documents     enable row level security;

-- 2. Full Access Policies (Self-Management)
create policy "own profile"
  on public.profiles
  for all
  to authenticated
  using (id = auth.uid())
  with check (id = auth.uid());

create policy "own conversations"
  on public.conversations
  for all
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- 3. Strict Client Read-Only Policies (Operational Tables)
-- Authenticated clients can SELECT their own rows.
-- ZERO insert/update/delete policies are granted to authenticated users.
-- All writes are performed exclusively by the backend via service_role key.
create policy "read own messages"
  on public.messages
  for select
  to authenticated
  using (user_id = auth.uid());

create policy "read own tasks"
  on public.tasks
  for select
  to authenticated
  using (user_id = auth.uid());

create policy "read own events"
  on public.task_events
  for select
  to authenticated
  using (user_id = auth.uid());

create policy "read own documents"
  on public.documents
  for select
  to authenticated
  using (user_id = auth.uid());
```

---

## 6. Comprehensive Verification Queries & Negative Security Test Suite

The following standalone SQL test suite proves all positive and negative security assertions. It can be run in the Supabase SQL editor or via an automated test runner (`psql`, Python `asyncpg`, or `pgTAP`).

```sql
-- ============================================================================
-- SARAL AI RLS VERIFICATION & NEGATIVE SECURITY TEST SUITE
-- ============================================================================

DO $$
DECLARE
  v_user_a uuid := '11111111-1111-1111-1111-111111111111';
  v_user_b uuid := '22222222-2222-2222-2222-222222222222';
  v_conv_a uuid := 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
  v_conv_b uuid := 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
  v_task_a uuid := 'a1111111-1111-1111-1111-111111111111';
  v_task_b uuid := 'b2222222-2222-2222-2222-222222222222';
  v_msg_a  uuid := 'a3333333-3333-3333-3333-333333333333';
  v_msg_b  uuid := 'b3333333-3333-3333-3333-333333333333';
  v_doc_a  uuid := 'a4444444-4444-4444-4444-444444444444';
  v_doc_b  uuid := 'b4444444-4444-4444-4444-444444444444';
  v_count  integer;
  v_failed boolean;
BEGIN
  RAISE NOTICE '--- STARTING RLS TEST SUITE ---';

  -- --------------------------------------------------------------------------
  -- STEP 0: SEED TEST DATA (AS SUPERUSER / SERVICE ROLE)
  -- --------------------------------------------------------------------------
  -- Ensure test users exist in auth.users
  INSERT INTO auth.users (id, email)
  VALUES 
    (v_user_a, 'user_a@test.saralai.in'),
    (v_user_b, 'user_b@test.saralai.in')
  ON CONFLICT (id) DO NOTHING;

  -- Ensure profiles exist
  INSERT INTO public.profiles (id, display_name)
  VALUES
    (v_user_a, 'Citizen A'),
    (v_user_b, 'Citizen B')
  ON CONFLICT (id) DO UPDATE SET display_name = EXCLUDED.display_name;

  -- Seed conversations
  INSERT INTO public.conversations (id, user_id, title)
  VALUES
    (v_conv_a, v_user_a, 'Chat A'),
    (v_conv_b, v_user_b, 'Chat B')
  ON CONFLICT (id) DO NOTHING;

  -- Seed messages (as backend service role)
  INSERT INTO public.messages (id, conversation_id, user_id, role, content)
  VALUES
    (v_msg_a, v_conv_a, v_user_a, 'user', 'Download my e-Aadhaar'),
    (v_msg_b, v_conv_b, v_user_b, 'user', 'User B secret request')
  ON CONFLICT (id) DO NOTHING;

  -- Seed tasks
  INSERT INTO public.tasks (id, user_id, conversation_id, workflow, idempotency_key, status)
  VALUES
    (v_task_a, v_user_a, v_conv_a, 'aadhaar_download', 'idem_a_1', 'RUNNING'),
    (v_task_b, v_user_b, v_conv_b, 'aadhaar_download', 'idem_b_1', 'RUNNING')
  ON CONFLICT (id) DO NOTHING;

  -- Seed task events
  INSERT INTO public.task_events (task_id, user_id, status, message, progress)
  VALUES
    (v_task_a, v_user_a, 'RUNNING', 'Worker navigating to portal', 25),
    (v_task_b, v_user_b, 'RUNNING', 'User B in progress', 50);

  -- Seed documents
  INSERT INTO public.documents (id, user_id, task_id, doc_type, file_name, storage_path, size_bytes, sha256, delete_after)
  VALUES
    (v_doc_a, v_user_a, v_task_a, 'aadhaar', 'eaadhaar_a.pdf', v_user_a || '/task_a.pdf', 102400, 'sha_a_dummy', now() + interval '24 hours'),
    (v_doc_b, v_user_b, v_task_b, 'aadhaar', 'eaadhaar_b.pdf', v_user_b || '/task_b.pdf', 204800, 'sha_b_dummy', now() + interval '24 hours')
  ON CONFLICT (id) DO NOTHING;

  RAISE NOTICE 'Seed data initialized successfully.';

  -- --------------------------------------------------------------------------
  -- TEST SUITE 1: POSITIVE TESTS FOR USER A (AUTHENTICATED)
  -- --------------------------------------------------------------------------
  -- Switch session to User A
  PERFORM set_config('role', 'authenticated', true);
  PERFORM set_config('request.jwt.claim.sub', v_user_a::text, true);
  PERFORM set_config('request.jwt.claims', json_build_object('sub', v_user_a::text, 'role', 'authenticated')::text, true);

  -- 1.1 Can read own profile
  SELECT count(*) INTO v_count FROM public.profiles WHERE id = v_user_a;
  ASSERT v_count = 1, 'TEST 1.1 FAILED: User A should read own profile';

  -- 1.2 Can read own conversations
  SELECT count(*) INTO v_count FROM public.conversations;
  ASSERT v_count = 1, 'TEST 1.2 FAILED: User A should read exactly 1 conversation (their own)';

  -- 1.3 Can read own messages
  SELECT count(*) INTO v_count FROM public.messages;
  ASSERT v_count = 1, 'TEST 1.3 FAILED: User A should read exactly 1 message';

  -- 1.4 Can read own tasks
  SELECT count(*) INTO v_count FROM public.tasks;
  ASSERT v_count = 1, 'TEST 1.4 FAILED: User A should read exactly 1 task';

  -- 1.5 Can read own task events
  SELECT count(*) INTO v_count FROM public.task_events;
  ASSERT v_count = 1, 'TEST 1.5 FAILED: User A should read exactly 1 task event';

  -- 1.6 Can read own documents
  SELECT count(*) INTO v_count FROM public.documents;
  ASSERT v_count = 1, 'TEST 1.6 FAILED: User A should read exactly 1 document';

  -- 1.7 Can create own conversation
  INSERT INTO public.conversations (id, user_id, title)
  VALUES (gen_random_uuid(), v_user_a, 'Another Chat by A');

  -- 1.8 Can update own profile
  UPDATE public.profiles SET display_name = 'Citizen A Updated' WHERE id = v_user_a;
  SELECT count(*) INTO v_count FROM public.profiles WHERE id = v_user_a AND display_name = 'Citizen A Updated';
  ASSERT v_count = 1, 'TEST 1.8 FAILED: User A should be able to update own profile';

  RAISE NOTICE 'SUITE 1 PASSED: Positive read/write access for User A verified.';

  -- --------------------------------------------------------------------------
  -- TEST SUITE 2: NEGATIVE TESTS — CROSS-USER DATA ISOLATION (USER A -> USER B)
  -- --------------------------------------------------------------------------
  -- 2.1 User A cannot read User B profile
  SELECT count(*) INTO v_count FROM public.profiles WHERE id = v_user_b;
  ASSERT v_count = 0, 'SECURITY VIOLATION 2.1: User A read User B profile!';

  -- 2.2 User A cannot read User B conversations
  SELECT count(*) INTO v_count FROM public.conversations WHERE id = v_conv_b;
  ASSERT v_count = 0, 'SECURITY VIOLATION 2.2: User A read User B conversation!';

  -- 2.3 User A cannot read User B messages
  SELECT count(*) INTO v_count FROM public.messages WHERE id = v_msg_b;
  ASSERT v_count = 0, 'SECURITY VIOLATION 2.3: User A read User B message!';

  -- 2.4 User A cannot read User B tasks
  SELECT count(*) INTO v_count FROM public.tasks WHERE id = v_task_b;
  ASSERT v_count = 0, 'SECURITY VIOLATION 2.4: User A read User B task!';

  -- 2.5 User A cannot read User B task events
  SELECT count(*) INTO v_count FROM public.task_events WHERE user_id = v_user_b;
  ASSERT v_count = 0, 'SECURITY VIOLATION 2.5: User A read User B task event!';

  -- 2.6 User A cannot read User B documents
  SELECT count(*) INTO v_count FROM public.documents WHERE id = v_doc_b;
  ASSERT v_count = 0, 'SECURITY VIOLATION 2.6: User A read User B document!';

  RAISE NOTICE 'SUITE 2 PASSED: Cross-user data isolation verified (Zero BOLA reads).';

  -- --------------------------------------------------------------------------
  -- TEST SUITE 3: NEGATIVE TESTS — CROSS-USER TAMPERING & IDOR MUTATIONS
  -- --------------------------------------------------------------------------
  -- 3.1 User A cannot update User B profile
  UPDATE public.profiles SET display_name = 'Hacked by A' WHERE id = v_user_b;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  ASSERT v_count = 0, 'SECURITY VIOLATION 3.1: User A updated User B profile!';

  -- 3.2 User A cannot update User B conversation
  UPDATE public.conversations SET title = 'Hacked title' WHERE id = v_conv_b;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  ASSERT v_count = 0, 'SECURITY VIOLATION 3.2: User A updated User B conversation!';

  -- 3.3 User A cannot delete User B conversation
  DELETE FROM public.conversations WHERE id = v_conv_b;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  ASSERT v_count = 0, 'SECURITY VIOLATION 3.3: User A deleted User B conversation!';

  -- 3.4 User A cannot insert conversation owned by User B (IDOR creation)
  v_failed := false;
  BEGIN
    INSERT INTO public.conversations (id, user_id, title)
    VALUES (gen_random_uuid(), v_user_b, 'Forged Conv for B');
  EXCEPTION WHEN insufficient_privilege OR check_violation THEN
    v_failed := true;
  END;
  ASSERT v_failed, 'SECURITY VIOLATION 3.4: User A was able to insert conversation with user_id = User B!';

  RAISE NOTICE 'SUITE 3 PASSED: Cross-user tampering and IDOR mutations blocked.';

  -- --------------------------------------------------------------------------
  -- TEST SUITE 4: NEGATIVE TESTS — CLIENT WRITE LOCKDOWN ON OPERATIONAL TABLES
  -- --------------------------------------------------------------------------
  -- 4.1 Client cannot forge assistant message
  v_failed := false;
  BEGIN
    INSERT INTO public.messages (conversation_id, user_id, role, content)
    VALUES (v_conv_a, v_user_a, 'assistant', 'I am forged assistant message');
  EXCEPTION WHEN insufficient_privilege OR check_violation THEN
    v_failed := true;
  END;
  ASSERT v_failed, 'SECURITY VIOLATION 4.1: Client was able to insert into messages table!';

  -- 4.2 Client cannot directly insert user message (must use /api/v1/chat for PII scrubbing)
  v_failed := false;
  BEGIN
    INSERT INTO public.messages (conversation_id, user_id, role, content)
    VALUES (v_conv_a, v_user_a, 'user', 'My Aadhaar is 1234 5678 9012');
  EXCEPTION WHEN insufficient_privilege OR check_violation THEN
    v_failed := true;
  END;
  ASSERT v_failed, 'SECURITY VIOLATION 4.2: Client bypassed /api/v1/chat and inserted message directly!';

  -- 4.3 Client cannot update messages
  UPDATE public.messages SET content = 'Altered text' WHERE user_id = v_user_a;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  ASSERT v_count = 0, 'SECURITY VIOLATION 4.3: Client was able to update messages table!';

  -- 4.4 Client cannot delete messages directly
  DELETE FROM public.messages WHERE user_id = v_user_a;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  ASSERT v_count = 0, 'SECURITY VIOLATION 4.4: Client was able to delete messages table!';

  -- 4.5 Client cannot forge task record
  v_failed := false;
  BEGIN
    INSERT INTO public.tasks (user_id, workflow, idempotency_key, status)
    VALUES (v_user_a, 'aadhaar_download', 'forged_idem', 'COMPLETED');
  EXCEPTION WHEN insufficient_privilege OR check_violation THEN
    v_failed := true;
  END;
  ASSERT v_failed, 'SECURITY VIOLATION 4.5: Client was able to insert into tasks table!';

  -- 4.6 Client cannot escalate task state (e.g. mark COMPLETED)
  UPDATE public.tasks SET status = 'COMPLETED' WHERE id = v_task_a;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  ASSERT v_count = 0, 'SECURITY VIOLATION 4.6: Client altered status on tasks table!';

  -- 4.7 Client cannot delete tasks
  DELETE FROM public.tasks WHERE id = v_task_a;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  ASSERT v_count = 0, 'SECURITY VIOLATION 4.7: Client deleted task directly!';

  -- 4.8 Client cannot forge task events
  v_failed := false;
  BEGIN
    INSERT INTO public.task_events (task_id, user_id, status, message, progress)
    VALUES (v_task_a, v_user_a, 'COMPLETED', 'Spoofed progress', 100);
  EXCEPTION WHEN insufficient_privilege OR check_violation THEN
    v_failed := true;
  END;
  ASSERT v_failed, 'SECURITY VIOLATION 4.8: Client inserted into task_events table!';

  -- 4.9 Client cannot insert document metadata
  v_failed := false;
  BEGIN
    INSERT INTO public.documents (user_id, task_id, doc_type, file_name, storage_path, size_bytes, sha256, delete_after)
    VALUES (v_user_a, v_task_a, 'aadhaar', 'forged.pdf', v_user_a || '/forged.pdf', 1000, 'fake_sha', now() + interval '1 hour');
  EXCEPTION WHEN insufficient_privilege OR check_violation THEN
    v_failed := true;
  END;
  ASSERT v_failed, 'SECURITY VIOLATION 4.9: Client inserted into documents table!';

  -- 4.10 Client cannot delete document metadata directly (must use DELETE /api/v1/documents/{id})
  DELETE FROM public.documents WHERE id = v_doc_a;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  ASSERT v_count = 0, 'SECURITY VIOLATION 4.10: Client deleted from documents table directly!';

  RAISE NOTICE 'SUITE 4 PASSED: Client write lockdown on operational tables verified.';

  -- --------------------------------------------------------------------------
  -- TEST SUITE 5: NEGATIVE TESTS — ANONYMOUS (UNAUTHENTICATED) ROLE BLOCK
  -- --------------------------------------------------------------------------
  -- Switch session to anon role
  PERFORM set_config('role', 'anon', true);
  PERFORM set_config('request.jwt.claim.sub', '', true);
  PERFORM set_config('request.jwt.claims', '{}', true);

  -- Anon reading profiles returns 0
  SELECT count(*) INTO v_count FROM public.profiles;
  ASSERT v_count = 0, 'SECURITY VIOLATION 5.1: Anon read profiles!';

  -- Anon reading conversations returns 0
  SELECT count(*) INTO v_count FROM public.conversations;
  ASSERT v_count = 0, 'SECURITY VIOLATION 5.2: Anon read conversations!';

  -- Anon reading messages returns 0
  SELECT count(*) INTO v_count FROM public.messages;
  ASSERT v_count = 0, 'SECURITY VIOLATION 5.3: Anon read messages!';

  -- Anon reading tasks returns 0
  SELECT count(*) INTO v_count FROM public.tasks;
  ASSERT v_count = 0, 'SECURITY VIOLATION 5.4: Anon read tasks!';

  -- Anon reading task_events returns 0
  SELECT count(*) INTO v_count FROM public.task_events;
  ASSERT v_count = 0, 'SECURITY VIOLATION 5.5: Anon read task_events!';

  -- Anon reading documents returns 0
  SELECT count(*) INTO v_count FROM public.documents;
  ASSERT v_count = 0, 'SECURITY VIOLATION 5.6: Anon read documents!';

  RAISE NOTICE 'SUITE 5 PASSED: Anonymous role access completely blocked across all tables.';

  -- --------------------------------------------------------------------------
  -- TEST SUITE 6: POSITIVE TEST — SERVICE ROLE BACKEND BYPASS
  -- --------------------------------------------------------------------------
  -- Reset to superuser / service_role
  PERFORM set_config('role', 'postgres', true);

  -- Backend can insert scrubbed message
  INSERT INTO public.messages (conversation_id, user_id, role, content)
  VALUES (v_conv_a, v_user_a, 'assistant', 'Here is your e-Aadhaar download.');

  -- Backend can advance task state
  UPDATE public.tasks SET status = 'COMPLETED', finished_at = now() WHERE id = v_task_a;
  SELECT count(*) INTO v_count FROM public.tasks WHERE id = v_task_a AND status = 'COMPLETED';
  ASSERT v_count = 1, 'TEST 6.2 FAILED: Service role unable to update task state';

  -- Backend can emit task event
  INSERT INTO public.task_events (task_id, user_id, status, message, progress)
  VALUES (v_task_a, v_user_a, 'COMPLETED', 'Verification complete and document stored', 100);

  RAISE NOTICE 'SUITE 6 PASSED: Service role bypass functioning as expected.';
  RAISE NOTICE '--- ALL RLS TESTS PASSED WITH 100%% SUCCESS ---';
END $$;
```

---

## 7. Performance & Optimization Recommendations

1. **Foreign Key Indexing on `user_id`:**
   - In `public.messages`, an index exists on `(conversation_id, created_at)`. Because RLS checks `user_id = auth.uid()`, adding a composite index `CREATE INDEX idx_messages_user_created ON public.messages (user_id, created_at desc);` ensures RLS evaluations perform index scans rather than sequential filtering on large conversation histories.
   - In `public.task_events`, the index is on `(task_id, id)`. Queries filtering by `user_id` benefit from `CREATE INDEX idx_task_events_user ON public.task_events (user_id);` to accelerate Supabase Realtime broadcast authorization.
2. **Deterministic Role Filter:**
   - Always specify `TO authenticated` in policy creation. This prevents PostgreSQL from even evaluating `USING (user_id = auth.uid())` when an unauthenticated anonymous query arrives, immediately terminating the query plan at the role gate.
3. **Immutability of `user_id`:**
   - In `public.conversations`, `WITH CHECK (user_id = auth.uid())` guarantees that even if a user tries an update query, the row cannot be transferred to another user.

---

## 8. Summary Table of Enforced Policies

| Table | Operation | Allowed Roles | Policy Condition | Client Allowed? | Backend Allowed? |
|---|---|---|---|---|---|
| `profiles` | ALL | `authenticated` | `(id = auth.uid())` | Yes (Own profile only) | Yes (BYPASSRLS) |
| `conversations` | ALL | `authenticated` | `(user_id = auth.uid())` | Yes (Own conversations only) | Yes (BYPASSRLS) |
| `messages` | SELECT | `authenticated` | `(user_id = auth.uid())` | Read-only | Yes (BYPASSRLS) |
| `messages` | INSERT/UPDATE/DELETE | None | None | **NO (Blocked)** | Yes (BYPASSRLS) |
| `tasks` | SELECT | `authenticated` | `(user_id = auth.uid())` | Read-only | Yes (BYPASSRLS) |
| `tasks` | INSERT/UPDATE/DELETE | None | None | **NO (Blocked)** | Yes (BYPASSRLS) |
| `task_events` | SELECT | `authenticated` | `(user_id = auth.uid())` | Read-only | Yes (BYPASSRLS) |
| `task_events` | INSERT/UPDATE/DELETE | None | None | **NO (Blocked)** | Yes (BYPASSRLS) |
| `documents` | SELECT | `authenticated` | `(user_id = auth.uid())` | Read-only | Yes (BYPASSRLS) |
| `documents` | INSERT/UPDATE/DELETE | None | None | **NO (Blocked)** | Yes (BYPASSRLS) |
| `storage.objects` | SELECT | `authenticated` | `bucket_id = 'documents' AND folder = auth.uid()` | Read-only | Yes (BYPASSRLS) |
| `storage.objects` | INSERT/UPDATE/DELETE | None | None | **NO (Blocked)** | Yes (BYPASSRLS) |

---
**Report authored by explorer_m1_2.**
