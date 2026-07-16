"""
Payee novelty check.

Spec ref: PDF Section 2.3: "flags the compound pattern of new payee + high
transfer amount + recent manipulation-flagged conversation -- each factor
alone is common and harmless; the combination is the signal."
"""
from __future__ import annotations
import time
from dataclasses import dataclass


@dataclass
class PayeeHistory:
    known_payees: set[str]
    # epoch of most recent manipulation-tactic flag, None if none this session/window
    last_manipulation_flag_epoch: float | None


@dataclass
class NoveltyResult:
    is_novel_payee: bool
    is_high_value: bool
    recent_manipulation_flag: bool
    compound_risk: bool
    explanation: str


HIGH_VALUE_THRESHOLD = 500.0
RECENT_FLAG_WINDOW_SECONDS = 2 * 60 * 60  # default 2-hour window per spec 2.3


def check(payee_id: str, amount: float, history: PayeeHistory, now: float | None = None) -> NoveltyResult:
    now = now if now is not None else time.time()

    is_novel = payee_id not in history.known_payees
    is_high_value = amount >= HIGH_VALUE_THRESHOLD
    recent_flag = (
        history.last_manipulation_flag_epoch is not None
        and (now - history.last_manipulation_flag_epoch) <= RECENT_FLAG_WINDOW_SECONDS
    )

    # Compound rule: no single factor alone triggers a warning -- matches
    # spec's explicit framing that each factor alone is "common and
    # harmless". At minimum two of the three must co-occur.
    factor_count = sum([is_novel, is_high_value, recent_flag])
    compound_risk = factor_count >= 2

    if compound_risk:
        reasons = []
        if is_novel:
            reasons.append("this is a new payee")
        if is_high_value:
            reasons.append(f"the amount (${amount:,.2f}) is above the ${HIGH_VALUE_THRESHOLD:,.0f} threshold")
        if recent_flag:
            reasons.append("a manipulation pattern was flagged in a recent conversation")
        explanation = "Compound risk: " + "; ".join(reasons) + "."
    else:
        explanation = "No compound risk: individual factors present are common and harmless on their own."

    return NoveltyResult(is_novel, is_high_value, recent_flag, compound_risk, explanation)
