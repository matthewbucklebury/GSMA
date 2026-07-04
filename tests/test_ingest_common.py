"""Test harness for the ingest common layer (brief section 8, session 1).

Everything runs against a temporary data root (see the ingest_root fixture);
no test touches the network or the repo's real data/ directory. The stub
adapter stands in for a real source and exercises every shared behaviour:
the four-stage contract, idempotency by snapshot date, quarantine, the
validation report, delta thresholds, the source_manifest enumeration, the
JSON run log, the CLI, and the secrets rule.
"""
import json
import sqlite3

import pandas as pd
import pytest

from ingest.cli import main as cli_main
from ingest.common import paths
from ingest.common.adapter import ValidationFailure
from ingest.common.countries import ISO_MARKETS
from ingest.common.manifest import coverage_for
from ingest.common.secrets import MissingSecretError, get_opencellid_key
from ingest.stub import BAD_ROWS, FAKE_ROWS, StubAdapter

DATE = "2026-07-01"
DATE2 = "2026-07-02"


def run_all(date=DATE):
    adapter = StubAdapter(date)
    result = adapter.run_all()
    return adapter, result


# ---------------------------------------------------------------- pipeline

def test_stub_full_pipeline(ingest_root):
    adapter, result = run_all()
    assert result["rows_normalised"] == FAKE_ROWS
    assert result["rows_quarantined"] == BAD_ROWS
    assert result["rows_emitted"] == FAKE_ROWS
    # raw retained, parquet written, quarantine explains itself
    assert (paths.raw_dir("stub", DATE) / "structures.csv").exists()
    parquet = paths.normalised_dir("stub", DATE) / "structures.parquet"
    df = pd.read_parquet(parquet)
    assert set(df.columns) >= {"structure_uid", "source", "country_iso2",
                               "lat", "lon", "height_m", "owner", "operators",
                               "status", "snapshot_date", "coverage_status"}
    assert (df["source"] == "stub").all()
    assert (df["snapshot_date"] == DATE).all()
    q = pd.read_csv(paths.quarantine_dir("stub", DATE) / "structures.csv")
    assert len(q) == BAD_ROWS and "quarantine_reason" in q.columns


def test_stages_are_separately_runnable_and_ordered(ingest_root):
    a = StubAdapter(DATE)
    with pytest.raises(Exception, match="run fetch first"):
        a.validate()
    with pytest.raises(Exception, match="run fetch first"):
        a.normalise()
    with pytest.raises(Exception, match="run normalise first"):
        a.emit()
    a.fetch()
    a.validate()
    a.normalise()
    assert a.emit() == FAKE_ROWS


def test_idempotent_by_snapshot_date(ingest_root):
    run_all(DATE)
    run_all(DATE)          # same date: overwrite, no duplicates
    run_all(DATE2)         # different date: coexists
    con = sqlite3.connect(paths.store_path())
    n1 = con.execute("SELECT COUNT(*) FROM structures WHERE snapshot_date=?",
                     (DATE,)).fetchone()[0]
    n2 = con.execute("SELECT COUNT(*) FROM structures WHERE snapshot_date=?",
                     (DATE2,)).fetchone()[0]
    assert n1 == FAKE_ROWS and n2 == FAKE_ROWS
    # re-running normalise alone does not require a re-fetch
    a = StubAdapter(DATE)
    counts = a.normalise()
    assert counts["rows_normalised"] == FAKE_ROWS
    con.close()


# ---------------------------------------------------------------- manifest

def test_manifest_enumerates_every_iso_market(ingest_root):
    run_all()
    con = sqlite3.connect(paths.store_path())
    con.row_factory = sqlite3.Row
    n = con.execute("SELECT COUNT(*) FROM source_manifest WHERE source='stub'"
                    ).fetchone()[0]
    assert n == len(ISO_MARKETS)
    # a market inside the adapter's remit
    assert coverage_for(con, "stub", "FR")["coverage_status"] == "covered_full"
    # a market outside it: explicit not_covered, never silent absence
    de = coverage_for(con, "stub", "DE")
    assert de["coverage_status"] == "not_covered"
    assert "no remit" in de["coverage_note"]
    stamped = con.execute("""SELECT COUNT(*) FROM source_manifest
                             WHERE source='stub' AND last_ingest IS NOT NULL"""
                          ).fetchone()[0]
    assert stamped == len(ISO_MARKETS)
    con.close()


