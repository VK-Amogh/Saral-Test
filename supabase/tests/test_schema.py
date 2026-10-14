import sys
from pathlib import Path
from supabase.tests.verify_schema import SchemaVerifier, MIGRATION_FILE, TEST_SQL_FILE

def test_supabase_schema_and_security_migration():
    """Validates 0001_init.sql and test_0001_init.sql with full 81-point verification suite."""
    verifier = SchemaVerifier(MIGRATION_FILE, TEST_SQL_FILE)
    exit_code = verifier.run_all()
    assert exit_code == 0, f"Schema verification suite reported {verifier.failed} failure(s): {verifier.errors}"
