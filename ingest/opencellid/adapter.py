"""OpenCelliD adapter: market-level cell statistics only (brief section 5.3).

Source: the OpenCelliD bulk full export (cell_towers.csv.gz), fetched with an
API key read from the OPENCELLID_API_KEY environment variable at the moment
of the request and never persisted anywhere.

The design point of this adapter is what it does NOT keep: the raw file
necessarily contains coordinates, but normalise never even loads the lon/lat
columns (pandas usecols) and no output — parquet, quarantine, store, logs —
contains location-level data. Aggregation is GROUP BY mcc, net, radio ->
cell_count / sample_count / latest_update, joined to the static MCC lookups
committed in this directory. If location-level ingest is ever wanted, that
is a new adapter decision, not a config flag.

Counts are observation-driven (crowdsourced); the caveat travels in
source_manifest.coverage_note for every market, all of which are
covered_partial at best. Licence CC BY-SA 4.0 with required attribution.
"""
import gzip
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

from ..common.adapter import BaseAdapter
from ..common.countries import ISO_MARKETS
from ..common.secrets import get_secret

CONFIG = yaml.safe_load((Path(__file__).parent / "config.yaml").read_text())
HERE = Path(__file__).parent


def _load_lookups():
    country = pd.read_csv(HERE / CONFIG["lookups"]["mcc_country"], comment="#")
    operator = pd.read_csv(HERE / CONFIG["lookups"]["mcc_mnc_operator"], comment="#")
    return (dict(zip(country["mcc"], country["country_iso2"])),
            dict(zip(zip(operator["mcc"], operator["mnc"]),
                     operator["operator_name"])))


