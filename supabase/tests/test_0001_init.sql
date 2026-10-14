-- ============================================================================
-- Saral AI: Milestone 1 (M1) Comprehensive SQL Verification Suite
-- File: supabase/tests/test_0001_init.sql
-- Description: Independent test suite verifying DDL, foreign keys, cascades,
--              check constraints, unique & partial indexes, trigger execution,
--              REPLICA IDENTITY FULL, RLS policies, storage bucket, and publications.
-- ============================================================================

begin;

-- ============================================================================
-- TEST 1: Extensions
-- ============================================================================
do $$
begin
  assert (select count(*) from pg_extension where extname = 'pgcrypto') = 1,
    'TEST 1 FAILED: Extension pgcrypto is not installed';
  raise notice 'TEST 1 PASSED: Extension pgcrypto verified.';
end $$;

-- ============================================================================
-- TEST 2: Schema & Table Existence
-- ============================================================================
do $$
declare
  tbl text;
  tbls text[] := array['profiles', 'conversations', 'tasks', 'messages', 'task_events', 'documents'];
begin
  foreach tbl in array tbls loop
    assert exists (
      select 1 from information_schema.tables 
      where table_schema = 'public' and table_name = tbl
    ), format('TEST 2 FAILED: Table public.%s does not exist', tbl);
  end loop;
  raise notice 'TEST 2 PASSED: All 6 core tables exist in public schema.';
end $$;

-- ============================================================================
-- TEST 3: Check Constraints
-- ============================================================================
do $$
declare
  u uuid := gen_random_uuid();
  c uuid := gen_random_uuid();
  t uuid := gen_random_uuid();
  failed boolean;
begin
  insert into auth.users (id, email) values (u, 'check_tester@saralai.in');
  insert into public.conversations (id, user_id, title) values (c, u, 'Test Conv');
  insert into public.tasks (id, user_id, conversation_id, workflow, idempotency_key, status)
  values (t, u, c, 'aadhaar_download', 'idem-check-1', 'RECEIVED');

  -- 3.1 Invalid message role check
  failed := false;
  begin
    insert into public.messages (conversation_id, user_id, role, content)
    values (c, u, 'unauthorized_role', 'Test message');
  exception when check_violation then
    failed := true;
  end;
  assert failed, 'TEST 3.1 FAILED: Expected check_violation on invalid message role';

  -- 3.2 Valid message roles ('user', 'assistant', 'system', 'task')
  insert into public.messages (conversation_id, user_id, role, content) values (c, u, 'user', 'hi');
  insert into public.messages (conversation_id, user_id, role, content) values (c, u, 'assistant', 'hi');
  insert into public.messages (conversation_id, user_id, role, content) values (c, u, 'system', 'hi');
  insert into public.messages (conversation_id, user_id, role, content) values (c, u, 'task', 'hi');

  -- 3.3 Invalid task status check
  failed := false;
  begin
    insert into public.tasks (user_id, workflow, idempotency_key, status)
    values (u, 'aadhaar_download', 'idem-check-2', 'INVALID_STATUS');
  exception when check_violation then
    failed := true;
  end;
  assert failed, 'TEST 3.3 FAILED: Expected check_violation on invalid task status';

  -- 3.4 Task events progress check (0 to 100)
  failed := false;
  begin
    insert into public.task_events (task_id, user_id, status, message, progress)
    values (t, u, 'RUNNING', 'Bad progress', -5);
  exception when check_violation then
    failed := true;
  end;
  assert failed, 'TEST 3.4 FAILED: Expected check_violation on negative progress';

  failed := false;
  begin
    insert into public.task_events (task_id, user_id, status, message, progress)
    values (t, u, 'RUNNING', 'Bad progress', 105);
  exception when check_violation then
    failed := true;
  end;
  assert failed, 'TEST 3.4 FAILED: Expected check_violation on progress > 100';

  insert into public.task_events (task_id, user_id, status, message, progress)
  values (t, u, 'RUNNING', 'Good progress', 50);

  raise notice 'TEST 3 PASSED: All check constraints verified.';
