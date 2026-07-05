"""Explorer ingest-layer API tests (brief session 5 / acceptance criteria s7).

These call the handler functions directly (no HTTP, no network) against the
committed data/ingest.db. If the store is absent the tests skip rather than
fail, since raw ingest artefacts are machine-local.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app"))

import server  # noqa: E402  (app/server.py)


@pytest.fixture(scope="module")
def store():
    if not server.INGEST_DB_PATH.exists():
        pytest.skip("data/ingest.db not built")
    return True


def test_meta_enumerates_three_sources(store):
    d = server.api_ingest_meta({})
    assert d["available"]
    names = {s["source"] for s in d["sources"]}
    assert {"anfr", "fcc_asr", "opencellid"} <= names
    by = {s["source"]: s for s in d["sources"]}
    # coverage manifests enumerate every ISO market for every source
    for s in by.values():
        assert sum(s["coverage_counts"].values()) == 250
    assert by["anfr"]["coverage_counts"].get("covered_full") == 1
    assert by["fcc_asr"]["coverage_counts"].get("covered_partial") == 1
    # opencellid holds real market aggregates since the 2026-07-05 live run
    assert by["opencellid"]["coverage_counts"].get("covered_partial") > 150
    assert by["opencellid"]["market_cell_stats"] > 1500
    assert by["anfr"]["structures"] > 90000
    assert by["fcc_asr"]["structures"] > 150000
    # caveats travel with the sources
    assert "FAA notice" in by["fcc_asr"]["caveat"]
    assert "Crowdsourced" in by["opencellid"]["caveat"]


def test_germany_returns_explicit_not_covered(store):
    d = server.api_ingest_coverage({"iso2": ["DE"]})
    assert d["available"] and d["iso2"] == "DE"
    statuses = {r["source"]: r["coverage_status"] for r in d["sources"]}
    assert statuses["anfr"] == "not_covered"
    assert statuses["fcc_asr"] == "not_covered"
    # since the real OpenCelliD run, Germany is covered_partial there
    assert statuses["opencellid"] == "covered_partial"
    # and the note explains it is remit, not absence of infrastructure
    notes = {r["source"]: r["coverage_note"] for r in d["sources"]}
    assert "remit" in notes["anfr"]


def test_country_detail_france_and_us(store):
    fr = server.api_ingest_country("FR", {})
    a = fr["structures"]["anfr"]
    assert a["count"] > 90000
    assert a["with_operators"] / a["count"] > 0.99      # operators populated (ANFR)
    assert a["top_owners"] and a["top_owners"][0][1] > 1000
    us = server.api_ingest_country("US", {})
    f = us["structures"]["fcc_asr"]
    assert f["count"] > 150000
    assert f["with_owner"] / f["count"] > 0.99          # owner populated (ASR)
    assert f["with_operators"] == 0                     # ASR records no operators
    cov = {r["source"]: r["coverage_status"] for r in us["coverage"]}
    assert cov["fcc_asr"] == "covered_partial"


def test_bad_iso_rejected(store):
    out = server.api_ingest_coverage({"iso2": ["XYZ"]})
    assert isinstance(out, tuple) and out[1] == 400
