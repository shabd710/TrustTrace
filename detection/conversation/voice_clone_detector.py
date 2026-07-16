"""
Voice-clone / synthetic-speech compound scorer.

Spec ref: PDF Section 2.2, corrected by 7.3 (codec-robustness) and 9.3
(acoustic codec pre-filtering as a complement, not a replacement).

REAL vs SIM: a genuine AASIST-style acoustic classifier needs trained
weights and real audio feature extraction (spectral flatness, CQT/LFCC
features, telephony-codec-aware training data) -- none of which exist in
this sandbox. What's implemented here for real is the piece the spec calls
out as the actual point of this module: COMPOUND scoring with the
conversation-content signal (2.1/2.2 -- "a cloned-voice flag alone is a
caution; cloned-voice plus urgency-and-payment-funneling language is a
strong stop-and-verify signal"). The acoustic classifier itself is a typed
interface (`AcousticScore`) a real AASIST model's output slots into
unchanged.
"""
from __future__ import annotations
from dataclasses import dataclass

from .model_cascade import CascadeResult


@dataclass
class AcousticScore:
    """What a real on-device AASIST-style classifier would emit per call
    segment. spoof_probability is trained/calibrated against
    codec-compressed telephony audio specifically (spec 7.3's correction:
    AMR-NB/WB compression artifacts are a real, documented confound with
    cloning artifacts, not "hardware phase deviation")."""
    spoof_probability: float  # 0..1
    codec_prefiltered: bool   # whether DSP codec-artifact stripping (spec 9.3) ran first


@dataclass
class CompoundVoiceVerdict:
    acoustic_flag: bool
    content_flag: bool
    compound_confidence: float
    explanation: str


ACOUSTIC_CAUTION_THRESHOLD = 0.6
COMPOUND_STOP_AND_VERIFY_THRESHOLD = 0.75


def score_call(acoustic: AcousticScore, conversation_cascade: CascadeResult) -> CompoundVoiceVerdict:
    """
    Combines the (real-in-production, simulated-here) acoustic score with
    the (genuinely running) conversation cascade score into the compound
    verdict spec 2.2 describes. Deliberately does NOT let a high acoustic
    score alone reach "strong" severity -- matches the spec's own framing
    that a cloned-voice flag ALONE is a caution, not a verdict.
    """
    acoustic_flag = acoustic.spoof_probability >= ACOUSTIC_CAUTION_THRESHOLD
    content_flag = len(conversation_cascade.candidates) > 0

    if acoustic_flag and content_flag:
        content_strength = max((c.base_score for c in conversation_cascade.candidates), default=0.0)
        compound = min(1.0, 0.5 * acoustic.spoof_probability + 0.5 * content_strength + 0.1)
        tactics = ", ".join(sorted({c.tactic_id for c in conversation_cascade.candidates}))
        explanation = (
            f"Voice shows synthetic-speech characteristics (p={acoustic.spoof_probability:.2f}) "
            f"AND the conversation content matches known manipulation tactics ({tactics}). "
            f"Compound signal: stop and verify independently before acting."
        )
    elif acoustic_flag:
        compound = acoustic.spoof_probability * 0.5  # caution only, per spec
        explanation = (
            f"Voice shows synthetic-speech characteristics (p={acoustic.spoof_probability:.2f}) "
            f"but no corroborating manipulation-pattern content was flagged. Caution, not a verdict."
        )
    elif content_flag:
        compound = max((c.base_score for c in conversation_cascade.candidates), default=0.0) * 0.6
        explanation = "Conversation content flagged manipulation patterns; acoustic signal did not corroborate."
    else:
        compound = 0.0
        explanation = "No acoustic or content-based manipulation signal detected."

    return CompoundVoiceVerdict(
        acoustic_flag=acoustic_flag,
        content_flag=content_flag,
        compound_confidence=round(compound, 3),
        explanation=explanation,
    )