end $$;

-- ============================================================================
-- TEST 4: Unique Constraints & Indexes
-- ============================================================================
do $$
declare
  u1 uuid := gen_random_uuid();
  u2 uuid := gen_random_uuid();
  failed boolean;
begin
  insert into auth.users (id, email) values (u1, 'u1_idx@saralai.in'), (u2, 'u2_idx@saralai.in');

  -- 4.1 Composite unique (user_id, idempotency_key) on tasks
  insert into public.tasks (user_id, workflow, idempotency_key, status)
  values (u1, 'aadhaar_download', 'idem-uniq-key', 'COMPLETED');

  -- Same key, different user -> MUST SUCCEED
  insert into public.tasks (user_id, workflow, idempotency_key, status)
  values (u2, 'aadhaar_download', 'idem-uniq-key', 'COMPLETED');

  -- Same key, same user -> MUST FAIL
  failed := false;
  begin
    insert into public.tasks (user_id, workflow, idempotency_key, status)
    values (u1, 'aadhaar_download', 'idem-uniq-key', 'COMPLETED');
  exception when unique_violation then
    failed := true;
  end;
  assert failed, 'TEST 4.1 FAILED: Duplicate (user_id, idempotency_key) should fail';

  -- 4.2 Unique storage_path on documents
  insert into public.documents (user_id, doc_type, file_name, storage_path, size_bytes, sha256, delete_after)
  values (u1, 'aadhaar', 'doc1.pdf', u1::text || '/task1.pdf', 1024, 'sha1', now() + interval '1 day');

  failed := false;
  begin
    insert into public.documents (user_id, doc_type, file_name, storage_path, size_bytes, sha256, delete_after)
    values (u2, 'aadhaar', 'doc2.pdf', u1::text || '/task1.pdf', 2048, 'sha2', now() + interval '1 day');
  exception when unique_violation then
    failed := true;
  end;
  assert failed, 'TEST 4.2 FAILED: Duplicate storage_path should fail';

  -- 4.3 Verify required index existence
  assert exists (
    select 1 from pg_indexes where schemaname = 'public' and tablename = 'conversations'
    and indexname = 'conversations_user_id_updated_at_idx'
  ), 'TEST 4.3 FAILED: Index conversations_user_id_updated_at_idx missing';

  assert exists (
    select 1 from pg_indexes where schemaname = 'public' and tablename = 'messages'
    and indexname = 'messages_conversation_id_created_at_idx'
  ), 'TEST 4.3 FAILED: Index messages_conversation_id_created_at_idx missing';

  assert exists (
    select 1 from pg_indexes where schemaname = 'public' and tablename = 'task_events'
    and indexname = 'task_events_task_id_id_idx'
  ), 'TEST 4.3 FAILED: Index task_events_task_id_id_idx missing';

  assert exists (
    select 1 from pg_indexes where schemaname = 'public' and tablename = 'documents'
    and indexname = 'documents_user_id_created_at_idx'
  ), 'TEST 4.3 FAILED: Index documents_user_id_created_at_idx missing';

  assert exists (
    select 1 from pg_indexes where schemaname = 'public' and tablename = 'documents'
    and indexname = 'documents_delete_after_idx'
  ), 'TEST 4.3 FAILED: Index documents_delete_after_idx missing';

  assert exists (
    select 1 from pg_indexes where schemaname = 'public' and tablename = 'tasks'
    and indexname = 'idx_tasks_queue'
  ), 'TEST 4.3 FAILED: Queue index idx_tasks_queue missing';

  raise notice 'TEST 4 PASSED: Unique constraints and indexes verified.';
end $$;

-- ============================================================================
-- TEST 5: Partial Unique Index one_active_task_per_workflow
-- ============================================================================
do $$
declare
  u uuid := gen_random_uuid();
  t1 uuid;
  failed boolean;
