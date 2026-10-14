# Handoff Report: M1 Storage & Realtime Design

**Agent:** `explorer_m1_3` (M1 Storage & Realtime Explorer)  
**Recipient:** `teamwork_preview_orchestrator_1` / M1 Implementer  
**Working Directory:** `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\explorer_m1_3\`  
**Date:** 2026-10-13  
**Status:** Complete (Hard Handoff)  

---

## 1. Observation

1. **`ORIGINAL_REQUEST.md` (lines 58–60):**
   > "Full Row Level Security (RLS) policies: users have read-only access to their own data; writes to tasks, events, and documents are restricted to backend service-role key. Private Supabase Storage bucket `documents` with user isolation. Supabase Realtime publication enabled for `tasks`, `task_events`, `messages`."

2. **`ORIGINAL_REQUEST.md` (lines 69–70):**
   > "OTP and CAPTCHA values are never persisted to Postgres, logged to console, sent to Supabase Realtime, or passed into any LLM prompt. Automated audit scan across backend logs, database rows, and Realtime messages confirms 0 occurrences of unmasked Aadhaar numbers, OTPs, or sensitive tokens."

3. **`PROJECT.md` (lines 175–176, Feature Inventory):**
   > "5 | Supabase Storage Policies | Private `documents` bucket, `<user_id>/<task_id>.pdf` path folder isolation | M1 | Survey 3"  
   > "6 | Supabase Realtime Publications | Realtime enabled for tasks, task_events, messages | M1 | Survey 3"

4. **`PROJECT.md` (lines 308–311, Interface Contract 3):**
   > "- Realtime: Subscribes to channels:
   >    - `postgres_changes` on `tasks` (filter: `user_id=eq.<uid>`)
   >    - `postgres_changes` on `task_events` (filter: `user_id=eq.<uid>`)
   >    - `postgres_changes` on `messages` (filter: `user_id=eq.<uid>`)"

5. **`SARAL_AI_IMPLEMENTATION_PLAN.md` (lines 187–195):**
   ```sql
   -- Private bucket; path convention '<user_id>/<file>'
   insert into storage.buckets (id, name, public) values ('documents','documents', false)
     on conflict (id) do nothing;
   create policy "read own files" on storage.objects for select to authenticated
     using (bucket_id = 'documents' and (storage.foldername(name))[1] = auth.uid()::text);
   -- No insert/update/delete policies for users: only the backend writes or deletes files.

   -- Realtime for live progress and history
   alter publication supabase_realtime add table public.tasks, public.task_events, public.messages;
   ```

6. **PostgreSQL / Supabase Realtime CDC Behavior:**
   - In PostgreSQL, logical replication defaults to `REPLICA IDENTITY DEFAULT`. On `UPDATE`, only primary key columns are recorded for old row states in the WAL.
   - For `public.tasks`, primary key is `id`, but Realtime subscriptions and RLS policies evaluate `user_id`. Without `REPLICA IDENTITY FULL`, Supabase Realtime cannot reliably filter `UPDATE` events by `user_id`.

---

## 2. Logic Chain

1. **Storage Bucket Privacy & Isolation:**
   - From Observation 1 & 5, `storage.buckets` requires an entry with `id = 'documents'`, `name = 'documents'`, and `public = false`.
   - Because `public = false`, Supabase Storage denies all unauthenticated requests to `/storage/v1/object/public/documents/...`.
   - Every file must follow the convention `<user_id>/<task_id>.pdf` (Observation 3).

2. **Storage RLS & Folder Parsing:**
   - Under Observation 5, the policy `"read own files"` enforces `bucket_id = 'documents' and (storage.foldername(name))[1] = auth.uid()::text`.
   - When user A with UUID `auth.uid()` requests an object, `storage.foldername(name)` splits the path on `/`.
   - If the top-level folder matches `auth.uid()::text`, `SELECT` is permitted.
   - If the path targets another user's folder (`<user_b>/...`), or is flat (`flat.pdf` returning NULL folder), the condition evaluates to `FALSE` or `NULL`, denying access.

3. **Client Mutation Lockdown (Zero Write Permissions):**
   - From Observation 1 & 5, no `INSERT`, `UPDATE`, or `DELETE` policies are defined for `storage.objects` for `authenticated` or `anon`.
   - PostgreSQL RLS enforces default-deny: any direct client write attempt fails with an RLS violation (HTTP 403).
   - Only backend services using the `service_role` key (which possesses `BYPASS_RLS`) can write or delete storage objects.
   - This guarantees that only PDFs verified by the Playwright worker's 5-stage document security verifier can enter the `documents` bucket.

4. **Realtime Publications & CDC Streaming:**
   - From Observation 1, 4 & 5, `public.tasks`, `public.task_events`, and `public.messages` must be added to `supabase_realtime`.
   - To prevent migration failure if relations are already members of the publication, the addition should be idempotent (checking `pg_publication_tables`).
   - From Observation 6, tasks update their state continuously (`RECEIVED` → `VALIDATING` → ... → `COMPLETED`). Because Flutter clients subscribe with `filter: user_id=eq.<uid>`, `alter table public.tasks replica identity full;` (along with `task_events` and `messages`) must be executed to ensure Postgres includes all column values in WAL records for `UPDATE` events.

5. **Zero-Leak Payload Guarantee:**
   - From Observation 2, OTP and CAPTCHA values must never leak over Realtime.
   - `tasks.pending_input` stores only prompt metadata (`kind`, `prompt`, `expires_in`, `attempts_left`), never secret values.
   - User chat inputs are scrubbed by the PII/Verhoeff scrubber before insertion into `public.messages`.
   - Realtime transmits only persisted table rows; therefore, broadcast payloads remain strictly sanitized.

---

## 3. Caveats

1. **Storage Extension Availability in Local Mock DBs:**
   - `storage.foldername()` is a built-in helper function of the Supabase Storage PostgreSQL extension. In standalone vanilla PostgreSQL test containers (without the Supabase Storage schema installed), `storage.foldername()` and `storage.objects` will not exist unless the mock creates the `storage` schema and helper functions.
2. **Realtime Publication in Standalone Postgres:**
   - Logical replication and publications (`create publication`) require `wal_level = logical` in `postgresql.conf`. In hosted Supabase Cloud, this is pre-configured. In local or ephemeral test environments, `wal_level = logical` must be enabled.
3. **Bucket Creation Idempotency:**
   - `insert into storage.buckets ... on conflict (id) do nothing;` is safe on rerun, but does not alter an existing bucket's configuration if it was previously created with different parameters.

---

## 4. Conclusion

1. **Canonical DDL for Storage & Realtime (`supabase/migrations/0001_init.sql`):**
   ```sql
   -- ============================================================================
   -- STORAGE BUCKET & STORAGE RLS
   -- ============================================================================
   insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
   values (
     'documents',
     'documents',
     false,
     10485760, -- 10 MB limit
     array['application/pdf']
   )
   on conflict (id) do nothing;

   alter table storage.objects enable row level security;

   drop policy if exists "read own files" on storage.objects;
   create policy "read own files" on storage.objects
     for select to authenticated
     using (
       bucket_id = 'documents'
       and (storage.foldername(name))[1] = auth.uid()::text
     );

   -- No client INSERT, UPDATE, or DELETE policies on storage.objects.
   -- All storage writes and deletions are restricted to backend service_role key.

   -- ============================================================================
   -- REALTIME PUBLICATIONS & REPLICA IDENTITY
   -- ============================================================================
   alter table public.tasks replica identity full;
   alter table public.task_events replica identity full;
   alter table public.messages replica identity full;

   do $$
   begin
     if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
       create publication supabase_realtime;
     end if;

     if not exists (
       select 1 from pg_publication_tables
       where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'tasks'
     ) then
       alter publication supabase_realtime add table public.tasks;
     end if;

     if not exists (
       select 1 from pg_publication_tables
       where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'task_events'
     ) then
       alter publication supabase_realtime add table public.task_events;
     end if;

     if not exists (
       select 1 from pg_publication_tables
       where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'messages'
     ) then
       alter publication supabase_realtime add table public.messages;
     end if;
   end $$;
   ```

2. **Integration Plan Alignment:**
   - The DDL strictly adheres to Section 4 of `SARAL_AI_IMPLEMENTATION_PLAN.md` and fulfills Features 5 & 6 of `PROJECT.md`.
   - Comprehensive technical analysis and test code have been recorded in `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\explorer_m1_3\analysis.md`.

---

## 5. Verification Method

### 1. Verification Commands (SQL Assertions)
Execute against the Supabase database:

```sql
-- 1. Assert bucket exists and is private
select (count(*) = 1) as bucket_ok
from storage.buckets
where id = 'documents' and public = false;

