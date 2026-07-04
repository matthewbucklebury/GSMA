"""FCC ASR adapter: registered US antenna structures (brief section 5.2).

Source: the FCC's weekly complete ASR bulk download (r_tower.zip of
headerless pipe-delimited .dat files). One structures row per registration:
RA.dat (registration attributes, heights in metres, structure type) joined
on unique system identifier to EN.dat owner entities (registrant name — the
headline payoff: direct portfolio mapping for American Tower, SBA, Crown
Castle et al.) and CO.dat tower coordinates (DMS components -> WGS84).

A deliberately partial register: only structures requiring FAA notice plus
voluntary registrations. coverage_status = covered_partial with the caveat
verbatim in coverage_note; every US Explorer view must surface it.
"""
import csv
import io
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd
import yaml

from ..common.adapter import BaseAdapter
from ..common.geo import dms_to_decimal

CONFIG = yaml.safe_load((Path(__file__).parent / "config.yaml").read_text())
FIELD_MAP = yaml.safe_load((Path(__file__).parent / "field_map.yaml").read_text())


def _records(zf: zipfile.ZipFile, member: str):
    """Yield pipe-split records from a headerless .dat member."""
    text = zf.read(member).decode(CONFIG["record_layout"]["encoding"])
    for line in text.splitlines():
        if line:
            yield line.split(CONFIG["record_layout"]["delimiter"])


def _iso_date(mdy):
    """MM/DD/YYYY -> YYYY-MM-DD, else None."""
    if not mdy or len(mdy) != 10:
        return None
    m, d, y = mdy[:2], mdy[3:5], mdy[6:]
    if not (m.isdigit() and d.isdigit() and y.isdigit()):
        return None
    return f"{y}-{m}-{d}"