begin
  insert into auth.users (id, email) values (u, 'partial_idx@saralai.in');

  -- First active task (RUNNING)
  insert into public.tasks (user_id, workflow, idempotency_key, status)
  values (u, 'aadhaar_download', 'active-1', 'RUNNING')
  returning id into t1;

  -- Second active task for same user & workflow (WAITING_FOR_USER) -> MUST FAIL
  failed := false;
  begin
    insert into public.tasks (user_id, workflow, idempotency_key, status)
    values (u, 'aadhaar_download', 'active-2', 'WAITING_FOR_USER');
  exception when unique_violation then
    failed := true;
  end;
  assert failed, 'TEST 5.1 FAILED: Expected partial unique index violation for duplicate active task';

  -- Active task for DIFFERENT workflow -> MUST SUCCEED
  insert into public.tasks (user_id, workflow, idempotency_key, status)
  values (u, 'pan_download', 'active-3', 'RUNNING');

  -- Transition t1 to terminal state COMPLETED
  update public.tasks set status = 'COMPLETED', finished_at = now() where id = t1;

  -- New active task for aadhaar_download -> MUST SUCCEED now that previous is terminal
  insert into public.tasks (user_id, workflow, idempotency_key, status)
  values (u, 'aadhaar_download', 'active-4', 'RECEIVED');

  -- Additional terminal tasks -> MUST SUCCEED without violation
  insert into public.tasks (user_id, workflow, idempotency_key, status)
  values (u, 'aadhaar_download', 'term-5', 'FAILED');

  insert into public.tasks (user_id, workflow, idempotency_key, status)
  values (u, 'aadhaar_download', 'term-6', 'CANCELLED');

  insert into public.tasks (user_id, workflow, idempotency_key, status)
  values (u, 'aadhaar_download', 'term-7', 'EXPIRED');

  raise notice 'TEST 5 PASSED: Partial unique index one_active_task_per_workflow verified.';
end $$;

-- ============================================================================
-- TEST 6: Trigger handle_new_user
-- ============================================================================
do $$
declare
  test_uid uuid := gen_random_uuid();
begin
  insert into auth.users (id, email, raw_user_meta_data)
  values (test_uid, 'newuser@saralai.in', '{"display_name": "Citizen Ramesh"}'::jsonb);

  assert exists (
    select 1 from public.profiles where id = test_uid and display_name = 'Citizen Ramesh'
  ), 'TEST 6 FAILED: handle_new_user failed to create profile row';

  raise notice 'TEST 6 PASSED: Trigger handle_new_user verified.';
end $$;

-- ============================================================================
-- TEST 7: Foreign Key Cascades & Set Null Rules
-- ============================================================================
do $$
declare
  u uuid := gen_random_uuid();
  c_id uuid;
  t_id uuid;
  m_id uuid;
  e_id bigint;
  d_id uuid;
