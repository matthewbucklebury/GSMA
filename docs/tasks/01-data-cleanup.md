# Task A2 — Data cleanup pass

**Recommended model:** Opus (judging which of two numbers is right needs care)
**Priority:** should (improves quality; the app works fine without it)
**Depends on:** nothing
**Status:** not started

---

## Objective and why it matters

Make the baseline data tidier and more trustworthy: reconcile the cases where a
company's global tower count (from the League Table) disagrees with the sum of
its per-country counts (from the guides), and tidy inconsistent company names.
These are the rough edges a viewer notices first.

## Background you need

The app already shows both numbers side by side (the league view has a
"cross-check" column: league total vs sum of per-country counts). Differences
are often legitimate (different publication dates), so **the goal is not to force
them equal** — it's to (a) confirm each difference is explainable, (b) fix any
that are actual data-entry errors, and (c) tidy names so the same company isn't
spelled two ways.

## Files involved

- `data/overrides_curated.json` — where manual corrections are recorded (the
  supported way to fix a value without editing extraction code).
- Read-only: `data/gsma.db` (to find the discrepancies), the app's league view.
- Do NOT edit `data/extraction/extract_pies.py` or `data/build_db.py`.

## Step-by-step

1. `git checkout main && git pull && git checkout -b task/A2-data-cleanup`.
2. **Find the biggest discrepancies.** Run:
   ```
   python3 -c "
   import sqlite3
   c=sqlite3.connect('data/gsma.db'); c.row_factory=sqlite3.Row
   for r in c.execute('''SELECT co.name, le.towers league,
       (SELECT SUM(o.value) FROM observations o WHERE o.company_id=co.id
        AND o.metric IN ('tower_count','towers','towers_owned') AND o.country_id IS NOT NULL
        AND o.deleted=0) persum
       FROM companies co JOIN league_entries le ON le.company_id=co.id
       ORDER BY le.towers DESC'''):
       lg, ps = r['league'], r['persum']
       if lg and ps and abs(lg-ps) > 0.15*max(lg,ps):
           print(f\"{r['name'][:30]:<30} league={lg:>9} sum={ps:>9}\")
   "
   ```
   This lists companies where the two numbers differ by more than 15%.
3. **For each, decide in plain terms** (this is the Opus judgement): is the
   difference explainable by different dates/coverage (leave it, it's fine), or
   is one number clearly a typo/error (fix it)? Present the list to Matt with a
   one-line plain-English recommendation for each ("leave — different dates" /
   "fix — the guide sum is missing Brazil"). **Let Matt confirm before changing
   any value.**
4. **Apply only the agreed fixes** via `data/overrides_curated.json` following
   the existing entries' format (open the file to copy the structure). Each
   override records the corrected value, the source, and a short reason.
5. **Tidy obvious name duplicates** only if clearly the same company (e.g.
   trailing spaces, "American Tower" vs "American Tower Corporation"). Record
   name fixes the same supported way; do not bulk-rename speculatively.
6. **Rebuild only if the override system requires it** — check how existing
   overrides get applied (search for where `overrides_curated.json` is read). If
   it's read live by the server, no rebuild is needed. If it's applied by
   `build_db.py`, run it and immediately verify numbers with the smoke test and
   the app. If unsure, ask Matt to prefer the no-rebuild path.
7. Verify: `python3 scripts/smoke_test.py` → PASS; `python -m pytest tests/ -q`
   → "4 passed, 1 skipped".
8. Merge to main per the CLAUDE.md git flow.

## Acceptance criteria

- A written list of the discrepancies with a recommendation for each.
- Only Matt-approved fixes applied, via the overrides file (not extraction code).
- Smoke test PASS; tests green; the app still loads.

## How Matt verifies this

1. Ask Claude to show you the discrepancy list with its plain-English
   recommendation for each. Approve or reject each in plain words.
2. After changes, open the site's **Towerco league** tab. The companies you
   agreed to fix should now show matching (or explained) numbers in the
   cross-check column. Nothing else should have moved.
3. Confirm **RESULT: PASS** from the smoke test.

## Do NOT

- Do not force league and per-country sums to match — many differences are
  legitimate. Only fix genuine errors.
- Do not edit `extract_pies.py` or `build_db.py`. Corrections go in
  `overrides_curated.json`.
- Do not bulk-rename companies. Only merge names that are obviously the same.

## Rollback

Not merged: `git checkout main && git branch -D task/A2-data-cleanup`.
Merged and a number looks wrong: `git revert HEAD && git push`, then confirm the
league tab looks normal again within ~5 minutes.
