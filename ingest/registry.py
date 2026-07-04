"""Adapter registry: maps CLI source names to adapter classes."""
from .anfr import AnfrAdapter
from .fcc_asr import FccAsrAdapter
from .opencellid import OpenCellIdAdapter
from .stub import StubAdapter

ADAPTERS = {
    "stub": StubAdapter,
    "anfr": AnfrAdapter,
    "fcc_asr": FccAsrAdapter,
    "opencellid": OpenCellIdAdapter,
}

PLANNED = {
}


def get_adapter(name: str, snapshot_date: str = None):
    if name in ADAPTERS:
        return ADAPTERS[name](snapshot_date)
    if name in PLANNED:
        raise SystemExit(f"adapter '{name}' is not implemented yet: {PLANNED[name]}")
    raise SystemExit(
        f"unknown source '{name}'; available: {', '.join([*ADAPTERS, *PLANNED])}")
