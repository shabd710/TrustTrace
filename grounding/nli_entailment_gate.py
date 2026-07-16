"""
NLI entailment gate -- the deterministic hard gate every Tier 1/2
manipulation-tactic flag must clear before it can ever reach the user.

Spec ref: PDF Section 2.5, 7.3 (determinism correction), 8.2 (no
battery-scaled threshold, no premise-embedding caching), 9.3 (evaluates
COMPLETE turns only, never streaming fragments), 10.5 (Strict Instruction
Summary's updated "complete turn" = reassembled burst, not raw single
message).

REAL vs SIM: production runs a small (sub-100M param), quantized,
INT8-mobile-GPU-delegated cross-encoder that jointly attends over
(premise, hypothesis) pairs, calibrated against the labeled manipulation
corpus. No such model/weights exist in this sandbox. This is a
deterministic, rule-based stand-in doing the same JOB: independently
re-check the flagged span actually supports the claimed tactic using
signals the Tier 0/1 pattern matcher itself does NOT use (so it isn't just
re-confirming its own bias) --
  - span specificity (a fragment carries less evidentiary weight than a
    full, unambiguous phrase)
  - hypothetical/interrogative framing ("what if someone asked me to wire
    money?" is ABOUT the tactic, not an instance of it)
  - negation ("I would never send a gift card" should NOT entail
    payment_channel_funneling just because the cue phrase is present)
Applied identically across every fixed hypothesis template in the tactic's
ensemble (7.3's determinism requirement -- no randomized template
injection).
"""
from __future__ import annotations
import re
from dataclasses import dataclass

from detection.conversation.tactic_taxonomy import TACTICS
from detection.conversation.model_cascade import TacticCandidate

_NEGATION_CUES = ("never", "not going to", "won't", "wouldn't", "did not", "didn't", "refuse to")

# --- Span specificity, information-weighted (spec 2.5 / 8.2) -----------------
#
# The original _specificity() derived confidence almost entirely from the
# TOKEN COUNT of a matched cue (words/3). That systematically mislabels the
# highest-signal scam evidence as "fragmentary": the strongest indicators of
# whole scam families are one- or two-word terms of art -- "OTP", "AnyDesk",
# "Bitcoin", "gift card" -- so they scored ~0.33 and were dropped below the
# ENTAILMENT_CONFIDENCE_CEILING even when Tier 0/1 matched them cleanly. A
# real NLI cross-encoder would not confuse "short" with "weak"; the token
# "OTP" is far MORE discriminative than a long, generic sentence. The fix is
# to weight a span by its EVIDENTIARY INFORMATION, not its length.
#
# Two curated, auditable sets do this (kept here, not in the taxonomy, because
# they are a property of the GATE's evidence-weighting, not of Tier 0 recall):
#
#   HIGH_INFORMATION_CUES -- short but near-unambiguous scam terms of art.
#   They act as a FLOOR on specificity (max with the word-count heuristic, so
#   a longer strong phrase is never penalised down to the floor). This never
#   makes a LONE cue self-surface: specificity is a multiplier <=1, and a
#   single Tier 0 cue only carries base_score ~0.22, still below the 0.35
#   ceiling -- these terms only stop being unfairly discounted once they are
#   corroborated (multiple cues, or co-occurring tactics), which IS the scam
#   signature per spec 2.2.
#
#   LOW_INFORMATION_CUES -- dual-use phrases that appear verbatim in BENIGN
#   messages too ("your bank account", "security alert", "unusual activity").
#   These are CAPPED (not floored): even several of them in one tactic cannot
#   clear the gate on their own, so a genuine bank notification abstains,
#   while the same phrases still contribute corroboration when a real
#   solicitation (OTP / payment / remote-access) co-occurs. This is what lets
#   the authority-impersonation taxonomy be expanded with modern phishing
#   language WITHOUT turning legitimate bank alerts into false positives.
#
# Determinism (spec 7.3): both sets are fixed data, applied identically to
# every template in a tactic's ensemble -- no randomness, fully reproducible.

HIGH_INFO_WEIGHT = 0.9
LOW_INFO_WEIGHT = 0.25

