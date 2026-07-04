"""Filesystem layout for the ingest layer (brief section 6).

All artefacts live under a single data root:

    data/raw/{source}/{snapshot_date}/         raw snapshots, retained forever
    data/normalised/{source}/{snapshot_date}/  parquet output of normalise
    data/quarantine/{source}/{snapshot_date}/  unmappable rows plus reason
    data/run_logs/{source}/                    JSON run logs and validation reports
    data/ingest.db                             SQLite Explorer store (three tables)

The root defaults to <repo>/data but can be overridden with the
INGEST_DATA_ROOT environment variable, which is how the test harness points
everything at a temporary directory.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def data_root() -> Path:
    override = os.environ.get("INGEST_DATA_ROOT")
    return Path(override) if override else REPO_ROOT / "data"


def raw_dir(source: str, snapshot_date: str) -> Path:
    return data_root() / "raw" / source / snapshot_date


def normalised_dir(source: str, snapshot_date: str) -> Path:
    return data_root() / "normalised" / source / snapshot_date


def quarantine_dir(source: str, snapshot_date: str) -> Path:
    return data_root() / "quarantine" / source / snapshot_date


def run_log_dir(source: str) -> Path:
    return data_root() / "run_logs" / source


def store_path() -> Path:
    return data_root() / "ingest.db"
