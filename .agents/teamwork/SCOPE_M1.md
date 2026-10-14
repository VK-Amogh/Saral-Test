# Scope: Milestone 1 — Supabase Database Schema, Migrations & Security

## Architecture & Responsibilities
- Deliverable: `supabase/migrations/0001_init.sql` and verification tests/scripts.
- Supabase Project URL: `https://rsftbslckmdkynprmpin.supabase.co`
- Supabase Project ID: `rsftbslckmdkynprmpin`

## Required Features (Features 1–6 from PROJECT.md)
1. **Extensions & Schema**:
   - `create extension if not exists pgcrypto;`
   - `profiles` table: `id uuid primary key references auth.users(id) on delete cascade`, `display_name text`, `created_at timestamptz not null default now()`.
   - `conversations` table: `id uuid primary key default gen_random_uuid()`, `user_id uuid not null references auth.users(id) on delete cascade`, `title text not null default 'New chat'`, `archived boolean not null default false`, `created_at`, `updated_at`. Index on `(user_id, updated_at desc)`.
   - `messages` table: `id uuid primary key default gen_random_uuid()`, `conversation_id uuid not null references public.conversations(id) on delete cascade`, `user_id uuid not null references auth.users(id) on delete cascade`, `role text not null check (role in ('user','assistant','system','task'))`, `content text not null`, `task_id uuid`, `created_at`. Index on `(conversation_id, created_at)`.
   - `tasks` table: `id uuid primary key default gen_random_uuid()`, `user_id uuid not null references auth.users(id) on delete cascade`, `conversation_id uuid references public.conversations(id) on delete set null`, `workflow text not null`, `status text not null default 'RECEIVED'` check across 12 states (`RECEIVED`,`VALIDATING`,`PLANNING`,`RUNNING`,`WAITING_FOR_USER`,`AUTHENTICATING`,`DOWNLOADING`,`VERIFYING`,`COMPLETED`,`FAILED`,`CANCELLED`,`EXPIRED`), `request_text text`, `idempotency_key text not null`, `pending_input jsonb` (NEVER values), `error_code text`, `error_message text`, `created_at`, `updated_at`, `finished_at`, unique `(user_id, idempotency_key)`.
   - Partial unique index: `one_active_task_per_workflow on public.tasks (user_id, workflow) where status not in ('COMPLETED','FAILED','CANCELLED','EXPIRED')`.
   - `task_events` table: `id bigint generated always as identity primary key`, `task_id uuid not null references public.tasks(id) on delete cascade`, `user_id uuid not null references auth.users(id) on delete cascade`, `status text not null`, `message text not null`, `progress smallint check (progress between 0 and 100)`, `created_at`. Index on `(task_id, id)`.
   - `documents` table: `id uuid primary key default gen_random_uuid()`, `user_id uuid not null references auth.users(id) on delete cascade`, `task_id uuid references public.tasks(id) on delete set null`, `doc_type text not null`, `file_name text not null`, `storage_path text not null unique`, `size_bytes integer not null`, `sha256 text not null`, `pdf_encrypted boolean not null default false`, `created_at`, `delete_after timestamptz not null`. Index on `(user_id, created_at desc)`.
2. **Row Level Security (RLS)**:
   - Enable RLS on all 6 tables.
   - `profiles`: `for all using (id = auth.uid()) with check (id = auth.uid())`.
   - `conversations`: `for all using (user_id = auth.uid()) with check (user_id = auth.uid())`.
   - `messages`: `for select using (user_id = auth.uid())` (Client read-only).
   - `tasks`: `for select using (user_id = auth.uid())` (Client read-only).
   - `task_events`: `for select using (user_id = auth.uid())` (Client read-only).
   - `documents`: `for select using (user_id = auth.uid())` (Client read-only).
3. **Storage Bucket & Policies**:
   - `insert into storage.buckets (id, name, public) values ('documents','documents', false) on conflict (id) do nothing;`
   - Policy: `read own files on storage.objects for select to authenticated using (bucket_id = 'documents' and (storage.foldername(name))[1] = auth.uid()::text)`.
   - No user insert/update/delete policies; writes restricted to service role key.
4. **Realtime Publications**:
   - `alter publication supabase_realtime add table public.tasks, public.task_events, public.messages;`
5. **Auth Trigger**:
   - Security definer trigger `on_auth_user_created` calling `handle_new_user()` to insert profile row on new user signup.

## Write Ownership
- Exclusive ownership: `supabase/migrations/0001_init.sql`, `supabase/tests/` or validation test script.
