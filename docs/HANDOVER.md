# HANDOVER — Tower Ownership Baseline (GSMA)

**Last updated:** 2026-07-06 (handover session, Claude Fable)

This is the baseline repo's master doc. It is a smaller, frozen project. The
main work is in the separate `tower-market-intelligence` platform repo, which
has its own, larger HANDOVER.

---

## 1. Plain-English summary (for Matt)

This website shows tower-ownership data — who owns how many towers in each
country — read from the TowerXchange guides and the League Table spreadsheet.
It is **basically finished**. You'll rarely touch it. It's live at
`tower-explorer-prototype.onrender.com`.

There are only two optional jobs left (below). Everything else about the project
happens in the platform repo.

---

## 2. Current state — honest buckets

### ✅ Works and verified (2026-07-06)
- App runs locally and the live site returns 200. Verified.
- `python3 scripts/smoke_test.py` → "PASS — all 10 checks passed."
- `python -m pytest tests/ -q` → "4 passed, 1 skipped".
- `data/gsma.db` populated: companies 707, observations 1065, plus
  countries/league/tenancy/footprint tables. Verified by the smoke test.
- The ingest layer was correctly removed (this repo's `/api/ingest/*` → 404,
  which the smoke test confirms). It lives in the platform repo now.

### ⚠️ Probably works but unverified this session
- Rebuilding `data/gsma.db` from the PDFs (`extract_pies.py` →
  `build_dataset.py` → `build_db.py`). Worked in earlier sessions; NOT re-run
  this session (it would overwrite the DB). Treat as fragile — don't rebuild
  unless a task requires it.

### ❌ Nothing is known broken.

---

## 3. How it fits together

```
League Table.xlsx ─┐
5 TowerXchange PDFs ┼─ data/extraction/extract_pies.py
                    │  + data/build_dataset.py (+ overrides_curated.json)
                    │  + data/build_db.py            ──► data/gsma.db
                    │                                       │
                    └───────────────────────────────► app/server.py (stdlib HTTP + JSON API)
                                                            │
                                                      app/static/ (vanilla JS UI)
                                                            │
                                                      Render (auto-deploys main)
```
Changing the extraction or `build_db.py` can silently change every number in the
app — highest blast radius. Editing `app/server.py` or `app/static/` is safe and
additive. The DB is committed, so the app runs with no build step.

---

## 4. Remaining tasks (both optional; the app is fine without them)

| # | Task | Priority | Model | Brief |
|---|---|---|---|---|
| A2 | Data cleanup: reconcile league-vs-guide differences, tidy names | should | Opus | `docs/tasks/01-data-cleanup.md` |
| A3 | Presentation polish + tag a v1.0 release | could | Sonnet | `docs/tasks/02-polish-and-freeze.md` |

---

## 5. Risk register

| Risk | Why dangerous | Failure on screen | First fix |
|---|---|---|---|
| Rebuilding `gsma.db` | Can silently change all numbers | Numbers change with no clear cause | `git checkout data/gsma.db` to restore the committed DB; don't rebuild unless the task says so |
| Editing extraction / overrides | Hand-tuned; breaks quietly | Some countries' pie values wrong/missing | Only touch under A2; verify against the on-screen totals |
| Adding deps to `app/server.py` | Render installs none for the server | Live site won't boot after deploy | Keep the server stdlib-only |
| Working on `main` directly | Deploys immediately | A bad change goes live | Use a task branch; merge only after smoke test PASS |

---

## 6. Decision log

- **This repo was trimmed to the baseline** on 2026-07-06 (the ingest layer,
  the 65 MB ingest.db, and the Site registers tab were removed and moved to the
  platform repo). Rationale: `docs/fork_plan.md`.
- **The server is deliberately stdlib-only** so Render deploys need no build.
- **`data/gsma.db` is committed** so the live demo runs with no build step.

---

## 7. Session log (newest first)

### 2026-07-06 — Claude Fable — Handover pack
- Audited the repo (clean tree, no uncommitted work). Tests 4 passed / 1
  skipped; smoke test PASS; live site healthy on the trimmed build.
- Added `scripts/smoke_test.py`, `CLAUDE.md`, this `HANDOVER.md`,
  `docs/OPERATOR-GUIDE.md`, and two task briefs (A2, A3).
- **Next recommended:** nothing required. If Matt wants to improve the baseline,
  do A2 (data cleanup) with Opus. Otherwise focus on the platform repo.
