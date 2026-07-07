#!/usr/bin/env python3
"""Smoke test — one-command health check for the baseline Tower Ownership app.

Run it any time with:

    python3 scripts/smoke_test.py

It checks that the baseline database is present and populated and that the
web server answers on every main endpoint, then prints a single PASS or FAIL
line at the end. It changes nothing — it only reads. Safe to run repeatedly.

This is the baseline repo (guides + League Table explorer). It has NO ingest
layer, so this test also confirms the /api/ingest/* endpoints are gone
(they were moved to the tower-market-intelligence platform repo).
"""
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PORT = 8798
BASE = f"http://127.0.0.1:{PORT}"

checks = []


def record(label, ok, detail=""):
    checks.append((label, ok, detail))
    mark = "ok  " if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))


def db_counts():
    import sqlite3
    print("Database:")
    g = REPO / "data" / "gsma.db"
    record("data/gsma.db exists", g.exists(), str(g) if not g.exists() else "")
    if g.exists():
        c = sqlite3.connect(g)
        companies = c.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        obs = c.execute("SELECT COUNT(*) FROM observations WHERE deleted=0").fetchone()[0]
        c.close()
        record("companies populated (expect ~707)", companies > 600, f"{companies} rows")
        record("observations populated (expect ~1065)", obs > 900, f"{obs} rows")


def http_checks():
    import os
    import json
    print(f"Starting the web server on port {PORT} …")
    env = {**os.environ, "PORT": str(PORT)}
    proc = subprocess.Popen(
        [sys.executable, "app/server.py"], cwd=REPO, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        up = False
        for _ in range(50):
            try:
                urllib.request.urlopen(BASE + "/", timeout=1)
                up = True
                break
            except Exception:
                time.sleep(0.2)
        record("server starts and answers on /", up)
        if not up:
            return

        def get(path):
            with urllib.request.urlopen(BASE + path, timeout=5) as r:
                return r.status, r.read()

        for path, key in [("/api/meta", "counts"), ("/api/league", "league"),
                          ("/api/mnos", "mnos"), ("/api/countries", "countries"),
                          ("/api/map", "rows")]:
            try:
                st, body = get(path)
                d = json.loads(body)
                record(f"GET {path}", st == 200 and key in d, f"status {st}")
            except Exception as e:
                record(f"GET {path}", False, str(e))

        # ingest endpoints must be ABSENT in the baseline (404)
        try:
            urllib.request.urlopen(BASE + "/api/ingest/meta", timeout=5)
            record("/api/ingest/meta is absent (expect 404)", False, "endpoint still present!")
        except urllib.error.HTTPError as e:
            record("/api/ingest/meta is absent (expect 404)", e.code == 404, f"status {e.code}")
        except Exception as e:
            record("/api/ingest/meta is absent (expect 404)", False, str(e))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def main():
    print("=" * 64)
    print("Tower Ownership Baseline — smoke test")
    print("=" * 64)
    db_counts()
    print()
    http_checks()
    print()
    failed = [c for c in checks if not c[1]]
    print("=" * 64)
    if failed:
        print(f"RESULT: FAIL — {len(failed)} of {len(checks)} checks failed:")
        for label, _, detail in failed:
            print(f"    - {label}" + (f" ({detail})" if detail else ""))
        print("Copy everything above this line and paste it to your Claude session.")
        sys.exit(1)
    print(f"RESULT: PASS — all {len(checks)} checks passed. The app is healthy.")
    sys.exit(0)


if __name__ == "__main__":
    main()
