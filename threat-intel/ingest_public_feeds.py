"""
Public feed ingestion: FTC/IC3 case-pattern summaries, GASA reports, EFF
Coalition Against Stalkerware indicator feed.

Spec ref: PDF Target Environment. This file's real job is parsing
external feed formats into this codebase's internal shapes
(CommunityReport for scam patterns, raw signature strings for
detection/device/stalkerware_signatures.py) -- it deliberately has NO
actual network fetch call in this sandbox (no network access here, and
more importantly, hitting real third-party feed endpoints from example
code isn't something to bake into a demo module). The parsing logic below
is real; the fetch step is a clearly-marked seam.
"""
from __future__ import annotations
from dataclasses import dataclass

from community_feed import CommunityReport, PatternKind


@dataclass
class FeedFetchError(Exception):
    source: str
    detail: str


def fetch_raw_feed(source_url: str) -> str:
    """
    SEAM: in production this performs an authenticated HTTPS GET against
    the configured feed partner endpoint (EFF/GASA/FTC-IC3 mirror, per
    institutional partnership agreements -- spec Section 6). Raises here
    rather than silently returning fake data, since a stubbed "successful"
    fetch that actually did nothing would be a worse failure mode than an
    honest error.
    """
    raise FeedFetchError(source=source_url, detail="No network access configured in this environment; wire a real HTTP client + credentials here in a deployed build.")


def parse_ic3_style_csv_line(line: str) -> CommunityReport | None:
    """
    Parses one line of a simplified IC3-style CSV export:
    `pattern_kind,pattern_value,category,epoch,attestation_token`
    Real parsing logic (type coercion, validation, malformed-row handling)
    -- just fed synthetic/local input in this sandbox instead of a live
    feed, per the fetch_raw_feed() seam above.
    """
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 5:
        return None
    kind_raw, value, category, epoch_raw, attestation = parts
    try:
        kind = PatternKind(kind_raw)
        epoch = float(epoch_raw)
    except ValueError:
        return None
    return CommunityReport(pattern_kind=kind, pattern_value=value, category=category,
                            reported_epoch=epoch, device_attestation_token=attestation)


def parse_feed_csv(raw_csv: str) -> list[CommunityReport]:
    reports = []
    for line in raw_csv.strip().splitlines():
        if not line or line.startswith("#"):
            continue
        parsed = parse_ic3_style_csv_line(line)
        if parsed is not None:
            reports.append(parsed)
    return reports
