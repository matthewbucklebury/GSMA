"""Adapter registry: maps CLI source names to adapter classes.

Real adapters (anfr, fcc_asr, opencellid) are later sessions in the brief;
they are pre-declared here so the CLI gives a precise "not yet implemented"
message rather than "unknown source".
"""
from .anfr import AnfrAdapter
from .fcc_asr import FccAsrAdapter
from .stub import StubAdapter

ADAPTERS = {
    "stub": StubAdapter,
    "anfr": AnfrAdapter,
    "fcc_asr": FccAsrAdapter,
}

PLANNED = {
    "opencellid": "OpenCelliD market aggregates adapter (brief session 4)",
}


def get_adapter(name: str, snapshot_date: str = None):
    if name in ADAPTERS:
        return ADAPTERS[name](snapshot_date)
    if name in PLANNED:
        raise SystemExit(f"adapter '{name}' is not implemented yet: {PLANNED[name]}")
    raise SystemExit(
        f"unknown source '{name}'; available: {', '.join([*ADAPTERS, *PLANNED])}")