-- 2. Assert storage.objects RLS is enabled and only 'read own files' policy exists
select (count(*) = 1) as policy_ok
from pg_policies
where schemaname = 'storage' and tablename = 'objects'
  and policyname = 'read own files' and cmd = 'SELECT';

select (count(*) = 0) as no_client_mutations_ok
from pg_policies
where schemaname = 'storage' and tablename = 'objects'
  and cmd in ('INSERT', 'UPDATE', 'DELETE')
  and ('authenticated' = any(roles) or 'anon' = any(roles));

-- 3. Assert Realtime publication contains all 3 tables
select count(*) = 3 as realtime_tables_ok
from pg_publication_tables
where pubname = 'supabase_realtime'
  and schemaname = 'public'
  and tablename in ('tasks', 'task_events', 'messages');

-- 4. Assert REPLICA IDENTITY FULL on all 3 tables
select count(*) = 3 as replica_identity_full_ok
from pg_class
where relname in ('tasks', 'task_events', 'messages')
  and relnamespace = 'public'::regnamespace
  and relreplident = 'f';
```

### 2. Verification via Pytest
In the backend test suite:
- `tests/test_storage_rls.py`: Runs the storage isolation suite defined in Section 7.2 of `analysis.md` (proves User A reads own file, User B is denied, direct client upload fails with 403, and service role upload/cleanup succeeds).
- `tests/test_realtime_payloads.py`: Runs the payload scanner defined in Section 7.4 of `analysis.md` (proves zero unmasked Aadhaar, OTPs, or CAPTCHA answers in Realtime events).

### 3. Invalidation Conditions
- Any occurrence of client `INSERT`, `UPDATE`, or `DELETE` policy on `storage.objects`.
- Setting `public = true` on `storage.buckets` for `documents`.
- Absence of `REPLICA IDENTITY FULL` on `public.tasks` causing dropped `UPDATE` events in Flutter Realtime subscriptions.
- Presence of raw credentials in `tasks.pending_input` or `task_events.message`.
