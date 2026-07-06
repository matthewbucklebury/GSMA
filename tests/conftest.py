"""Shared pytest fixtures.

- `con`: SQLite connection to the Explorer snapshot database, for the legacy
  v2 checks in test_changes.py (which also still runs as a plain script).
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


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Structural guarantee that no test touches the network.

    Any socket connection to a non-loopback address fails loudly. Loopback
    stays open for the legacy explorer-API test, which skips if no local
    server is running.
    """
    import socket
    real_connect = socket.socket.connect

    def guarded(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, (bytes, bytearray)):
            host = host.decode(errors="replace")
        if isinstance(host, str) and host not in ("127.0.0.1", "::1", "localhost"):
            raise RuntimeError(f"test attempted network access to {host!r}; "
                               f"tests must run offline")
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded)