begin
  insert into auth.users (id, email) values (u, 'cascade@saralai.in');

  insert into public.conversations (user_id, title) values (u, 'Cascade Thread')
  returning id into c_id;

  insert into public.tasks (user_id, conversation_id, workflow, idempotency_key, status)
  values (u, c_id, 'aadhaar_download', 'idem-cascade', 'COMPLETED')
  returning id into t_id;

  insert into public.messages (conversation_id, user_id, role, content, task_id)
  values (c_id, u, 'user', 'Download Aadhaar', t_id)
  returning id into m_id;

  insert into public.task_events (task_id, user_id, status, message, progress)
  values (t_id, u, 'COMPLETED', 'Finished', 100)
  returning id into e_id;

  insert into public.documents (user_id, task_id, doc_type, file_name, storage_path, size_bytes, sha256, delete_after)
  values (u, t_id, 'aadhaar', 'card.pdf', u::text || '/card.pdf', 2048, 'sha256demo', now() + interval '1 day')
  returning id into d_id;

  -- 7.1 Deleting conversation cascades messages, but SET NULL on tasks.conversation_id
  delete from public.conversations where id = c_id;
  assert not exists (select 1 from public.messages where id = m_id),
    'TEST 7.1 FAILED: Messages should cascade delete on conversation deletion';
  assert (select conversation_id from public.tasks where id = t_id) is null,
    'TEST 7.1 FAILED: Task conversation_id should be SET NULL on conversation deletion';

  -- 7.2 Deleting task cascades task_events, but SET NULL on documents.task_id
  delete from public.tasks where id = t_id;
  assert not exists (select 1 from public.task_events where id = e_id),
    'TEST 7.2 FAILED: Task events should cascade delete on task deletion';
  assert (select task_id from public.documents where id = d_id) is null,
    'TEST 7.2 FAILED: Document task_id should be SET NULL on task deletion';

  -- 7.3 Deleting user cascades profiles and documents
  delete from auth.users where id = u;
  assert not exists (select 1 from public.profiles where id = u),
    'TEST 7.3 FAILED: Profile should cascade delete on user deletion';
  assert not exists (select 1 from public.documents where id = d_id),
    'TEST 7.3 FAILED: Document should cascade delete on user deletion';

  raise notice 'TEST 7 PASSED: Foreign key cascade and set null semantics verified.';
end $$;

-- ============================================================================
-- TEST 8: REPLICA IDENTITY FULL
-- ============================================================================
do $$
begin
  assert (
    select relreplident from pg_class where relname = 'tasks' and relnamespace = 'public'::regnamespace
  ) = 'f', 'TEST 8 FAILED: tasks table does not have REPLICA IDENTITY FULL';

  assert (
    select relreplident from pg_class where relname = 'task_events' and relnamespace = 'public'::regnamespace
  ) = 'f', 'TEST 8 FAILED: task_events table does not have REPLICA IDENTITY FULL';

  assert (
    select relreplident from pg_class where relname = 'messages' and relnamespace = 'public'::regnamespace
  ) = 'f', 'TEST 8 FAILED: messages table does not have REPLICA IDENTITY FULL';

  raise notice 'TEST 8 PASSED: REPLICA IDENTITY FULL verified on operational tables.';
end $$;

-- ============================================================================
-- TEST 9: Row Level Security Policies
-- ============================================================================
do $$
declare
  u_a uuid := '11111111-1111-1111-1111-111111111111';
  u_b uuid := '22222222-2222-2222-2222-222222222222';
  conv_a uuid := 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
  conv_b uuid := 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
  task_a uuid := 'a1111111-1111-1111-1111-111111111111';
  task_b uuid := 'b2222222-2222-2222-2222-222222222222';
  msg_a uuid := 'a3333333-3333-3333-3333-333333333333';
  msg_b uuid := 'b3333333-3333-3333-3333-333333333333';
  doc_a uuid := 'a4444444-4444-4444-4444-444444444444';
  doc_b uuid := 'b4444444-4444-4444-4444-444444444444';
  v_count integer;
  failed boolean;
