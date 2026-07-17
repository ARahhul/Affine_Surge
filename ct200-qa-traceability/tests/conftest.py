"""Shared pytest fixtures — real TestClient backed by temp-file SQLite."""

import os
import sys
import tempfile

import pytest

# Must set DATABASE_URL before ct200.main is imported for the first time
_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_db_file.name}"
os.environ.setdefault("NVIDIA_NIM_API_KEY", "test-key")
os.environ.setdefault("AUTH_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fastapi.testclient import TestClient  # noqa: E402

import ct200.main as _main_module  # noqa: E402
import ct200.database as _db_module  # noqa: E402
from ct200.database import Base  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

# Create a single engine + session factory for the entire test session
_TEST_DB_URL = f"sqlite:///{_db_file.name}"
_test_engine = create_engine(_TEST_DB_URL)
Base.metadata.create_all(_test_engine)

# Create FTS5 table (mirrors what get_engine does)
with _test_engine.connect() as _conn:
    _conn.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5("
            "node_id UNINDEXED, heading, body, "
            "tokenize='porter unicode61')"
        )
    )
    _conn.commit()

_TestSessionLocal = sessionmaker(bind=_test_engine)


def _test_get_session(database_url=None):
    """Always return a session bound to our test engine."""
    return _TestSessionLocal()


# Monkey-patch get_session so all route handlers use our test DB
_db_module.get_session = _test_get_session
_main_module.get_session = _test_get_session
_main_module.DATABASE_URL = _TEST_DB_URL


@pytest.fixture(scope="session")
def client():
    """Session-scoped TestClient — one app instance, one SQLite file."""
    with TestClient(_main_module.app, raise_server_exceptions=False) as c:
        yield c


# --- Real PDF paths ---
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
PDF_V1 = os.path.join(_REPO_ROOT, "pdf", "ct200_manual.pdf")
PDF_V2 = os.path.join(_REPO_ROOT, "pdf", "ct200_manual_v2.pdf")

skip_if_no_pdf = pytest.mark.skipif(
    not os.path.exists(PDF_V1),
    reason="ct200_manual.pdf not found in pdf/ — skipping real-data tests",
)


@pytest.fixture(scope="session")
def ingest_v1(client):
    """POST the real ct200_manual.pdf once for the whole test session."""
    with open(PDF_V1, "rb") as f:
        resp = client.post(
            "/api/v1/documents",
            files={"file": ("ct200_manual.pdf", f, "application/pdf")},
        )
    assert resp.status_code == 201, f"v1 ingest failed: {resp.text}"
    return resp.json()


@pytest.fixture(scope="session")
def ingest_v2(client, ingest_v1):
    """POST ct200_manual_v2.pdf — same document name, creates version 2."""
    with open(PDF_V2, "rb") as f:
        resp = client.post(
            "/api/v1/documents",
            files={"file": ("ct200_manual.pdf", f, "application/pdf")},
        )
    assert resp.status_code in (200, 201), f"v2 ingest failed: {resp.text}"
    return resp.json()
