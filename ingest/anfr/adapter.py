"""ANFR adapter: French radio-site structures (brief section 5.1).

Source: ANFR's bulk open-data export "Données sur les installations
radioélectriques de plus de 5 watts", published monthly on data.gouv.fr as
two ZIPs (data tables + reference lookups). See config.yaml for what was
verified and pinned at build time, and field_map.yaml for every raw-column
mapping.

Shape of the data: SUP_SUPPORT has one row per (support, station) pair, so a
physical structure appears once per station it hosts. Normalise groups by
support id (one structures row per support), converts the DMS coordinate
components to WGS84 decimal degrees, maps the nature lookup to
structure_type (raw label retained), and populates operators as the
semicolon list of distinct operators across the support's stations — which
is exactly the set of operators across its transmitters, since every
transmitter belongs to a station and the station carries the operator.
"""
import io
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd
import yaml

from ..common.adapter import BaseAdapter

CONFIG = yaml.safe_load((Path(__file__).parent / "config.yaml").read_text())
FIELD_MAP = yaml.safe_load((Path(__file__).parent / "field_map.yaml").read_text())


def _read_table(zf: zipfile.ZipFile, member: str) -> pd.DataFrame:
    raw = zf.read(member)
    csv_cfg = CONFIG["csv"]
    try:
        text = raw.decode(csv_cfg["encoding"])
    except UnicodeDecodeError:
        text = raw.decode(csv_cfg["encoding_fallback"])
    return pd.read_csv(io.StringIO(text), sep=csv_cfg["delimiter"], dtype=str)


def dms_to_decimal(deg, minute, sec, direction):
    """DMS components -> signed WGS84 decimal degrees; None if unusable."""
    def num(x, default=None):
        if x is None or (isinstance(x, float) and x != x) or x == "":
            return default
        try:
            v = float(x)
        except (TypeError, ValueError):
            return None
        return None if v != v else v          # NaN guard (pandas blanks)
    d = num(deg)
    m = num(minute, 0.0)
    s = num(sec, 0.0)
    if d is None or m is None or s is None:
        return None
    if direction not in ("N", "S", "E", "W"):
        return None
    if not (0 <= m < 60 and 0 <= s < 60):
        return None
    value = d + m / 60 + s / 3600
    if direction in ("S", "W"):
        value = -value
    if abs(value) > 180 or (direction in ("N", "S") and abs(value) > 90):
        return None
    return round(value, 6)


