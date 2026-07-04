#!/usr/bin/env python3
"""GSMA v2 migration for an existing data/gsma.db.

Adds verification levels, removes SIM/population/subscriber metrics and the
separate towers_total metric (country totals are now the sum of tracked
owners), normalises the JV Infraco business-model casing, and ensures China
Tower's footprint includes China.

Idempotent: safe to run more than once. A fresh rebuild via data/build_db.py
produces the same schema, so this script is only needed for databases that
cannot be rebuilt (e.g. one holding live manual entries).
"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "gsma.db"

DATA_QUALITY_LEVELS = {
    "public_gsma_verified": "Public data, GSMA verified",
    "public_trusted": "Public data, trusted but not GSMA verified",
    "public_unverified": "Public data, not GSMA verified",
    "private_gsma_verified": "Private data, GSMA verified",
    "estimated": "Estimated",
}

REMOVED_METRICS = ("sims_per_tower", "sim_penetration_pct", "subscribers",
                   "population", "towers_total")


def add_column(cur, table, coldef):
    col = coldef.split()[0]
    have = [r[1] for r in cur.execute(f"PRAGMA table_info({table})")]
    if col in have:
        print(f"   = {table}.{col} already exists")
        return
    cur.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
    print(f"   + {table}.{col} added")


def main():
    if not DB_PATH.exists():
        sys.exit(f"{DB_PATH} not found")
    print("GSMA v2 migration starting...")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    print("\n1. Verification columns")
    add_column(cur, "observations", "verification_level TEXT DEFAULT 'public_unverified'")
    add_column(cur, "observations", "last_updated TEXT")
    add_column(cur, "companies", "verification_level TEXT DEFAULT 'public_unverified'")
    add_column(cur, "companies", "last_updated TEXT")

    print("\n2. Removing retired metrics")
    for metric in REMOVED_METRICS:
        cur.execute("DELETE FROM observations WHERE metric = ?", (metric,))
        print(f"   - {metric}: deleted {cur.rowcount} observations")

    print("\n3. Backfilling verification levels")
    cur.execute("""UPDATE observations
                   SET verification_level = 'public_unverified'
                   WHERE verification_level IS NULL""")
    cur.execute("""UPDATE observations SET last_updated = datetime('now')
                   WHERE last_updated IS NULL""")
    cur.execute("""UPDATE companies
                   SET verification_level = 'public_unverified'
                   WHERE verification_level IS NULL""")
    cur.execute("""UPDATE companies SET last_updated = datetime('now')
                   WHERE last_updated IS NULL""")
    print("   done")

    print("\n4. Normalising JV Infraco business model casing")
    cur.execute("""UPDATE companies SET business_model = 'JV Infraco'
                   WHERE business_model IS NOT NULL
                     AND LOWER(business_model) LIKE '%jv%'
                     AND business_model != 'JV Infraco'""")
    print(f"   updated {cur.rowcount} companies")

    print("\n5. Ensuring China Tower footprint includes China")
    china = cur.execute("SELECT id FROM countries WHERE name = 'China'").fetchone()
    if not china:
        cur.execute("INSERT INTO countries(name, iso3, region) VALUES ('China','CHN','Asia')")
        china = cur.execute("SELECT id FROM countries WHERE name = 'China'").fetchone()
    ct = cur.execute(
        "SELECT id FROM companies WHERE name LIKE '%China Tower%'").fetchone()
    if ct:
        cur.execute(
            "INSERT OR IGNORE INTO footprints(company_id, country_id, source) VALUES (?,?,?)",
            (ct[0], china[0], "migration fix"))
        print("   verified")
    else:
        print("   ! China Tower company not found")

    con.commit()

    total_obs = cur.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    leftovers = cur.execute(
        f"""SELECT COUNT(*) FROM observations
            WHERE metric IN ({','.join('?' * len(REMOVED_METRICS))})""",
        REMOVED_METRICS).fetchone()[0]
    print(f"\nMigration complete. Observations: {total_obs}; "
          f"retired-metric rows remaining: {leftovers} (should be 0)")
    con.close()
    return 0 if leftovers == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
