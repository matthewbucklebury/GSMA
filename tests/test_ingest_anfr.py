"""ANFR adapter tests (brief session 2). All offline: fetch is never called;
the committed fixture under tests/fixtures/anfr/ is a real extract of 300
supports (447 support-station rows) plus the full reference lookups from the
July 2026 bulk export.
"""
import shutil
import sqlite3
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from ingest.anfr.adapter import AnfrAdapter, dms_to_decimal
from ingest.common import paths
from ingest.common.adapter import ValidationFailure
from ingest.common.manifest import coverage_for

FIXTURES = Path(__file__).parent / "fixtures" / "anfr"
DATE = "2026-07-01"


def place_fixture(date=DATE, mutate=None):
    """Copy the committed fixture into the (temporary) raw dir, optionally
    mutating the data zip's SUP_SUPPORT table first."""
    raw = paths.raw_dir("anfr", date)
    raw.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "etalab-ref.zip", raw / "etalab-ref.zip")
    if mutate is None:
        shutil.copy(FIXTURES / "etalab-data.zip", raw / "etalab-data.zip")
        return raw
    src = zipfile.ZipFile(FIXTURES / "etalab-data.zip")
    with zipfile.ZipFile(raw / "etalab-data.zip", "w") as out:
        for m in src.namelist():
            data = src.read(m).decode("utf-8")
            out.writestr(m, mutate(m, data))
    return raw


def run_pipeline(date=DATE):
    a = AnfrAdapter(date)
    a.validate()
    counts = a.normalise()
    written = a.emit()
    return a, counts, written


# ---------------------------------------------------------------- units

def test_dms_to_decimal():
    assert dms_to_decimal("48", "51", "24", "N") == pytest.approx(48.856667, abs=1e-5)
    assert dms_to_decimal("0", "21", "19", "W") == pytest.approx(-0.355278, abs=1e-5)
    assert dms_to_decimal("45", "0", "0", "S") == -45.0
    assert dms_to_decimal("2", "", "", "E") == 2.0          # missing mn/sc -> 0
    assert dms_to_decimal("", "10", "10", "N") is None       # no degrees
    assert dms_to_decimal("48", "61", "0", "N") is None      # minutes out of range
    assert dms_to_decimal("48", "10", "10", "X") is None     # bad direction
    assert dms_to_decimal("91", "0", "0", "N") is None       # out of bounds


# ---------------------------------------------------------------- pipeline

def test_full_pipeline_loads_france(ingest_root):
    place_fixture()
    a, counts, written = run_pipeline()
    assert counts["rows_normalised"] == 300          # one row per support
    assert counts["rows_quarantined"] == 0           # real rows all mappable
    assert written == 300
    df = pd.read_parquet(paths.normalised_dir("anfr", DATE) / "structures.parquet")
    assert (df["country_iso2"] == "FR").all()
    assert (df["source"] == "anfr").all()
    assert df["structure_uid"].str.match(r"anfr:\d+").all()
    # WGS84 sanity: France incl. overseas territories
    assert df["lat"].between(-90, 90).all() and df["lon"].between(-180, 180).all()
    assert df["lat"].between(41, 52).mean() > 0.8    # most in metropolitan France
    # operators populated as semicolon lists of distinct operators
    with_ops = df["operators"].notna()
    assert with_ops.mean() > 0.9
    some_multi = df.loc[with_ops, "operators"].str.contains(";").any()
    assert some_multi, "expected at least one support with multiple operators"
    ops = set()
    for s in df.loc[with_ops, "operators"]:
        parts = s.split(";")
        assert parts == sorted(set(parts))           # distinct + deterministic
        ops.update(parts)
    assert {"ORANGE", "BOUYGUES TELECOM"} & ops      # real French operators
    # structure_type mapped with raw retained
    assert "pylon" in set(df["structure_type"])
    assert df["structure_type"].isin(
        ["mast", "tower", "pylon", "rooftop", "water_tower", "building", "other"]).all()
    assert df.loc[df["structure_type"] == "pylon", "structure_type_raw"]\
             .str.contains("Pylône|pylône", regex=True).all()
    # status derived from station service dates
    assert set(df["status"]) <= {"active", "granted", "other"}
    assert (df["status"] == "active").mean() > 0.5
    assert (df["coverage_status"] == "covered_full").all()


def test_store_and_manifest(ingest_root):
    place_fixture()
    run_pipeline()
    con = sqlite3.connect(paths.store_path())
    con.row_factory = sqlite3.Row
    n = con.execute("""SELECT COUNT(*) FROM structures
                       WHERE source='anfr' AND country_iso2='FR'""").fetchone()[0]
    assert n == 300
    ops = con.execute("""SELECT COUNT(*) FROM structures
                         WHERE source='anfr' AND operators IS NOT NULL""").fetchone()[0]
    assert ops > 250
    assert coverage_for(con, "anfr", "FR")["coverage_status"] == "covered_full"
    de = coverage_for(con, "anfr", "DE")
    assert de["coverage_status"] == "not_covered"
    assert "remit" in de["coverage_note"]
    con.close()


def test_idempotent_rerun(ingest_root):
    place_fixture()
    run_pipeline()
    run_pipeline()   # same date again: replaced, not duplicated
    con = sqlite3.connect(paths.store_path())
    n = con.execute("SELECT COUNT(*) FROM structures WHERE source='anfr'").fetchone()[0]
    assert n == 300
    con.close()


# ---------------------------------------------------------------- quarantine

def test_bad_coordinates_are_quarantined_with_reason(ingest_root):
    def corrupt(member, text):
        if member != "SUP_SUPPORT.txt":
            return text
        lines = text.splitlines()
        # blank the latitude-degrees field of the first two data rows
        for i in (1, 2):
            parts = lines[i].split(";")
            parts[3] = ""            # COR_NB_DG_LAT
            lines[i] = ";".join(parts)
        return "\n".join(lines) + "\n"
    place_fixture(mutate=corrupt)
    a = AnfrAdapter(DATE)
    a.validate()
    counts = a.normalise()
    assert counts["rows_quarantined"] >= 1
    q = pd.read_csv(paths.quarantine_dir("anfr", DATE) / "supports.csv")
    assert (q["quarantine_reason"] == "invalid or missing DMS coordinates").all()
    assert counts["rows_normalised"] + len(set(q["SUP_ID"])) == 300


# ---------------------------------------------------------------- validation

def test_validate_fails_on_missing_table(ingest_root):
    raw = paths.raw_dir("anfr", DATE)
    raw.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "etalab-ref.zip", raw / "etalab-ref.zip")
    src = zipfile.ZipFile(FIXTURES / "etalab-data.zip")
    with zipfile.ZipFile(raw / "etalab-data.zip", "w") as out:
        for m in src.namelist():
            if m != "SUP_STATION.txt":               # drop a mandatory table
                out.writestr(m, src.read(m))
    with pytest.raises(ValidationFailure, match="data_zip_members|station_columns"):
        AnfrAdapter(DATE).validate()


def test_validate_fails_on_missing_column(ingest_root):
    def drop_col(member, text):
        if member != "SUP_SUPPORT.txt":
            return text
        lines = text.splitlines()
        idx = lines[0].split(";").index("SUP_NM_HAUT")
        return "\n".join(";".join(p for i, p in enumerate(l.split(";")) if i != idx)
                         for l in lines) + "\n"
    place_fixture(mutate=drop_col)
    with pytest.raises(ValidationFailure, match="mandatory_columns"):
        AnfrAdapter(DATE).validate()
