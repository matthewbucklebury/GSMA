"""Shared ingest CLI (brief section 4):

    python -m ingest {source} {stage} --date YYYY-MM-DD
    python -m ingest {source} --all   --date YYYY-MM-DD

Stages are separately runnable so failures are isolated; --all runs the full
fetch -> validate -> normalise -> emit pipeline. --date defaults to today.
Re-running any stage for the same date overwrites that date's output and
nothing else.
"""
import argparse
import re
import sys

from .common.adapter import STAGES, IngestError
from .registry import ADAPTERS, PLANNED, get_adapter


def build_parser():
    p = argparse.ArgumentParser(
        prog="python -m ingest",
        description="Tower Explorer data ingest pipeline")
    p.add_argument("source", help=f"source adapter ({', '.join([*ADAPTERS, *PLANNED])})")
    p.add_argument("stage", nargs="?", choices=STAGES,
                   help="single stage to run (omit when using --all)")
    p.add_argument("--all", action="store_true", dest="run_all",
                   help="run the full pipeline: " + " -> ".join(STAGES))
    p.add_argument("--date", default=None, metavar="YYYY-MM-DD",
                   help="snapshot date (default: today)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if bool(args.stage) == bool(args.run_all):
        print("error: give exactly one of a stage or --all", file=sys.stderr)
        return 2
    if args.date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        print(f"error: --date must be YYYY-MM-DD, got {args.date!r}", file=sys.stderr)
        return 2
    adapter = get_adapter(args.source, args.date)
    try:
        if args.run_all:
            result = adapter.run_all()
            print(f"{adapter.source} {adapter.snapshot_date}: pipeline complete "
                  f"({result})")
        else:
            out = getattr(adapter, args.stage)()
            print(f"{adapter.source} {adapter.snapshot_date}: {args.stage} ok ({out})")
            if args.stage != "emit":     # emit writes the run log itself
                adapter.run_log.write()
    except IngestError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0
