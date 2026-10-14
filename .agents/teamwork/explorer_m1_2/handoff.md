# Handoff Report: Row Level Security Design & Policies (M1)

**Agent:** `explorer_m1_2` (M1 Row Level Security Explorer)  
**Parent / Recipient:** `b5871ec8-28ec-4ff6-821a-198f59d99e91`  
**Milestone:** M1 — Database Architecture & Security  
**Target File:** `supabase/migrations/0001_init.sql`  
**Artifact Path:** `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\explorer_m1_2\analysis.md`  
**Status:** COMPLETE (Hard Handoff)  

---

## 1. Observation

Direct examination of authoritative specification files reveals the exact requirements for Row Level Security (RLS) in Saral AI:

1. **`d:\Startup\Saral Ai\Saral_app\.agents\teamwork\ORIGINAL_REQUEST.md` (Lines 55–60):**
   > "### R4. Supabase Schema, Security & Operations
   > - Database migrations in `supabase/migrations/0001_init.sql` matching Section 4 of `SARAL_AI_IMPLEMENTATION_PLAN.md`:
   >   - Tables: `profiles`, `conversations`, `messages`, `tasks`, `task_events`, `documents`.
   >   - Full Row Level Security (RLS) policies: users have read-only access to their own data; writes to tasks, events, and documents are restricted to backend service-role key.
   >   - Private Supabase Storage bucket `documents` with user isolation.
   >   - Supabase Realtime publication enabled for `tasks`, `task_events`, `messages`."

2. **`d:\Startup\Saral Ai\Saral_app\SARAL_AI_IMPLEMENTATION_PLAN.md` (Section 4, Lines 170–193 & Line 205):**
   > ```sql
   > alter table public.profiles      enable row level security;
   > alter table public.conversations enable row level security;
   > alter table public.messages      enable row level security;
   > alter table public.tasks         enable row level security;
   > alter table public.task_events   enable row level security;
   > alter table public.documents     enable row level security;
   > 
   > create policy "own profile"       on public.profiles      for all    using (id = auth.uid()) with check (id = auth.uid());
   > create policy "own conversations" on public.conversations for all    using (user_id = auth.uid()) with check (user_id = auth.uid());
   > -- messages, tasks, events, documents: users can READ only. The backend (secret key) writes them,
   > -- so a client can never forge assistant messages, task states, or documents.
   > create policy "read own messages"  on public.messages    for select using (user_id = auth.uid());
   > create policy "read own tasks"     on public.tasks       for select using (user_id = auth.uid());
   > create policy "read own events"    on public.task_events for select using (user_id = auth.uid());
   > create policy "read own documents" on public.documents   for select using (user_id = auth.uid());
   > ```
   > Line 205: "Keys (important): Flutter gets only the publishable key (formerly 'anon'). The secret key (formerly 'service_role') lives only in the backend and worker environments."

3. **`d:\Startup\Saral Ai\Saral_app\PROJECT.md` (Lines 9–10, Lines 306–313):**
   > "Tables with strict RLS (client read-only for operational tables, backend writes with service key), private `documents` bucket, and Realtime publications."
   > Under interface contracts: Flutter app reads directly from Supabase under RLS, subscribes to Realtime on `tasks`, `task_events`, `messages` with `user_id=eq.<uid>`, but all mutations for tasks and messages pass through FastAPI.

4. **`d:\Startup\Saral Ai\Saral_app\.agents\teamwork\SCOPE_M1.md` (Lines 18–25):**
   > "2. Row Level Security (RLS): Enable RLS on all 6 tables. profiles: for all using (id = auth.uid()) with check (id = auth.uid()). conversations: for all using (user_id = auth.uid()) with check (user_id = auth.uid()). messages, tasks, task_events, documents: for select using (user_id = auth.uid()) (Client read-only)."

---

## 2. Logic Chain

1. **Premise 1 (Postgres Default-Deny RLS):** Enabling RLS on a table (`ALTER TABLE ... ENABLE ROW LEVEL SECURITY;`) causes PostgreSQL to deny all queries (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) by default unless an explicit policy grants access.
2. **Premise 2 (Zero Write Policies = Absolute Client Write Lockdown):**
   - For `messages`, `tasks`, `task_events`, and `documents`, defining ONLY `FOR SELECT TO authenticated USING (user_id = auth.uid())` guarantees that authenticated clients (and anonymous clients) CANNOT execute `INSERT`, `UPDATE`, or `DELETE`.
   - Any client attempt to directly insert, update, or delete rows in these 4 tables fails with a policy violation error or modifies 0 rows.
3. **Premise 3 (Service Role Elevated Writes):**
   - The FastAPI backend and Playwright worker connect using Supabase's `service_role` secret key.
   - The PostgreSQL role `service_role` has the `BYPASSRLS` attribute enabled in Supabase.
   - Therefore, backend APIs (`/api/v1/chat`, `/api/v1/tasks`, worker verifiers, and cleanup jobs) can write and delete rows unconstrained by client RLS.