class FccAsrAdapter(BaseAdapter):
    source = "fcc_asr"
    licence = CONFIG["licence"]
    refresh_cadence = CONFIG["refresh_cadence"]
    target_table = "structures"
    coverage = {"US": ("covered_partial", CONFIG["coverage_note"])}
    max_row_delta_pct = CONFIG["max_row_delta_pct"]
    mandatory_columns = ()   # headerless format: drift is caught by the
                             # per-record-type field-count checks instead

    # ---- fetch --------------------------------------------------------------
    def do_fetch(self, raw_path) -> int:
        import requests
        url = CONFIG["download"]["url"]
        dest = raw_path / CONFIG["raw_files"]["zip"]
        with requests.get(url, stream=True, timeout=180) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            done, next_mark = 0, 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if done >= next_mark:
                        if total:
                            print(f"\r  r_tower.zip: {done/1e6:6.1f}/{total/1e6:.1f} MB "
                                  f"({100*done/total:5.1f}%)",
                                  end="", file=sys.stderr, flush=True)
                        else:
                            print(f"\r  r_tower.zip: {done/1e6:6.1f} MB",
                                  end="", file=sys.stderr, flush=True)
                        next_mark += max(total // 20, 1 << 21)
            print(file=sys.stderr)
            (raw_path / "fetch_meta.json").write_text(json.dumps({
                "url": url,
                "bytes": done,
                "source_last_modified": r.headers.get("Last-Modified"),
            }, indent=2))
        return self.raw_row_count(raw_path)

    # ---- validate -----------------------------------------------------------
    def _zip(self, raw_path):
        return zipfile.ZipFile(raw_path / CONFIG["raw_files"]["zip"])

    def raw_row_count(self, raw_path):
        with self._zip(raw_path) as z:
            with z.open(CONFIG["zip_members"]["registration"]) as f:
                return sum(1 for _ in f)

    def do_validate(self, raw_path):
        checks = []
        with self._zip(raw_path) as z:
            present = set(z.namelist())
            missing = [m for m in FIELD_MAP["mandatory_members"] if m not in present]
            checks.append({"name": "zip_members", "passed": not missing,
                           "detail": f"missing: {missing}" if missing else
                                     f"all mandatory members present: "
                                     f"{FIELD_MAP['mandatory_members']}"})
            # schema drift on a positional format = field-count change
            for member, rectype in (("registration", "RA"), ("entity", "EN"),
                                    ("coordinates", "CO")):
                name = CONFIG["zip_members"][member]
                if name not in present:
                    continue
                expected = CONFIG["record_layout"]["field_counts"][rectype]
                bad = total = 0
                for i, rec in enumerate(_records(z, name)):
                    if i >= 5000:
                        break
                    total += 1
                    if len(rec) != expected:
                        bad += 1
                ok = total > 0 and bad / total < 0.01
                checks.append({
                    "name": f"{rectype}_field_count",
                    "passed": ok,
                    "detail": (f"{bad}/{total} sampled records deviate from the "
                               f"pinned {expected}-field layout"),
                })
        return checks

    # ---- normalise ----------------------------------------------------------
    def do_normalise(self, raw_path, normalised_path, quarantine_path) -> dict:
        ra_f = FIELD_MAP["ra_fields"]
        en_f = FIELD_MAP["en_fields"]
        co_f = FIELD_MAP["co_fields"]
        type_map = FIELD_MAP["structure_type_map"]
        status_map = FIELD_MAP["status_map"]

        with self._zip(raw_path) as z:
            owners = {}
            for rec in _records(z, CONFIG["zip_members"]["entity"]):
                if len(rec) > en_f["entity_name"] and \
                        rec[en_f["entity_type"]] == FIELD_MAP["en_owner_type"]:
                    owners[rec[en_f["unique_system_identifier"]]] = \
                        rec[en_f["entity_name"]].strip() or None
            coords = {}
            for rec in _records(z, CONFIG["zip_members"]["coordinates"]):
                if len(rec) > co_f["lon_dir"] and \
                        rec[co_f["coordinate_type"]] == FIELD_MAP["co_tower_type"]:
                    lat = dms_to_decimal(rec[co_f["lat_deg"]], rec[co_f["lat_min"]],
                                         rec[co_f["lat_sec"]], rec[co_f["lat_dir"]])
                    lon = dms_to_decimal(rec[co_f["lon_deg"]], rec[co_f["lon_min"]],
                                         rec[co_f["lon_sec"]], rec[co_f["lon_dir"]])
                    # 0/0/0 placeholders on terminated registrations are not
                    # real coordinates
                    if lat == 0 and lon == 0:
                        lat = lon = None
                    coords[rec[co_f["unique_system_identifier"]]] = (lat, lon)

            rows, quarantined = [], []
            for rec in _records(z, CONFIG["zip_members"]["registration"]):
                if len(rec) < CONFIG["record_layout"]["field_counts"]["RA"]:
                    quarantined.append({"raw": "|".join(rec),
                                        "quarantine_reason": "short RA record"})
                    continue
                usi = rec[ra_f["unique_system_identifier"]]
                reg = rec[ra_f["registration_number"]]
                lat, lon = coords.get(usi, (None, None))
                if lat is None or lon is None:
                    quarantined.append({
                        "registration_number": reg, "unique_system_identifier": usi,
                        "status_code": rec[ra_f["status_code"]],
                        "quarantine_reason": "no usable tower coordinates in CO.dat"})
                    continue
                raw_type = rec[ra_f["structure_type"]].strip() or None
                try:
                    height = float(rec[ra_f["overall_height_above_ground_m"]])
                except (TypeError, ValueError):
                    height = None
                status_code = rec[ra_f["status_code"]]
                record_date = (_iso_date(rec[ra_f["date_action"]])
                               or _iso_date(rec[ra_f["date_issued"]])
                               or _iso_date(rec[ra_f["date_entered"]]))
                rows.append({
                    "structure_uid": f"{self.source}:{reg}",
                    "source": self.source,
                    "source_record_id": reg,
                    "country_iso2": "US",
                    "lat": lat,
                    "lon": lon,
                    "structure_type": type_map.get(raw_type, "other"),
                    "structure_type_raw": raw_type,
                    "height_m": height,
                    "owner": owners.get(usi),
                    "operators": None,      # ASR does not record operators
                    "status": status_map.get(status_code, "other"),
                    "record_date": record_date,
                    "snapshot_date": self.snapshot_date,
                    "coverage_status": "covered_partial",
                })

        out = pd.DataFrame(rows)
        out.to_parquet(normalised_path / "structures.parquet", index=False)
        if quarantined:
            buf = io.StringIO()
            keys = sorted({k for q in quarantined for k in q})
            w = csv.DictWriter(buf, fieldnames=keys)
            w.writeheader()
            w.writerows(quarantined)
            (quarantine_path / "registrations.csv").write_text(buf.getvalue())
        return {"rows_normalised": len(out), "rows_quarantined": len(quarantined)}

    # ---- emit ---------------------------------------------------------------
    def do_emit(self, con, normalised_path) -> int:
        from ..common.store import replace_snapshot_rows
        df = pd.read_parquet(normalised_path / "structures.parquet")
        df = df.astype(object).where(pd.notna(df), None)
        return replace_snapshot_rows(con, "structures", self.source,
                                     self.snapshot_date, df.to_dict("records"))