begin
  -- Seed data as superuser / backend
  insert into auth.users (id, email) values (u_a, 'user_a@saralai.in'), (u_b, 'user_b@saralai.in')
  on conflict (id) do nothing;

  insert into public.profiles (id, display_name) values (u_a, 'Citizen A'), (u_b, 'Citizen B')
  on conflict (id) do update set display_name = excluded.display_name;

  insert into public.conversations (id, user_id, title) values (conv_a, u_a, 'Chat A'), (conv_b, u_b, 'Chat B')
  on conflict (id) do nothing;

  insert into public.tasks (id, user_id, conversation_id, workflow, idempotency_key, status)
  values (task_a, u_a, conv_a, 'aadhaar_download', 'idem-a-rls', 'RUNNING'),
         (task_b, u_b, conv_b, 'aadhaar_download', 'idem-b-rls', 'RUNNING')
  on conflict (id) do nothing;

  insert into public.messages (id, conversation_id, user_id, role, content, task_id)
  values (msg_a, conv_a, u_a, 'user', 'Download e-Aadhaar', task_a),
         (msg_b, conv_b, u_b, 'user', 'Secret message', task_b)
  on conflict (id) do nothing;

  insert into public.task_events (task_id, user_id, status, message, progress)
  values (task_a, u_a, 'RUNNING', 'Navigating to portal', 20),
         (task_b, u_b, 'RUNNING', 'Progress for B', 40);

  insert into public.documents (id, user_id, task_id, doc_type, file_name, storage_path, size_bytes, sha256, delete_after)
  values (doc_a, u_a, task_a, 'aadhaar', 'doc_a.pdf', u_a::text || '/task_a.pdf', 1024, 'sha_a', now() + interval '1 day'),
         (doc_b, u_b, task_b, 'aadhaar', 'doc_b.pdf', u_b::text || '/task_b.pdf', 2048, 'sha_b', now() + interval '1 day')
  on conflict (id) do nothing;

  -- 9.1 Test Positive Access for User A (Authenticated)
  perform set_config('role', 'authenticated', true);
  perform set_config('request.jwt.claim.sub', u_a::text, true);
  perform set_config('request.jwt.claims', json_build_object('sub', u_a::text, 'role', 'authenticated')::text, true);

  select count(*) into v_count from public.profiles where id = u_a;
  assert v_count = 1, 'TEST 9.1 FAILED: User A cannot read own profile';

  select count(*) into v_count from public.conversations;
  assert v_count = 1, 'TEST 9.1 FAILED: User A should see only their own conversation';

  select count(*) into v_count from public.messages;
  assert v_count = 1, 'TEST 9.1 FAILED: User A should see only their own messages';

  select count(*) into v_count from public.tasks;
  assert v_count = 1, 'TEST 9.1 FAILED: User A should see only their own tasks';

  select count(*) into v_count from public.task_events;
  assert v_count = 1, 'TEST 9.1 FAILED: User A should see only their own task events';

  select count(*) into v_count from public.documents;
  assert v_count = 1, 'TEST 9.1 FAILED: User A should see only their own documents';

  -- 9.2 Test Negative Isolation: User A cannot see User B records (Zero BOLA)
  select count(*) into v_count from public.profiles where id = u_b;
  assert v_count = 0, 'TEST 9.2 FAILED: User A was able to read User B profile';

  select count(*) into v_count from public.conversations where id = conv_b;
  assert v_count = 0, 'TEST 9.2 FAILED: User A was able to read User B conversation';

  select count(*) into v_count from public.messages where id = msg_b;
  assert v_count = 0, 'TEST 9.2 FAILED: User A was able to read User B message';

  select count(*) into v_count from public.tasks where id = task_b;
  assert v_count = 0, 'TEST 9.2 FAILED: User A was able to read User B task';

  select count(*) into v_count from public.documents where id = doc_b;
  assert v_count = 0, 'TEST 9.2 FAILED: User A was able to read User B document';

  -- 9.3 Test Negative Write: Client cannot insert directly into messages table
  failed := false;
  begin
    insert into public.messages (conversation_id, user_id, role, content)
    values (conv_a, u_a, 'assistant', 'Forged message');
  exception when insufficient_privilege or check_violation then
    failed := true;
  end;
  assert failed, 'TEST 9.3 FAILED: Client was able to insert into messages table directly';

  -- 9.4 Test Negative Write: Client cannot insert directly into tasks table
  failed := false;
  begin
    insert into public.tasks (user_id, workflow, idempotency_key, status)
    values (u_a, 'aadhaar_download', 'forged-task', 'COMPLETED');
  exception when insufficient_privilege or check_violation then
    failed := true;
  end;
  assert failed, 'TEST 9.4 FAILED: Client was able to insert into tasks table directly';

  -- 9.5 Test Negative Write: Client cannot insert into task_events table
  failed := false;
  begin
    insert into public.task_events (task_id, user_id, status, message, progress)
    values (task_a, u_a, 'COMPLETED', 'Forged event', 100);
  exception when insufficient_privilege or check_violation then
    failed := true;
  end;
  assert failed, 'TEST 9.5 FAILED: Client was able to insert into task_events table directly';

  -- 9.6 Test Negative Write: Client cannot insert into documents table
  failed := false;
  begin
    insert into public.documents (user_id, task_id, doc_type, file_name, storage_path, size_bytes, sha256, delete_after)
    values (u_a, task_a, 'aadhaar', 'forged.pdf', u_a::text || '/forged.pdf', 1024, 'sha', now() + interval '1 day');
  exception when insufficient_privilege or check_violation then
    failed := true;
  end;
  assert failed, 'TEST 9.6 FAILED: Client was able to insert into documents table directly';

  -- 9.7 Test Anonymous Access Blocked
  perform set_config('role', 'anon', true);
  perform set_config('request.jwt.claim.sub', '', true);
  perform set_config('request.jwt.claims', '{}', true);

  select count(*) into v_count from public.profiles;
  assert v_count = 0, 'TEST 9.7 FAILED: Anon was able to read profiles';

  select count(*) into v_count from public.tasks;
  assert v_count = 0, 'TEST 9.7 FAILED: Anon was able to read tasks';

  -- Reset role to postgres
  perform set_config('role', 'postgres', true);
  raise notice 'TEST 9 PASSED: All RLS policies and positive/negative access rules verified.';
