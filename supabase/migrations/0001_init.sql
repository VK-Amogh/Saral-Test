-- ============================================================================
-- Saral AI: Database Migration 0001_init.sql
-- Milestone 1 (M1): Schema, Tables, Constraints, Indexes, Triggers, RLS, Storage & Realtime
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
-- Chat sessions grouped in History Drawer
-- ============================================================================
create table public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null default 'New chat',
  archived boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.conversations is 'Chat sessions displayed in mobile app History Drawer';

create index conversations_user_id_updated_at_idx 
  on public.conversations (user_id, updated_at desc);

-- ============================================================================
-- 3. Table: public.tasks
-- Background automation tasks managed by FastAPI state machine & worker
-- Defined before public.messages to support optional FK references
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

-- Operational Queue Index: Fast dequeue via FOR UPDATE SKIP LOCKED
create index idx_tasks_queue 
  on public.tasks (created_at asc)
  where status = 'RECEIVED';

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

create index documents_user_id_created_at_idx 
  on public.documents (user_id, created_at desc);

create index documents_delete_after_idx 
  on public.documents (delete_after);

-- ============================================================================
-- 7. Trigger: Automated Profile Creation on User Signup
-- Security Definer with immutable search_path and idempotent on conflict
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

-- ============================================================================
-- 8. REPLICA IDENTITY FULL
-- Guarantees full previous row image in WAL for Realtime RLS filtering & updates
-- ============================================================================
alter table public.tasks replica identity full;
alter table public.task_events replica identity full;
alter table public.messages replica identity full;

-- ============================================================================
-- 9. Row Level Security (RLS) Policies
-- Default-deny model: Operational tables are client read-only.
-- Zero client write policies on operational tables (writes via service_role key).
-- ============================================================================

-- Enable RLS on all 6 tables
alter table public.profiles      enable row level security;
alter table public.conversations enable row level security;
alter table public.tasks         enable row level security;
alter table public.messages      enable row level security;
alter table public.task_events   enable row level security;
alter table public.documents     enable row level security;

-- Profiles: Full self-management for own profile
create policy "own profile"
  on public.profiles
  for all
  to authenticated
  using (id = auth.uid())
  with check (id = auth.uid());

-- Conversations: Full self-management for own conversations
create policy "own conversations"
  on public.conversations
  for all
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- Operational Tables: Client Read-Only
-- ZERO insert/update/delete policies are granted to authenticated users.
-- Backend mutations occur exclusively via service_role key (BYPASSRLS).
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

-- ============================================================================
-- 10. Private Storage Bucket & Storage RLS Policies
-- ============================================================================

-- Create private 'documents' bucket idempotently with file size and mime constraints
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'documents',
  'documents',
  false,
  10485760,
  array['application/pdf']
)
on conflict (id) do update set
  public = false,
  file_size_limit = 10485760,
  allowed_mime_types = array['application/pdf'];

-- Enable RLS on storage.objects (Supabase enables this by default; ignore insufficient_privilege if run by postgres role)
do $$
begin
  alter table storage.objects enable row level security;
exception
  when insufficient_privilege then
    null;
  when others then
    null;
end $$;

-- Client read policy with folder-level isolation (<user_id>/<task_id>.pdf)
drop policy if exists "read own files" on storage.objects;
create policy "read own files"
  on storage.objects
  for select
  to authenticated
  using (
    bucket_id = 'documents'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

-- Zero client insert/update/delete policies on storage.objects.
-- All uploads and deletes are executed by backend worker via service_role key.

-- ============================================================================
-- 11. Realtime Publication Configuration
-- ============================================================================
do $$
begin
  -- Ensure publication exists
  if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    create publication supabase_realtime;
  end if;

  -- Add public.tasks if not already registered
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'tasks'
  ) then
    alter publication supabase_realtime add table public.tasks;
  end if;

  -- Add public.task_events if not already registered
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'task_events'
  ) then
    alter publication supabase_realtime add table public.task_events;
  end if;

  -- Add public.messages if not already registered
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'messages'
  ) then
    alter publication supabase_realtime add table public.messages;
  end if;
end $$;
