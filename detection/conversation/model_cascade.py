"""
Tier 0 / Tier 1 / Tier 2 cascade routing logic.

Spec ref: PDF Target Environment + Section 3.1/3.4 + Strict Instruction
Summary ("The tiered model cascade is mandatory infrastructure -- Tier 2
must not be the default path for routine message scoring in any build.").

REAL vs SIM, stated plainly (same discipline as the MVP's own README):
  - Tier 0 here is a real, if small, sub-10M-parameter-equivalent heuristic:
    lexical cue matching + a handful of structural features, genuinely
    cheap (microseconds in Python, single-digit ms on-device in a compiled
    form) and genuinely running on real input.
  - Tier 1 / Tier 2 in production are Llama-3.2-1B / Llama-3.2-3B running
    through an on-device runtime (llama.cpp / MLC-LLM / MLX / MediaPipe,
    per Target Environment) with cross-tier speculative decoding (PDF 3.4).
    Actually loading multi-GB weights and a GGUF-compatible runtime isn't
    possible in this sandbox (no network, no accelerator, no runtime
    binary). Tier 1/2 here are DETERMINISTIC STAND-INS that do the same
    *job* the spec assigns them -- escalate borderline Tier 0 cases,
    compound multiple weak signals into a stronger verdict, and always
    cite which cue(s) fired -- using weighted pattern-matching instead of
    an LLM forward pass. The interface (`CascadeResult`, `route()`) is
    what a real model-backed Tier 1/2 would slot into without changing any
    caller.

Cross-layer security note: Tier 2 must never become the default path (see
docstring above) -- this file enforces that structurally, not just by
convention: `route()` only escalates past Tier 0 when Tier 0's own score
crosses TIER0_ESCALATION_THRESHOLD, and only escalates past Tier 1 when
Tier 1's compounded score crosses TIER1_ESCALATION_THRESHOLD. There is no
call path that invokes Tier 2 directly.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .tactic_taxonomy import TACTICS, is_scoreable_tactic
from .transcript_normalizer import normalize_text
from .fast_pattern_matcher import scan_cues

TIER0_ESCALATION_THRESHOLD = 0.28
TIER1_ESCALATION_THRESHOLD = 0.55


@dataclass
class TacticCandidate:
    tactic_id: str
    matched_spans: list[str]
    base_score: float
    sentence_context: str


@dataclass
class CascadeResult:
    tier_reached: int  # 0, 1, or 2
    candidates: list[TacticCandidate]
    tier0_score: float
    notes: list[str] = field(default_factory=list)


def _tier0_score_message(text: str) -> tuple[float, list[TacticCandidate]]:
    """Sub-10M-param-equivalent heuristic: cheap substring/keyword scan
    across every tactic's cue_phrases. Runs on every single message --
    the spec's "high-volume, usually-benign majority" path -- so it must
    stay O(cues) per message, no model invocation of any kind."""
    normalized = normalize_text(text)
    lowered = normalized.lower()
    candidates: list[TacticCandidate] = []
    hits = 0
    # Single-pass Aho-Corasick scan over ALL tactics' cues at once,
    # replacing the original per-cue substring loop -- output is verified
    # cue-for-cue identical to the naive scan (tests/test_optimizations.py),
    # only the scan cost changed: O(N + matches) vs O(T*C*N).
    matched_by_tactic = scan_cues(lowered)
    for tactic_id in TACTICS:  # taxonomy order preserved, as before
        matched = matched_by_tactic.get(tactic_id)
        if matched:
            hits += len(matched)
            candidates.append(TacticCandidate(
                tactic_id=tactic_id,
                matched_spans=matched,
                base_score=min(1.0, 0.22 * len(matched)),
                sentence_context=normalized,
            ))
    # Score scales with distinct cue diversity, not raw hit count, so one
    # phrase repeated three times doesn't outweigh three different weak
    # signals compounding together.
    score = min(1.0, 0.18 * len({c.tactic_id for c in candidates}) + 0.05 * hits)
    return score, candidates


def _tier1_refine(candidates: list[TacticCandidate], session_prior_flags: set[str]) -> list[TacticCandidate]:
    """Borderline-case refinement: boosts a candidate if the SAME tactic
    (or a compounding one -- payment_channel_funneling compounds with
    anything) has already fired earlier in this session, modeling the
    narrative-arc principle from spec 2.1/10.1 without holding a full LLM
    context window. This is exactly the kind of session-level compounding
    a real Tier 1 forward pass would also be doing, just via attention
    over the full window instead of an explicit prior-flags set."""
    distinct_tactics_this_turn = {c.tactic_id for c in candidates}
    intra_turn_compounding = len(distinct_tactics_this_turn) >= 3

    refined = []
    for c in candidates:
        boost = 0.0
        if c.tactic_id in session_prior_flags:
            boost += 0.15
        if c.tactic_id == "payment_channel_funneling":
            # Strongest compound signal per spec 2.1: boosted either by
            # recurring across the session, or by co-occurring with two+
            # other distinct tactics in the very same turn (e.g. authority
            # impersonation + isolation + payment funneling together).
            if session_prior_flags:
                boost += 0.20
            if intra_turn_compounding:
                boost += 0.20
        elif intra_turn_compounding:
            boost += 0.10
        refined.append(TacticCandidate(
            tactic_id=c.tactic_id,
            matched_spans=c.matched_spans,
            base_score=min(1.0, c.base_score + boost),
            sentence_context=c.sentence_context,
        ))

    # Optional REAL model blends, each 50/50 with whatever score preceded it.
    # Both are no-ops returning the input unchanged when their model is absent
    # (the sandbox/CPU-only path, and every existing test) -- a missing optional
    # model must never break detection.
    #
    # Order matters: the trained ONNX classifier blends FIRST (it is the
    # purpose-trained scam detector), then the Llama pass refines further if
    # weights are present. Neither can introduce a tactic Tier 0's cues didn't
    # already surface -- the rule engine stays a floor -- and both still pass
    # the NLI entailment gate downstream before anything reaches a user.
    text = candidates[0].sentence_context if candidates else ""

    def _blend(cands, conf_by_tactic):
        out = []
        for c in cands:
            if c.tactic_id in conf_by_tactic:
                out.append(TacticCandidate(
                    tactic_id=c.tactic_id, matched_spans=c.matched_spans,
                    base_score=min(1.0, 0.5 * c.base_score + 0.5 * conf_by_tactic[c.tactic_id]),
                    sentence_context=c.sentence_context,
                ))
            else:
                out.append(c)
        return out

    try:
        from .onnx_scorer import score_candidates_with_onnx
        onnx_out = score_candidates_with_onnx(text, [c.tactic_id for c in refined])
    except Exception:
        onnx_out = None
    if onnx_out:
        refined = _blend(refined, {r.tactic_id: r.confidence for r in onnx_out})

    try:
        from .llm_runtime import refine_candidates_with_llm
        llm_out = refine_candidates_with_llm(text, [c.tactic_id for c in refined], tier=1)
    except Exception:
        llm_out = None
    if llm_out:
        refined = _blend(refined, {r.tactic_id: r.confidence for r in llm_out})

    return refined


def _apply_mutual_exclusivity(candidates: list[TacticCandidate], all_candidates: list[TacticCandidate]) -> list[TacticCandidate]:
    """PDF 8.2: drop a flag when a mutually-exclusive tactic (e.g. explicit
    calming_reassurance alongside urgency_injection) scores comparably in
    the same turn -- treated as a contradiction, not two independent
    signals. Fits confidence_gate.py's fail-closed philosophy: ambiguous
    beats wrong."""
    by_tactic = {c.tactic_id: c.base_score for c in all_candidates}
    survivors = []
    for c in candidates:
        spec = TACTICS.get(c.tactic_id, {})
        conflict = False
        for other_id in spec.get("mutually_exclusive_with", ()):
            if by_tactic.get(other_id, 0.0) >= c.base_score * 0.7:
                conflict = True
                break
        if not conflict:
            survivors.append(c)
    return survivors


def route(text: str, session_prior_flags: set[str] | None = None) -> CascadeResult:
    """
    Entry point matching the spec file's described role: "Tier 0/1/2
    routing logic". Returns every scoreable candidate reached, tagged with
    which tier produced the final score, for confidence_gate.py /
    nli_entailment_gate.py to independently re-check downstream -- this
    function never itself decides what reaches the user.
    """
    session_prior_flags = session_prior_flags or set()
    notes: list[str] = []

    tier0_score, candidates = _tier0_score_message(text)
    candidates = [c for c in candidates if is_scoreable_tactic(c.tactic_id)]

    if tier0_score < TIER0_ESCALATION_THRESHOLD or not candidates:
        notes.append("Tier 0 only: below escalation threshold, high-volume benign path.")
        return CascadeResult(tier_reached=0, candidates=[], tier0_score=tier0_score, notes=notes)

    # Tier 1: borderline-case refinement.
    all_candidates_incl_benign = _tier0_score_message(text)[1]  # includes calming_reassurance for the exclusivity check
    refined = _tier1_refine(candidates, session_prior_flags)
    refined = _apply_mutual_exclusivity(refined, all_candidates_incl_benign)
    tier1_max = max((c.base_score for c in refined), default=0.0)

    if tier1_max < TIER1_ESCALATION_THRESHOLD:
        notes.append("Tier 1 resolved: borderline case handled without Tier 2 escalation.")
        return CascadeResult(tier_reached=1, candidates=refined, tier0_score=tier0_score, notes=notes)

    # Tier 2: genuinely ambiguous / high-stakes -- in production, the
    # full-context Llama-3.2-3B pass; here, the same refined candidates are
    # passed through unchanged plus a note, since Tier 2's marginal job
    # (full conversational context, cross-tier speculative decoding) isn't
    # something this stand-in can meaningfully simulate beyond Tier 1.
    notes.append("Tier 2 invoked: genuinely ambiguous/high-stakes case per Tier 1 escalation.")
    return CascadeResult(tier_reached=2, candidates=refined, tier0_score=tier0_score, notes=notes)
