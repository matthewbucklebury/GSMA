# GSMA Tower Ownership Data Platform

A data platform for tracking mobile-infrastructure assets — who owns how many
sites in each country — built from the files in this repository:

- `League Table.xlsx` — global towerco league table (+ customer/anchor-tenant table)
- `MENA guide[1].pdf`, `LATAM guide[1].pdf`, `Europe guide[1].pdf`,
  `Asia guide[1].pdf`, `Africa guide[1].pdf` — TowerXchange country-by-country
  regional guides, whose per-country ownership data is presented as pie charts.

> **Scope note (2026-07-06).** This repository is the **baseline**: a clean,
> presentable read-out of the guides + league table with manual data entry.
> The multi-source ingest layer (ANFR, FCC ASR, OpenCelliD) and everything
> built on top of it moved to the `tower-market-intelligence` platform repo,
> seeded from this repo's history at commit `9a70acd`. See
> `docs/fork_plan.md` for the split and each fork's workload.

## Quick start

```bash
python3 app/server.py            # open http://localhost:8000
```

No dependencies are needed to run the explorer — the server is Python stdlib
only and the SQLite database (`data/gsma.db`) is committed.

## What the explorer offers

| View | What it does |
|---|---|
| **Towerco league** | Sortable league table of tower ownership: rank, towers, business model, owners, footprint, per-row *last updated* quarter tags, and a cross-check column showing the sum of that company's per-country counts from the guides. |
| **MNOs** | The MNO analogue: markets each operator is active in (an MNO can be a tenant without owning sites), towers it owns per the guides, and which towercos list it as a public anchor tenant. |
| **Countries** | Country-level stats: estimated total towers, sum of tracked owners, towerco-owned share, largest owner, SIMs per tower. |
| **Map** | World choropleth (total towers, towerco share, owner count, SIMs per tower). Click a country to open its detail panel. |
| **Explore & compare** | Comparison builder: pick up to 8 countries or companies, view stacked ownership breakdowns, totals, shares — chart or table view. |
| **Data entry** | Input and override data. Each submission records one metric (partial updates are natural), tagged with year+quarter (or *unknown*), source and confidence. Overrides never destroy extracted history and can be removed. |
| **Detail panels** | Clicking any company or country pulls out its full profile: holdings, footprint, tenants, MNO markets, and the complete observation history. |

**Time series:** every fact is an *observation* keyed to a year+quarter (or
"unknown" when the source gives none). The header's **View as of** selector
replays the dataset at any earlier period, so future data snapshots and manual
updates accumulate into a queryable history rather than overwriting.

## Architecture

```
League Table.xlsx ─┐
5 regional PDFs  ──┤→ data/extraction/extract_pies.py → pages_raw.json
                   │→ data/build_dataset.py (+ overrides_curated.json) → dataset.json
                   │→ data/build_db.py → data/gsma.db  (SQLite = callable SQL layer)
                   └→ app/server.py (stdlib HTTP + JSON API) → app/static/ (UI)
```

- **`data/extraction/extract_pies.py`** parses the PDFs with PyMuPDF: it reads
  each country's stats block and extracts the ownership pie charts by matching
  legend swatch colours to slice fills, computing each slice's angular interval
  from its vector path, and assigning the printed value labels to slices by
  angle, radial band, and value/angle fraction consistency. Every assignment is
  verified against the slice's angular fraction and the stated country total.
- **`data/overrides_curated.json`** documents the charts automation cannot
  fully resolve (numbered legends, two-ring ground/rooftop charts, duplicated
  legend colours, sub-degree sliver fans) with the manually verified values and
  the reasoning for each.
- **`data/build_dataset.py`** consolidates both sources: normalises countries
  (ISO3, region), tags every record with its as-of period, and classifies each
  owner as towerco / MNO / JV infraco / broadcaster / government / aggregate.
- **`data/build_db.py`** loads everything into SQLite. Re-running it rebuilds
  the base data while preserving user-entered overrides.
- **`app/server.py`** exposes the JSON API (league, MNOs, countries, map,
  compare, search, observations CRUD) and serves the static front end. All
  chart/map libraries are vendored, so the app works offline.

## Rebuilding the database from the source files

```bash
pip install -r requirements.txt        # openpyxl + pymupdf (extraction only)
python3 data/extraction/extract_pies.py data/extraction/pages_raw.json
python3 data/build_dataset.py
python3 data/build_db.py               # preserves manual overrides
```

## Data quality & caveats

- **Gaps are expected.** Tower counts are estimates; companies and countries
  are missing; no count is guaranteed complete. Some markets have stats but no
  ownership chart (Bahrain, Lebanon, UAE, Malawi, Namibia, Niger, Rwanda);
  Mongolia and South Korea publish MNO market share (%) rather than counts.
- Several source pies are **not drawn to scale**; printed values were kept when
  they sum to the stated country totals, and such rows carry a note.
- Values inferred as residuals or read as "+N" approximations are flagged
  `inferred` / `approx` and shown as such in the UI.
- The league table (per-row quarter tags) and the guides (publication quarter)
  are different vintages, so a company's global count can legitimately differ
  from the sum of its per-country counts; the league view shows both
  side-by-side as a cross-check.

See the **About the data** tab in the app for the full methodology notes.
