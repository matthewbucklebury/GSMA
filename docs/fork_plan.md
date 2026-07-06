# Fork plan — baseline / platform split (session 7)

Date: 2026-07-06 · Status: agreed with the owner; step 0 + A1 executed this
session.

## Why

The build was getting heavy: this repo carried two products under one roof —
the presentable guides/league-table explorer (`gsma.db`, ~400 KB) and the
growing multi-source ingest layer (`ingest.db`, 65 MB and climbing). The
project forks into two legs:

1. **Baseline (this repo).** A cleaned-up, straightforward read-out of the
   TowerXchange guides + League Table: towercos, MNOs, countries, site counts
   and stats. A proof of concept of a static representation of the data and a
   time saver on data entry. Presentable as a baseline model.
2. **Platform (new repo: `tower-market-intelligence`).** Takes the simplified
   layer and builds up: the purpose becomes **identifying gaps in market
   knowledge in the moment and through time**. Who owns what and who does
   business with whom is partially known; the platform ranks where boot-leather
   research is worth spending — the last 20% of market information that
   provides 80% of the value.

## Decisions (owner, 2026-07-06)

- **Topology: two repos.** This repo is trimmed to the baseline; a new repo
  hosts the platform, seeded as a full-history copy of this repo at the fork
  point. The platform consumes the baseline's `dataset.json` at a version tag
  as one source among several — no runtime coupling.
- **Ingest layer moves to the platform only.** The baseline is stripped of
  `ingest/`, `ingest.db`, the ingest tests, the "Site registers (POC)" tab
  and the `/api/ingest/*` endpoints.
- **Baseline form: cleaned live explorer** (league, MNOs, countries, map,
  compare, data entry) on its stable Render URL.
- **Platform focus accounts: global pureplays + MNO captives/carve-outs**
  (American Tower, Cellnex, SBA, IHS, Helios, Phoenix Tower; Vantage, TOTEM,
  Deutsche Funkturm/GD Towers, Indus, …) — the entity spine starts from
  roughly these twelve.

## Fork point

**Commit `9a70acd`** ("Merge pull request #9" — first real OpenCelliD
ingest). The platform repo is seeded from exactly this commit with full
history. Everything the baseline deletes (ingest layer, brief, handovers,
source register, ingest.db) lives on there and in this repo's history.
A local annotated tag `fork-base` marks it; the hosting proxy does not accept
tag pushes, so the SHA recorded here is the durable reference.

## Workload

### Fork A — baseline (this repo) · ~2–3 sessions

- **A1 — Trim (this session).** Delete `ingest/`, `data/ingest.db`, ingest
  tests + fixtures, the Site registers tab, `/api/ingest/*` endpoints and
  routing; slim `requirements.txt` back to extraction-only; `.gitignore`
  cleanup; README rewrite around the baseline story; move the ingest brief,
  session 2–6 handovers and the source register to the platform repo (i.e.
  delete here — preserved there and in history); drop stray artefacts
  (`gsma.db.backup-*`).
- **A2 — Data cleanup pass.** Reconcile league-table vs guide-sum
  discrepancies account by account (the cross-check column exposes them);
  normalise entity-name aliases; verify every `overrides_curated.json` entry;
  number formatting and vintage-tag consistency; tighten the About tab into a
  walkthrough-ready methodology story.
- **A3 — Presentation polish + freeze.** Demo-path polish, stable Render
  deploy, tag `v1.0-baseline`, freeze policy: data corrections and manual
  entry only; features go to the platform.

### Fork B — platform (`tower-market-intelligence`) · ~6–8 sessions to first gap report

- **B0 — Bootstrap.** Owner creates the GitHub repo (the session's GitHub
  integration cannot create repositories) and a second Render service, and
  sets `OPENCELLID_API_KEY` there. Seed with full history from fork point
  `9a70acd`; then a reverse trim (drop the baseline-only extraction/UI or
  keep temporarily as scaffolding — decide at bootstrap).
- **B1 — Entity spine.** Canonical account registry for the focus accounts:
  entity IDs, aliases, markets, and relationships as first-class data
  (owner-of, anchor-tenant-of, JV-partner), every edge carrying an as-of
  period and a source.
- **B2 — Claims model.** Generalise the observations time-series into
  source-tagged claims: (entity, market, metric, value, as-of, source,
  confidence). Guides, league table, ANFR, FCC ASR, OpenCelliD and manual
  field research all land in one comparable structure. The load-bearing
  refactor — everything after it is views over claims.
- **B3 — Gap & conflict engine.** Per account × market: what is known, from
  which sources, how stale, where sources disagree. Gap classes: no data;
  stale (>N quarters); single-source/uncorroborated; conflicting claims;
  coverage mismatch (account claims presence, registers show nothing — or
  vice versa). Output: a ranked boot-leather list.
- **B4 — Change detection through time.** Snapshot diffing per source and
  per account (the ingest layer already snapshots by date); quarterly vintage
  comparison for guide/league data; a "what changed since I last looked"
  view.
- **B5 — Visualisation.** Account dossiers (holdings, tenancy graph, claim
  timeline), gap heat-map by market coloured by staleness/conflict (space),
  time slider (time). The highlighting is the product: fresh-corroborated vs
  stale vs contested vs unknown.
- **B6 — New sources, incrementally.** The source register is the menu; each
  new source is an adapter writing claims. The ingest brief's standing
  antitrust guardrail — no pricing, rate-card or lease data, ever — carries
  over verbatim.

## Sequencing

B0 → A1–A3 (baseline presentable early) → B1–B3 (MVP: first gap report on
the focus accounts) → B4–B6. After B0 the forks are independent and can
interleave. (This session ran A1 before B0's push because repo creation
needs the owner; the fork point SHA makes the order safe.)

## Owner actions outstanding

1. Create `tower-market-intelligence` on GitHub (private) and add it to a
   Claude session so the full history can be pushed from fork point
   `9a70acd`.
2. Create the platform's Render service pointing at the new repo; set
   `OPENCELLID_API_KEY` in its environment.
3. Baseline Render service stays pointed at this repo's `main` — after A1 it
   serves the trimmed explorer (the Site registers tab disappears from the
   public demo until the platform's own service is live).