HIGH_INFORMATION_CUES = frozenset({
    # One-time-code / OTP solicitation
    "otp", "verification code", "one-time code", "one time code",
    "6-digit code", "six-digit code", "6 digit code",
    "read me the code", "share the code", "tell me the code", "send the code",
    # Remote-access tooling (brand names are terms of art)
    "anydesk", "teamviewer", "remote access", "remote support",
    # Irreversible payment rails
    "gift card", "buy a gift card", "wire transfer", "wire money",
    "wire the money", "western union", "money order",
    # Crypto rails
    "bitcoin", "crypto", "usdt", "crypto wallet",
    # Explicit authority impersonation openers (strong, not dual-use)
    "this is the irs", "this is your bank", "this is your ceo",
    "federal agent", "law enforcement", "this is the police",
    "arrest warrant", "digital arrest",
    # UPI PIN is only ever entered to SEND money -- unambiguous receive-scam
    # signal, unlike the dual-use app/brand names.
    "upi pin", "enter your upi pin",
    # Sextortion / coercion terms of art.
    "leak your photos", "leak your video", "expose you", "intimate photos",
    "i have your videos", "send nudes", "pay or i will",
})

# Dual-use banking/phishing language: high-recall for Tier 0, but ambiguous
# on its own, so the gate refuses to surface it without corroboration.
LOW_INFORMATION_CUES = frozenset({
    "your bank account", "account locked", "account has been locked",
    "account suspended", "account has been suspended", "security alert",
    "verify your identity", "confirm your identity", "fraud department",
    "unusual activity", "suspicious activity",
    # Delivery / customs / KYC impersonation (real couriers and banks say these)
    "your parcel", "your package", "parcel is held", "package is held",
    "kyc", "update your kyc", "kyc verification", "kyc expired",
    "customs department", "income tax department",
    # UPI / QR rails used in benign payments too -- capped, need corroboration
    "upi", "upi id", "google pay", "phonepe", "paytm", "gpay",
    "collect request", "scan the qr", "scan this qr", "scan to pay", "qr code",
    # Advance-fee framing and job/investment bait -- dual-use, need corroboration
    "registration fee", "processing fee", "advance fee", "security deposit",
    "work from home", "part-time job", "part time job", "earn daily",
    "daily income", "no experience needed", "guaranteed job",
    "high returns", "investment opportunity", "trading tips",
})


def _information_weight(span: str) -> float:
    """Evidentiary weight of a single matched cue span, in [0, 1].

    Dual-use phrases are capped (they need corroboration); strong terms of
    art get a high floor; everything else falls back to the original
    token-count heuristic so previously-tuned behaviour is preserved.
    """
    s = span.lower().strip()
    if not s:
        return 0.0
    if s in LOW_INFORMATION_CUES:
        return LOW_INFO_WEIGHT
    word_based = min(1.0, len(s.split()) / 3.0)
    high = HIGH_INFO_WEIGHT if any(cue in s for cue in HIGH_INFORMATION_CUES) else 0.0
    return min(1.0, max(word_based, high))


@dataclass
class EntailmentResult:
    tactic_id: str
    survived: bool
    final_confidence: float
    per_template_scores: list[float]
    reason: str


# Tuned confidence ceiling -- a flag below this is dropped as ungrounded
# inference before it ever reaches the user (spec 2.5). This threshold is
# NEVER scaled by battery level or any device-state signal (Strict
# Instruction Summary) -- it is a fixed epistemic bar.
ENTAILMENT_CONFIDENCE_CEILING = 0.35


def _specificity(matched_spans: list[str]) -> float:
    """Specificity = the information weight of the STRONGEST single matched
    cue (spec 2.5's "a fragment carries less evidentiary weight than a full,
    unambiguous phrase" -- reframed so "unambiguous" is measured by
    discriminative information, not raw length). A candidate is only as
    grounded as its best piece of evidence; that best piece is a highly
    discriminative term of art ("OTP", "gift card") when present, and a
    capped dual-use phrase otherwise. Corroboration across independent
    tactics is added separately in gate_candidates(), not here."""
    if not matched_spans:
        return 0.0
    return min(1.0, max(_information_weight(s) for s in matched_spans))


def _has_negation(sentence: str, matched_spans: list[str]) -> bool:
    """
    Proximity-scoped, not sentence-wide: a negation cue only counts if it
    appears within a small word-window BEFORE one of the actually-matched
    cue phrases. Sentence-wide negation matching produces a real false
    negative -- e.g. "I've never felt this way before, but I need you to
    wire money urgently" contains "never" (part of unrelated
    too-good-to-be-true framing) which must NOT suppress the genuine
    payment-funneling flag later in the same sentence. Negation has to be
    local to what it's negating, same as it would be for a real NLI
    cross-encoder attending over the actual premise/hypothesis pair.
    """
    lowered = sentence.lower()
    words = lowered.split()
    if not matched_spans:
        return any(cue in lowered for cue in _NEGATION_CUES)

    for span in matched_spans:
        span_words = span.lower().split()
        span_first_word = span_words[0] if span_words else ""
        for i, w in enumerate(words):
            if w.startswith(span_first_word[:4]) and span_first_word:
                window_start = max(0, i - 6)
                window = " ".join(words[window_start:i])
                if any(cue in window for cue in _NEGATION_CUES):
                    return True
    return False