class AnfrAdapter(BaseAdapter):
    source = "anfr"
    licence = CONFIG["licence"]
    refresh_cadence = CONFIG["refresh_cadence"]
    target_table = "structures"
    coverage = {"FR": ("covered_full",
                       "ANFR authorises every radio site in France; complete "
                       "structure-level register (installations > 5 watts), "
                       "including overseas territories under FR")}
    max_row_delta_pct = CONFIG["max_row_delta_pct"]
    mandatory_columns = tuple(FIELD_MAP["mandatory_support_columns"])

    # ---- fetch --------------------------------------------------------------
    def resolve_resources(self):
        """Latest data+ref ZIP URLs via the data.gouv.fr dataset API."""
        import re
        import requests
        disc = CONFIG["discovery"]
        r = requests.get(disc["api_url"], timeout=60)
        r.raise_for_status()
        resources = r.json()["resources"]
        months = {m: i + 1 for i, m in enumerate(
            ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
             "aout", "septembre", "octobre", "novembre", "decembre"])}
        def vintage(title):
            """(year, month) parsed from the French title; portals sometimes
            touch old resources' last_modified, so the title is the truth."""
            t = (title or "").lower().replace("é", "e").replace("û", "u")
            m = re.search(r"(janvier|fevrier|mars|avril|mai|juin|juillet|aout"
                          r"|septembre|octobre|novembre|decembre)\s+(\d{4})", t)
            return (int(m.group(2)), months[m.group(1)]) if m else (0, 0)
        def newest(pattern):
            # titles are inconsistent about accents across vintages
            pat = re.compile(pattern.replace("é", "[eé]"), re.IGNORECASE)
            hits = [res for res in resources
                    if pat.search(res.get("title") or "")
                    or pat.search((res.get("title") or "").replace("é", "e"))]
            if not hits:
                raise RuntimeError(
                    f"no resource matching {pattern!r} on {disc['dataset_page']}; "
                    f"the portal layout may have changed — re-verify config.yaml")
            return max(hits, key=lambda res: (vintage(res.get("title")),
                                              res.get("last_modified") or ""))
        return (newest(disc["data_resource_title_pattern"]),
                newest(disc["ref_resource_title_pattern"]))

    @staticmethod
    def _stream_download(url, dest: Path, label: str):
        import requests
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            next_mark = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if total and done >= next_mark:
                        pct = 100 * done / total
                        print(f"\r  {label}: {done/1e6:6.1f}/{total/1e6:.1f} MB "
                              f"({pct:5.1f}%)", end="", file=sys.stderr, flush=True)
                        next_mark += max(total // 20, 1 << 20)
            if total:
                print(file=sys.stderr)
        return done

    def do_fetch(self, raw_path) -> int:
        data_res, ref_res = self.resolve_resources()
        files = CONFIG["raw_files"]
        self._stream_download(data_res["url"], raw_path / files["data_zip"],
                              data_res["title"])
        self._stream_download(ref_res["url"], raw_path / files["ref_zip"],
                              ref_res["title"])
        (raw_path / "fetch_meta.json").write_text(json.dumps({
            "data_resource": {k: data_res.get(k) for k in
                              ("title", "url", "last_modified", "filesize")},
            "ref_resource": {k: ref_res.get(k) for k in
                             ("title", "url", "last_modified", "filesize")},
        }, indent=2, ensure_ascii=False))
        return self.raw_row_count(raw_path)

    # ---- validate -----------------------------------------------------------
    def _data_zip(self, raw_path):
        return zipfile.ZipFile(raw_path / CONFIG["raw_files"]["data_zip"])

    def _ref_zip(self, raw_path):
        return zipfile.ZipFile(raw_path / CONFIG["raw_files"]["ref_zip"])

    def raw_columns(self, raw_path):
        with self._data_zip(raw_path) as z:
            with z.open(CONFIG["zip_members"]["data"]["support"]) as f:
                header = f.readline().decode(CONFIG["csv"]["encoding"], "replace")
        return [c.strip() for c in header.rstrip("\r\n").split(CONFIG["csv"]["delimiter"])]

    def raw_row_count(self, raw_path):
        with self._data_zip(raw_path) as z:
            with z.open(CONFIG["zip_members"]["data"]["support"]) as f:
                return sum(1 for _ in f) - 1

    def do_validate(self, raw_path):
        checks = []
        members = CONFIG["zip_members"]
        with self._data_zip(raw_path) as z:
            present = set(z.namelist())
        missing = [m for m in members["data"].values() if m not in present]
        checks.append({"name": "data_zip_members", "passed": not missing,
                       "detail": f"missing: {missing}" if missing else
                                 f"all {len(members['data'])} data tables present"})
        with self._ref_zip(raw_path) as z:
            present = set(z.namelist())
        missing = [m for m in members["ref"].values() if m not in present]
        checks.append({"name": "ref_zip_members", "passed": not missing,
                       "detail": f"missing: {missing}" if missing else
                                 f"all {len(members['ref'])} lookup tables present"})
        with self._data_zip(raw_path) as z:
            member = members["data"]["station"]
            if member in z.namelist():
                station_cols = _read_table(z, member).columns
                missing = [c for c in FIELD_MAP["mandatory_station_columns"]
                           if c not in station_cols]
                checks.append({"name": "station_columns", "passed": not missing,
                               "detail": f"missing: {missing}" if missing else
                                         "all mandatory station columns present"})
            else:
                checks.append({"name": "station_columns", "passed": False,
                               "detail": f"{member} absent; cannot check columns"})
        return checks

    # ---- normalise ----------------------------------------------------------
    def do_normalise(self, raw_path, normalised_path, quarantine_path) -> dict:
        members = CONFIG["zip_members"]
        sup_cols = FIELD_MAP["support_columns"]
        sta_cols = FIELD_MAP["station_columns"]
        with self._data_zip(raw_path) as z:
            support = _read_table(z, members["data"]["support"])
            station = _read_table(z, members["data"]["station"])
        with self._ref_zip(raw_path) as z:
            nature = _read_table(z, members["ref"]["nature"])
            proprietaire = _read_table(z, members["ref"]["proprietaire"])
            exploitant = _read_table(z, members["ref"]["exploitant"])

        nature_map = dict(zip(nature["NAT_ID"], nature["NAT_LB_NOM"]))
        owner_map = dict(zip(proprietaire["TPO_ID"], proprietaire["TPO_LB"]))
        operator_map = dict(zip(exploitant["ADM_ID"], exploitant["ADM_LB_NOM"]))
        type_map = FIELD_MAP["structure_type_map"]

        # station -> (operator name, in-service flag, best date)
        station = station.copy()
        station["_operator"] = station[sta_cols["operator_id"]].map(operator_map)
        station["_in_service"] = station[sta_cols["in_service"]].notna() & \
            (station[sta_cols["in_service"]].astype(str).str.strip() != "")
        def _iso_date(s):
            dt = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
            return dt.dt.strftime("%Y-%m-%d")
        station["_date"] = _iso_date(station[sta_cols["modified"]]).fillna(
            _iso_date(station[sta_cols["implanted"]]))
        sta_info = station.groupby(sta_cols["station"]).agg(
            _operators=("_operator", lambda s: sorted({x for x in s if pd.notna(x)})),
            _any_in_service=("_in_service", "any"),
            _record_date=("_date", "max"),
        )

        quarantined = []
        out_rows = {}
        for sup_id, grp in support.groupby(sup_cols["id"], sort=False):
            first = grp.iloc[0]
            lat = dms_to_decimal(first[sup_cols["lat_deg"]], first[sup_cols["lat_min"]],
                                 first[sup_cols["lat_sec"]], first[sup_cols["lat_dir"]])
            lon = dms_to_decimal(first[sup_cols["lon_deg"]], first[sup_cols["lon_min"]],
                                 first[sup_cols["lon_sec"]], first[sup_cols["lon_dir"]])
            if lat is None or lon is None:
                row = first.to_dict()
                row["quarantine_reason"] = "invalid or missing DMS coordinates"
                quarantined.append(row)
                continue
            stations = [s for s in grp[sup_cols["station"]].dropna().unique()]
            ops, in_service, rec_date = set(), False, None
            for s in stations:
                if s in sta_info.index:
                    info = sta_info.loc[s]
                    ops.update(info["_operators"])
                    in_service = in_service or bool(info["_any_in_service"])
                    if info["_record_date"] and (rec_date is None or
                                                 info["_record_date"] > rec_date):
                        rec_date = info["_record_date"]
            rules = FIELD_MAP["status_rules"]
            status = (rules["in_service"] if in_service else
                      rules["not_in_service"] if stations else rules["no_station"])
            raw_type = nature_map.get(str(first[sup_cols["nature_id"]]))
            try:
                height = float(first[sup_cols["height_m"]])
            except (TypeError, ValueError):
                height = None
            out_rows[sup_id] = {
                "structure_uid": f"{self.source}:{sup_id}",
                "source": self.source,
                "source_record_id": str(sup_id),
                "country_iso2": "FR",
                "lat": lat,
                "lon": lon,
                "structure_type": type_map.get(raw_type, "other"),
                "structure_type_raw": raw_type,
                "height_m": height,
                "owner": owner_map.get(str(first[sup_cols["proprietor_id"]])),
                "operators": ";".join(sorted(ops)) if ops else None,
                "status": status,
                "record_date": rec_date,
                "snapshot_date": self.snapshot_date,
                "coverage_status": "covered_full",
            }

        out = pd.DataFrame(list(out_rows.values()))
        out.to_parquet(normalised_path / "structures.parquet", index=False)
        if quarantined:
            pd.DataFrame(quarantined).to_csv(
                quarantine_path / "supports.csv", index=False)
        return {"rows_normalised": len(out), "rows_quarantined": len(quarantined)}

    # ---- emit ---------------------------------------------------------------
    def do_emit(self, con, normalised_path) -> int:
        from ..common.store import replace_snapshot_rows
        df = pd.read_parquet(normalised_path / "structures.parquet")
        df = df.astype(object).where(pd.notna(df), None)
        return replace_snapshot_rows(con, "structures", self.source,
                                     self.snapshot_date, df.to_dict("records"))
