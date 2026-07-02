#!/usr/bin/env python3
"""Extract country tower-ownership pie charts + stat blocks from TowerXchange guides.

Method: legend swatch colour -> company label; pie slice colour -> legend colour;
numeric text angle from pie centre -> slice angular interval -> value assignment.
Verification: slice angular fraction vs value/total fraction.
"""
import fitz, re, json, math, sys

GUIDES = {
    "MENA":   ("MENA guide[1].pdf",   7,  "Q1 2025"),
    "LATAM":  ("LATAM guide[1].pdf",  6,  "Q2 2025"),
    "Europe": ("Europe guide[1].pdf", 8,  "Q2 2025"),
    "Asia":   ("Asia guide[1].pdf",   8,  "Q4 2024"),
    "Africa": ("Africa guide[1].pdf", 11, "Q2 2025"),
}
# last country page per guide (to skip trailing transaction/heatmap figures)
LAST_PAGE = {"MENA": 31, "LATAM": 32, "Europe": 47, "Asia": 34, "Africa": 43}

def ckey(c):
    return tuple(round(x, 3) for x in c) if c else None

def cdist(a, b):
    return max(abs(x - y) for x, y in zip(a, b))

def hexc(c):
    return "#%02x%02x%02x" % tuple(int(round(x * 255)) for x in c)

GREYISH = lambda c: abs(c[0]-c[1]) < 0.05 and abs(c[1]-c[2]) < 0.05

def sample_points(items):
    pts = []
    for it in items:
        kind = it[0]
        if kind == "l":
            pts += [it[1], it[2]]
        elif kind == "c":
            p0, p1, p2, p3 = it[1], it[2], it[3], it[4]
            for t in (0, .2, .4, .6, .8, 1):
                x = (1-t)**3*p0.x + 3*(1-t)**2*t*p1.x + 3*(1-t)*t*t*p2.x + t**3*p3.x
                y = (1-t)**3*p0.y + 3*(1-t)**2*t*p1.y + 3*(1-t)*t*t*p2.y + t**3*p3.y
                pts.append(fitz.Point(x, y))
        elif kind == "re":
            r = it[1]
            pts += [fitz.Point(r.x0, r.y0), fitz.Point(r.x1, r.y1),
                    fitz.Point(r.x0, r.y1), fitz.Point(r.x1, r.y0)]
    return pts

def angular_interval(pts, cx, cy):
    """(span_deg, mid_deg) of angular interval covered by points, wrap-safe."""
    angs = sorted(set(round(math.degrees(math.atan2(p.y - cy, p.x - cx)) % 360, 1)
                      for p in pts if math.hypot(p.x - cx, p.y - cy) > 4))
    if not angs:
        return None
    if len(angs) == 1:
        return (2.0, angs[0])
    gaps = [((angs[(i+1) % len(angs)] - angs[i]) % 360, i) for i in range(len(angs))]
    biggest, imax = max(gaps)
    if biggest < 15:  # full circle
        return (360.0, None)
    span = 360 - biggest
    start = angs[(imax + 1) % len(angs)]
    mid = (start + span / 2) % 360
    return (round(span, 1), round(mid, 1))

def get_spans(page):
    spans = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b["lines"]:
            for s in l["spans"]:
                spans.append(s)
    return spans