def _is_hypothetical(sentence: str) -> bool:
    s = sentence.strip()
    return s.endswith("?") or s.lower().startswith(("what if", "suppose", "imagine if"))


def evaluate_entailment(candidate: TacticCandidate) -> EntailmentResult:
    """
    Independently re-checks ONE Tier 1/2 candidate against the fixed
    hypothesis-template ensemble for its tactic. Must be called on a
    COMPLETE reassembled turn (see detection/conversation/
    transcript_normalizer.reassemble_turns) -- never a raw streaming
    fragment, per spec 9.3/10.5.
    """
    spec = TACTICS.get(candidate.tactic_id)
    if spec is None:
        return EntailmentResult(candidate.tactic_id, False, 0.0, [], "unknown tactic id")

    templates = spec["hypothesis_templates"]
    specificity = _specificity(candidate.matched_spans)
    hypothetical_penalty = 0.55 if _is_hypothetical(candidate.sentence_context) else 1.0
    negation_penalty = 0.15 if _has_negation(candidate.sentence_context, candidate.matched_spans) else 1.0

    per_template_scores = []
    for _template in templates:
        score = candidate.base_score * specificity * hypothetical_penalty * negation_penalty
        per_template_scores.append(round(min(1.0, score), 4))

    final_confidence = round(sum(per_template_scores) / len(per_template_scores), 4)
    survived = final_confidence >= ENTAILMENT_CONFIDENCE_CEILING

    if not survived:
        if negation_penalty < 1.0:
            reason = "Dropped: negated framing does not entail the tactic despite matching cue phrases."
        elif hypothetical_penalty < 1.0:
            reason = "Dropped: hypothetical/interrogative framing does not entail an actual instance of the tactic."
        else:
            reason = "Dropped: evidence too fragmentary to support entailment at the required confidence ceiling."
    else:
        reason = "Survived: flagged span entails the tactic claim across the full template ensemble."

    return EntailmentResult(
        tactic_id=candidate.tactic_id,
        survived=survived,
        final_confidence=final_confidence,
        per_template_scores=per_template_scores,
        reason=reason,
    )


def gate_candidates(candidates: list[TacticCandidate]) -> tuple[list[TacticCandidate], list[EntailmentResult]]:
    """Batch entry point: returns (surviving_candidates, all_results) so
    callers can show both what reached the user AND what was dropped and
    why -- consistent with the MVP's own UI pattern of showing dropped
    flags for transparency, not just survivors.

    Compound corroboration (spec 2.2/2.5 "compound confidence"): multiple
    INDEPENDENT tactics co-occurring in one turn is itself evidence -- a
    lone cue may be ambiguous, but urgency + authority-impersonation +
    payment-funneling together is the signature of a scam, not noise. Each
    additional distinct corroborating tactic lends a bounded boost to its
    peers' entailment confidence, applied BEFORE the ceiling test. This is
    still deterministic and evidence-grounded: the boost derives only from
    other independently-matched, real spans in the same turn, never from
    model speculation, and a single un-corroborated weak flag still fails
    closed exactly as before.
    """
    base_results = [evaluate_entailment(c) for c in candidates]

    distinct_tactics = {c.tactic_id for c in candidates}
    corroboration = min(0.30, 0.15 * max(0, len(distinct_tactics) - 1))

    results: list[EntailmentResult] = []
    for c, r in zip(candidates, base_results):
        if corroboration > 0 and r.final_confidence < ENTAILMENT_CONFIDENCE_CEILING:
            boosted = round(min(1.0, r.final_confidence + corroboration), 4)
            survived = boosted >= ENTAILMENT_CONFIDENCE_CEILING
            reason = (
                "Survived: corroborated by "
                f"{len(distinct_tactics)} independent co-occurring tactics in the same turn."
                if survived else r.reason
            )
            results.append(EntailmentResult(
                tactic_id=r.tactic_id, survived=survived, final_confidence=boosted,
                per_template_scores=r.per_template_scores, reason=reason,
            ))
        else:
            results.append(r)

    survivors = [c for c, r in zip(candidates, results) if r.survived]
    return survivors, results
