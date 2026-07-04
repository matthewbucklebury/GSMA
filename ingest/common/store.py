"""SQLite Explorer store for the ingest layer (brief section 3).

Three tables, and adapters write to these and nothing else:

  structures         one row per physical structure (structure-level sources)
  market_cell_stats  one row per market/operator/radio (aggregate sources)
  source_manifest    every source enumerated against every ISO market

The store is a separate database (data/ingest.db) from the Explorer snapshot
database (data/gsma.db) because data/build_db.py rebuilds gsma.db from
scratch and would destroy ingested tables. Joining the two stores in the
Explorer UI is a later session in the brief.

Writes are idempotent by (source, snapshot_date): emitting the same snapshot
again replaces that snapshot's rows and nothing else.
"""
import sqlite3
from .paths import store_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS structures (
  structure_uid TEXT NOT NULL,          -- {source}:{source_record_id}
  source TEXT NOT NULL,
  source_record_id TEXT NOT NULL,
  country_iso2 TEXT NOT NULL,
  lat REAL,
  lon REAL,
  structure_type TEXT,                  -- mast|tower|pylon|rooftop|water_tower|building|other
  structure_type_raw TEXT,
  height_m REAL,
  owner TEXT,
  operators TEXT,                       -- semicolon list where the source provides it
  status TEXT,                          -- active|dismantled|granted|other
  record_date TEXT,
  snapshot_date TEXT NOT NULL,
  coverage_status TEXT,
  PRIMARY KEY (structure_uid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_structures_market
  ON structures(country_iso2, source, snapshot_date);

CREATE TABLE IF NOT EXISTS market_cell_stats (
  country_iso2 TEXT,
  mcc INTEGER NOT NULL,
  mnc INTEGER NOT NULL,
  operator_name TEXT,
  radio TEXT NOT NULL,                  -- GSM|UMTS|LTE|NR|CDMA
  cell_count INTEGER,
  sample_count INTEGER,
  latest_update TEXT,
  snapshot_date TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'opencellid',
  PRIMARY KEY (mcc, mnc, radio, snapshot_date, source)
);

CREATE TABLE IF NOT EXISTS source_manifest (
  source TEXT NOT NULL,
  country_iso2 TEXT NOT NULL,
  coverage_status TEXT NOT NULL,        -- covered_full|covered_partial|not_covered
  coverage_note TEXT,
  licence TEXT,
  refresh_cadence TEXT,
  last_ingest TEXT,
  PRIMARY KEY (source, country_iso2)
);
"""


def connect() -> sqlite3.Connection:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def replace_snapshot_rows(con, table: str, source: str, snapshot_date: str,
                          rows: list) -> int:
    """Idempotent snapshot write: delete this source+date's rows, insert anew."""
    if table not in ("structures", "market_cell_stats"):
        raise ValueError(f"adapters may not write to table {table!r}")
    con.execute(f"DELETE FROM {table} WHERE source=? AND snapshot_date=?",
                (source, snapshot_date))
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ",".join("?" * len(cols))
    con.executemany(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
        [[r.get(c) for c in cols] for r in rows])
    return len(rows)
