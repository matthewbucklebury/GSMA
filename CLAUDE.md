# CLAUDE.md — Tower Ownership Baseline (GSMA)

Standing context for every session in this repo. Read this, then
`docs/HANDOVER.md`, then the specific task you were asked to do.

## What this project is

The **baseline**: a clean, presentable web explorer of tower-ownership data from
the TowerXchange regional guides and the League Table spreadsheet — who owns how
many towers in each country. It is **essentially finished and frozen**. Most
active development happens in the *other* repo, `tower-market-intelligence` (the
platform), which builds a gap-finder on top of this data. See `docs/fork_plan.md`.

Only work in this repo for: data corrections, small presentation polish, or the
two remaining tasks in `docs/HANDOVER.md`.

## Architecture in a paragraph

Python **stdlib-only** HTTP server (`app/server.py`) serves a vanilla-JS front
end (`app/static/`) over one committed SQLite database, `data/gsma.db`
(companies, countries, an observations time-series, ownership/tenancy tables).
The DB is built offline from `League Table.xlsx` + five TowerXchange PDFs by
`data/extraction/extract_pies.py` → `data/build_dataset.py` → `data/build_db.py`.
The server has no runtime dependencies. Pushing to `main` auto-deploys to Render
(`tower-explorer-prototype.onrender.com`).

## Key commands

```bash
python3 scripts/smoke_test.py        # health check — PASS/FAIL. Run before & after any change.
python -m pytest tests/ -q           # tests. Healthy = "4 passed, 1 skipped".
python3 app/server.py                # run locally, http://localhost:8000
```

The "1 skipped" test needs a local server on port 8765 and is always expected —
not a failure.

## Hard rules

1. **This repo is frozen. Do only the task you were asked to do.** No refactors,
   no "improvements".
2. **Never mark a task done until its verification passed** and you showed the
   output. Never say "it should work now" without proof.
3. **Do not touch these** unless the task is specifically about them:
   - `data/extraction/extract_pies.py` and `data/overrides_curated.json` —
     hand-tuned PDF pie-chart parsing, extremely fiddly, breaks silently.
   - `data/build_db.py` — rebuilds `data/gsma.db` from scratch; can silently
     change every number in the app.
   - `app/static/vendor/` — vendored chart/map libraries. Never edit.
4. **Keep `app/server.py` stdlib-only** — no pandas/requests in the server, or
   the Render deploy breaks (deps aren't installed there).
5. **The ingest layer is gone from this repo** (it moved to the platform). Do
   not re-add it. `/api/ingest/*` returning 404 here is correct.

## Standard git flow for a task

Render deploys `main`, so keep it healthy:
1. `git checkout main && git pull && git checkout -b task/short-name`
2. do the work; commit.
3. `python3 scripts/smoke_test.py` (must PASS) and `python -m pytest tests/ -q`.
4. only if green: `git checkout main && git merge task/short-name && git push`.

## Session-close protocol (mandatory)

Before ending any session: run the smoke test (never leave `main` broken),
update `docs/HANDOVER.md` (status + a dated session-log entry + next task),
commit and push everything, and tell Matt in plain English what changed and
whether the smoke test passed.

## Pointers

- `docs/HANDOVER.md` — state, remaining tasks, decisions, session log.
- `docs/OPERATOR-GUIDE.md` — Matt's plain-English manual.
- `docs/tasks/NN-*.md` — the two remaining task briefs.
- The platform project lives in the separate `tower-market-intelligence` repo.
