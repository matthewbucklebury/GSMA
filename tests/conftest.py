"""Shared pytest fixtures.

- `con`: SQLite connection to the Explorer snapshot database, for the legacy
  v2 checks in test_changes.py (which also still runs as a plain script).
- `ingest_root`: points the ingest layer at a temporary data root via
  INGEST_DATA_ROOT, so no test touches the repo's real data/ directory.
"""
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def con():
    db = REPO / "data" / "gsma.db"
    if not db.exists():
        pytest.skip("data/gsma.db not built")
    c = sqlite3.connect(db)
    yield c
    c.close()


@pytest.fixture()
def ingest_root(tmp_path, monkeypatch):
    monkeypatch.setenv("INGEST_DATA_ROOT", str(tmp_path))
    return tmp_path
