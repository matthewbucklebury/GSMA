"""JSON run log and validation report (brief section 6).

Every run writes a JSON run log: rows fetched, rows normalised, rows
quarantined, and deltas against the previous snapshot. Deltas above a
configured threshold fail the run for manual review.
"""
import json
from datetime import datetime, timezone

from .paths import run_log_dir


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunLog:
    """Accumulates per-stage results for one (source, snapshot_date) run."""

    def __init__(self, source: str, snapshot_date: str):
        self.source = source
        self.snapshot_date = snapshot_date
        self.started_at = _now()
        self.stages = {}
        self.deltas = {}
        self.status = "running"

    def record_stage(self, stage: str, **counts):
        self.stages[stage] = {"finished_at": _now(), "status": "ok", **counts}

    def record_failure(self, stage: str, error: str, **counts):
        self.stages[stage] = {"finished_at": _now(), "status": "failed",
                              "error": error, **counts}
        self.status = "failed"

    def record_deltas(self, previous_rows, current_rows, threshold_pct):
        d = {"previous_rows": previous_rows, "current_rows": current_rows,
             "threshold_pct": threshold_pct}
        if previous_rows:
            d["delta_pct"] = round(100 * (current_rows - previous_rows) / previous_rows, 2)
        self.deltas = d

    def path(self):
        return run_log_dir(self.source) / f"{self.snapshot_date}.json"

    def write(self):
        if self.status == "running":
            self.status = "ok" if all(
                s.get("status") == "ok" for s in self.stages.values()) else "failed"
        payload = {
            "source": self.source,
            "snapshot_date": self.snapshot_date,
            "started_at": self.started_at,
            "finished_at": _now(),
            "status": self.status,
            "stages": self.stages,
            "deltas": self.deltas,
        }
        p = self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2))
        return p


def previous_snapshot_rows(source: str, snapshot_date: str):
    """Rows fetched in the most recent earlier snapshot, for delta checks."""
    d = run_log_dir(source)
    if not d.exists():
        return None
    earlier = sorted(p for p in d.glob("*.json")
                     if p.stem < snapshot_date and not p.stem.endswith("validation"))
    for p in reversed(earlier):
        try:
            log = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        rows = log.get("stages", {}).get("fetch", {}).get("rows_fetched")
        if rows is not None:
            return rows
    return None


def write_validation_report(source: str, snapshot_date: str, passed: bool,
                            checks: list) -> "Path":
    """Pass/fail plus a readable per-check report (brief section 4, validate)."""
    p = run_log_dir(source) / f"{snapshot_date}.validation.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "source": source,
        "snapshot_date": snapshot_date,
        "written_at": _now(),
        "passed": passed,
        "checks": checks,
    }, indent=2))
    return p
