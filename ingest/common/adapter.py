"""Base adapter class implementing the four-stage contract (brief section 4).

Each source adapter subclasses BaseAdapter and implements the four do_*
hooks. The base class owns everything the stages share: directory layout,
idempotency (re-running a stage for a date overwrites that date's output and
nothing else), the validation report, delta checks against the previous
snapshot, the store write, the source_manifest update, and the JSON run log.

Stages (each separately runnable so failures are isolated):

  fetch      pull raw data, no transformation      -> data/raw/{source}/{date}/
  validate   check raw payload against expectations -> pass/fail + JSON report
  normalise  map raw to the standard model; quarantine unmappable rows
                                                   -> data/normalised/... (parquet)
  emit       write to the Explorer store, stamp source_manifest.last_ingest,
             write the run log

Common rules enforced here:
  * raw snapshots are retained; normalise re-runs never re-fetch
  * every output row carries source and snapshot_date
  * secrets come from environment variables (ingest.common.secrets) and are
    never written to any file
"""
import shutil
from datetime import date as _date

from . import store as store_mod
from .manifest import write_manifest, mark_ingest
from .paths import raw_dir, normalised_dir, quarantine_dir
from .runlog import RunLog, previous_snapshot_rows, write_validation_report

STAGES = ("fetch", "validate", "normalise", "emit")


class IngestError(RuntimeError):
    """Raised when a stage fails in a way that needs manual review."""


class ValidationFailure(IngestError):
    """Raised when validate finds the raw payload unacceptable."""


class BaseAdapter:
    # ---- subclass declarations -------------------------------------------
    source = None                 # adapter identifier, e.g. "anfr"
    licence = ""                  # licence string + attribution requirement
    refresh_cadence = ""          # weekly | monthly | quarterly
    target_table = "structures"   # structures | market_cell_stats
    # coverage: {ISO2: (coverage_status, coverage_note)}; every other ISO
    # market is written to the manifest as not_covered.
    coverage = {}
    # validate fails the run when fetched row count moves more than this
    # percentage against the previous snapshot (brief section 6).
    max_row_delta_pct = 50.0
    # raw columns that must be present for validate to pass
    mandatory_columns = ()

    def __init__(self, snapshot_date: str = None):
        if not self.source:
            raise ValueError("adapter must declare a source id")
        self.snapshot_date = snapshot_date or _date.today().isoformat()
        self.run_log = RunLog(self.source, self.snapshot_date)

    # ---- directories ------------------------------------------------------
    @property
    def raw_path(self):
        return raw_dir(self.source, self.snapshot_date)

    @property
    def normalised_path(self):
        return normalised_dir(self.source, self.snapshot_date)

    @property
    def quarantine_path(self):
        return quarantine_dir(self.source, self.snapshot_date)

    @staticmethod
    def _reset(path):
        """Idempotency: clear this snapshot date's output, nothing else."""
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    # ---- hooks for subclasses ---------------------------------------------
    def do_fetch(self, raw_path) -> int:
        """Write raw files into raw_path; return the row count fetched."""
        raise NotImplementedError

    def do_validate(self, raw_path) -> list:
        """Return a list of check dicts: {name, passed, detail}.

        The base class adds the mandatory-column and row-delta checks; put
        source-specific checks here.
        """
        return []

    def raw_columns(self, raw_path) -> list:
        """Column names of the primary raw payload (for the mandatory check)."""
        return []

    def raw_row_count(self, raw_path) -> int:
        """Row count of the primary raw payload (for the delta check)."""
        raise NotImplementedError

    def do_normalise(self, raw_path, normalised_path, quarantine_path) -> dict:
        """Map raw to the standard model; write parquet + quarantine files.

        Return {"rows_normalised": int, "rows_quarantined": int}.
        """
        raise NotImplementedError

    def do_emit(self, con, normalised_path) -> int:
        """Write normalised rows to the store; return rows written.

        Use store.replace_snapshot_rows for idempotent snapshot replacement.
        """
        raise NotImplementedError

    # ---- stages -----------------------------------------------------------
    def fetch(self) -> int:
        self._reset(self.raw_path)
        try:
            rows = self.do_fetch(self.raw_path)
        except Exception as e:
            self.run_log.record_failure("fetch", str(e))
            self.run_log.write()
            raise
        self.run_log.record_stage("fetch", rows_fetched=rows)
        return rows

    def validate(self) -> bool:
        if not self.raw_path.exists():
            raise IngestError(
                f"no raw snapshot for {self.source} {self.snapshot_date}; run fetch first")
        checks = []
        cols = list(self.raw_columns(self.raw_path))
        missing = [c for c in self.mandatory_columns if c not in cols]
        checks.append({
            "name": "mandatory_columns",
            "passed": not missing,
            "detail": f"missing: {missing}" if missing else
                      f"all {len(self.mandatory_columns)} mandatory columns present",
        })
        rows = self.raw_row_count(self.raw_path)
        prev = previous_snapshot_rows(self.source, self.snapshot_date)
        self.run_log.record_deltas(prev, rows, self.max_row_delta_pct)
        if prev:
            delta_pct = abs(100 * (rows - prev) / prev)
            checks.append({
                "name": "row_count_delta",
                "passed": delta_pct <= self.max_row_delta_pct,
                "detail": (f"{rows} rows vs {prev} previously "
                           f"({delta_pct:.1f}% change, threshold "
                           f"{self.max_row_delta_pct}%)"),
            })
        else:
            checks.append({"name": "row_count_delta", "passed": True,
                           "detail": f"{rows} rows; no previous snapshot to compare"})
        checks.extend(self.do_validate(self.raw_path))
        passed = all(c["passed"] for c in checks)
        report = write_validation_report(self.source, self.snapshot_date, passed, checks)
        if not passed:
            failed = [c["name"] for c in checks if not c["passed"]]
            self.run_log.record_failure("validate", f"checks failed: {failed}",
                                        rows_validated=rows)
            self.run_log.write()
            raise ValidationFailure(
                f"validation failed for {self.source} {self.snapshot_date}: "
                f"{failed}; see {report}")
        self.run_log.record_stage("validate", rows_validated=rows)
        return True

    def normalise(self) -> dict:
        if not self.raw_path.exists():
            raise IngestError(
                f"no raw snapshot for {self.source} {self.snapshot_date}; run fetch first")
        self._reset(self.normalised_path)
        self._reset(self.quarantine_path)
        try:
            counts = self.do_normalise(self.raw_path, self.normalised_path,
                                       self.quarantine_path)
        except Exception as e:
            self.run_log.record_failure("normalise", str(e))
            self.run_log.write()
            raise
        self.run_log.record_stage("normalise", **counts)
        return counts

    def emit(self) -> int:
        if not self.normalised_path.exists():
            raise IngestError(
                f"no normalised output for {self.source} {self.snapshot_date}; "
                f"run normalise first")
        con = store_mod.connect()
        try:
            written = self.do_emit(con, self.normalised_path)
            write_manifest(con, self.source, self.coverage, self.licence,
                           self.refresh_cadence)
            mark_ingest(con, self.source)
            con.commit()
        except Exception as e:
            con.rollback()
            self.run_log.record_failure("emit", str(e))
            self.run_log.write()
            raise
        finally:
            con.close()
        self.run_log.record_stage("emit", rows_emitted=written)
        self.run_log.write()
        return written

    def run_all(self) -> dict:
        """fetch -> validate -> normalise -> emit for this snapshot date."""
        self.fetch()
        self.validate()
        counts = self.normalise()
        written = self.emit()
        return {"rows_emitted": written, **counts}
