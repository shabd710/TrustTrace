"""
Confidence gate -- fails closed, everywhere, uniformly.

Spec ref: PDF Section 2.5: "Confidence gate fails closed: abstain rather
than guess, everywhere." Applied identically whether the upstream signal
is conversation-cascade candidates, a device permission-graph finding, or
a campaign-graph match -- this file doesn't know or care which module
called it, it only knows how to say "not enough signal" instead of
guessing.

Also implements spec 8.2's mutual-exclusivity consistency check (simultaneous
high-scoring mutually-exclusive tactics -- e.g. urgency_injection and
calming_reassurance -- get dropped as a contradiction, not trusted as two
independent signals) as a second, independent fail-closed layer on top of
whatever model_cascade.py already applied, since this file is meant to be
the LAST checkpoint before something becomes user-facing.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

from detection.conversation.tactic_taxonomy import TACTICS
from grounding.nli_entailment_gate import EntailmentResult


class GateVerdict(str, Enum):
    SURFACED = "surfaced"                       # confident enough, cited, shown to user
    ABSTAINED_LOW_CONFIDENCE = "abstained_low_confidence"   # explicitly "not enough signal"
    ABSTAINED_ENTAILMENT_FAILED = "abstained_entailment_failed"
    ABSTAINED_MUTUAL_EXCLUSION = "abstained_mutual_exclusion"


@dataclass
class GatedFlag:
    tactic_id: str
    verdict: GateVerdict
    confidence: float
    explanation: str


# Distinct from the NLI gate's own ceiling -- this is a final, slightly
# stricter user-facing bar, since a flag can survive NLI entailment but
# still be too weak to justify interrupting the user with a warning.
USER_FACING_CONFIDENCE_FLOOR = 0.4


def apply(entailment_results: list[EntailmentResult]) -> list[GatedFlag]:
    gated: list[GatedFlag] = []

    survivors_by_tactic = {r.tactic_id: r for r in entailment_results if r.survived}

    for result in entailment_results:
        if not result.survived:
            gated.append(GatedFlag(
                tactic_id=result.tactic_id,
                verdict=GateVerdict.ABSTAINED_ENTAILMENT_FAILED,
                confidence=result.final_confidence,
                explanation=result.reason,
            ))
            continue

        if result.final_confidence < USER_FACING_CONFIDENCE_FLOOR:
            gated.append(GatedFlag(
                tactic_id=result.tactic_id,
                verdict=GateVerdict.ABSTAINED_LOW_CONFIDENCE,
                confidence=result.final_confidence,
                explanation="Below threshold: not enough signal -- explicitly distinct from 'this is safe'.",
            ))
            continue

        # mutual-exclusivity re-check at the final checkpoint
        spec = TACTICS.get(result.tactic_id, {})
        conflict_id = next(
            (other for other in spec.get("mutually_exclusive_with", ())
             if other in survivors_by_tactic and survivors_by_tactic[other].final_confidence >= result.final_confidence * 0.7),
            None,
        )
        if conflict_id:
            gated.append(GatedFlag(
                tactic_id=result.tactic_id,
                verdict=GateVerdict.ABSTAINED_MUTUAL_EXCLUSION,
                confidence=result.final_confidence,
                explanation=f"Dropped: contradicts co-occurring signal '{conflict_id}' at comparable confidence.",
            ))
            continue

        gated.append(GatedFlag(
            tactic_id=result.tactic_id,
            verdict=GateVerdict.SURFACED,
            confidence=result.final_confidence,
            explanation="Confidence and entailment both cleared threshold -- surfaced with cited evidence.",
        ))

    return gated


def any_surfaced(gated_flags: list[GatedFlag]) -> bool:
    return any(f.verdict == GateVerdict.SURFACED for f in gated_flags)