end $$;

-- ============================================================================
-- TEST 10: Storage Bucket & Storage RLS Policies
-- ============================================================================
do $$
begin
  -- 10.1 Verify bucket existence and private configuration
  assert exists (
    select 1 from storage.buckets
    where id = 'documents' and public = false and file_size_limit = 10485760
  ), 'TEST 10.1 FAILED: Storage bucket documents configuration mismatch';

  -- 10.2 Verify RLS on storage.objects
  assert exists (
    select 1 from pg_tables
    where schemaname = 'storage' and tablename = 'objects' and rowsecurity = true
  ), 'TEST 10.2 FAILED: RLS not enabled on storage.objects';

  -- 10.3 Verify read own files policy exists
  assert exists (
    select 1 from pg_policies
    where schemaname = 'storage' and tablename = 'objects'
      and policyname = 'read own files' and cmd = 'SELECT'
  ), 'TEST 10.3 FAILED: Policy read own files missing on storage.objects';

  -- 10.4 Verify no write policies for authenticated or anon on storage.objects
  assert not exists (
    select 1 from pg_policies
    where schemaname = 'storage' and tablename = 'objects'
      and cmd in ('INSERT', 'UPDATE', 'DELETE')
      and ('authenticated' = any(roles) or 'anon' = any(roles))
  ), 'TEST 10.4 FAILED: Client write policies should not exist on storage.objects';

  raise notice 'TEST 10 PASSED: Storage bucket and storage RLS verified.';
end $$;

-- ============================================================================
-- TEST 11: Realtime Publications
-- ============================================================================
do $$
begin
  assert exists (
    select 1 from pg_publication where pubname = 'supabase_realtime'
  ), 'TEST 11.1 FAILED: Publication supabase_realtime does not exist';

  assert exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'tasks'
  ), 'TEST 11.2 FAILED: tasks not member of supabase_realtime';

  assert exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'task_events'
  ), 'TEST 11.3 FAILED: task_events not member of supabase_realtime';

  assert exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'messages'
  ), 'TEST 11.4 FAILED: messages not member of supabase_realtime';

  raise notice 'TEST 11 PASSED: Supabase Realtime publications verified.';
end $$;

rollback; -- Clean rollback of test execution
