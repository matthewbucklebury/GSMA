# Tower Explorer ingest layer

Common infrastructure for source adapters, per the POC brief
(`Tower_Explorer_POC_Ingest_Brief.docx`, sections 4 and 6). All four adapters are
delivered: the stub (session 1), ANFR France (session 2), FCC ASR United
States (session 3) and OpenCelliD market aggregates (session 4) — see each
adapter's `config.yaml` for what was verified against the live source, and
`docs/session_0N_handover.md` for divergences and open items. Session 5
(Explorer surfacing of the three layers) remains.

## Usage

```bash
python -m ingest anfr --all     --date 2026-07-04   # full ANFR run (downloads ~65 MB)
python -m ingest fcc_asr --all  --date 2026-07-04   # full FCC ASR run (downloads ~37 MB)
python -m ingest opencellid --all --date 2026-07-04  # needs OPENCELLID_API_KEY exported
python -m ingest stub fetch     --date 2026-07-01   # single stage
python -m ingest stub validate  --date 2026-07-01
python -m ingest stub normalise --date 2026-07-01
python -m ingest stub emit      --date 2026-07-01
python -m ingest stub --all     --date 2026-07-01   # full pipeline
```

`--date` defaults to today. Re-running a stage for the same date overwrites
that date's output and nothing else (idempotent by snapshot date).

## The four-stage contract

| Stage | Responsibility | Output |
|---|---|---|
| fetch | Pull raw data, no transformation | `data/raw/{source}/{date}/` |
| validate | Mandatory columns, row-count delta vs previous snapshot, source checks | pass/fail + `data/run_logs/{source}/{date}.validation.json` |
| normalise | Map raw to the standard model; quarantine unmappable rows | parquet in `data/normalised/{source}/{date}/`, rejects in `data/quarantine/{source}/{date}/` |
| emit | Write the store, stamp `source_manifest.last_ingest`, write the run log | `data/ingest.db` + `data/run_logs/{source}/{date}.json` |

Raw snapshots are retained: normalisation bugs are fixed by re-running
`normalise` on stored raw data, never by re-fetching.

## Writing an adapter

Subclass `ingest.common.adapter.BaseAdapter`, declare `source`, `licence`,
`refresh_cadence`, `coverage` (`{ISO2: (status, note)}` — every other ISO
market is written to `source_manifest` as an explicit `not_covered` row),
`mandatory_columns` and `max_row_delta_pct`, and implement `do_fetch`,
`raw_columns`, `raw_row_count`, `do_normalise`, `do_emit` (and optionally
`do_validate` for source-specific checks). Register it in
`ingest/registry.py`. `ingest/stub.py` is the worked example.

Every output row must carry `source` and `snapshot_date`; adapters write to
the three standard tables (`structures`, `market_cell_stats`,
`source_manifest`) and nothing else.

## Store

`data/ingest.db` (SQLite) holds the three tables from brief section 3. It is
deliberately a separate database from `data/gsma.db`: `data/build_db.py`
rebuilds gsma.db from scratch on every snapshot refresh and would destroy
ingested tables. Surfacing the ingest layers in the Explorer UI is brief
session 5.

## Secrets

The OpenCelliD API key is read from the `OPENCELLID_API_KEY` environment
variable via `ingest.common.secrets.get_opencellid_key()` at the moment of
use. It is never written to any file, log, manifest or config, and the test
harness asserts that nothing under the data root contains it.

## Dependencies

`requests`, `pandas`, `pyarrow`, `pyyaml` (see `requirements.txt`). These are
ingest-only: `app/server.py` remains stdlib-only, so the deployed Explorer on
Render is unaffected (its build step installs nothing).

## Tests

```bash
python -m pytest tests/ -q
```

The harness (`tests/test_ingest_common.py`) drives the stub adapter through
every shared behaviour against a temporary data root (`INGEST_DATA_ROOT`).
No test touches the network.
