"""Shared pytest configuration.

The FastAPI application loads its Settings (including API keys) at import time,
so test API keys must be present in the environment BEFORE any test module
imports `media_service.api.app`. conftest.py is imported by pytest before test
modules, which makes this the correct place for that wiring.

Production credentials are never hard-coded in application code: the app reads
API_KEYS from the environment only.
"""

import os

TEST_API_KEYS = "dev-admin-key-12345:tenant-alpha,dev-admin-key-load:load_tenant"

# Override any ambient API_KEYS (e.g. from a dev container) so the suite is
# deterministic regardless of where it runs.
os.environ["API_KEYS"] = TEST_API_KEYS
os.environ.setdefault("WEBHOOK_SECRET", "test_webhook_secret_1234567890")
os.environ.setdefault("ENVIRONMENT", "development")
