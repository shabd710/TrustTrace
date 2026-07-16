"""
Transaction-time risk scorer.

Spec ref: PDF Section 2.3. Hard rule (Strict Instruction Summary, restated
here because this is the single highest-stakes file in the repo for that
rule): this module produces a warning screen only. No function in this
file returns anything resembling "cancel", "block", or "reverse" -- the
return type is deliberately just a rendering payload, never an action.
"""
from __future__ import annotations
from dataclasses import dataclass

from .payee_novelty_check import NoveltyResult
from grounding.evidence_citer import Citation, cite_transcript_span, render_for_user


@dataclass
class TransactionWarning:
    should_warn: bool
    headline: str
    citations: list[Citation]
    rendered_explanation: str
    # The only two user actions this warning payload can ever represent.
    # There is deliberately no third option like "cancel_transaction".
    available_actions: tuple[str, ...] = ("i_understand_continue_anyway", "go_back")


def build_warning(
    novelty: NoveltyResult,
    flagged_spans: list[tuple[str, int]],  # (span_text, turn_index) pairs already past the NLI + confidence gate
) -> TransactionWarning:
    if not novelty.compound_risk:
        return TransactionWarning(
            should_warn=False,
            headline="No compound risk detected.",
            citations=[],
            rendered_explanation="",
        )

    citations = [cite_transcript_span(span, idx) for span, idx in flagged_spans]
    headline = "This payment matches a pattern seen in scam cases -- take a moment before continuing."
    rendered = novelty.explanation
    if citations:
        rendered += "\n\n" + render_for_user(citations)

    return TransactionWarning(
        should_warn=True,
        headline=headline,
        citations=citations,
        rendered_explanation=rendered,
    )
