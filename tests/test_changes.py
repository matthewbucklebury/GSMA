#!/usr/bin/env python3
"""Test suite for GSMA v2 changes (run: python3 tests/test_changes.py).

Checks the database contract after Phase 1-4: retired metrics gone,
verification levels present, China Tower visible in China, JV Infraco not
duplicated, and the API endpoints returning the v2 shapes.
"""
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "gsma.db"
BASE = "http://localhost:8765"

RETIRED = ("sims_per_tower", "sim_penetration_pct", "subscribers",
           "population", "towers_total")


def test_no_retired_metrics(con):
    for metric in RETIRED:
        n = con.execute("SELECT COUNT(*) FROM observations WHERE metric=?",
                        (metric,)).fetchone()[0]
        assert n == 0, f"{n} observations still use retired metric '{metric}'"
    print("PASS no retired metrics (SIM stats, towers_total) in database")


def test_verification_levels(con):
    cols = [r[1] for r in con.execute("PRAGMA table_info(observations)")]
    assert "verification_level" in cols and "last_updated" in cols, \
        "observations missing verification columns"
    cols = [r[1] for r in con.execute("PRAGMA table_info(companies)")]
    assert "verification_level" in cols and "last_updated" in cols, \
        "companies missing verification columns"
    n = con.execute("""SELECT COUNT(*) FROM observations
                       WHERE verification_level IS NULL""").fetchone()[0]
    assert n == 0, f"{n} observations lack a verification_level"
    print("PASS verification_level + last_updated present and populated")


def test_china_tower(con):
    row = con.execute("""
        SELECT o.value FROM observations o
        JOIN companies c ON c.id = o.company_id
        JOIN countries k ON k.id = o.country_id
        WHERE c.name LIKE '%China Tower%' AND k.name = 'China'
          AND o.metric = 'towers' AND o.deleted = 0""").fetchone()
    assert row and row[0] > 0, "China Tower has no towers observation in China"
    fp = con.execute("""
        SELECT 1 FROM footprints f
        JOIN companies c ON c.id = f.company_id
        JOIN countries k ON k.id = f.country_id
        WHERE c.name LIKE '%China Tower%' AND k.name = 'China'""").fetchone()
    assert fp, "China Tower footprint does not include China"
    print(f"PASS China Tower in China ({row[0]:,.0f} towers) with footprint")


def test_jv_infraco_single(con):
    models = [r[0] for r in con.execute(
        """SELECT DISTINCT business_model FROM companies
           WHERE business_model IS NOT NULL AND LOWER(business_model) LIKE '%jv%'""")]
    assert len(models) == 1, f"JV business model duplicated: {models}"
    print(f"PASS single JV business model: {models[0]!r}")


def api(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return json.load(r)


def test_api_shapes():
    meta = api("/api/meta")
    assert set(meta["metrics"]) == {"towers", "towers_global", "market_share_pct"}, \
        f"unexpected metrics: {meta['metrics']}"
    assert len(meta["data_quality_levels"]) == 5
    league = api("/api/league")["league"]
    top = league[0]
    for key in ("towers_sum", "known_tenants", "data_quality", "data_quality_label"):
        assert key in top, f"league entry missing '{key}'"
    mnos = api("/api/mnos")["mnos"]
    m0 = mnos[0]
    for key in ("footprint", "owns_in", "towercos", "towers_owned"):
        assert key in m0, f"mno entry missing '{key}'"
    assert len(mnos[0]["footprint"]) >= len(mnos[-1]["footprint"]), \
        "MNOs not ranked by footprint size"
    countries = api("/api/countries")["countries"]
    names = [c["name"] for c in countries]
    assert names == sorted(names), "countries not alphabetical"
    c0 = next(c for c in countries if c["name"] == "Algeria")
    for key in ("total_towers", "towercos", "mnos", "towercos_active", "mnos_active",
                "towerco_share"):
        assert key in c0, f"country entry missing '{key}'"
    rows = api("/api/map?metric=towers")["rows"]
    assert any(r["name"] == "China" and r["value"] and r["value"] > 1_000_000 for r in rows), \
        "China missing from towers map"
    assert api("/api/map?metric=sims_per_tower")["metric"] == "towers", \
        "map should reject retired metrics"
    s = api("/api/search?q=spain&type=towerco")
    assert s["towercos"], "towerco search by footprint country found nothing"
    obs = api("/api/observations")["observations"]
    assert all(o["metric"] not in RETIRED for o in obs), "retired metrics in observations API"
    print("PASS API shapes: meta, league, mnos, countries, map, search, observations")


def main():
    con = sqlite3.connect(DB_PATH)
    failures = 0
    for test in (test_no_retired_metrics, test_verification_levels,
                 test_china_tower, test_jv_infraco_single):
        try:
            test(con)
        except AssertionError as e:
            failures += 1
            print(f"FAIL {test.__name__}: {e}")
    con.close()
    try:
        test_api_shapes()
    except AssertionError as e:
        failures += 1
        print(f"FAIL test_api_shapes: {e}")
    except OSError:
        print("SKIP API tests (server not running on :8765)")
    print("\nALL TESTS PASSED" if not failures else f"\n{failures} TEST(S) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
