"""
Community-sourced, opt-in, anonymized pattern/hash feed intake.

Spec ref: PDF Target Environment + Section 2.7: seeded from FTC/IC3
case-pattern summaries, GASA reports, and the EFF Coalition Against
Stalkerware indicator feed.

Consent/anonymity boundary enforced structurally: `CommunityReport` has NO
field for a user identifier of any kind -- not a hashed one, not a
pseudonymous one. A report is: what pattern (payee/number/script), what
category, when. That's it. This is what makes the k-anonymity floor in
campaign_graph.py meaningful rather than a policy promise layered on top
of identifiable data.
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from enum import Enum


class PatternKind(str, Enum):
    PAYEE_ACCOUNT = "payee_account"
    PHONE_NUMBER = "phone_number"
    SCRIPT_HASH = "script_hash"       # hash of a normalized scam-script pattern, not raw text
    CRYPTO_WALLET = "crypto_wallet"


@dataclass(frozen=True)
class CommunityReport:
    """No user-identifying field exists on this type -- see module docstring."""
    pattern_kind: PatternKind
    pattern_value: str
    category: str   # e.g. "romance_scam", "tech_support_scam", "irs_impersonation"
    reported_epoch: float
    # Sybil-resistance signal (spec 10.4/10.5): device attestation proof,
    # NOT a user identity -- a hardware-attestation token proves "a real
    # device submitted this" without proving WHICH device or WHO owns it.
    device_attestation_token: str


def new_report(pattern_kind: PatternKind, pattern_value: str, category: str, device_attestation_token: str) -> CommunityReport:
    return CommunityReport(
        pattern_kind=pattern_kind,
        pattern_value=pattern_value,
        category=category,
        reported_epoch=time.time(),
        device_attestation_token=device_attestation_token,
    )
