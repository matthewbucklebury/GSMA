# Session 4 handover — OpenCelliD adapter

Date: 2026-07-04 · Scope: brief §5.3 (OpenCelliD, market aggregates only) on
the common layer. Status: **complete** — the first live run (2026-07-05,
session 6) closed open items 1–2; see the addendum at the bottom.

## What was verified against the live source, and what was pinned

All pinned in `ingest/opencellid/config.yaml`:

1. **Bulk endpoint confirmed live:**
   `https://opencellid.org/ocid/downloads?token=<KEY>&type=full&file=cell_towers.csv.gz`.
   An invalid token returns **HTTP 200 with a JSON error body**
   (`{"status":"error","message":"INVALID_TOKEN"}`) rather than an HTTP
   error — fetch sniffs the first bytes and fails cleanly instead of saving
   JSON as a .gz.
2. **Export columns** verified against the OpenCelliD wiki: radio, mcc, net,
   area, cell, unit, lon, lat, range, samples, changeable, created, updated,
   averageSignal. The wiki lists radio GSM/UMTS/LTE/CDMA; NR appears in
   newer exports and is accepted.
3. **`OPENCELLID_API_KEY` was NOT set in this environment**, so the full
   download could not be exercised. Everything else — aggregation,
   lookups, coordinate-drop, manifest, store writes — is proven on a
   format-faithful fixture.

## The coordinate-drop guarantee (the point of this adapter)

- normalise loads the export with pandas `usecols` that **exclude lon/lat**
  — coordinates are never read into memory, which is as early as a drop can
  happen.
- `tests/test_ingest_opencellid.py::test_no_coordinates_survive_anywhere`
  proves it: the fixture deliberately contains sentinel coordinates
  (48.8566, 52.5200, …); the test confirms they exist in raw, then asserts
  no lon/lat columns in the parquet or the store, and **byte-scans every
  non-raw artefact** (normalised, quarantine, run logs, ingest.db) for the
  sentinels. Location-level ingest, if ever wanted, is a new adapter
  decision per the brief — there is no flag to turn it on.

## Secrets

The key is read from `OPENCELLID_API_KEY` at the moment of the request
(`ingest.common.secrets`), the recorded fetch URL is token-redacted, and
requests exceptions are re-raised with the token scrubbed (they can embed
the full URL). Tests prove a set key reaches no file under the data root,
and the CLI fails with a readable message when the key is absent.

## Lookups committed in the repo (brief §5.3/§6)

- `ingest/opencellid/mcc_country.csv` — 229 MCCs → ISO2 (modal ISO where an
  MCC spans territories).
- `ingest/opencellid/mcc_mnc_operator.csv` — 2,092 MCC+MNC → operator name
  (names joined with " / " where MVNO aggregation codes share an MNC).
- Provenance in each file header: ITU-T E.212 allocations via the public
  mcc-mnc-table compilation, fetched 2026-07-04. Spot-checked: 208/1 Orange,
  310/410 AT&T, 262/1 Telekom, MCC 639 → KE.

## What was built

- `ingest/opencellid/` — config, adapter (streaming fetch with error-body
  detection and progress; validate = full 14-column header check + row
  delta; normalise = chunked GROUP BY mcc/net/radio → cell_count /
  sample_count / latest_update with lookup joins, unknown MCCs quarantined
  with reason; emit = `market_cell_stats` + **data-driven manifest**:
  covered_partial for every market present in the export, not_covered
  otherwise, crowdsourced + CC BY-SA caveat in every coverage_note).
- Fixture: synthetic but format-faithful export (137 cells across FR/DE/US/
  KE + an unknown MCC), with hand-checkable aggregates. 7 tests.
- Registry: all three brief adapters (anfr, fcc_asr, opencellid) plus stub
  now registered; the "planned" list is empty.

## Divergences from the brief

| Brief said | Found / done |
|---|---|
| radio: GSM \| UMTS \| LTE \| NR \| CDMA | Wiki documents GSM/UMTS/LTE/CDMA; NR accepted when present. Fixture covers all five |
| "cell identifiers for distinct counting" | The full export is the cell table (one row per cell), so cell_count = row count per group; assumption documented in the adapter docstring |
| Fixtures are "small real extracts" | Not possible without the API key; the fixture is synthetic but column-exact per the wiki. Swap in a real extract cut from the first live fetch (open item 2) |

## Open items

1. ~~First live run needs `OPENCELLID_API_KEY` exported.~~ **Done 2026-07-05**
   (session 6) — see the addendum below.
2. ~~After that first run, cut ~300 real rows into the fixture.~~ **Done
   2026-07-05** — the fixture is now 283 real rows from the live export.
3. **Share-alike watch:** CC BY-SA 4.0 applies to published derivatives.
   Publishing the OpenCelliD-derived aggregates on the public Render
   Explorer with the existing CC BY-SA attribution display was approved
   (session 6), so the committed store now carries the real aggregates.
4. MCC→country is modal for the handful of MCCs spanning territories
   (e.g. 340 French Antilles); refine if territory-level accuracy matters.
5. `sample_count` sums can overflow reasonable display ranges for dense
   markets; Explorer views should format with thousands separators (session 5).

## Addendum — first live run (2026-07-05, session 6)

- `python -m ingest opencellid --all --date 2026-07-05` ran end to end in
  ~75 s: full export 114,341,518 bytes (compressed), **5,245,100 raw rows**,
  streamed fetch + chunked normalise as designed.
- Store: **1,948 `market_cell_stats` rows** (mcc,net,radio groups) across
  **192 markets**, **5,239,919 cells** total. Manifest: 192 covered_partial
  + 58 not_covered = 250 ISO markets. Top markets by cell count:
  JP 694,329 · US 667,472 · FR 390,907 · DE 244,649 · MX 200,697.
- Quarantine: 23 groups / 5,181 cells, all MCC 313/314/315 (US CBRS and
  regional allocations genuinely absent from the committed lookup) — the
  quarantine path works on real data exactly as designed.
- **Bug found and fixed on real data:** Namibia's ISO2 is `NA`, which
  `pd.read_csv` parsed as NaN when loading `mcc_country.csv`, so MCC 649
  rows landed in the store with NULL `country_iso2` and the manifest called
  the market not_covered. Fixed with `keep_default_na=False` in
  `_load_lookups`; Namibia rows are in the fixture as a regression test.
- The acceptance-criterion-3 byte-scan was re-run against the REAL run's
  artefacts (100 distinctive real coordinate sentinels sampled from the raw
  export, scanned against every non-raw file under `data/`): no coordinate
  survives in any parquet, quarantine file, run log or the store. The API
  key likewise appears in no file under `data/`.
- Fixture upgraded to real (open item 2): 283 rows, 16 groups, 8 markets
  (FR, DE, US, JP, KE, NA, MX, CA), all five radio types, two real
  unmapped-MCC-313 groups. All hand-checked expectations updated; suite
  passes offline.
