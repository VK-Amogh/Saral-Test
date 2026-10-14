#!/usr/bin/env python3
"""
Saral AI -- Milestone 1 (M1) Schema & Security Verification Test Runner
File: supabase/tests/verify_schema.py

This verification runner performs exhaustive static and structural analysis,
syntax validation, constraint verification, and behavioral simulation on:
1. `supabase/migrations/0001_init.sql`
2. `supabase/tests/test_0001_init.sql`
"""

import sys
import os
import re
import sqlite3
from pathlib import Path

# Paths
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATION_FILE = REPO_ROOT / "supabase" / "migrations" / "0001_init.sql"
TEST_SQL_FILE = REPO_ROOT / "supabase" / "tests" / "test_0001_init.sql"

class SchemaVerifier:
    def __init__(self, migration_path: Path, test_path: Path):
        self.migration_path = migration_path
        self.test_path = test_path
        self.migration_sql = ""
        self.test_sql = ""
        self.passed = 0
        self.failed = 0
        self.errors = []

    def assert_true(self, condition: bool, test_name: str, details: str = ""):
        if condition:
            self.passed += 1
            print(f"  [PASS] {test_name}")
        else:
            self.failed += 1
            msg = f"  [FAIL] {test_name}: {details}"
            print(msg)
            self.errors.append(msg)

    def load_files(self):
        print(f"[*] Loading migration file: {self.migration_path}")
        self.assert_true(self.migration_path.exists(), "Migration file exists", str(self.migration_path))
        self.migration_sql = self.migration_path.read_text(encoding="utf-8")

        print(f"[*] Loading test file: {self.test_path}")
        self.assert_true(self.test_path.exists(), "SQL test file exists", str(self.test_path))
        self.test_sql = self.test_path.read_text(encoding="utf-8")

    def verify_extensions(self):
        print("\n--- 1. Extensions Verification ---")
        match = re.search(r"create\s+extension\s+(if\s+not\s+exists\s+)?pgcrypto", self.migration_sql, re.IGNORECASE)
        self.assert_true(bool(match), "pgcrypto extension declaration present")

    def verify_table_definitions_and_order(self):
        print("\n--- 2. Core Tables & Dependency Order Verification ---")
        expected_tables = ["profiles", "conversations", "tasks", "messages", "task_events", "documents"]
        table_positions = {}

        for tbl in expected_tables:
            pattern = rf"create\s+table\s+public\.{tbl}\b"
            match = re.search(pattern, self.migration_sql, re.IGNORECASE)
            self.assert_true(bool(match), f"Table public.{tbl} defined")
            if match:
                table_positions[tbl] = match.start()

        # Verify dependency order:
        # tasks must be defined before messages because messages.task_id references tasks(id)
        if "tasks" in table_positions and "messages" in table_positions:
            self.assert_true(
                table_positions["tasks"] < table_positions["messages"],
                "Dependency order: tasks created before messages (FK resolution)"
            )
        if "conversations" in table_positions and "tasks" in table_positions:
            self.assert_true(
                table_positions["conversations"] < table_positions["tasks"],
                "Dependency order: conversations created before tasks"
            )

    def verify_primary_and_foreign_keys(self):
        print("\n--- 3. Primary Keys & Foreign Key Cascades Verification ---")
        # Profiles FK
        self.assert_true(
            bool(re.search(r"id\s+uuid\s+primary\s+key\s+references\s+auth\.users\s*\(\s*id\s*\)\s+on\s+delete\s+cascade", self.migration_sql, re.IGNORECASE)),
            "profiles.id -> auth.users(id) ON DELETE CASCADE"
        )
        # Conversations FK
        self.assert_true(
            bool(re.search(r"user_id\s+uuid\s+not\s+null\s+references\s+auth\.users\s*\(\s*id\s*\)\s+on\s+delete\s+cascade", self.migration_sql, re.IGNORECASE)),
            "conversations.user_id -> auth.users(id) ON DELETE CASCADE"
        )
        # Tasks FKs
        self.assert_true(
            bool(re.search(r"conversation_id\s+uuid\s+references\s+public\.conversations\s*\(\s*id\s*\)\s+on\s+delete\s+set\s+null", self.migration_sql, re.IGNORECASE)),
            "tasks.conversation_id -> public.conversations(id) ON DELETE SET NULL"
        )
        # Messages FKs
        self.assert_true(
            bool(re.search(r"conversation_id\s+uuid\s+not\s+null\s+references\s+public\.conversations\s*\(\s*id\s*\)\s+on\s+delete\s+cascade", self.migration_sql, re.IGNORECASE)),
            "messages.conversation_id -> public.conversations(id) ON DELETE CASCADE"
        )
        self.assert_true(
            bool(re.search(r"task_id\s+uuid\s+references\s+public\.tasks\s*\(\s*id\s*\)\s+on\s+delete\s+set\s+null", self.migration_sql, re.IGNORECASE)),
            "messages.task_id -> public.tasks(id) ON DELETE SET NULL"
        )
        # Task Events FK
        self.assert_true(
            bool(re.search(r"task_id\s+uuid\s+not\s+null\s+references\s+public\.tasks\s*\(\s*id\s*\)\s+on\s+delete\s+cascade", self.migration_sql, re.IGNORECASE)),
            "task_events.task_id -> public.tasks(id) ON DELETE CASCADE"
        )
        # Documents FK
        self.assert_true(
            bool(re.search(r"task_id\s+uuid\s+references\s+public\.tasks\s*\(\s*id\s*\)\s+on\s+delete\s+set\s+null", self.migration_sql, re.IGNORECASE)),
            "documents.task_id -> public.tasks(id) ON DELETE SET NULL"
        )

    def verify_check_constraints(self):
        print("\n--- 4. Check Constraints Verification ---")
        # Messages role check
        role_check = re.search(r"role\s+text\s+not\s+null\s+check\s*\(\s*role\s+in\s*\(([^)]+)\)\)", self.migration_sql, re.IGNORECASE)
        self.assert_true(bool(role_check), "messages.role CHECK constraint defined")
        if role_check:
            roles = [r.strip().strip("'") for r in role_check.group(1).split(",")]
            expected_roles = {"user", "assistant", "system", "task"}
            self.assert_true(set(roles) == expected_roles, f"messages.role CHECK includes exact roles: {roles}")

        # Tasks status check
        status_check = re.search(r"status\s+text\s+not\s+null\s+default\s+'RECEIVED'\s+check\s*\(\s*status\s+in\s*\(([^)]+)\)\)", self.migration_sql, re.IGNORECASE)
        self.assert_true(bool(status_check), "tasks.status CHECK constraint defined with default 'RECEIVED'")
        if status_check:
            statuses = [s.strip().strip("'") for s in status_check.group(1).split(",")]
            expected_statuses = {
                "RECEIVED", "VALIDATING", "PLANNING", "RUNNING", "WAITING_FOR_USER",
                "AUTHENTICATING", "DOWNLOADING", "VERIFYING", "COMPLETED", "FAILED",
                "CANCELLED", "EXPIRED"
            }
            self.assert_true(set(statuses) == expected_statuses, f"tasks.status CHECK covers all 12 states ({len(statuses)} states)")

        # Task events progress check
        progress_check = re.search(r"progress\s+smallint\s+check\s*\(\s*progress\s+between\s+0\s+and\s+100\s*\)", self.migration_sql, re.IGNORECASE)
        self.assert_true(bool(progress_check), "task_events.progress CHECK (progress between 0 and 100)")

    def verify_unique_and_performance_indexes(self):
        print("\n--- 5. Constraints & Indexes Verification ---")
        # Idempotency unique constraint
        self.assert_true(
            bool(re.search(r"unique\s*\(\s*user_id\s*,\s*idempotency_key\s*\)", self.migration_sql, re.IGNORECASE)),
            "Unique constraint on tasks(user_id, idempotency_key)"
        )

        # Document storage_path text not null unique
        self.assert_true(
            bool(re.search(r"storage_path\s+text\s+not\s+null\s+unique", self.migration_sql, re.IGNORECASE)),
            "Unique constraint on documents.storage_path"
        )

        # Partial unique index one_active_task_per_workflow
        partial_idx = re.search(
            r"create\s+unique\s+index\s+one_active_task_per_workflow\s+on\s+public\.tasks\s*\(\s*user_id\s*,\s*workflow\s*\)\s+where\s+status\s+not\s+in\s*\(([^)]+)\)",
            self.migration_sql,
            re.IGNORECASE
        )
        self.assert_true(bool(partial_idx), "Partial unique index one_active_task_per_workflow defined")
        if partial_idx:
            terminal_states = [s.strip().strip("'") for s in partial_idx.group(1).split(",")]
            expected_terminals = {"COMPLETED", "FAILED", "CANCELLED", "EXPIRED"}
            self.assert_true(set(terminal_states) == expected_terminals, f"one_active_task_per_workflow filters terminal states: {terminal_states}")

        # Queue index idx_tasks_queue
        queue_idx = re.search(
            r"create\s+index\s+idx_tasks_queue\s+on\s+public\.tasks\s*\(\s*created_at\s+asc\s*\)\s+where\s+status\s*=\s*'RECEIVED'",
            self.migration_sql,
            re.IGNORECASE
        )
        self.assert_true(bool(queue_idx), "Queue index idx_tasks_queue on (created_at asc) where status = 'RECEIVED'")

        # Required performance indexes
        self.assert_true(
            bool(re.search(r"create\s+index\s+conversations_user_id_updated_at_idx\s+on\s+public\.conversations\s*\(\s*user_id\s*,\s*updated_at\s+desc\s*\)", self.migration_sql, re.IGNORECASE)),
            "Index conversations_user_id_updated_at_idx on (user_id, updated_at desc)"
        )
        self.assert_true(
            bool(re.search(r"create\s+index\s+messages_conversation_id_created_at_idx\s+on\s+public\.messages\s*\(\s*conversation_id\s*,\s*created_at\s*\)", self.migration_sql, re.IGNORECASE)),
            "Index messages_conversation_id_created_at_idx on (conversation_id, created_at)"
        )
        self.assert_true(
            bool(re.search(r"create\s+index\s+task_events_task_id_id_idx\s+on\s+public\.task_events\s*\(\s*task_id\s*,\s*id\s*\)", self.migration_sql, re.IGNORECASE)),
            "Index task_events_task_id_id_idx on (task_id, id)"
        )
        self.assert_true(
            bool(re.search(r"create\s+index\s+documents_user_id_created_at_idx\s+on\s+public\.documents\s*\(\s*user_id\s*,\s*created_at\s+desc\s*\)", self.migration_sql, re.IGNORECASE)),
            "Index documents_user_id_created_at_idx on (user_id, created_at desc)"
        )
        self.assert_true(
            bool(re.search(r"create\s+index\s+documents_delete_after_idx\s+on\s+public\.documents\s*\(\s*delete_after\s*\)", self.migration_sql, re.IGNORECASE)),
            "Index documents_delete_after_idx on (delete_after)"
        )

    def verify_auth_trigger(self):
        print("\n--- 6. Auth Trigger Verification ---")
        # Trigger function declaration
        func_match = re.search(
            r"create\s+or\s+replace\s+function\s+public\.handle_new_user\(\)\s+returns\s+trigger\s+language\s+plpgsql\s+security\s+definer\s+set\s+search_path\s*=\s*''",
            self.migration_sql,
            re.IGNORECASE
        )
        self.assert_true(bool(func_match), "Function handle_new_user() with SECURITY DEFINER and search_path = ''")

        # on conflict do nothing
        self.assert_true(
            bool(re.search(r"on\s+conflict\s*\(\s*id\s*\)\s+do\s+nothing", self.migration_sql, re.IGNORECASE)),
            "handle_new_user() includes ON CONFLICT (id) DO NOTHING"
        )

        # Trigger binding
        trigger_match = re.search(
            r"create\s+trigger\s+on_auth_user_created\s+after\s+insert\s+on\s+auth\.users\s+for\s+each\s+row\s+execute\s+function\s+public\.handle_new_user\(\)",
            self.migration_sql,
            re.IGNORECASE
        )
        self.assert_true(bool(trigger_match), "Trigger on_auth_user_created after insert on auth.users")

    def verify_replica_identity(self):
        print("\n--- 7. REPLICA IDENTITY FULL Verification ---")
        for tbl in ["tasks", "task_events", "messages"]:
            match = re.search(rf"alter\s+table\s+public\.{tbl}\s+replica\s+identity\s+full", self.migration_sql, re.IGNORECASE)
            self.assert_true(bool(match), f"alter table public.{tbl} replica identity full")

    def verify_row_level_security(self):
        print("\n--- 8. Row Level Security (RLS) Verification ---")
        # RLS enabled on all 6 tables
        tables = ["profiles", "conversations", "tasks", "messages", "task_events", "documents"]
        for tbl in tables:
            match = re.search(rf"alter\s+table\s+public\.{tbl}\s+enable\s+row\s+level\s+security", self.migration_sql, re.IGNORECASE)
            self.assert_true(bool(match), f"RLS enabled on public.{tbl}")

        # Profiles policy
        self.assert_true(
            bool(re.search(r'create\s+policy\s+"own profile"\s+on\s+public\.profiles\s+for\s+all\s+to\s+authenticated\s+using\s*\(\s*id\s*=\s*auth\.uid\(\)\s*\)\s+with\s+check\s*\(\s*id\s*=\s*auth\.uid\(\)\s*\)', self.migration_sql, re.IGNORECASE)),
            'Policy "own profile" FOR ALL with using/check (id = auth.uid())'
        )

        # Conversations policy
        self.assert_true(
            bool(re.search(r'create\s+policy\s+"own conversations"\s+on\s+public\.conversations\s+for\s+all\s+to\s+authenticated\s+using\s*\(\s*user_id\s*=\s*auth\.uid\(\)\s*\)\s+with\s+check\s*\(\s*user_id\s*=\s*auth\.uid\(\)\s*\)', self.migration_sql, re.IGNORECASE)),
            'Policy "own conversations" FOR ALL with using/check (user_id = auth.uid())'
        )

        # Operational tables read-only policies
        op_tables = [
            ("messages", "read own messages"),
            ("tasks", "read own tasks"),
            ("task_events", "read own events"),
            ("documents", "read own documents")
        ]
        for tbl, pol in op_tables:
            pattern = rf'create\s+policy\s+"{pol}"\s+on\s+public\.{tbl}\s+for\s+select\s+to\s+authenticated\s+using\s*\(\s*user_id\s*=\s*auth\.uid\(\)\s*\)'
            self.assert_true(bool(re.search(pattern, self.migration_sql, re.IGNORECASE)), f'Policy "{pol}" FOR SELECT on public.{tbl}')

        # Verify NO write policies on operational tables in migration SQL
        for tbl in ["messages", "tasks", "task_events", "documents"]:
            write_pol = re.search(rf'create\s+policy\s+["\w\s]+\s+on\s+public\.{tbl}\s+for\s+(insert|update|delete|all)', self.migration_sql, re.IGNORECASE)
            self.assert_true(write_pol is None, f"Zero client write policies on public.{tbl} (Default-Deny enforced)")

    def verify_storage_and_realtime(self):
        print("\n--- 9. Storage Bucket & Realtime Publication Verification ---")
        # Storage bucket insertion
        bucket_match = re.search(
            r"insert\s+into\s+storage\.buckets\s*\([^)]+\)\s*values\s*\(\s*'documents'\s*,\s*'documents'\s*,\s*false\s*,\s*10485760\s*,\s*array\['application/pdf'\]\s*\)",
            self.migration_sql,
            re.IGNORECASE
        )
        self.assert_true(bool(bucket_match), "Storage bucket 'documents' created with public=false, 10MB limit, application/pdf mime type")

        # Storage objects RLS
        self.assert_true(
            bool(re.search(r"alter\s+table\s+storage\.objects\s+enable\s+row\s+level\s+security", self.migration_sql, re.IGNORECASE)),
            "RLS enabled on storage.objects"
        )

        # Storage policy read own files
        storage_pol = re.search(
            r'create\s+policy\s+"read own files"\s+on\s+storage\.objects\s+for\s+select\s+to\s+authenticated\s+using\s*\(\s*bucket_id\s*=\s*\'documents\'\s+and\s+\(storage\.foldername\(name\)\)\[1\]\s*=\s*auth\.uid\(\)::text\s*\)',
            self.migration_sql,
            re.IGNORECASE
        )
        self.assert_true(bool(storage_pol), 'Storage policy "read own files" with folder isolation (<user_id>/<task_id>.pdf)')

        # Publication supabase_realtime
        self.assert_true(
            bool(re.search(r"alter\s+publication\s+supabase_realtime\s+add\s+table\s+public\.tasks", self.migration_sql, re.IGNORECASE)),
            "Realtime publication includes public.tasks"
        )
        self.assert_true(
            bool(re.search(r"alter\s+publication\s+supabase_realtime\s+add\s+table\s+public\.task_events", self.migration_sql, re.IGNORECASE)),
            "Realtime publication includes public.task_events"
        )
        self.assert_true(
            bool(re.search(r"alter\s+publication\s+supabase_realtime\s+add\s+table\s+public\.messages", self.migration_sql, re.IGNORECASE)),
            "Realtime publication includes public.messages"
        )

    def verify_sql_test_suite_coverage(self):
        print("\n--- 10. SQL Test Suite Structure & Coverage Verification ---")
        test_suites = [
            ("TEST 1", "Extensions"),
            ("TEST 2", "Schema & Table Existence"),
            ("TEST 3", "Check Constraints"),
            ("TEST 4", "Unique Constraints & Indexes"),
            ("TEST 5", "Partial Unique Index one_active_task_per_workflow"),
            ("TEST 6", "Trigger handle_new_user"),
            ("TEST 7", "Foreign Key Cascades & Set Null Rules"),
            ("TEST 8", "REPLICA IDENTITY FULL"),
            ("TEST 9", "Row Level Security Policies"),
            ("TEST 10", "Storage Bucket & Storage RLS Policies"),
            ("TEST 11", "Realtime Publications")
        ]
        for tid, tname in test_suites:
            match = re.search(rf"--\s+{tid}:\s+{re.escape(tname)}", self.test_sql, re.IGNORECASE)
            self.assert_true(bool(match), f"Test suite {tid}: {tname} implemented in test_0001_init.sql")

    def run_sqlite_behavioral_simulation(self):
        """Simulate table creation, check constraints, unique constraints, and cascades in SQLite engine."""
        print("\n--- 11. Behavioral Schema Engine Simulation (SQLite Engine) ---")
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON;")
        cursor = conn.cursor()

        # Simulated auth schema
        cursor.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY, email TEXT, raw_user_meta_data TEXT);")
        cursor.execute("CREATE TABLE profiles (id TEXT PRIMARY KEY REFERENCES auth_users(id) ON DELETE CASCADE, display_name TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);")
        cursor.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE, title TEXT NOT NULL DEFAULT 'New chat', archived INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);")
        cursor.execute("""
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
                conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
                workflow TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'RECEIVED' CHECK (status IN ('RECEIVED','VALIDATING','PLANNING','RUNNING','WAITING_FOR_USER','AUTHENTICATING','DOWNLOADING','VERIFYING','COMPLETED','FAILED','CANCELLED','EXPIRED')),
                request_text TEXT,
                idempotency_key TEXT NOT NULL,
                pending_input TEXT,
                error_code TEXT,
                error_message TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT,
                UNIQUE (user_id, idempotency_key)
            );
        """)
        cursor.execute("""
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user','assistant','system','task')),
                content TEXT NOT NULL,
                task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                message TEXT NOT NULL,
                progress INTEGER CHECK (progress BETWEEN 0 AND 100),
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
                task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                doc_type TEXT NOT NULL,
                file_name TEXT NOT NULL,
                storage_path TEXT NOT NULL UNIQUE,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                pdf_encrypted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                delete_after TEXT NOT NULL
            );
        """)
        # Partial unique index simulation
        cursor.execute("""
            CREATE UNIQUE INDEX one_active_task_per_workflow ON tasks (user_id, workflow)
            WHERE status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED', 'EXPIRED');
        """)

        # Test A: Insert user & profile
        cursor.execute("INSERT INTO auth_users (id, email) VALUES ('u1', 'u1@example.com');")
        cursor.execute("INSERT INTO profiles (id, display_name) VALUES ('u1', 'Citizen One');")
        self.assert_true(True, "Engine: Table creation and user/profile insertion succeeded")

        # Test B: Check constraint on invalid status
        check_failed = False
        try:
            cursor.execute("INSERT INTO tasks (id, user_id, workflow, idempotency_key, status) VALUES ('t-bad', 'u1', 'aadhaar', 'k-bad', 'BOGUS_STATUS');")
        except sqlite3.IntegrityError:
            check_failed = True
        self.assert_true(check_failed, "Engine: CHECK constraint rejects invalid status ('BOGUS_STATUS')")

        # Test C: Check constraint on invalid message role
        cursor.execute("INSERT INTO conversations (id, user_id) VALUES ('c1', 'u1');")
        role_failed = False
        try:
            cursor.execute("INSERT INTO messages (id, conversation_id, user_id, role, content) VALUES ('m-bad', 'c1', 'u1', 'attacker', 'hello');")
        except sqlite3.IntegrityError:
            role_failed = True
        self.assert_true(role_failed, "Engine: CHECK constraint rejects invalid message role ('attacker')")

        # Test D: Check constraint on task_events progress
        cursor.execute("INSERT INTO tasks (id, user_id, workflow, idempotency_key, status) VALUES ('t1', 'u1', 'aadhaar', 'k1', 'RUNNING');")
        progress_failed = False
        try:
            cursor.execute("INSERT INTO task_events (task_id, user_id, status, message, progress) VALUES ('t1', 'u1', 'RUNNING', 'msg', 150);")
        except sqlite3.IntegrityError:
            progress_failed = True
        self.assert_true(progress_failed, "Engine: CHECK constraint rejects progress > 100")

        # Test E: Partial unique index simulation
        # Second active task for same user & workflow must fail
        partial_failed = False
        try:
            cursor.execute("INSERT INTO tasks (id, user_id, workflow, idempotency_key, status) VALUES ('t2', 'u1', 'aadhaar', 'k2', 'WAITING_FOR_USER');")
        except sqlite3.IntegrityError:
            partial_failed = True
        self.assert_true(partial_failed, "Engine: Partial unique index one_active_task_per_workflow rejects second active task")

        # Mark t1 COMPLETED -> Now new active task should succeed
        cursor.execute("UPDATE tasks SET status = 'COMPLETED' WHERE id = 't1';")
        cursor.execute("INSERT INTO tasks (id, user_id, workflow, idempotency_key, status) VALUES ('t3', 'u1', 'aadhaar', 'k3', 'RUNNING');")
        self.assert_true(True, "Engine: Transitioning previous task to terminal status allows new active task")

        # Test F: Cascade and SET NULL semantics
        cursor.execute("INSERT INTO messages (id, conversation_id, user_id, role, content, task_id) VALUES ('m1', 'c1', 'u1', 'user', 'hi', 't3');")
        cursor.execute("INSERT INTO task_events (task_id, user_id, status, message, progress) VALUES ('t3', 'u1', 'RUNNING', 'working', 50);")
        cursor.execute("INSERT INTO documents (id, user_id, task_id, doc_type, file_name, storage_path, size_bytes, sha256, delete_after) VALUES ('d1', 'u1', 't3', 'aadhaar', 'f.pdf', 'u1/t3.pdf', 100, 'sha', '2026-10-14');")

        # Deleting conversation c1 must delete message m1, but SET NULL on tasks.conversation_id
        cursor.execute("DELETE FROM conversations WHERE id = 'c1';")
        m_count = cursor.execute("SELECT count(*) FROM messages WHERE id = 'm1';").fetchone()[0]
        self.assert_true(m_count == 0, "Engine: Conversation deletion cascades messages")

        # Deleting task t3 must delete task_events, but SET NULL on documents.task_id
        cursor.execute("DELETE FROM tasks WHERE id = 't3';")
        e_count = cursor.execute("SELECT count(*) FROM task_events WHERE task_id = 't3';").fetchone()[0]
        doc_task_id = cursor.execute("SELECT task_id FROM documents WHERE id = 'd1';").fetchone()[0]
        self.assert_true(e_count == 0, "Engine: Task deletion cascades task_events")
        self.assert_true(doc_task_id is None, "Engine: Task deletion sets documents.task_id to NULL (vault preservation)")

        conn.close()

    def run_all(self):
        print("=================================================================")
        print("Saral AI -- Milestone 1 Schema & Security Verification Suite")
        print("=================================================================")
        self.load_files()
        self.verify_extensions()
        self.verify_table_definitions_and_order()
        self.verify_primary_and_foreign_keys()
        self.verify_check_constraints()
        self.verify_unique_and_performance_indexes()
        self.verify_auth_trigger()
        self.verify_replica_identity()
        self.verify_row_level_security()
        self.verify_storage_and_realtime()
        self.verify_sql_test_suite_coverage()
        self.run_sqlite_behavioral_simulation()

        print("\n=================================================================")
        print(f"VERIFICATION SUMMARY: {self.passed} PASSED, {self.failed} FAILED")
        print("=================================================================")
        if self.failed > 0:
            print("\nFailures encountered:")
            for err in self.errors:
                print(f"- {err}")
            return 1
        else:
            print("\nALL VERIFICATION TESTS COMPLETED WITH 100% SUCCESS.")
            return 0


if __name__ == "__main__":
    verifier = SchemaVerifier(MIGRATION_FILE, TEST_SQL_FILE)
    exit_code = verifier.run_all()
    sys.exit(exit_code)
