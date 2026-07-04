"""FCC ASR adapter tests (brief session 3). Offline: the committed fixture is
a real stratified extract of 300 registrations (200 constructed, 40 granted,
30 terminated, 20 A, 10 I) with their matching entity and coordinate records
from the 2026-06-28 weekly r_tower.zip.
"""
import shutil
import sqlite3
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from ingest.common import paths
from ingest.common.adapter import ValidationFailure
from ingest.common.manifest import coverage_for
from ingest.fcc_asr.adapter import FccAsrAdapter, _iso_date

FIXTURE = Path(__file__).parent / "fixtures" / "fcc_asr" / "r_tower.zip"
DATE = "2026-07-01"


def place_fixture(date=DATE, mutate=None):
    raw = paths.raw_dir("fcc_asr", date)
    raw.mkdir(parents=True, exist_ok=True)
    if mutate is None:
        shutil.copy(FIXTURE, raw / "r_tower.zip")
        return raw
    src = zipfile.ZipFile(FIXTURE)
    with zipfile.ZipFile(raw / "r_tower.zip", "w") as out:
        for m in src.namelist():
            data = src.read(m).decode("latin-1")
            result = mutate(m, data)
            if result is not None:
                out.writestr(m, result)
    return raw


def run_pipeline(date=DATE):
    a = FccAsrAdapter(date)
    a.validate()
    counts = a.normalise()
    written = a.emit()
    return a, counts, written


def test_iso_date():
    assert _iso_date("09/21/1999") == "1999-09-21"
    assert _iso_date("") is None and _iso_date("bad") is None


def test_full_pipeline_loads_us_structures(ingest_root):
    place_fixture()
    a, counts, written = run_pipeline()
    # terminated/withdrawn registrations without surface coordinates are
    # quarantined, everything else normalises
    assert counts["rows_normalised"] + counts["rows_quarantined"] == 300
    assert counts["rows_normalised"] >= 280
    assert written == counts["rows_normalised"]
    df = pd.read_parquet(paths.normalised_dir("fcc_asr", DATE) / "structures.parquet")
    assert (df["country_iso2"] == "US").all()
    assert df["structure_uid"].str.match(r"fcc_asr:\d+").all()
    # continental US + AK/HI/territories bounds, longitudes west
    assert df["lat"].between(15, 72).all()
    assert (df["lon"] < 0).mean() > 0.99
    # owner = registrant entity name, the analytical payoff
    assert df["owner"].notna().mean() > 0.95
    # ASR provides no operators
    assert df["operators"].isna().all()
    # heights are metres: US registrations cluster above the ~61 m threshold
    heights = df["height_m"].dropna()
    assert 30 < heights.median() < 120
    assert heights.max() < 700          # tallest US masts ~630 m; feet would exceed
    assert set(df["status"]) <= {"active", "granted", "dismantled", "other"}
    assert (df["status"] == "active").sum() >= 180
    assert (df["coverage_status"] == "covered_partial").all()
    assert df.loc[df["structure_type_raw"] == "TOWER", "structure_type"].eq("tower").all()
    assert df.loc[df["structure_type_raw"] == "MTOWER", "structure_type"].eq("mast").all()


def test_store_manifest_and_partial_caveat(ingest_root):
    place_fixture()
    run_pipeline()
    con = sqlite3.connect(paths.store_path())
    con.row_factory = sqlite3.Row
    us = coverage_for(con, "fcc_asr", "US")
    assert us["coverage_status"] == "covered_partial"
    # the completeness caveat travels verbatim in the manifest (brief s5.2)
    assert "FAA notice" in us["coverage_note"]
    assert "200 feet" in us["coverage_note"]
    de = coverage_for(con, "fcc_asr", "DE")
    assert de["coverage_status"] == "not_covered"
    n = con.execute("""SELECT COUNT(*) FROM structures
                       WHERE source='fcc_asr' AND country_iso2='US'""").fetchone()[0]
    assert n >= 280
    con.close()


def test_quarantine_reasons_for_missing_coordinates(ingest_root):
    place_fixture()
    a = FccAsrAdapter(DATE)
    a.validate()
    counts = a.normalise()
    if counts["rows_quarantined"]:
        q = pd.read_csv(paths.quarantine_dir("fcc_asr", DATE) / "registrations.csv")
        assert q["quarantine_reason"].str.contains("coordinates").all()


def test_validate_fails_on_missing_member(ingest_root):
    place_fixture(mutate=lambda m, d: None if m == "EN.dat" else d)
    with pytest.raises(ValidationFailure, match="zip_members"):
        FccAsrAdapter(DATE).validate()


def test_validate_fails_on_layout_drift(ingest_root):
    def drop_field(m, d):
        if m != "RA.dat":
            return d
        return "\n".join("|".join(l.split("|")[:-2]) for l in d.splitlines()) + "\n"
    place_fixture(mutate=drop_field)
    with pytest.raises(ValidationFailure, match="RA_field_count"):
        FccAsrAdapter(DATE).validate()


def test_idempotent_rerun(ingest_root):
    place_fixture()
    run_pipeline()
    _, counts, _ = run_pipeline()
    con = sqlite3.connect(paths.store_path())
    n = con.execute("SELECT COUNT(*) FROM structures WHERE source='fcc_asr'").fetchone()[0]
    assert n == counts["rows_normalised"]
    con.close()
