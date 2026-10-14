"""Pytest fixtures for Saral AI backend unit and integration test suite."""

import os
import sys

# Ensure repository root and backend directory are on sys.path
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import pytest
from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.broker import challenge_broker
from backend.app.main import app
from backend.app.queue import job_queue
from backend.app.store import store

TEST_PRIMARY_USER_ID = "usr_primary_88e36780"
TEST_PRIMARY_TOKEN = "jwt_bearer_valid_token_primary_usr_primary_88e36780"

TEST_SECONDARY_USER_ID = "usr_secondary_99f45610"
TEST_SECONDARY_TOKEN = "jwt_bearer_valid_token_secondary_usr_secondary_99f45610"

CLEANUP_SECRET = "saral_cleanup_cron_secret_auth_token_7766"
WORKER_SECRET = "saral_worker_shared_secret_secure_key_9988"


@pytest.fixture(autouse=True)
def reset_backend_state():
    """Reset store, queue, and broker state before each test execution."""
    store.reset()
    yield
    store.reset()


@pytest.fixture
def client():
    """Synchronous FastAPI TestClient."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    """Headers for authenticated primary citizen."""
    return {"Authorization": f"Bearer {TEST_PRIMARY_TOKEN}"}


@pytest.fixture
def secondary_auth_headers():
    """Headers for authenticated secondary citizen."""
    return {"Authorization": f"Bearer {TEST_SECONDARY_TOKEN}"}
