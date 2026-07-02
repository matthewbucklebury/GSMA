#!/usr/bin/env python3
"""Build the SQLite database (data/gsma.db) from data/dataset.json.

The database is the callable SQL layer for the explorer app. Re-running this
script rebuilds the base data but PRESERVES user-entered observations
(is_override = 1) by re-applying them after the rebuild.
"""
import json, re, sqlite3, sys, unicodedata
from pathlib import Path

DATA = Path(__file__).resolve().parent
DB = DATA / "gsma.db"

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  type TEXT NOT NULL DEFAULT 'unknown',          -- towerco | mno | jv-infraco | broadcaster | government | aggregate | unknown
  business_model TEXT,                           -- league table: Operator owned | Pureplay independent | JV Infraco
  owners TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS countries (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  iso3 TEXT,
  region TEXT                                    -- MENA | LATAM | Europe | Asia | Africa | Other
);

-- Every fact is an observation tagged with an as-of period (year+quarter or
-- unknown), a source and a confidence. Multiple periods per fact = history.
CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY,
  company_id INTEGER REFERENCES companies(id),   -- NULL for country-level metrics
  country_id INTEGER REFERENCES countries(id),   -- NULL for global (league) tower counts
  metric TEXT NOT NULL,                          -- towers | towers_total | towers_global | market_share_pct | population | subscribers | sims_per_tower | sim_penetration_pct
  segment TEXT NOT NULL DEFAULT 'all',           -- all | ground | rooftop | alternative | broadcast
  value REAL,
  value_text TEXT,
  as_of_year INTEGER,                            -- NULL = unknown
  as_of_quarter INTEGER,                         -- NULL = unknown
  source TEXT,
  confidence TEXT DEFAULT 'reported',            -- reported | inferred | approx | estimate | unknown
  note TEXT,
  is_override INTEGER NOT NULL DEFAULT 0,        -- 1 = entered/overridden via the data-entry page
  created_at TEXT DEFAULT (datetime('now')),
  deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_obs_lookup ON observations(country_id, company_id, metric, segment);
CREATE INDEX IF NOT EXISTS idx_obs_company ON observations(company_id);

-- League table snapshot: a company's global tower count and rank.
CREATE TABLE IF NOT EXISTS league_entries (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  rank INTEGER,
  towers INTEGER,
  country_count INTEGER,
  as_of_year INTEGER,
  as_of_quarter INTEGER,
  as_of_raw TEXT,
  source TEXT
);

-- Geographic footprint from the league table (owner present in country).
CREATE TABLE IF NOT EXISTS footprints (
  company_id INTEGER NOT NULL REFERENCES companies(id),
  country_id INTEGER NOT NULL REFERENCES countries(id),
  source TEXT,
  PRIMARY KEY (company_id, country_id)
);

