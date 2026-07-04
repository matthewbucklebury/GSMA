"""Stub adapter: exercises every part of the common layer with no network.

It fabricates a deterministic raw CSV of fake structures (including two
deliberately unmappable rows), normalises them to the standard structures
schema with quarantine, and emits to the store. It exists so the test harness
and CLI can be proven before any real adapter is written (brief section 8,
session 1), and stays useful afterwards as a smoke test.
"""
import csv

import pandas as pd

from .common.adapter import BaseAdapter

FAKE_ROWS = 100          # mappable rows generated
BAD_ROWS = 2             # rows with missing coordinates -> quarantined


class StubAdapter(BaseAdapter):
    source = "stub"
    licence = "None (synthetic test data)"
    refresh_cadence = "monthly"
    target_table = "structures"
    coverage = {"FR": ("covered_full", "Synthetic test market")}
    mandatory_columns = ("record_id", "latitude", "longitude", "kind", "height_ft")
    max_row_delta_pct = 50.0

    def do_fetch(self, raw_path) -> int:
        rows = []
        for i in range(FAKE_ROWS):
            rows.append({
                "record_id": f"STUB-{i:04d}",
                "latitude": 43.0 + i * 0.01,
                "longitude": 1.0 + i * 0.01,
                "kind": ["Pylone", "Tour hertzienne", "Chateau d'eau"][i % 3],
                "height_ft": 100 + i,
                "proprietor": ["TDF", "ATC France", "Cellnex FR"][i % 3],
                "ops": "Orange;SFR" if i % 2 else "Bouygues Telecom",
                "state": "En service" if i % 5 else "Projet approuvé",
                "updated": "2026-06-01",
            })
        for i in range(BAD_ROWS):  # unmappable: no coordinates
            rows.append({"record_id": f"STUB-BAD-{i}", "latitude": "", "longitude": "",
                         "kind": "??", "height_ft": "", "proprietor": "", "ops": "",
                         "state": "", "updated": ""})
        out = raw_path / "structures.csv"
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        return len(rows)

    # ---- validate helpers ---------------------------------------------------
    def _raw_file(self, raw_path):
        return raw_path / "structures.csv"

    def raw_columns(self, raw_path):
        with open(self._raw_file(raw_path), newline="") as f:
            return next(csv.reader(f))

    def raw_row_count(self, raw_path):
        with open(self._raw_file(raw_path), newline="") as f:
            return sum(1 for _ in f) - 1

    # ---- normalise -----------------------------------------------------------
    KIND_MAP = {"Pylone": "pylon", "Tour hertzienne": "tower",
                "Chateau d'eau": "water_tower"}
    STATE_MAP = {"En service": "active", "Projet approuvé": "granted"}

    def do_normalise(self, raw_path, normalised_path, quarantine_path) -> dict:
        df = pd.read_csv(self._raw_file(raw_path))
        bad = df[df["latitude"].isna() | df["longitude"].isna()].copy()
        good = df.drop(bad.index)
        out = pd.DataFrame({
            "structure_uid": self.source + ":" + good["record_id"].astype(str),
            "source": self.source,
            "source_record_id": good["record_id"].astype(str),
            "country_iso2": "FR",
            "lat": good["latitude"].astype(float),
            "lon": good["longitude"].astype(float),
            "structure_type": good["kind"].map(self.KIND_MAP).fillna("other"),
            "structure_type_raw": good["kind"],
            "height_m": (good["height_ft"].astype(float) * 0.3048).round(2),
            "owner": good["proprietor"],
            "operators": good["ops"],
            "status": good["state"].map(self.STATE_MAP).fillna("other"),
            "record_date": good["updated"],
            "snapshot_date": self.snapshot_date,
            "coverage_status": "covered_full",
        })
        out.to_parquet(normalised_path / "structures.parquet", index=False)
        if len(bad):
            bad["quarantine_reason"] = "missing coordinates"
            bad.to_csv(quarantine_path / "structures.csv", index=False)
        return {"rows_normalised": len(out), "rows_quarantined": len(bad)}

    # ---- emit -----------------------------------------------------------------
    def do_emit(self, con, normalised_path) -> int:
        from .common.store import replace_snapshot_rows
        df = pd.read_parquet(normalised_path / "structures.parquet")
        rows = df.to_dict("records")
        return replace_snapshot_rows(con, "structures", self.source,
                                     self.snapshot_date, rows)