class OpenCellIdAdapter(BaseAdapter):
    source = "opencellid"
    licence = CONFIG["licence"]
    refresh_cadence = CONFIG["refresh_cadence"]
    target_table = "market_cell_stats"
    # coverage is data-driven: set during normalise/emit to covered_partial
    # for every market present in the export, not_covered otherwise.
    coverage = {}
    max_row_delta_pct = CONFIG["max_row_delta_pct"]
    mandatory_columns = tuple(CONFIG["csv"]["columns"])

    # ---- fetch --------------------------------------------------------------
    def do_fetch(self, raw_path) -> int:
        import requests
        token = get_secret(CONFIG["download"]["token_env_var"])
        params = dict(CONFIG["download"]["params"])
        params["token"] = token
        url = CONFIG["download"]["url"]
        dest = raw_path / CONFIG["raw_files"]["export"]
        try:
            with requests.get(url, params=params, stream=True, timeout=300) as r:
                r.raise_for_status()
                first = next(r.iter_content(chunk_size=1 << 16), b"")
                if first.lstrip()[:1] == b"{":
                    # API error body (e.g. INVALID_TOKEN) arrives as JSON 200
                    msg = first[:200].decode("utf-8", "replace")
                    raise RuntimeError(f"OpenCelliD API refused the download: {msg}")
                total = int(r.headers.get("Content-Length") or 0)
                done = len(first)
                next_mark = 0
                with open(dest, "wb") as f:
                    f.write(first)
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                        done += len(chunk)
                        if done >= next_mark:
                            if total:
                                print(f"\r  cell_towers.csv.gz: {done/1e6:7.1f}/"
                                      f"{total/1e6:.1f} MB ({100*done/total:5.1f}%)",
                                      end="", file=sys.stderr, flush=True)
                            else:
                                print(f"\r  cell_towers.csv.gz: {done/1e6:7.1f} MB",
                                      end="", file=sys.stderr, flush=True)
                            next_mark += 1 << 22
                print(file=sys.stderr)
        except requests.RequestException as e:
            # requests exceptions can embed the full URL including the token —
            # re-raise with the secret scrubbed
            raise RuntimeError(
                f"OpenCelliD download failed: {type(e).__name__}: "
                f"{str(e).replace(token, '<redacted>')}") from None
        (raw_path / "fetch_meta.json").write_text(json.dumps({
            "url": f"{url}?token=<redacted>&type={params['type']}&file={params['file']}",
            "bytes": dest.stat().st_size,
        }, indent=2))
        return self.raw_row_count(raw_path)

    # ---- validate -----------------------------------------------------------
    def _export_path(self, raw_path):
        return raw_path / CONFIG["raw_files"]["export"]

    def raw_columns(self, raw_path):
        with gzip.open(self._export_path(raw_path), "rt") as f:
            return [c.strip() for c in f.readline().rstrip("\r\n").split(",")]

    def raw_row_count(self, raw_path):
        with gzip.open(self._export_path(raw_path), "rt") as f:
            return sum(1 for _ in f) - 1

    # ---- normalise ----------------------------------------------------------
    def do_normalise(self, raw_path, normalised_path, quarantine_path) -> dict:
        mcc_country, mcc_mnc_operator = _load_lookups()
        usecols = CONFIG["csv"]["usecols"]      # lon/lat never loaded
        agg = {}
        reader = pd.read_csv(
            self._export_path(raw_path), usecols=usecols,
            chunksize=CONFIG["csv"]["chunk_rows"],
            dtype={"radio": str, "mcc": "Int64", "net": "Int64",
                   "samples": "Int64", "updated": "Int64"})
        for chunk in reader:
            # one export row per cell (the export is the cell table)
            g = chunk.groupby(["mcc", "net", "radio"], dropna=True).agg(
                cell_count=("radio", "size"),
                sample_count=("samples", "sum"),
                latest_update=("updated", "max"))
            for key, row in g.iterrows():
                if key in agg:
                    a = agg[key]
                    a[0] += int(row["cell_count"])
                    a[1] += int(row["sample_count"] or 0)
                    a[2] = max(a[2], int(row["latest_update"] or 0))
                else:
                    agg[key] = [int(row["cell_count"]),
                                int(row["sample_count"] or 0),
                                int(row["latest_update"] or 0)]

        rows, quarantined = [], []
        for (mcc, net, radio), (cells, samples, updated) in sorted(agg.items()):
            country = mcc_country.get(int(mcc))
            latest = (pd.Timestamp(updated, unit="s").strftime("%Y-%m-%d")
                      if updated else None)
            rec = {
                "country_iso2": country,
                "mcc": int(mcc),
                "mnc": int(net),
                "operator_name": mcc_mnc_operator.get((int(mcc), int(net))),
                "radio": radio,
                "cell_count": cells,
                "sample_count": samples,
                "latest_update": latest,
                "snapshot_date": self.snapshot_date,
                "source": self.source,
            }
            if country is None:
                rec["quarantine_reason"] = (
                    f"MCC {mcc} not in the committed mcc_country lookup")
                quarantined.append(rec)
            else:
                rows.append(rec)

        out = pd.DataFrame(rows)
        out.to_parquet(normalised_path / "market_cell_stats.parquet", index=False)
        if quarantined:
            pd.DataFrame(quarantined).to_csv(
                quarantine_path / "unmapped_mcc.csv", index=False)
        return {"rows_normalised": len(out), "rows_quarantined": len(quarantined)}

    # ---- emit ---------------------------------------------------------------
    def do_emit(self, con, normalised_path) -> int:
        from ..common.store import replace_snapshot_rows
        df = pd.read_parquet(normalised_path / "market_cell_stats.parquet")
        df = df.astype(object).where(pd.notna(df), None)
        # data-driven coverage: every market present in this export is
        # covered_partial (crowdsourced); the base class writes not_covered
        # rows for the rest of the ISO list.
        note = CONFIG["coverage_note"]
        present = {c for c in df["country_iso2"].unique() if c in ISO_MARKETS}
        self.coverage = {c: ("covered_partial", note) for c in sorted(present)}
        return replace_snapshot_rows(con, "market_cell_stats", self.source,
                                     self.snapshot_date, df.to_dict("records"))
