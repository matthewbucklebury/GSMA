---
name: ship-task
description: Finish a baseline task the same way every time — verify green, then merge the task branch into main so Render deploys. Use at the end of any task in the GSMA baseline repo, before telling Matt it's done.
---

# Ship a task (verify → merge → deploy)

Run at the end of a task, after the work is written, so `main` only ever gets a
verified change.

## Steps (in order; stop if any fails)

1. Confirm you're on a task branch, not main: `git branch --show-current`
   (should be `task/...`; if it says `main`, run `git checkout -b task/name`
   first — it carries your changes over).
2. Commit: `git add -A && git commit -m "<short description>"`.
3. Push the branch (preserves work, no deploy): `git push -u origin task/name`.
4. Tests must be green: `python -m pytest tests/ -q` → `4 passed, 1 skipped`
   (the 1 skip is always expected).
5. Smoke test must PASS: `python3 scripts/smoke_test.py` →
   `RESULT: PASS — all 10 checks passed.`
6. Do the task brief's own verification steps.
7. Only if all green, merge & deploy:
   `git checkout main && git pull && git merge task/name && git push`.
8. Update `docs/HANDOVER.md` (status + dated session-log entry + next task),
   then `git commit` and `git push` it.
9. Tell Matt in plain English: what changed, that the smoke test passed, how to
   verify on the site, and what (if anything) is next.

If a merge conflict appears, stop and tell Matt to start a fresh session on the
task rather than forcing it.
