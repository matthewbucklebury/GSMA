# Task A3 — Presentation polish + tag a release

**Recommended model:** Sonnet (well-specified, mechanical)
**Priority:** could (nice-to-have; the app is presentable already)
**Depends on:** A2 ideally done first (so the release captures the tidied data)
**Status:** not started

---

## Objective and why it matters

Small presentation improvements so the baseline is clean to demo, then tag a
`v1.0-baseline` release so there's a named, frozen version to point people at.

## Files involved

- `app/static/index.html`, `app/static/app.js`, `app/static/style.css` — copy,
  default view, caption tweaks only.
- No database or server-logic changes.

## Step-by-step

1. `git checkout main && git pull && git checkout -b task/A3-polish`.
2. **Only make changes Matt asks for.** Ask Matt first: "Anything on the site
   you want reworded or tidied before I tag the release?" Typical safe polish:
   - Fix any typos in on-screen text.
   - Make sure the default tab and default country selection look good on first
     load.
   - Confirm the "About the data" tab reads clearly.
   Make each change small and check the site still loads after each.
3. After each change: `python3 scripts/smoke_test.py` → PASS, and open the app
   to eyeball it.
4. Merge to main per the CLAUDE.md git flow and let it deploy.
5. **Tag the release** once the live site looks right:
   ```
   git checkout main && git pull
   git tag -a v1.0-baseline -m "Baseline explorer v1.0 (guides + League Table)"
   git push origin v1.0-baseline
   ```
   NOTE: if `git push origin v1.0-baseline` fails with a proxy disconnect (a
   known quirk in these sessions), tell Matt the tag couldn't be pushed and that
   he can create the release/tag from the GitHub website instead (Releases →
   Draft a new release → tag `v1.0-baseline`). Do not force it.

## Acceptance criteria

- Only Matt-approved text/presentation changes made.
- Smoke test PASS; site looks right on the live URL.
- A `v1.0-baseline` tag exists (via git or the GitHub UI).

## How Matt verifies this

Open `tower-explorer-prototype.onrender.com` and read the pages you asked to be
polished — the wording should be fixed and the first-load view tidy. On GitHub,
the repo's Releases/Tags should show `v1.0-baseline`.

## Do NOT

- Do not change any numbers or data here (that's A2).
- Do not touch `app/static/vendor/`, the server logic, or the extraction.
- Do not restructure the UI — this is copy/polish only.

## Rollback

Not merged: `git checkout main && git branch -D task/A3-polish`.
Merged and something looks off: `git revert HEAD && git push`.
A bad tag: `git push --delete origin v1.0-baseline` (or delete it in the GitHub
UI) and re-tag.
