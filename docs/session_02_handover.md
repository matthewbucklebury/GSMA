# Session 2 handover — ANFR adapter

Date: 2026-07-04 · Scope: brief §5.1 (ANFR reference adapter) on the
session-1 common layer. Status: **complete** — all done-when criteria met.

## What was verified against the live source, and what was pinned

The brief said to confirm the dataset and bulk route on data.anfr.fr before
writing code. Findings (all pinned in `ingest/anfr/config.yaml`):

1. **data.anfr.fr is no longer OpenDataSoft.** It has migrated to a
   Drupal/"d4c" portal. Its catalogue API
   (`/d4c/api/datasets/1.0/search/`) still answers ODS-v1-style queries and
   lists the dataset
   `donnees_sur_les_installations_radioelectriques_de_plus_de_5_wa`, but the
   dataset record exposes **no bulk file attachments** (records_count 0,
   attachments empty). The ODS API route described in the brief is gone.
2. **The bulk export lives on data.gouv.fr** under ANFR's official
   organisation account, dataset id `551d4ff3c751df55da0cd89f`
   ("Données sur les installations radioélectriques de plus de 5 watts",
   274 resources, monthly since ~2016 — a useful backfill archive).
3. **It is two ZIPs per month, not one:**
   - *Tables supports antennes émetteurs bandes {month} {year}* (~65 MB):
     `SUP_SUPPORT.txt`, `SUP_ANTENNE.txt`, `SUP_EMETTEUR.txt`,
     `SUP_BANDE.txt`, `SUP_STATION.txt`
   - *Tables de référence {month} {year}* (~5 KB): `SUP_NATURE.txt`,
     `SUP_PROPRIETAIRE.txt`, `SUP_EXPLOITANT.txt`, `SUP_TYPE_ANTENNE.txt`
4. **File format:** semicolon-delimited, UTF-8 (config keeps a latin-1
   fallback). Coordinates are DMS components (deg/min/sec + N/S/E/W) as the
   brief expected. `SUP_NM_HAUT` is metres. Verified July 2026 URLs are
   recorded in config for reference; fetch re-resolves via the stable
   data.gouv.fr API because concrete file URLs change monthly.

## Divergences from the brief

| Brief said | Found / done |
|---|---|
| OpenDataSoft API on data.anfr.fr, or bulk ZIP | Portal migrated; bulk export fetched from data.gouv.fr (ANFR's official account) |
| A single ZIP including lookup tables | Two ZIPs (data + reference); both fetched and retained in raw |
| "operators = distinct operators across that support's transmitters" | Implemented via stations: SUP_SUPPORT has one row per (support, station); station carries the operator (`ADM_ID` → `SUP_EXPLOITANT`). Every transmitter belongs to a station, so the operator set is identical, without parsing the 118 MB transmitter table |
| status normalised per source | The bulk export has **no status column**. Derived from station dates instead: any station in service → `active`; stations but none in service → `granted`; else `other`. Rule documented in `field_map.yaml` |
| — (discovered) | Resource `last_modified` on data.gouv.fr is unreliable (a "Mai 2023" file carried a newer timestamp than July 2026); the adapter selects the newest vintage by parsing the French month/year from the resource title. Titles are also inconsistent about accents ("émetteurs"/"emetteurs") — matching handles both |

## What was built

- `ingest/anfr/config.yaml` — pinned discovery (dataset id, title patterns,
  verified URLs), local raw names, ZIP member names, CSV dialect, licence
  (Licence Ouverte / Etalab, attribution ANFR), monthly cadence, 20% row
  delta threshold.
- `ingest/anfr/field_map.yaml` — every raw column mapping, mandatory
  columns for validate, the full nature→structure_type map (verified against
  the July 2026 `SUP_NATURE` table), status rules.
- `ingest/anfr/adapter.py` — `AnfrAdapter(BaseAdapter)`: streaming fetch
  with progress + `fetch_meta.json` provenance; validate (ZIP members,
  mandatory support+station columns, inherited row-delta check); normalise
  (one row per support, DMS→WGS84, lookups joined, operators as sorted
  distinct semicolon list, quarantine with reasons); emit via the common
  store with `covered_full`/FR manifest.
- `tests/fixtures/anfr/` — committed real extract: 300 supports
  (447 support-station rows, chosen to include multi-station supports) +
  full reference lookups, ~30 KB. `tests/test_ingest_anfr.py` — 7 tests, no
  network: DMS unit cases, full fixture pipeline (operators >90% populated,
  types mapped, FR bounds), store + manifest (Germany → `not_covered`),
  idempotent re-run, corrupted-fixture quarantine, two validate failures.

## Real-run results (2026-07-04, July 2026 export)

- **98,698 structures** (one per distinct support; 198,524 raw
  support-station rows; 1 row quarantined for unusable coordinates).
- **operators populated on 100.0%** of rows; e.g. `anfr:26393` — pylon,
  owner HIVORY, operators `BOUYGUES TELECOM;SFR`.
- Types: 54,812 pylon · 31,886 building · 4,546 mast · 3,943 water_tower ·
  3,065 other · 294 tower · 152 rooftop. Status: 93,461 active / 5,237 granted.
- Manifest: 250 ISO markets; FR `covered_full`, DE `not_covered` with remit
  note. Run log + validation report under `data/run_logs/anfr/`.
- pytest: 22 passed, 1 skipped (explorer-API test without a local server),
  offline, ~2.5 s.

## Open items

1. **ANFR includes French overseas territories under FR** (Réunion,
   Antilles, etc. — the register's STA codes are national). They are kept as
   `country_iso2 = FR`; the Explorer map will show points outside the
   hexagon. Decide later whether to split DOM-TOM into their own ISO codes
   (GP/MQ/RE/…) — doable from coordinates or the department code in
   `STA_NM_ANFR`'s prefix.
2. **Backfill opportunity:** the data.gouv.fr dataset retains monthly
   exports back years. The adapter's snapshot-date model supports ingesting
   historical months to build a time series; needs only a `--date`-aware
   resource selector (currently fetch always takes the newest vintage).
3. `SUP_ANTENNE`, `SUP_EMETTEUR`, `SUP_BANDE` are fetched and retained in
   raw but not parsed. They become relevant if technology/band detail per
   structure is wanted (and for the session-5 Explorer views).
4. The quarantined row count is tiny (1 of 198k); worth a periodic eyeball
   of `data/quarantine/anfr/` after each monthly run.
5. Explorer UI surfacing of the ingest store (three layers, caveats,
   not_covered rendering) remains session 5 of the brief.