def extract_pies(page, kind="count", stated_total=None):
    """Return list of pies found on the page (usually 0 or 1)."""
    draws = page.get_drawings()
    swatches, fills = [], []
    for dr in draws:
        f = dr.get("fill")
        if not f or min(f) > 0.85:  # skip white / near-white
            continue
        r = dr["rect"]
        kinds = [i[0] for i in dr["items"]]
        if kinds == ["re"] and 6 <= r.width <= 16 and 6 <= r.height <= 16:
            swatches.append({"rect": r, "color": ckey(f)})
        elif "c" in kinds and r.width >= 2 and r.height >= 2 and (r.width > 20 or r.height > 20):
            fills.append({"rect": r, "color": ckey(f), "items": dr["items"]})
    if not swatches or not fills:
        return []
    spans = get_spans(page)
    # legend labels: nearest text right of swatch on same row
    legend = []
    for sw in swatches:
        r = sw["rect"]
        cands = [s for s in spans
                 if 0 <= s["bbox"][0] - r.x1 <= 18
                 and abs((s["bbox"][1] + s["bbox"][3]) / 2 - (r.y0 + r.y1) / 2) < 7]
        if not cands:
            continue
        cands.sort(key=lambda s: s["bbox"][0])
        label = cands[0]["text"]
        x_end = cands[0]["bbox"][2]
        for s in cands[1:]:
            if s["bbox"][0] - x_end < 10:
                label += " " + s["text"]
                x_end = s["bbox"][2]
        legend.append({"color": sw["color"], "label": re.sub(r"\s+", " ", label).strip(),
                       "rect": r})
    if not legend:
        return []
    legend_colors = [l["color"] for l in legend]
    slices = [f for f in fills
              if min(cdist(f["color"], lc) for lc in legend_colors) < 0.02]
    if not slices:
        return []
    # true centre = path point shared by the most slices (wedges meet at centre)
    from collections import Counter
    cnt = Counter()
    for s in slices:
        seen = set()
        for it in s["items"]:
            if it[0] == "l":
                for pt in (it[1], it[2]):
                    seen.add((round(pt.x), round(pt.y)))
        for p_ in seen:
            cnt[p_] += 1
    centre = None
    if cnt:
        (mx, my), mc = cnt.most_common(1)[0]
        if mc >= max(2, len(slices) // 2):
            centre = (float(mx), float(my))
    if centre:
        # keep only wedges anchored at the centre (drops flags/icons that
        # happen to share a legend colour elsewhere on the page)
        def anchored(s):
            for it in s["items"]:
                if it[0] == "l":
                    for pt in (it[1], it[2]):
                        if math.hypot(pt.x - centre[0], pt.y - centre[1]) < 6:
                            return True
            return fitz.Rect(s["rect"]).contains(fitz.Point(*centre))
        slices = [s for s in slices if anchored(s)]
    if not slices:
        return []
    ub = fitz.Rect(slices[0]["rect"])
    for s in slices[1:]:
        ub |= s["rect"]
    cx, cy = (ub.x0 + ub.x1) / 2, (ub.y0 + ub.y1) / 2
    radius = max(ub.width, ub.height) / 2
    if centre and math.hypot(centre[0] - cx, centre[1] - cy) < radius * 0.6:
        cx, cy = centre
    # merge slices by legend colour
    slice_pts = {}
    for s in slices:
        key = min(legend_colors, key=lambda lc: cdist(s["color"], lc))
        slice_pts.setdefault(key, []).extend(sample_points(s["items"]))
    entries = []
    legend_only = []
    min_r = radius * 0.25
    for l in legend:
        if l["color"] not in slice_pts:
            legend_only.append(l)
            continue
        dists = [math.hypot(p_.x - cx, p_.y - cy) for p_ in slice_pts[l["color"]]]
        pts = [p_ for p_, d_ in zip(slice_pts[l["color"]], dists) if d_ > min_r]
        ai = angular_interval(pts, cx, cy)
        if not ai:
            continue
        keep = [d_ for d_ in dists if d_ > min_r]
        entries.append({"label": l["label"], "color": hexc(l["color"]),
                        "span": ai[0], "mid": ai[1],
                        "rmin": min(keep), "rmax": max(keep)})
    if not entries:
        return []
    numbered = sum(bool(re.match(r"\d+\.", e["label"])) for e in entries) >= 2
    if numbered:
        return [{"center": [round(cx), round(cy)], "radius": round(radius),
                 "numbered": True, "entries": entries, "unused_nums": []}]
    # candidate numeric spans near pie
    def collect_nums(k):
        out = []
        for s in spans:
            t = s["text"].strip()
            if k == "share":
                m = re.fullmatch(r"<?(\d+(?:\.\d+)?)%", t)
            else:
                m = re.fullmatch(r"\+?(\d{1,3}(?:,\d{3})*|\d+)", t)
            if not m:
                continue
            val = float(m.group(1).replace(",", ""))
            if k != "share" and val >= 1_000_000:
                continue
            if k == "share" and val > 100:
                continue
            x = (s["bbox"][0] + s["bbox"][2]) / 2
            y = (s["bbox"][1] + s["bbox"][3]) / 2
            dist = math.hypot(x - cx, y - cy)
            if dist <= radius * 1.6:
                ang = math.degrees(math.atan2(y - cy, x - cx)) % 360
                out.append({"text": t, "val": val, "ang": ang, "dist": dist,
                            "approx": t.startswith("+")})
        return out
    nums = collect_nums(kind)
    if kind == "share" and not nums:  # e.g. Nepal: "market share" caption, count values
        kind = "count"
        nums = collect_nums("count")
    # Assignment: bipartite matching combining angular deviation (numbers sit
    # at slice mid, possibly fanned out on leader lines), a radial-band check
    # (distinguishes inner/outer ring slices in two-ring charts), and fraction
    # deviation (value/total vs slice angular share).
    def assign(denom):
        pairs = []
        for ei, e in enumerate(entries):
            for ni, n in enumerate(nums):
                dev = 0.0 if e["mid"] is None else abs((n["ang"] - e["mid"] + 180) % 360 - 180)
                limit = 360 if e["span"] >= 355 else max(e["span"] / 2 + 8, 14)
                if dev > limit:
                    continue
                if not (e["rmin"] * 0.4 <= n["dist"] <= e["rmax"] * 1.75):
                    continue
                cost = dev / 15.0
                if denom and kind != "share":
                    cost += abs(n["val"] / denom - e["span"] / 360) * 40
                pairs.append((cost, dev, ei, ni))
        pairs.sort()
        used_e, used_n, out = set(), set(), {}
        for cost, dev, ei, ni in pairs:
            if ei in used_e or ni in used_n:
                continue
            used_e.add(ei); used_n.add(ni)
            out[ei] = (ni, dev)
        return out, used_n
    denom = stated_total or sum(n["val"] for n in nums)
    res, used_n = assign(denom)
    got = sum(nums[ni]["val"] for ni, _ in res.values())
    if stated_total and got and abs(got - stated_total) / stated_total > 0.15:
        # stated country total disagrees with the chart; re-run using chart sum
        res, used_n = assign(got)
        got = sum(nums[ni]["val"] for ni, _ in res.values())
    for ei, (ni, dev) in res.items():
        entries[ei]["value_text"] = nums[ni]["text"]
        entries[ei]["value"] = nums[ni]["val"]
        entries[ei]["ang_dev"] = round(dev, 1)
        if nums[ni]["approx"]:
            entries[ei]["approx"] = True
    # residual inference when exactly one slice lacks a value and total known
    missing = [e for e in entries if "value" not in e]
    have = sum(e.get("value", 0) for e in entries)
    if len(missing) == 1 and stated_total and stated_total > have:
        e = missing[0]
        resid = stated_total - have
        if e["span"] and abs(resid / stated_total - e["span"] / 360) < 0.05:
            e["value"] = resid
            e["value_text"] = f"{resid:,.0f}"
            e["inferred"] = True
    # legend colour with no detected wedge (sliver too thin): assign leftover
    # number if it matches the residual vs the stated total
    if len(legend_only) == 1 and stated_total:
        have2 = sum(e.get("value", 0) for e in entries)
        resid = stated_total - have2
        for i, n in enumerate(nums):
            if i not in used_n and resid > 0 and abs(n["val"] - resid) / stated_total < 0.02:
                l = legend_only[0]
                entries.append({"label": l["label"], "color": hexc(l["color"]),
                                "span": None, "mid": None, "value": n["val"],
                                "value_text": n["text"], "sliver": True})
                used_n.add(i)
                break
    # fraction verification (prefer stated country total as denominator)
    allv = sum(e.get("value", 0) for e in entries)
    total = stated_total if stated_total else allv
    if not total or (allv and abs(allv - total) / total > 0.25):
        total = allv
    for e in entries:
        if "value" in e and e.get("span") and total > 0:
            vf = e["value"] / total
            af = e["span"] / 360
            e["frac_value"] = round(vf, 3)
            e["frac_angle"] = round(af, 3)
            e["frac_ok"] = abs(vf - af) < 0.05
    for e in entries:
        e.pop("rmin", None); e.pop("rmax", None)
    return [{"center": [round(cx), round(cy)], "radius": round(radius),
             "entries": entries, "stated_total": stated_total, "kind": kind,
             "unused_nums": [n["text"] for i, n in enumerate(nums) if i not in used_n]}]

STAT_RE = {
    "towers_total": r"Towers:\s*\n?\s*([\d,\.]+(?:mn)?(?:\s*[-–]\s*[\d,\.]+(?:mn)?)?)",
    "population": r"Population:\s*\n?\s*([\d,\.]+\s*mn?)",
    "subscribers": r"Subscribers:\s*\n?\s*([\d,\.]+\s*mn?)",
    "sims_per_tower": r"SIMs per tower:\s*\n?\s*([\d,]+)",
    "sim_penetration": r"SIM penetration:?\s*\n?\s*([\d\.]+%)",
    "mnos": r"MNOs:\s*(.+?)(?=\s(?:Towerco activity:|Towercos?:|ESCOs?:|Towers:|Figure|SIMs per tower|SIM penetration|Source:)|$)",
    "towerco_activity": r"(?:Towerco activity|Towercos):\s*(.+?)(?=\s(?:MNOs:|ESCOs?:|Towers:|Figure|SIMs per tower|SIM penetration|Source:)|$)",
}

def extract_stats(text):
    out = {}
    for k, pat in STAT_RE.items():
        m = re.search(pat, text, re.S)
        if m:
            v = re.sub(r"\s+", " ", m.group(1)).strip()
            out[k] = v
    return out

def heading_country(text, region):
    lines = [l.strip() for l in text.split("\n")]
    hdr = {"MENA": "MENA", "LATAM": "LATAM", "Europe": "EUROPE",
           "Asia": "ASIA", "Africa": "AFRICA"}[region]
    for i, l in enumerate(lines[:10]):
        if l.upper() == hdr and i + 1 < len(lines):
            nxt = lines[i + 1]
            if (nxt and len(nxt) < 32 and not nxt.startswith("Figure")
                    and not any(ch.isdigit() for ch in nxt)
                    and nxt.upper() != "REGIONAL GUIDE"):
                return nxt.strip()
    return None

CAPTION_RE = re.compile(
    r"Figure \d+:\s*([^\n]+?)\s*[–\-—]\s*"
    r"(estimated tower (?:count|ownership)|MNO market share|pre-war tower estimates"
    r"|Estimated tower ownership)", re.I)

def main():
    result = {}
    for region, (fname, start, pub) in GUIDES.items():
        doc = fitz.open(fname)
        pages = []
        for i in range(start, min(LAST_PAGE[region] + 1, len(doc))):
            page = doc[i]
            text = page.get_text()
            cap = CAPTION_RE.search(text)
            stats = extract_stats(text)
            country_h = heading_country(text, region)
            kind = "share" if cap and "market share" in cap.group(2).lower() else "count"
            st = None
            if "towers_total" in stats:
                m = re.match(r"[\d,]+$", stats["towers_total"])
                if m:
                    st = float(stats["towers_total"].replace(",", ""))
            pies = extract_pies(page, kind, st)
            if not (cap or stats or pies):
                continue
            pages.append({
                "page": i,
                "caption_country": cap.group(1).strip() if cap else None,
                "caption_kind": cap.group(2).strip() if cap else None,
                "heading_country": country_h,
                "stats": stats,
                "pie": pies[0] if pies else None,
            })
        result[region] = {"file": fname, "publication": pub, "pages": pages}
    json.dump(result, open(sys.argv[1], "w"), indent=1, ensure_ascii=False)
    nflag = 0
    for region, r in result.items():
        print("=" * 20, region)
        for p in r["pages"]:
            pie = p["pie"]
            line = (f" p{p['page']:3d} {str(p['caption_country'] or p['heading_country']):20.20s} ")
            if pie and pie.get("numbered"):
                line += f"pie:{len(pie['entries'])} NUMBERED (needs override)"
                print(line)
                continue
            if pie:
                probs = [e for e in pie["entries"] if "value" not in e or not e.get("frac_ok", True)]
                line += f"pie:{len(pie['entries'])} "
                if probs:
                    nflag += 1
                    line += "FLAG " + "; ".join(
                        f"{e['label']}={e.get('value_text','?')}(a{e.get('frac_angle','?')}/v{e.get('frac_value','?')})"
                        for e in probs)
                if pie["unused_nums"]:
                    line += f" unused={pie['unused_nums']}"
            else:
                line += "pie:-"
            print(line)
    print("flagged pies:", nflag)

if __name__ == "__main__":
    main()
