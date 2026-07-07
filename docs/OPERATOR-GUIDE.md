# Operator Guide — Baseline repo (for Matt)

This is the **baseline** repo (`GSMA`). It is basically finished and frozen. Your
main work is in the other repo, `tower-market-intelligence`, which has its own,
fuller operator guide. Read this only when you're specifically working on the
baseline site.

## The one thing to know

The baseline website is done. Don't change it unless you have a specific reason
(a data correction, or one of the two optional tasks in `docs/HANDOVER.md`).

## How to run a task here

1. Start a **fresh session** in the `GSMA` repository (not the platform repo).
2. Paste:
   ```
   Read CLAUDE.md and docs/HANDOVER.md, then do task 01
   (docs/tasks/01-data-cleanup.md). Work on a task branch, run the smoke test
   before merging, and follow the session-close protocol. Explain what you're
   doing in plain English.
   ```
   (Change `01` / the filename for the task you want.)
3. Let it work; it should end by showing you `python3 scripts/smoke_test.py`
   printing **RESULT: PASS**.
4. Verify using the task brief's "How Matt verifies this" section.

## How to tell it worked

- Claude showed **RESULT: PASS** from the smoke test.
- You did the brief's verification steps and saw what it promised.
- Claude says it committed and merged the work.

If it says "it should work now" without a PASS, it's not done — ask:
`Please run the smoke test and show me the result.`

## Warning signs — stop

- Same error tried more than twice (looping).
- Big unrequested changes ("I also refactored…").
- It wants to **rebuild the database** or edit the PDF-extraction code when the
  task wasn't about that — that risks silently changing every number. Stop it.

## When something breaks

Paste to a fresh session:
```
Read CLAUDE.md and docs/HANDOVER.md. Something went wrong. Here's the smoke test
output: [paste from: python3 scripts/smoke_test.py]. Here's what I see on screen:
[describe]. Please fix it, show me the smoke test passing, and tell me how to
verify.
```

Universal undo:
```
Please revert to the last commit where the smoke test passed on main, then run
the smoke test and show me it passes.
```

## Opus vs Sonnet

- **A2 (data cleanup)** needs judgement → use **Opus**.
- **A3 (polish + release)** is mechanical → use **Sonnet**.

## Deploying is automatic

When Claude merges to `main`, Render rebuilds the site in a few minutes. Confirm
by opening `tower-explorer-prototype.onrender.com` and checking the change.
