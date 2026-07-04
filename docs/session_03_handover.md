# Session 3 handover — FCC ASR adapter

Date: 2026-07-04 · Scope: brief §5.2 (FCC ASR United States) on the common
layer. Status: **complete** — all done-when criteria met.

## What was verified against the live source, and what was pinned

All pinned in `ingest/fcc_asr/config.yaml` + `field_map.yaml`:

1. **The historic bulk route works exactly as the brief describes:**
   `https://data.fcc.gov/download/pub/uls/complete/r_tower.zip`, weekly full
   replace (observed file dated Sunday 2026-06-28, 37.4 MB compressed).
2. **ZIP members:** `counts` (row manifest), `RA.dat` (registrations,
   196,677 rows, 49 fields), `EN.dat` (entities, 25 fields), `CO.dat`
   (coordinates, 18 fields), plus `HS.dat`/`RE.dat`/`SC.dat` retained raw and
   unparsed. All pipe-delimited, headerless, latin-1.
3. **Field positions were pinned empirically, not from the data dictionary.**
   fcc.gov's documentation endpoints (`pubacc_asr_intro.pdf`, `patower.xls`)
   were unreachable at build time (503/timeouts). Positions were derived from
   the live extract and cross-verified: structure-type column identified by
   its code vocabulary (TOWER/GTOWER/POLE… on 96% of populated values),
   height columns by internal consistency (ground elevation + height above
   ground = height AMSL), date columns by MM/DD/YYYY shape, coordinate
   columns by valid DMS ranges resolving to US territory. Confirm against
   the official data dictionary when fcc.gov is reachable (open item 1).
4. **Heights are metres, as the brief suspected** — median overall height
   61.8 m (the 200 ft ≈ 61 m registration threshold showing through) and
   max 608 m (the tallest US masts); a feet reading is physically
   implausible. No conversion needed.
5. **Coordinates live in `CO.dat`** (record type `T` = tower location, `A` =
   array point), not in the registration file as the brief sketched. DMS
   components convert via the shared `ingest.common.geo.dms_to_decimal`
   (moved out of the ANFR adapter this session). Terminated registrations
   often carry 0/0 placeholders — treated as "no usable coordinates" and
   quarantined with that reason.
6. **Join keys verified on the full extract:** registration numbers unique
   across all 196,677 RA rows; owner entities (`EN` type `O`) exist for
   196,663; tower coordinates for 196,648.

## Divergences from the brief

| Brief said | Found / done |
|---|---|
| Registration file contains coordinates | Coordinates are a separate record type (`CO.dat`), joined on unique system identifier |
| Confirm .dat names and height units at build time | Done: names as listed above; heights metres (evidence in config comments) |
| "Ingest all statuses, normalise" | Status codes observed: C 141,463 / G 18,254 / A 15,628 / I 12,415 / T 8,904. Mapped C→active, G→granted, T→dismantled; **A and I map to `other`** because the FCC codes document was unreachable to confirm their meanings (open item 2) |
| — (discovered) | Registrants file under many legal entities: Crown Castle and SBA appear as dozens of LLCs (CCATT LLC, Crown Castle South LLC, SBA 2012 TC Assets LLC…). Owner strings are stored verbatim; entity rollup is reconciliation-phase work, deliberately out of POC scope |

## What was built

- `ingest/fcc_asr/` — config (pinned URL, members, per-record field counts,
  US-Gov public-domain licence, weekly cadence, 10% delta threshold),
  field_map (every position used, structure-type map, status map), adapter
  (streaming fetch with progress + Last-Modified provenance; validate =
  member presence + per-record-type field-count drift checks, the
  positional-format equivalent of mandatory columns; normalise = RA⋈EN(O)⋈
  CO(T) with DMS→WGS84 and quarantine; emit with `covered_partial` US
  manifest carrying the completeness caveat **verbatim**).
- `ingest/common/geo.py` — `dms_to_decimal` promoted from the ANFR adapter;
  both adapters share it.
- `tests/fixtures/fcc_asr/r_tower.zip` — real stratified extract (300
  registrations across all five status codes + their EN/CO rows, ~70 KB).
  7 tests: dates, full pipeline (owner ≥95%, no operators, metre heights,
  US bounds, type/status mapping), manifest caveat verbatim + Germany
  `not_covered`, quarantine reasons, member/layout-drift validation
  failures, idempotent re-run.
- **Structural no-network guard**: an autouse pytest fixture now fails any
  test that opens a non-loopback socket. Added after a registry update made
  an old CLI test *actually download* the 37 MB file mid-suite — the
  "no network in tests" rule is now enforced by the harness, not by
  discipline.

## Real-run results (2026-07-04, 2026-06-28 weekly file)

- **196,648 US structures** loaded; 29 quarantined (no usable coordinates);
  **owner populated on 99.3%**.
- Top constructed-structure registrants: American Towers LLC 16,544 ·
  Cellco Partnership 5,360 · CCATT LLC 4,838 · Array Digital Infrastructure
  3,954 · Tillman Infrastructure 2,383 · Crown Castle South 2,234 ·
  SBA 2012 TC Assets 2,016 — the direct portfolio-mapping payoff the brief
  called out.
- Status: 141,460 active / 18,254 granted / 8,900 dismantled / 28,034 other.
  Types: 131,047 tower / 45,619 mast / 3,064 rooftop / 1,097 water_tower.
- Manifest: US `covered_partial` with the FAA-notice caveat verbatim;
  Germany `not_covered`. The store now holds ANFR (FR) and FCC ASR (US)
  side by side, source-tagged.
- pytest: 29 passed, 1 skipped, ~2.6 s, offline enforced.

## Open items

1. Cross-check the empirically pinned RA/EN/CO field positions against the
   official FCC data dictionary (`patower.xls` / `pubacc_asr_intro.pdf`)
   when fcc.gov stops 503ing; positions live in one YAML file if anything
   needs adjusting.
2. Confirm the meaning of ASR status codes `A` and `I` (currently → `other`,
   28k rows) from the FCC codes document; remap if they turn out to be
   constructed/granted variants.
3. US territories (PR, GU, VI…) are registered with state codes but kept as
   `country_iso2 = US` — same decision as ANFR's overseas territories;
   revisit when the Explorer map work lands (session 5).
4. Owner entity rollup (Crown Castle's/SBA's many LLCs → parent) is
   reconciliation-phase work, explicitly out of POC scope per brief §1.1.
5. `HS.dat` (registration history) is retained raw; it could later provide
   dismantle dates for lifecycle analysis.
