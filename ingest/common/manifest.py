"""source_manifest writer (brief sections 2 and 3.3).

Every adapter declares the markets it covers; this writer enumerates the
adapter against *all* ISO 3166 markets so that absence of remit is stored as
an explicit not_covered row rather than silent absence. The Explorer can then
distinguish "no infrastructure", "not covered by this source" and "no data
yet" — three states a naive implementation collapses into one.
"""
from datetime import datetime, timezone

from .countries import ISO_MARKETS, COVERAGE_STATUSES


def write_manifest(con, source: str, coverage: dict, licence: str,
                   refresh_cadence: str, default_note: str = "") -> int:
    """Upsert one row per ISO market for this source.

    coverage: {country_iso2: (coverage_status, coverage_note)} for covered
    markets; every other ISO market gets an explicit not_covered row.
    Returns the number of rows written.
    """
    for iso2, (status, _note) in coverage.items():
        if status not in COVERAGE_STATUSES:
            raise ValueError(f"bad coverage_status {status!r} for {iso2}")
        if iso2 not in ISO_MARKETS:
            raise ValueError(f"unknown ISO market {iso2!r} in coverage for {source}")
    rows = []
    for iso2 in ISO_MARKETS:
        status, note = coverage.get(
            iso2, ("not_covered", default_note or
                   f"{source} has no remit in this market; empty set by design"))
        rows.append((source, iso2, status, note, licence, refresh_cadence))
    con.executemany(
        """INSERT INTO source_manifest
             (source, country_iso2, coverage_status, coverage_note,
              licence, refresh_cadence)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(source, country_iso2) DO UPDATE SET
             coverage_status=excluded.coverage_status,
             coverage_note=excluded.coverage_note,
             licence=excluded.licence,
             refresh_cadence=excluded.refresh_cadence""",
        rows)
    return len(rows)


def mark_ingest(con, source: str) -> None:
    """Stamp source_manifest.last_ingest after a successful emit."""
    con.execute("UPDATE source_manifest SET last_ingest=? WHERE source=?",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), source))


def coverage_for(con, source: str, country_iso2: str):
    """Explicit-empty-result lookup: returns the manifest row for a market."""
    return con.execute(
        """SELECT coverage_status, coverage_note FROM source_manifest
           WHERE source=? AND country_iso2=?""", (source, country_iso2)).fetchone()
