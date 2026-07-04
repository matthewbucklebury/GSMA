"""OpenCelliD adapter tests (brief session 4). Offline.

The fixture is a format-faithful synthetic export (the API key was not
available in the build environment, so no real extract could be committed;
column layout verified against the OpenCelliD wiki). It deliberately
CONTAINS coordinates so the tests can prove they never survive
normalisation — the central design requirement of this adapter.
"""
import gzip
import shutil
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from ingest.common import paths
from ingest.common.adapter import ValidationFailure
from ingest.common.manifest import coverage_for
from ingest.common.secrets import MissingSecretError
from ingest.opencellid.adapter import OpenCellIdAdapter

FIXTURE = Path(__file__).parent / "fixtures" / "opencellid" / "cell_towers.csv.gz"
DATE = "2026-07-01"
# distinctive coordinate substrings present in the fixture
SENTINEL_COORDS = (b"48.8566", b"52.5200", b"33.7490", b"-1.2921", b"2.3522")


def place_fixture(date=DATE):
    raw = paths.raw_dir("opencellid", date)
    raw.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE, raw / "cell_towers.csv.gz")
    return raw


def run_pipeline(date=DATE):
    a = OpenCellIdAdapter(date)
    a.validate()
    counts = a.normalise()
    written = a.emit()
    return a, counts, written


def test_market_stats_aggregation(ingest_root):
    place_fixture()
    a, counts, written = run_pipeline()
    # 7 mapped (mcc,net,radio) groups + 1 unknown-MCC group quarantined
    assert counts["rows_normalised"] == 7
    assert counts["rows_quarantined"] == 1
    assert written == 7
    df = pd.read_parquet(
        paths.normalised_dir("opencellid", DATE) / "market_cell_stats.parquet")
    fr_lte = df[(df.mcc == 208) & (df.mnc == 1) & (df.radio == "LTE")].iloc[0]
    assert fr_lte["country_iso2"] == "FR"
    assert fr_lte["operator_name"] == "Orange"
    assert fr_lte["cell_count"] == 40
    assert fr_lte["sample_count"] == 200          # 40 cells x 5 samples
    assert fr_lte["latest_update"] == "2025-06-15"  # unix 1750000000
    us = df[(df.mcc == 310) & (df.radio == "LTE")].iloc[0]
    assert us["country_iso2"] == "US" and "AT&T" in us["operator_name"]
    assert set(df["radio"]) <= {"GSM", "UMTS", "LTE", "NR", "CDMA"}
    assert (df["source"] == "opencellid").all()
    assert (df["snapshot_date"] == DATE).all()


def test_no_coordinates_survive_anywhere(ingest_root):
    """The brief's explicit exclusion: the raw file contains coordinates and
    nothing else may. Checks column names in every output and scans every
    non-raw byte for the fixture's sentinel coordinate values."""
    place_fixture()
    run_pipeline()
    # raw genuinely contains them (otherwise this test proves nothing)
    with gzip.open(paths.raw_dir("opencellid", DATE) / "cell_towers.csv.gz", "rb") as f:
        raw_bytes = f.read()
    assert all(s in raw_bytes for s in SENTINEL_COORDS)
    # parquet: no lon/lat columns
    df = pd.read_parquet(
        paths.normalised_dir("opencellid", DATE) / "market_cell_stats.parquet")
    assert not ({"lon", "lat", "longitude", "latitude"} & set(df.columns))
    # store: no coordinate columns in market_cell_stats
    con = sqlite3.connect(paths.store_path())
    cols = [r[1] for r in con.execute("PRAGMA table_info(market_cell_stats)")]
    assert not ({"lon", "lat"} & set(cols))
    con.close()
    # every non-raw artefact is coordinate-free byte-wise
    root = Path(str(ingest_root))
    offenders = []
    for p in root.rglob("*"):
        if not p.is_file() or "raw" in p.parts:
            continue
        data = p.read_bytes()
        if any(s in data for s in SENTINEL_COORDS):
            offenders.append(p)
    assert not offenders, f"coordinates leaked into: {offenders}"


def test_unknown_mcc_quarantined_with_reason(ingest_root):
    place_fixture()
    run_pipeline()
    q = pd.read_csv(paths.quarantine_dir("opencellid", DATE) / "unmapped_mcc.csv")
    assert len(q) == 1 and q.iloc[0]["mcc"] == 999
    assert "not in the committed mcc_country lookup" in q.iloc[0]["quarantine_reason"]


def test_manifest_datadriven_partial_coverage(ingest_root):
    place_fixture()
    run_pipeline()
    con = sqlite3.connect(paths.store_path())
    con.row_factory = sqlite3.Row
    for iso in ("FR", "DE", "US", "KE"):
        row = coverage_for(con, "opencellid", iso)
        assert row["coverage_status"] == "covered_partial"
        assert "Crowdsourced" in row["coverage_note"]
        assert "CC BY-SA" in row["coverage_note"]
    # market with no cells in the export -> explicit not_covered
    assert coverage_for(con, "opencellid", "VA")["coverage_status"] == "not_covered"
    con.close()


def test_fetch_requires_env_key_and_never_persists_it(ingest_root, monkeypatch):
    monkeypatch.delenv("OPENCELLID_API_KEY", raising=False)
    a = OpenCellIdAdapter(DATE)
    with pytest.raises((MissingSecretError, Exception), match="OPENCELLID_API_KEY"):
        a.fetch()
    # with a key set, run the offline pipeline and prove the key reaches no file
    secret = "ocid-test-key-4419"
    monkeypatch.setenv("OPENCELLID_API_KEY", secret)
    place_fixture()
    run_pipeline()
    root = Path(str(ingest_root))
    offenders = [p for p in root.rglob("*")
                 if p.is_file() and secret.encode() in p.read_bytes()]
    assert not offenders, f"API key leaked into: {offenders}"


def test_validate_fails_on_missing_column(ingest_root):
    raw = paths.raw_dir("opencellid", DATE)
    raw.mkdir(parents=True, exist_ok=True)
    with gzip.open(FIXTURE, "rt") as f:
        lines = f.read().splitlines()
    lines[0] = lines[0].replace(",updated", ",upd8ed")   # header drift
    with gzip.open(raw / "cell_towers.csv.gz", "wt") as f:
        f.write("\n".join(lines) + "\n")
    with pytest.raises(ValidationFailure, match="mandatory_columns"):
        OpenCellIdAdapter(DATE).validate()


def test_idempotent_rerun(ingest_root):
    place_fixture()
    run_pipeline()
    run_pipeline()
    con = sqlite3.connect(paths.store_path())
    n = con.execute("SELECT COUNT(*) FROM market_cell_stats WHERE source='opencellid'"
                    ).fetchone()[0]
    assert n == 7
    con.close()