# ---------------------------------------------------------------- run log

def test_run_log_written_with_counts_and_deltas(ingest_root):
    run_all(DATE)
    log = json.loads((paths.run_log_dir("stub") / f"{DATE}.json").read_text())
    assert log["status"] == "ok"
    assert log["stages"]["fetch"]["rows_fetched"] == FAKE_ROWS + BAD_ROWS
    assert log["stages"]["normalise"]["rows_quarantined"] == BAD_ROWS
    assert log["stages"]["emit"]["rows_emitted"] == FAKE_ROWS
    assert log["deltas"]["previous_rows"] is None
    run_all(DATE2)   # second snapshot sees the first in its delta check
    log2 = json.loads((paths.run_log_dir("stub") / f"{DATE2}.json").read_text())
    assert log2["deltas"]["previous_rows"] == FAKE_ROWS + BAD_ROWS
    assert log2["deltas"]["delta_pct"] == 0.0


# ---------------------------------------------------------------- validation

def test_validation_fails_on_missing_column(ingest_root):
    a = StubAdapter(DATE)
    a.fetch()
    raw = paths.raw_dir("stub", DATE) / "structures.csv"
    df = pd.read_csv(raw)
    df.drop(columns=["latitude"]).to_csv(raw, index=False)  # corrupt the payload
    with pytest.raises(ValidationFailure, match="mandatory_columns"):
        StubAdapter(DATE).validate()
    report = json.loads(
        (paths.run_log_dir("stub") / f"{DATE}.validation.json").read_text())
    assert report["passed"] is False
    failed = {c["name"]: c for c in report["checks"] if not c["passed"]}
    assert "latitude" in failed["mandatory_columns"]["detail"]


def test_validation_fails_on_absurd_row_delta(ingest_root):
    run_all(DATE)
    a = StubAdapter(DATE2)
    a.fetch()
    raw = paths.raw_dir("stub", DATE2) / "structures.csv"
    df = pd.read_csv(raw)
    pd.concat([df] * 5).to_csv(raw, index=False)   # 5x rows vs previous snapshot
    with pytest.raises(ValidationFailure, match="row_count_delta"):
        StubAdapter(DATE2).validate()


# ---------------------------------------------------------------- CLI

def test_cli_single_stage_and_all(ingest_root, capsys):
    assert cli_main(["stub", "fetch", "--date", DATE]) == 0
    assert cli_main(["stub", "validate", "--date", DATE]) == 0
    assert cli_main(["stub", "normalise", "--date", DATE]) == 0
    assert cli_main(["stub", "emit", "--date", DATE]) == 0
    assert cli_main(["stub", "--all", "--date", DATE2]) == 0
    out = capsys.readouterr().out
    assert "pipeline complete" in out


def test_cli_argument_errors(ingest_root, capsys):
    assert cli_main(["stub", "--date", DATE]) == 2            # no stage, no --all
    assert cli_main(["stub", "fetch", "--all", "--date", DATE]) == 2  # both
    assert cli_main(["stub", "fetch", "--date", "01-07-2026"]) == 2   # bad date
    with pytest.raises(SystemExit):
        cli_main(["fcc_asr", "--all", "--date", DATE])        # planned, not built
    with pytest.raises(SystemExit):
        cli_main(["nonsense", "--all", "--date", DATE])       # unknown


# ---------------------------------------------------------------- secrets

def test_opencellid_key_comes_from_env_only(ingest_root, monkeypatch):
    monkeypatch.delenv("OPENCELLID_API_KEY", raising=False)
    with pytest.raises(MissingSecretError, match="OPENCELLID_API_KEY"):
        get_opencellid_key()
    monkeypatch.setenv("OPENCELLID_API_KEY", "sk-test-do-not-persist")
    assert get_opencellid_key() == "sk-test-do-not-persist"


def test_secret_never_written_to_data_root(ingest_root, monkeypatch):
    """Run the whole pipeline with the key set; no output file may contain it."""
    secret = "sk-test-do-not-persist-8827"
    monkeypatch.setenv("OPENCELLID_API_KEY", secret)
    run_all()
    offenders = [p for p in ingest_root.rglob("*")
                 if p.is_file() and secret.encode() in p.read_bytes()]
    assert not offenders, f"secret leaked into: {offenders}"