-- MNO active in a market (from the guides' per-country MNO lists); an MNO can
-- be active as tenant without owning sites.
CREATE TABLE IF NOT EXISTS mno_presences (
  company_id INTEGER NOT NULL REFERENCES companies(id),
  country_id INTEGER NOT NULL REFERENCES countries(id),
  role TEXT DEFAULT 'mno',
  source TEXT,
  PRIMARY KEY (company_id, country_id)
);

-- Public anchor tenants per towerco (customer table).
CREATE TABLE IF NOT EXISTS anchor_tenancies (
  towerco_id INTEGER NOT NULL REFERENCES companies(id),
  tenant_company_id INTEGER REFERENCES companies(id),
  tenant_name TEXT NOT NULL,
  source TEXT,
  PRIMARY KEY (towerco_id, tenant_name)
);
"""

def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

sys.path.insert(0, str(DATA))
from build_dataset import ISO3  # noqa: E402  (footprint countries need iso3 too)

def main():
    ds = json.load(open(DATA / "dataset.json"))

    saved_overrides = []
    if DB.exists():
        old = sqlite3.connect(DB)
        old.row_factory = sqlite3.Row
        try:
            saved_overrides = [dict(r) for r in old.execute(
                """SELECT c.name AS company, k.name AS country, o.* FROM observations o
                   LEFT JOIN companies c ON c.id = o.company_id
                   LEFT JOIN countries k ON k.id = o.country_id
                   WHERE o.is_override = 1""")]
        except sqlite3.OperationalError:
            pass
        old.close()
        DB.unlink()

    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)

    comp_ids = {}   # norm name -> id
    comp_display = {}

    def company_id(name, ctype=None, business_model=None, owners=None):
        name = re.sub(r"\s+", " ", str(name)).strip()
        n = norm(name)
        if not n:
            return None
        if n in comp_ids:
            cid = comp_ids[n]
            if ctype and ctype != "unknown":
                con.execute("UPDATE companies SET type=? WHERE id=? AND type='unknown'", (ctype, cid))
            if business_model:
                con.execute("UPDATE companies SET business_model=COALESCE(business_model,?) WHERE id=?",
                            (business_model, cid))
            if owners:
                con.execute("UPDATE companies SET owners=COALESCE(owners,?) WHERE id=?", (owners, cid))
            return cid
        cur = con.execute(
            "INSERT INTO companies(name, type, business_model, owners) VALUES (?,?,?,?)",
            (name, ctype or "unknown", business_model, owners))
        comp_ids[n] = cur.lastrowid
        comp_display[n] = name
        return cur.lastrowid

    country_ids = {}
    def country_id(name, iso3=None, region=None):
        name = re.sub(r"\s+", " ", str(name)).strip()
        if name in country_ids:
            if region:
                con.execute("UPDATE countries SET region=COALESCE(region,?) WHERE id=?",
                            (region, country_ids[name]))
            return country_ids[name]
        cur = con.execute("INSERT INTO countries(name, iso3, region) VALUES (?,?,?)",
                          (name, iso3 or ISO3.get(name), region))
        country_ids[name] = cur.lastrowid
        return cur.lastrowid

    # countries from guides
    for c in ds["countries"]:
        country_id(c["name"], c["iso3"], c["region"])

    # league: companies + league entries + footprints + global tower obs
    bm_type = lambda bm: "jv-infraco" if bm and "jv" in bm.lower() else "towerco"
    for l in ds["league"]:
        cid = company_id(l["company"], bm_type(l["business_model"]),
                         l["business_model"], l["owners"])
        con.execute(
            """INSERT INTO league_entries(company_id, rank, towers, country_count,
               as_of_year, as_of_quarter, as_of_raw, source)
               VALUES (?,?,?,?,?,?,?,?)""",
            (cid, l["rank"], l["towers"], l["country_count"],
             l["as_of_year"], l["as_of_quarter"], l["as_of_raw"], "League Table.xlsx"))
        con.execute(
            """INSERT INTO observations(company_id, country_id, metric, value,
               as_of_year, as_of_quarter, source, confidence)
               VALUES (?,NULL,'towers_global',?,?,?,?,?)""",
            (cid, l["towers"], l["as_of_year"], l["as_of_quarter"],
             "League Table.xlsx",
             "reported" if l["as_of_year"] else "unknown"))
        for cname in l["footprint"]:
            kid = country_id(cname)
            con.execute("INSERT OR IGNORE INTO footprints VALUES (?,?,?)",
                        (cid, kid, "League Table.xlsx"))

    # guide country-level stats
    def pct(s):
        if not s:
            return None
        m = re.search(r"([\d\.]+)", s)
        return float(m.group(1)) if m else None
    for c in ds["countries"]:
        kid = country_ids[c["name"]]
        rows = [
            ("towers_total", c["towers_total"], c["towers_total_raw"]),
            ("sims_per_tower", c["sims_per_tower"], None),
            ("sim_penetration_pct", pct(c["sim_penetration"]), c["sim_penetration"]),
            ("population", None, c["population_raw"]),
            ("subscribers", None, c["subscribers_raw"]),
        ]
        for metric, val, vtext in rows:
            if val is None and not vtext:
                continue
            con.execute(
                """INSERT INTO observations(country_id, metric, value, value_text,
                   as_of_year, as_of_quarter, source)
                   VALUES (?,?,?,?,?,?,?)""",
                (kid, metric, val, vtext, c["as_of_year"], c["as_of_quarter"], c["source"]))

    # holdings (pie extractions)
    for h in ds["holdings"]:
        cid = company_id(h["company"], h["company_type"])
        kid = country_ids[h["country"]]
        con.execute(
            """INSERT INTO observations(company_id, country_id, metric, segment,
               value, as_of_year, as_of_quarter, source, confidence, note)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (cid, kid, h["metric"], h["segment"], h["value"],
             h["as_of_year"], h["as_of_quarter"], h["source"],
             h["confidence"], h.get("note")))

    # MNO presences
    for p in ds["mno_presences"]:
        cid = company_id(p["company"], "mno")
        kid = country_ids[p["country"]]
        con.execute("INSERT OR IGNORE INTO mno_presences VALUES (?,?,?,?)",
                    (cid, kid, p["role"], "TowerXchange guide"))

    # anchor tenants
    for t in ds["tenants"]:
        tid = company_id(t["company"])
        for tenant in t["anchor_tenants"]:
            tenant = re.sub(r"\s+", " ", tenant).strip()
            if not tenant or len(tenant) > 60:
                continue
            ten_id = comp_ids.get(norm(tenant))
            con.execute(
                "INSERT OR IGNORE INTO anchor_tenancies VALUES (?,?,?,?)",
                (tid, ten_id, tenant, "League Table.xlsx (Customer table)"))

    # re-apply preserved user overrides
    for o in saved_overrides:
        cid = company_id(o["company"]) if o["company"] else None
        kid = country_id(o["country"]) if o["country"] else None
        con.execute(
            """INSERT INTO observations(company_id, country_id, metric, segment, value,
               value_text, as_of_year, as_of_quarter, source, confidence, note,
               is_override, created_at, deleted)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
            (cid, kid, o["metric"], o["segment"], o["value"], o["value_text"],
             o["as_of_year"], o["as_of_quarter"], o["source"], o["confidence"],
             o["note"], o["created_at"], o["deleted"]))

    con.commit()
    n_obs = con.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    n_comp = con.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    n_ctry = con.execute("SELECT COUNT(*) FROM countries").fetchone()[0]
    print(f"gsma.db built: {n_comp} companies, {n_ctry} countries, {n_obs} observations, "
          f"{len(saved_overrides)} preserved overrides")
    con.close()

if __name__ == "__main__":
    main()
