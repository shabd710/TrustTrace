"""
Detection -> CampaignGraph ingestion.

This closes the gap identified in review: the analyze path computed grounded
flags but NOTHING ever called CampaignGraph.record_incident(), so the graph
the dashboard reads from (`/v1/campaign-graph`) stayed permanently empty.

Two responsibilities, kept deliberately separate and honest:

1. record_detection(): when a transcript analysis surfaces >= 1 grounded
   flag, extract the CORRELATABLE PATTERNS it contains -- phone numbers,
   crypto wallets, and a script-pattern hash of the normalized text -- and
   record them as ONE incident. This records PATTERNS, never tactic labels
   and never raw transcript text: the graph's whole contract
   (community_feed.py / campaign_graph.py) is that it holds anonymized,
   correlatable indicators gated behind the k-anonymity floor before
   anything is exposed. This function upholds that floor -- it does NOT
   lower K_ANONYMITY_FLOOR.

2. seed_demo_campaign(): OPT-IN, dev/demo only (guarded by the
   TRUSTTRACE_SEED_DEMO_CAMPAIGN env var). By design the dashboard exposes
   only links corroborated by >= K_ANONYMITY_FLOOR (5) INDEPENDENT incidents
   -- so a single real detection can never, by itself, surface a link. To
   let the dashboard actually render in a demo WITHOUT weakening that
   privacy floor, this seeds 5 independent synthetic incidents that
   legitimately CROSS the floor. It changes no thresholds; unset the env var
   and the graph is populated only by real corroborated traffic.
"""
from __future__ import annotations
import hashlib
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "threat-intel"))

from community_feed import CommunityReport, PatternKind  # noqa: E402

# Phone: 8+ digits allowing separators, so "+1 415-555-0142" and
# "4155550142" both normalize to the same digit string below.
_PHONE_RE = re.compile(r"\+?\d(?:[\d\-\s().]{6,})\d")
# Crypto: BTC bech32 / legacy, and 0x EVM addresses.
_CRYPTO_RE = re.compile(r"\b(?:bc1[a-z0-9]{20,}|0x[a-fA-F0-9]{40}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")


def _script_hash(text: str) -> str:
    """A hash of the NORMALIZED script text -- lets the same reused scam
    script correlate across independent reports without ever storing the
    raw transcript (community_feed.py's anonymity contract)."""
    normalized = " ".join(text.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def extract_patterns(text: str, category: str = "unknown") -> list[CommunityReport]:
    """Pull correlatable indicators out of a flagged transcript. Always
    includes the script hash (so recurring scripts correlate even with no
    phone/wallet present); a phone or wallet, when present, gives the
    incident a second node so an EDGE can form."""
    now = time.time()
    reports: list[CommunityReport] = []
    seen: set[tuple[str, str]] = set()

    for m in _PHONE_RE.findall(text):
        digits = re.sub(r"\D", "", m)
        if len(digits) >= 8 and ("phone", digits) not in seen:
            seen.add(("phone", digits))
            reports.append(CommunityReport(PatternKind.PHONE_NUMBER, digits, category, now, "server-ingest"))

    for w in _CRYPTO_RE.findall(text):
        if ("crypto", w) not in seen:
            seen.add(("crypto", w))
            reports.append(CommunityReport(PatternKind.CRYPTO_WALLET, w, category, now, "server-ingest"))

    reports.append(CommunityReport(PatternKind.SCRIPT_HASH, _script_hash(text), category, now, "server-ingest"))
    return reports


def record_detection(graph, text: str, category: str = "unknown") -> str | None:
    """Record one incident's worth of patterns from a transcript that
    surfaced >= 1 grounded flag. Returns the incident_id, or None if there
    was nothing correlatable to record (there always is -- the script hash
    -- but kept defensive)."""
    reports = extract_patterns(text, category)
    if not reports:
        return None
    return graph.record_incident(reports)


def seed_demo_campaign(graph) -> None:
    """Dev/demo only: seed enough INDEPENDENT corroborating incidents that a
    link legitimately clears the k-anonymity floor, so the dashboard renders
    real (non-empty) output. Does not touch K_ANONYMITY_FLOOR. No-op unless
    TRUSTTRACE_SEED_DEMO_CAMPAIGN is set."""
    if not os.environ.get("TRUSTTRACE_SEED_DEMO_CAMPAIGN"):
        return
    now = time.time()
    # A single reused tech-support script + call-back number, reported by 5
    # independent devices -> the (script_hash, phone) link crosses the floor.
    shared = [
        CommunityReport(PatternKind.SCRIPT_HASH, "demo_techsupport_script_0001", "tech_support_scam", now, "seed"),
        CommunityReport(PatternKind.PHONE_NUMBER, "18005550142", "tech_support_scam", now, "seed"),
    ]
    for i in range(5):
        graph.record_incident(shared, incident_id=f"demo-incident-{i}")
