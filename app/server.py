#!/usr/bin/env python3
"""Tower ownership data explorer — zero-dependency API + static server.

Run:  python3 app/server.py  [--port 8000]
Data: data/gsma.db (build with data/build_dataset.py && data/build_db.py)

Endpoints (all JSON under /api/):
  GET  /api/meta
  GET  /api/league            ?at=YYYYQn
  GET  /api/mnos
  GET  /api/countries
  GET  /api/country/<id>
  GET  /api/company/<id>
  GET  /api/map?metric=...    ?at=YYYYQn
  GET  /api/compare?kind=country|company&ids=1,2&metric=...
  GET  /api/search?q=...
  GET  /api/observations?country_id=&company_id=&overrides=1
  POST /api/observations      (insert data / override; partial by metric)
  POST /api/observations/<id>/delete   (soft-delete an override row)
"""
import json, re, sqlite3, sys
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT.parent / "data" / "gsma.db"
STATIC = ROOT / "static"

METRICS = ["towers", "towers_global", "market_share_pct"]
SEGMENTS = ["all", "ground", "rooftop", "alternative", "broadcast"]
CONFIDENCES = ["reported", "estimate", "inferred", "approx", "unknown"]
DATA_QUALITY_LEVELS = {
    "public_gsma_verified": "Public data, GSMA verified",
    "public_trusted": "Public data, trusted but not GSMA verified",
    "public_unverified": "Public data, not GSMA verified",
    "private_gsma_verified": "Private data, GSMA verified",
    "estimated": "Estimated",
}
RETIRED_METRICS = ("sims_per_tower", "sim_penetration_pct", "subscribers",
                   "population", "towers_total")

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def parse_at(q):
    """'2024Q3' -> (2024,3) or None."""
    at = (q.get("at") or [None])[0]
    if not at:
        return None
    m = re.fullmatch(r"(\d{4})Q([1-4])", at.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None

# Latest observation per (company,country,metric,segment).
# Dated rows beat unknown-dated; later dates beat earlier; overrides beat base
# rows of the same date; newer inserts beat older.
LATEST_CTE = """
WITH ranked AS (
  SELECT o.*, ROW_NUMBER() OVER (
    PARTITION BY o.company_id, o.country_id, o.metric, o.segment
    ORDER BY (o.as_of_year IS NOT NULL) DESC,
             o.as_of_year DESC, o.as_of_quarter DESC,
             o.is_override DESC, o.created_at DESC, o.id DESC
  ) rn
  FROM observations o
  WHERE o.deleted = 0 {at_filter}
)
"""

def latest_cte(at):
    if at:
        y, q = at
        f = (f"AND (o.as_of_year IS NULL OR o.as_of_year < {y} "
             f"OR (o.as_of_year = {y} AND o.as_of_quarter <= {q}))")
    else:
        f = ""
    return LATEST_CTE.format(at_filter=f)

def period_str(r):
    if r["as_of_year"]:
        return f"Q{r['as_of_quarter']} {r['as_of_year']}" if r["as_of_quarter"] else str(r["as_of_year"])
    return "unknown"

def rowdicts(rows):
    return [dict(r) for r in rows]

# ---------------------------------------------------------------- handlers

def api_meta(q):
    con = db()
    periods = con.execute(
        """SELECT DISTINCT as_of_year y, as_of_quarter qt FROM observations
           WHERE deleted=0 AND as_of_year IS NOT NULL ORDER BY y, qt""").fetchall()
    regions = [r[0] for r in con.execute(
        "SELECT DISTINCT region FROM countries WHERE region IS NOT NULL ORDER BY region")]
    counts = {
        "companies": con.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
        "countries": con.execute("SELECT COUNT(*) FROM countries").fetchone()[0],
        "observations": con.execute("SELECT COUNT(*) FROM observations WHERE deleted=0").fetchone()[0],
        "overrides": con.execute("SELECT COUNT(*) FROM observations WHERE deleted=0 AND is_override=1").fetchone()[0],
    }
    con.close()
    return {"periods": [f"{r['y']}Q{r['qt']}" for r in periods],
            "regions": regions, "metrics": METRICS, "segments": SEGMENTS,
            "confidences": CONFIDENCES,
            "data_quality_levels": DATA_QUALITY_LEVELS, "counts": counts}

def api_league(q):
    at = parse_at(q)
    con = db()
    league = rowdicts(con.execute(
        """SELECT le.*, c.name company, c.type, c.business_model, c.owners,
                  c.verification_level, c.last_updated
           FROM league_entries le JOIN companies c ON c.id = le.company_id
           ORDER BY le.towers DESC"""))
    # guide-derived country sums (latest per country, 'all' rollup)
    sums = {}
    for r in con.execute(latest_cte(at) + """
        SELECT company_id, SUM(value) s, COUNT(DISTINCT country_id) nc
        FROM ranked WHERE rn=1 AND metric='towers' AND company_id IS NOT NULL
        GROUP BY company_id"""):
        sums[r["company_id"]] = {"guide_sum": r["s"], "guide_countries": r["nc"]}
    fps = {}
    for r in con.execute("""SELECT f.company_id, k.name FROM footprints f
                            JOIN countries k ON k.id=f.country_id"""):
        fps.setdefault(r["company_id"], []).append(r["name"])
    tenants = {}
    for r in con.execute("SELECT towerco_id, tenant_name FROM anchor_tenancies"):
        tenants.setdefault(r["towerco_id"], []).append(r["tenant_name"])
    for l in league:
        l["as_of"] = period_str(l)
        l.update(sums.get(l["company_id"], {}))
        l["towers_sum"] = l.get("guide_sum")
        l["footprint"] = sorted(fps.get(l["company_id"], []))
        l["known_tenants"] = sorted(tenants.get(l["company_id"], []))
        l["data_quality"] = l.get("verification_level") or "public_unverified"
        l["data_quality_label"] = DATA_QUALITY_LEVELS.get(l["data_quality"], "Unknown")
    con.close()
    return {"league": league}

def api_mnos(q):
    at = parse_at(q)
    con = db()
    pres = {}
    def entry(r):
        return pres.setdefault(r["company_id"], {
            "company_id": r["company_id"], "company": r["company"],
            "type": r["type"],
            "footprint": [],        # markets the MNO is active in (may be tenant only)
            "owns_in": {},          # country -> towers owned
            "towers_owned": 0,
            "towercos": [],         # towercos it leases from (anchor tenant of)
        })
    for r in con.execute("""SELECT p.company_id, c.name company, c.type, k.name country, k.region
                            FROM mno_presences p JOIN companies c ON c.id=p.company_id
                            JOIN countries k ON k.id=p.country_id"""):
        entry(r)["footprint"].append({"country": r["country"], "region": r["region"]})
    for r in con.execute(latest_cte(at) + """
        SELECT r.company_id, c.name company, c.type, k.name country, SUM(r.value) v
        FROM ranked r JOIN companies c ON c.id=r.company_id
        JOIN countries k ON k.id=r.country_id
        WHERE r.rn=1 AND r.metric='towers' AND c.type IN ('mno','jv-infraco')
        GROUP BY r.company_id, k.name"""):
        d = entry(r)
        d["owns_in"][r["country"]] = r["v"]
        d["towers_owned"] += r["v"] or 0
        if not any(m["country"] == r["country"] for m in d["footprint"]):
            d["footprint"].append({"country": r["country"], "region": None})
    for r in con.execute("""SELECT t.tenant_company_id cid, c2.name towerco
                            FROM anchor_tenancies t JOIN companies c2 ON c2.id=t.towerco_id
                            WHERE t.tenant_company_id IS NOT NULL"""):
        if r["cid"] in pres:
            pres[r["cid"]]["towercos"].append(r["towerco"])
    # ranked by footprint breadth (number of markets), then towers owned
    out = sorted(pres.values(),
                 key=lambda d: (-len(d["footprint"]), -d["towers_owned"]))
    con.close()
    return {"mnos": out}

def api_countries(q):
    at = parse_at(q)
    con = db()
    countries = rowdicts(con.execute("SELECT * FROM countries ORDER BY name"))
    own = {}
    for r in con.execute(latest_cte(at) + """
        SELECT r.country_id, r.company_id, c.name company, c.type, SUM(r.value) v
        FROM ranked r JOIN companies c ON c.id = r.company_id
        WHERE r.rn=1 AND r.metric='towers'
        GROUP BY r.country_id, r.company_id"""):
        own.setdefault(r["country_id"], []).append(
            {"company_id": r["company_id"], "company": r["company"],
             "type": r["type"], "towers": r["v"]})
    mnos = {}
    for r in con.execute("""SELECT p.country_id, p.company_id, c.name company
                            FROM mno_presences p JOIN companies c ON c.id=p.company_id
                            ORDER BY c.name"""):
        mnos.setdefault(r["country_id"], []).append(
            {"company_id": r["company_id"], "company": r["company"]})
    for c in countries:
        owners = sorted(own.get(c["id"], []), key=lambda o: -(o["towers"] or 0))
        towercos = [o for o in owners if o["type"] in ("towerco", "jv-infraco")]
        c["owners"] = owners
        c["owners_count"] = len(owners)
        c["top_owner"] = owners[0] if owners else None
        c["towercos"] = towercos
        c["towercos_active"] = len(towercos)
        c["mnos"] = mnos.get(c["id"], [])
        c["mnos_active"] = len(c["mnos"])
        tot = sum(o["towers"] or 0 for o in owners)
        tc = sum(o["towers"] or 0 for o in towercos)
        c["total_towers"] = tot          # sum of tracked owners
        c["holdings_sum"] = tot          # kept for backward compatibility
        c["towerco_share"] = round(100 * tc / tot, 1) if tot else None
    con.close()
    return {"countries": countries}

def api_country(cid, q):
    con = db()
    c = con.execute("SELECT * FROM countries WHERE id=?", (cid,)).fetchone()
    if not c:
        return {"error": "not found"}, 404
    obs = rowdicts(con.execute(
        """SELECT o.*, comp.name company, comp.type company_type
           FROM observations o LEFT JOIN companies comp ON comp.id=o.company_id
           WHERE o.country_id=? AND o.deleted=0
           ORDER BY o.metric, comp.name, o.as_of_year, o.as_of_quarter""", (cid,)))
    for o in obs:
        o["as_of"] = period_str(o)
    mnos = rowdicts(con.execute(
        """SELECT c2.id company_id, c2.name company FROM mno_presences p
           JOIN companies c2 ON c2.id=p.company_id WHERE p.country_id=?
           ORDER BY c2.name""", (cid,)))
    footprint = rowdicts(con.execute(
        """SELECT c2.id company_id, c2.name company, c2.type FROM footprints f
           JOIN companies c2 ON c2.id=f.company_id WHERE f.country_id=?
           ORDER BY c2.name""", (cid,)))
    con.close()
    return {"country": dict(c), "observations": obs, "mnos": mnos,
            "league_footprint": footprint}

def api_company(cid, q):
    con = db()
    c = con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
    if not c:
        return {"error": "not found"}, 404
    obs = rowdicts(con.execute(
        """SELECT o.*, k.name country, k.region FROM observations o
           LEFT JOIN countries k ON k.id=o.country_id
           WHERE o.company_id=? AND o.deleted=0
           ORDER BY k.name, o.metric, o.as_of_year, o.as_of_quarter""", (cid,)))
    for o in obs:
        o["as_of"] = period_str(o)
    league = rowdicts(con.execute(
        "SELECT * FROM league_entries WHERE company_id=?", (cid,)))
    for l in league:
        l["as_of"] = period_str(l)
    footprint = [r["name"] for r in con.execute(
        """SELECT k.name FROM footprints f JOIN countries k ON k.id=f.country_id
           WHERE f.company_id=? ORDER BY k.name""", (cid,))]
    markets = [r["name"] for r in con.execute(
        """SELECT k.name FROM mno_presences p JOIN countries k ON k.id=p.country_id
           WHERE p.company_id=? ORDER BY k.name""", (cid,))]
    tenants = rowdicts(con.execute(
        """SELECT tenant_name, tenant_company_id FROM anchor_tenancies
           WHERE towerco_id=? ORDER BY tenant_name""", (cid,)))
    tenant_of = rowdicts(con.execute(
        """SELECT t.towerco_id company_id, c2.name company FROM anchor_tenancies t
           JOIN companies c2 ON c2.id=t.towerco_id WHERE t.tenant_company_id=?
           ORDER BY c2.name""", (cid,)))
    con.close()
    return {"company": dict(c), "observations": obs, "league": league,
            "footprint": footprint, "mno_markets": markets,
            "anchor_tenants": tenants, "anchor_tenant_of": tenant_of}

def api_map(q):
    at = parse_at(q)
    metric = (q.get("metric") or ["towers"])[0]
    if metric not in ("towers", "towerco_share", "owners_count"):
        metric = "towers"
    con = db()
    out = []
    if metric == "towers":
        rows = con.execute(latest_cte(at) + """
            SELECT k.iso3, k.name, k.region, SUM(r.value) v
            FROM ranked r JOIN countries k ON k.id=r.country_id
            WHERE r.rn=1 AND r.metric='towers' AND r.company_id IS NOT NULL
            GROUP BY k.id""")
        out = [{"iso3": r["iso3"], "name": r["name"], "region": r["region"],
                "value": r["v"], "as_of": None} for r in rows]
    elif metric == "towerco_share":
        agg = {}
        for r in con.execute(latest_cte(at) + """
            SELECT k.iso3, k.name, k.region, c.type, SUM(r.value) v
            FROM ranked r JOIN countries k ON k.id=r.country_id
            JOIN companies c ON c.id=r.company_id
            WHERE r.rn=1 AND r.metric='towers'
            GROUP BY k.id, c.type"""):
            d = agg.setdefault(r["name"], {"iso3": r["iso3"], "name": r["name"],
                                           "region": r["region"], "tot": 0, "tc": 0})
            d["tot"] += r["v"] or 0
            if r["type"] in ("towerco", "jv-infraco"):
                d["tc"] += r["v"] or 0
        out = [{"iso3": d["iso3"], "name": d["name"], "region": d["region"],
                "value": round(100 * d["tc"] / d["tot"], 1), "as_of": None}
               for d in agg.values() if d["tot"]]
    elif metric == "owners_count":
        rows = con.execute(latest_cte(at) + """
            SELECT k.iso3, k.name, k.region, COUNT(DISTINCT r.company_id) v
            FROM ranked r JOIN countries k ON k.id=r.country_id
            WHERE r.rn=1 AND r.metric='towers' GROUP BY k.id""")
        out = [{"iso3": r["iso3"], "name": r["name"], "region": r["region"],
                "value": r["v"], "as_of": None} for r in rows]
    con.close()
    return {"metric": metric, "rows": out}

def api_compare(q):
    kind = (q.get("kind") or ["country"])[0]
    ids = [int(x) for x in (q.get("ids") or [""])[0].split(",") if x.strip().isdigit()]
    metric = (q.get("metric") or ["towers"])[0]
    con = db()
    out = []
    if kind == "country":
        for cid in ids[:10]:
            k = con.execute("SELECT * FROM countries WHERE id=?", (cid,)).fetchone()
            if not k:
                continue
            owners = rowdicts(con.execute(latest_cte(None) + """
                SELECT c.name company, c.type, SUM(r.value) v FROM ranked r
                JOIN companies c ON c.id=r.company_id
                WHERE r.rn=1 AND r.metric='towers' AND r.country_id=?
                GROUP BY r.company_id ORDER BY v DESC""", (cid,)))
            stats = rowdicts(con.execute(latest_cte(None) + """
                SELECT metric, value, value_text FROM ranked
                WHERE rn=1 AND company_id IS NULL AND country_id=?""", (cid,)))
            out.append({"id": cid, "name": k["name"], "region": k["region"],
                        "owners": owners, "stats": {s["metric"]: s for s in stats}})
    else:
        for cid in ids[:10]:
            c = con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
            if not c:
                continue
            holdings = rowdicts(con.execute(latest_cte(None) + """
                SELECT k.name country, k.region, SUM(r.value) v FROM ranked r
                JOIN countries k ON k.id=r.country_id
                WHERE r.rn=1 AND r.metric='towers' AND r.company_id=?
                GROUP BY r.country_id ORDER BY v DESC""", (cid,)))
            hist = rowdicts(con.execute("""
                SELECT as_of_year y, as_of_quarter qt, value v, metric, source
                FROM observations WHERE company_id=? AND deleted=0
                  AND metric IN ('towers_global','towers')
                ORDER BY y, qt""", (cid,)))
            glob = con.execute(
                "SELECT towers, rank FROM league_entries WHERE company_id=? ORDER BY towers DESC",
                (cid,)).fetchone()
            out.append({"id": cid, "name": c["name"], "type": c["type"],
                        "holdings": holdings, "history": hist,
                        "league_towers": glob["towers"] if glob else None,
                        "league_rank": glob["rank"] if glob else None})
    con.close()
    return {"kind": kind, "metric": metric, "items": out}

def api_search(q):
    term = (q.get("q") or [""])[0].strip()
    search_type = (q.get("type") or ["all"])[0]   # towerco | mno | all
    if len(term) < 2:
        return {"companies": [], "towercos": [], "mnos": [], "countries": []}
    like = f"%{term}%"
    con = db()
    towercos, mnos = [], []
    if search_type in ("towerco", "all"):
        # match by name, business model, footprint country, or tenant name
        towercos = rowdicts(con.execute(
            """SELECT c.id, c.name, c.type, c.business_model,
                      (SELECT COUNT(*) FROM observations o WHERE o.company_id=c.id AND o.deleted=0) nobs
               FROM companies c
               WHERE c.type IN ('towerco','jv-infraco')
                 AND (c.name LIKE ? OR c.business_model LIKE ?
                      OR c.id IN (SELECT f.company_id FROM footprints f
                                  JOIN countries k ON k.id=f.country_id WHERE k.name LIKE ?)
                      OR c.id IN (SELECT towerco_id FROM anchor_tenancies WHERE tenant_name LIKE ?))
               ORDER BY nobs DESC, c.name LIMIT 25""", (like, like, like, like)))
    if search_type in ("mno", "all"):
        # match by name, presence country, or towerco they anchor for
        mnos = rowdicts(con.execute(
            """SELECT c.id, c.name, c.type,
                      (SELECT COUNT(*) FROM observations o WHERE o.company_id=c.id AND o.deleted=0) nobs
               FROM companies c
               WHERE c.type = 'mno'
                 AND (c.name LIKE ?
                      OR c.id IN (SELECT p.company_id FROM mno_presences p
                                  JOIN countries k ON k.id=p.country_id WHERE k.name LIKE ?)
                      OR c.id IN (SELECT t.tenant_company_id FROM anchor_tenancies t
                                  JOIN companies tc ON tc.id=t.towerco_id WHERE tc.name LIKE ?))
               ORDER BY nobs DESC, c.name LIMIT 25""", (like, like, like)))
    comps = rowdicts(con.execute(
        """SELECT c.id, c.name, c.type,
                  (SELECT COUNT(*) FROM observations o WHERE o.company_id=c.id AND o.deleted=0) nobs
           FROM companies c WHERE c.name LIKE ? ORDER BY nobs DESC, c.name LIMIT 25""", (like,)))
    ctrys = rowdicts(con.execute(
        "SELECT id, name, iso3, region FROM countries WHERE name LIKE ? ORDER BY name LIMIT 25",
        (like,)))
    con.close()
    return {"companies": comps, "towercos": towercos, "mnos": mnos, "countries": ctrys}

def api_observations_list(q):
    con = db()
    where, args = ["o.deleted=0",
                   f"o.metric NOT IN ({','.join(repr(m) for m in RETIRED_METRICS)})"], []
    if q.get("country_id"):
        where.append("o.country_id=?"); args.append(int(q["country_id"][0]))
    if q.get("company_id"):
        where.append("o.company_id=?"); args.append(int(q["company_id"][0]))
    if q.get("overrides"):
        where.append("o.is_override=1")
    rows = rowdicts(con.execute(
        f"""SELECT o.*, c.name company, k.name country FROM observations o
            LEFT JOIN companies c ON c.id=o.company_id
            LEFT JOIN countries k ON k.id=o.country_id
            WHERE {' AND '.join(where)}
            ORDER BY o.created_at DESC, o.id DESC LIMIT 500""", args))
    for r in rows:
        r["as_of"] = period_str(r)
    con.close()
    return {"observations": rows}

def get_or_create_company(con, name, ctype=None):
    """Get a company id by name (case-insensitive) or create it."""
    name = re.sub(r"\s+", " ", str(name)).strip()
    if not name:
        return None
    r = con.execute("SELECT id FROM companies WHERE name=? COLLATE NOCASE", (name,)).fetchone()
    if r:
        return r["id"]
    return con.execute(
        """INSERT INTO companies(name, type, verification_level, last_updated)
           VALUES (?,?,?,datetime('now'))""",
        (name, ctype or "unknown", "public_unverified")).lastrowid

def get_or_create_country(con, name, iso3=None, region=None):
    """Get a country id by name (case-insensitive) or create it."""
    name = re.sub(r"\s+", " ", str(name)).strip()
    if not name:
        return None
    r = con.execute("SELECT id FROM countries WHERE name=? COLLATE NOCASE", (name,)).fetchone()
    if r:
        if region:
            con.execute("UPDATE countries SET region=COALESCE(region,?) WHERE id=?",
                        (region, r["id"]))
        return r["id"]
    return con.execute(
        "INSERT INTO countries(name, iso3, region) VALUES (?,?,?)",
        (name, iso3, region or "Other")).lastrowid

def parse_as_of(body):
    """Return (year, quarter) or raise ValueError; ''/None/'unknown' -> (None, None)."""
    year, quarter = body.get("as_of_year"), body.get("as_of_quarter")
    if year in ("", None, "unknown"):
        return None, None
    year = int(year)
    quarter = int(quarter) if quarter not in ("", None) else None
    if not (1990 <= year <= 2100) or (quarter is not None and quarter not in (1, 2, 3, 4)):
        raise ValueError("as-of period out of range")
    return year, quarter

def parse_verification(body):
    v = body.get("verification_level") or "public_unverified"
    if v not in DATA_QUALITY_LEVELS:
        raise ValueError(f"verification_level must be one of {list(DATA_QUALITY_LEVELS)}")
    return v

def insert_towers_obs(con, company_id, country_id, towers, year, quarter,
                      verification, note=None, segment="all"):
    con.execute(
        """INSERT INTO observations(company_id, country_id, metric, segment, value,
           as_of_year, as_of_quarter, source, confidence, note,
           is_override, verification_level, last_updated)
           VALUES (?,?,'towers',?,?,?,?,'manual entry','estimate',?,1,?,datetime('now'))""",
        (company_id, country_id, segment, towers, year, quarter, note, verification))

def api_country_observations_post(cid, body):
    """Bulk entry for one country: who owns how many sites there."""
    con = db()
    try:
        if not con.execute("SELECT 1 FROM countries WHERE id=?", (cid,)).fetchone():
            return {"error": "country not found"}, 404
        try:
            year, quarter = parse_as_of(body)
            verification = parse_verification(body)
        except (ValueError, TypeError) as e:
            return {"error": str(e)}, 400
        added = 0
        for entry in body.get("ownership", []):
            cname = (entry.get("company") or "").strip()
            if not cname:
                continue
            towers = entry.get("towers")
            try:
                towers = float(str(towers).replace(",", "")) if towers not in ("", None) else None
            except ValueError:
                return {"error": f"towers for '{cname}' must be numeric"}, 400
            ctype = entry.get("type") or "unknown"
            company_id = get_or_create_company(con, cname, ctype)
            if towers is not None:
                insert_towers_obs(con, company_id, cid, towers, year, quarter,
                                  verification, body.get("note") or entry.get("note"))
                added += 1
            if ctype in ("towerco", "jv-infraco"):
                con.execute("INSERT OR IGNORE INTO footprints VALUES (?,?,?)",
                            (company_id, cid, "manual entry"))
        con.commit()
        return {"ok": True, "added": added}
    except Exception as e:  # noqa: BLE001
        con.rollback()
        return {"error": str(e)}, 500
    finally:
        con.close()

def api_mno_observations_post(mno_id, body):
    """Bulk entry for one MNO: markets it is active in / owns towers in, and
    the towercos it leases from."""
    con = db()
    try:
        if not con.execute("SELECT 1 FROM companies WHERE id=? AND type='mno'",
                           (mno_id,)).fetchone():
            return {"error": "MNO not found"}, 404
        try:
            year, quarter = parse_as_of(body)
            verification = parse_verification(body)
        except (ValueError, TypeError) as e:
            return {"error": str(e)}, 400
        added = 0
        for entry in body.get("markets", []):
            cname = (entry.get("country") or "").strip()
            if not cname:
                continue
            country_id = get_or_create_country(con, cname)
            con.execute("INSERT OR IGNORE INTO mno_presences VALUES (?,?,?,?)",
                        (mno_id, country_id, "mno", "manual entry"))
            towers = entry.get("towers_owned", entry.get("towers"))
            try:
                towers = float(str(towers).replace(",", "")) if towers not in ("", None) else None
            except ValueError:
                return {"error": f"towers for '{cname}' must be numeric"}, 400
            if towers is not None and towers > 0:
                insert_towers_obs(con, mno_id, country_id, towers, year, quarter,
                                  verification, body.get("note") or entry.get("note"))
            added += 1
        for towerco_name in body.get("towercos", []):
            if not (towerco_name or "").strip():
                continue
            towerco_id = get_or_create_company(con, towerco_name, "towerco")
            mno_name = con.execute("SELECT name FROM companies WHERE id=?",
                                   (mno_id,)).fetchone()["name"]
            con.execute("INSERT OR IGNORE INTO anchor_tenancies VALUES (?,?,?,?)",
                        (towerco_id, mno_id, mno_name, "manual entry"))
        con.commit()
        con.execute("UPDATE companies SET last_updated=datetime('now') WHERE id=?", (mno_id,))
        con.commit()
        return {"ok": True, "markets_processed": added}
    except Exception as e:  # noqa: BLE001
        con.rollback()
        return {"error": str(e)}, 500
    finally:
        con.close()

def api_towerco_observations_post(towerco_id, body):
    """Bulk entry for one towerco: markets (towers per country) and known tenants."""
    con = db()
    try:
        if not con.execute(
                "SELECT 1 FROM companies WHERE id=? AND type IN ('towerco','jv-infraco')",
                (towerco_id,)).fetchone():
            return {"error": "towerco not found"}, 404
        try:
            year, quarter = parse_as_of(body)
            verification = parse_verification(body)
        except (ValueError, TypeError) as e:
            return {"error": str(e)}, 400
        added = 0
        for entry in body.get("markets", []):
            cname = (entry.get("country") or "").strip()
            if not cname:
                continue
            country_id = get_or_create_country(con, cname)
            con.execute("INSERT OR IGNORE INTO footprints VALUES (?,?,?)",
                        (towerco_id, country_id, "manual entry"))
            towers = entry.get("towers")
            try:
                towers = float(str(towers).replace(",", "")) if towers not in ("", None) else None
            except ValueError:
                return {"error": f"towers for '{cname}' must be numeric"}, 400
            if towers is not None:
                insert_towers_obs(con, towerco_id, country_id, towers, year, quarter,
                                  verification, body.get("note") or entry.get("note"))
            added += 1
        for tenant_name in body.get("tenants", []):
            tenant_name = (tenant_name or "").strip()
            if not tenant_name:
                continue
            tenant_id = get_or_create_company(con, tenant_name, "mno")
            con.execute("INSERT OR IGNORE INTO anchor_tenancies VALUES (?,?,?,?)",
                        (towerco_id, tenant_id, tenant_name, "manual entry"))
        con.execute("UPDATE companies SET last_updated=datetime('now') WHERE id=?",
                    (towerco_id,))
        con.commit()
        return {"ok": True, "markets_processed": added}
    except Exception as e:  # noqa: BLE001
        con.rollback()
        return {"error": str(e)}, 500
    finally:
        con.close()

def api_observations_post(body):
    metric = body.get("metric")
    if metric not in METRICS:
        return {"error": f"metric must be one of {METRICS}"}, 400
    segment = body.get("segment") or "all"
    if segment not in SEGMENTS:
        return {"error": f"segment must be one of {SEGMENTS}"}, 400
    value = body.get("value")
    value_text = body.get("value_text")
    if value is None and not value_text:
        return {"error": "value or value_text required"}, 400
    if value is not None:
        try:
            value = float(str(value).replace(",", ""))
        except ValueError:
            return {"error": "value must be numeric"}, 400
    year, quarter = body.get("as_of_year"), body.get("as_of_quarter")
    if year in ("", None, "unknown"):
        year, quarter = None, None
    else:
        try:
            year = int(year)
            quarter = int(quarter) if quarter not in ("", None) else None
        except ValueError:
            return {"error": "as_of_year/quarter must be integers"}, 400
        if not (1990 <= year <= 2100) or (quarter is not None and quarter not in (1, 2, 3, 4)):
            return {"error": "as_of period out of range"}, 400
    confidence = body.get("confidence") or "estimate"
    if confidence not in CONFIDENCES:
        return {"error": f"confidence must be one of {CONFIDENCES}"}, 400
    verification_level = body.get("verification_level") or "public_unverified"
    if verification_level not in DATA_QUALITY_LEVELS:
        return {"error": f"verification_level must be one of {list(DATA_QUALITY_LEVELS)}"}, 400

    con = db()
    country_id = company_id = None
    if body.get("country"):
        country_id = get_or_create_country(con, body["country"], body.get("iso3"),
                                           body.get("region"))
    if body.get("company"):
        company_id = get_or_create_company(con, body["company"], body.get("company_type"))
        if body.get("company_type"):
            con.execute("UPDATE companies SET type=?, last_updated=datetime('now') WHERE id=?",
                        (body["company_type"], company_id))
    if metric in ("towers", "market_share_pct") and (company_id is None or country_id is None):
        con.close()
        return {"error": f"metric '{metric}' needs both company and country"}, 400
    if metric == "towers_global" and company_id is None:
        con.close()
        return {"error": "towers_global needs a company"}, 400

    cur = con.execute(
        """INSERT INTO observations(company_id, country_id, metric, segment, value,
           value_text, as_of_year, as_of_quarter, source, confidence, note,
           is_override, verification_level, last_updated)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,datetime('now'))""",
        (company_id, country_id, metric, segment, value, value_text, year, quarter,
         body.get("source") or "manual entry", confidence, body.get("note"),
         verification_level))
    con.commit()
    oid = cur.lastrowid
    row = con.execute("SELECT * FROM observations WHERE id=?", (oid,)).fetchone()
    con.close()
    return {"ok": True, "observation": dict(row)}

def api_observation_delete(oid):
    con = db()
    r = con.execute("SELECT is_override FROM observations WHERE id=?", (oid,)).fetchone()
    if not r:
        con.close()
        return {"error": "not found"}, 404
    if not r["is_override"]:
        con.close()
        return {"error": "only manually entered rows can be deleted"}, 400
    con.execute("UPDATE observations SET deleted=1 WHERE id=?", (oid,))
    con.commit()
    con.close()
    return {"ok": True}

# ---------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _send(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _static(self, path, head_only=False):
        if path in ("/", "/index.html"):
            path = "/index.html"
        f = (STATIC / path.lstrip("/")).resolve()
        if not str(f).startswith(str(STATIC)) or not f.is_file():
            body = b"Not Found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head_only:
                self.wfile.write(body)
            return
        ctype = {"html": "text/html", "js": "application/javascript",
                 "css": "text/css", "json": "application/json",
                 "svg": "image/svg+xml", "png": "image/png"}.get(
            f.suffix.lstrip("."), "application/octet-stream")
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def do_HEAD(self):
        """Health checks (Render et al.) probe with HEAD — answer like GET, no body."""
        u = urlparse(self.path)
        if u.path.startswith("/api/"):
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._static(u.path, head_only=True)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            m = re.fullmatch(r"/api/country/(\d+)", u.path)
            if m:
                return self._reply(api_country(int(m.group(1)), q))
            m = re.fullmatch(r"/api/company/(\d+)", u.path)
            if m:
                return self._reply(api_company(int(m.group(1)), q))
            route = {
                "/api/meta": api_meta, "/api/league": api_league,
                "/api/mnos": api_mnos, "/api/countries": api_countries,
                "/api/map": api_map, "/api/compare": api_compare,
                "/api/search": api_search, "/api/observations": api_observations_list,
            }.get(u.path)
            if route:
                return self._reply(route(q))
            if u.path.startswith("/api/"):
                return self._send({"error": "unknown endpoint"}, 404)
            return self._static(u.path)
        except Exception as e:  # noqa: BLE001
            return self._send({"error": str(e)}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send({"error": "invalid JSON"}, 400)
        try:
            m = re.fullmatch(r"/api/country/(\d+)/observations", u.path)
            if m:
                return self._reply(api_country_observations_post(int(m.group(1)), body))
            m = re.fullmatch(r"/api/mno/(\d+)/observations", u.path)
            if m:
                return self._reply(api_mno_observations_post(int(m.group(1)), body))
            m = re.fullmatch(r"/api/towerco/(\d+)/observations", u.path)
            if m:
                return self._reply(api_towerco_observations_post(int(m.group(1)), body))
            m = re.fullmatch(r"/api/observations/(\d+)/delete", u.path)
            if m:
                return self._reply(api_observation_delete(int(m.group(1))))
            if u.path == "/api/observations":
                return self._reply(api_observations_post(body))
            return self._send({"error": "unknown endpoint"}, 404)
        except Exception as e:  # noqa: BLE001
            return self._send({"error": str(e)}, 500)

    def _reply(self, result):
        if isinstance(result, tuple):
            return self._send(result[0], result[1])
        return self._send(result)

def main():
    import os
    port = int(os.environ.get("PORT", 8000))   # hosting platforms set $PORT
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    if not DB_PATH.exists():
        sys.exit("data/gsma.db not found — run: python3 data/build_dataset.py && python3 data/build_db.py")
    print(f"Tower explorer on http://localhost:{port}  (db: {DB_PATH})")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()

if __name__ == "__main__":
    main()