4. **Premise 4 (Crucial Security Invariants Protected):**
   - **Assistant Message Forgery:** If clients had `INSERT` on `messages`, an attacker could inject fraudulent `role = 'assistant'` or `role = 'system'` messages. Restricting `messages` to read-only guarantees all messages pass through `POST /api/v1/chat`, enforcing PII/Verhoeff scrubbing before storage.
   - **Task State Escalation:** If clients had `UPDATE` on `tasks`, an attacker could set `status = 'COMPLETED'` without undergoing portal automation and document verification. Zero write policies enforce the state machine gatekeeper (`transition()`).
   - **Realtime Spoofing:** Restricting `task_events` to read-only guarantees the mobile `task_stepper_card.dart` reflects only genuine worker/orchestrator events.
   - **Document Deletion Coordination:** Restricting `documents` to read-only prevents clients from deleting database rows while leaving orphan files in Supabase Storage. Clients must invoke `DELETE /api/v1/documents/{id}` for coordinated DB + Storage deletion.
5. **Premise 5 (Self-Management Scoping):**
   - `profiles` allows citizens to update their `display_name` via `id = auth.uid()`.
   - `conversations` allows citizens to create, rename, archive, and delete their chat sessions via `user_id = auth.uid()`.
   - `WITH CHECK` clauses on both tables prevent cross-tenant ownership transfer (IDOR).
6. **Premise 6 (Anonymous Role Lockdown):**
   - By explicitly scoping policies `TO authenticated`, unauthenticated callers (`role = 'anon'`) have zero matching policies across all 6 tables, completely eliminating unauthorized data enumeration.

---

## 3. Caveats

1. **Storage Objects Policy Scope:** While storage bucket creation and storage RLS belong principally to explorer_m1_3, storage object security (`storage.objects`) is tightly coupled with `public.documents`. The folder isolation policy `(storage.foldername(name))[1] = auth.uid()::text` must align with the database table convention `<user_id>/<task_id>.pdf`.
2. **Supabase Realtime REPLICA IDENTITY:** For Supabase Realtime to broadcast update events on `public.tasks` with full row data under RLS filtering, `tasks` uses its primary key (`id uuid`), which is sufficient for Realtime. If non-PK column filters were required, `REPLICA IDENTITY FULL` would be needed, but our filter is on `user_id=eq.<uid>` which is stable and set at creation.
3. **Performance of user_id Filter:** `public.messages` has index `(conversation_id, created_at)`. Adding `CREATE INDEX idx_messages_user_created ON public.messages (user_id, created_at desc);` is recommended to optimize RLS sequential scans when filtering purely by `user_id`.

---

## 4. Conclusion

1. **Exact SQL DDL to Include in `supabase/migrations/0001_init.sql`:**
   ```sql
   -- Enable RLS on all 6 tables
   alter table public.profiles      enable row level security;
   alter table public.conversations enable row level security;
   alter table public.messages      enable row level security;
   alter table public.tasks         enable row level security;
   alter table public.task_events   enable row level security;
   alter table public.documents     enable row level security;

   -- Full access for own profile and conversations
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

   -- Strict client read-only for operational tables
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
2. **Security Assurance:**
   - 0 write permissions for authenticated users on `messages`, `tasks`, `task_events`, `documents`.
   - 0 read permissions for User A on User B's resources (complete cross-tenant isolation).
   - 0 access for anonymous/unauthenticated users.
   - 100% TRACE BOLA/IDOR compliance.

---

## 5. Verification Method

### 5.1 Verification Commands & Script
The RLS policies are independently verifiable by running the automated PL/pgSQL test harness provided in Section 6 of `d:\Startup\Saral Ai\Saral_app\.agents\teamwork\explorer_m1_2\analysis.md`.

Execution steps:
1. Apply `supabase/migrations/0001_init.sql` to Postgres.
2. Run the test block using `psql` or the Supabase SQL editor:
   ```bash
   psql -h <SUPABASE_DB_HOST> -U postgres -d postgres -f <path_to_test_block.sql>
   ```
3. Or verify via Python `pytest` integration test using `asyncpg` with:
   ```python
   # Sets session claim to user A
   await conn.execute("SET LOCAL ROLE authenticated;")
   await conn.execute("SELECT set_config('request.jwt.claim.sub', '11111111-1111-1111-1111-111111111111', true);")
   # Attempting to query user B's tasks returns 0 rows:
   rows = await conn.fetch("SELECT * FROM public.tasks WHERE user_id = '22222222-2222-2222-2222-222222222222';")
   assert len(rows) == 0
   ```

### 5.2 Invalidation Conditions
This analysis and design would be invalidated if:
1. Any client `INSERT` or `UPDATE` policy is added to `public.tasks` or `public.messages`.
2. A policy omits `using (user_id = auth.uid())`, allowing cross-tenant data visibility.
3. The backend service role key is compromised or exposed to the Flutter client.
