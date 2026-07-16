"""
Transcript normalizer.

Spec ref: PDF Section 2.1 file list; Section 8.2 ("cross-lingual/mixed-script
normalization ahead of the NLI gate", "a regex pre-filter ahead of Tier 0").

Runs before anything touches the cascade. Two independent jobs:

1. Cheap regex pre-filter: strips/normalizes noise (repeated whitespace,
   zero-width characters, homoglyph substitution used to dodge keyword
   matching -- e.g. "urgnt" or Cyrillic "о" standing in for Latin "o") so
   Tier 0's lexical cues aren't trivially evaded by cosmetic obfuscation.
   This is NOT the adversarial-evasion defense the spec cares about most
   (Section 10.1 is explicit that a well-written, non-obfuscated low-signal
   message defeats this trivially -- narrative-arc detection is the real
   defense). This module only closes the crude, cheap version of evasion.

2. Turn reassembly for NLI gating (PDF Section 10.5's fragmentation-evasion
   revision): a scammer sending five rapid single-word messages to stay
   under a naive per-message boundary must be reassembled into one
   "complete turn" before entailment evaluation, per the Strict Instruction
   Summary's updated definition of "complete context".
"""
from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass

_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_MULTI_WS = re.compile(r"\s+")

# A small, explicit homoglyph map -- deliberately not "clever": an
# over-aggressive confusable-normalizer risks mangling legitimate
# non-Latin-script text, which would itself be an equity failure (PDF
# Section 4's equity_eval.py exists specifically to catch this class of
# regression). Only visually-near-identical single characters known to be
# used for evasion are mapped.
_HOMOGLYPHS = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x",  # Cyrillic look-alikes
    "０": "0", "１": "1", "２": "2", "３": "3",  # fullwidth digits
}


def normalize_text(raw: str) -> str:
    """Single-message normalization: Unicode NFKC fold, zero-width strip,
    homoglyph fold, whitespace collapse. Idempotent and lossless enough to
    still show the original alongside it in evidence citations upstream."""
    text = unicodedata.normalize("NFKC", raw)
    text = _ZERO_WIDTH.sub("", text)
    text = "".join(_HOMOGLYPHS.get(ch, ch) for ch in text)
    text = _MULTI_WS.sub(" ", text).strip()
    return text


@dataclass
class RawTurn:
    sender: str
    text: str
    timestamp_ms: int


@dataclass
class ReassembledTurn:
    sender: str
    text: str
    start_ms: int
    end_ms: int
    source_message_count: int


# PDF 10.5: a burst of rapid-fire short messages from the SAME sender within
# a short window is reassembled into one coherent unit before it ever
# reaches the NLI gate. Two independently tunable knobs, not one, because
# "rapid" and "short" are different failure modes to guard against:
BURST_WINDOW_MS = 4000       # messages within this gap of the previous one join the burst
SHORT_MESSAGE_WORD_LIMIT = 4  # only short messages trigger burst-joining logic


def reassemble_turns(raw_turns: list[RawTurn]) -> list[ReassembledTurn]:
    """
    Collapse a same-sender burst of short, rapid-fire messages into one
    ReassembledTurn. A single long message is left as its own turn
    untouched -- this only targets the specific fragmentation-evasion
    pattern (PDF 10.5), not general multi-message conversations, so it
    never accidentally merges two genuinely separate exchanges.
    """
    if not raw_turns:
        return []

    out: list[ReassembledTurn] = []
    bucket: list[RawTurn] = [raw_turns[0]]

    def _flush():
        texts = [normalize_text(t.text) for t in bucket]
        out.append(ReassembledTurn(
            sender=bucket[0].sender,
            text=" ".join(texts).strip(),
            start_ms=bucket[0].timestamp_ms,
            end_ms=bucket[-1].timestamp_ms,
            source_message_count=len(bucket),
        ))

    for prev, cur in zip(raw_turns, raw_turns[1:]):
        same_sender = cur.sender == prev.sender
        rapid = (cur.timestamp_ms - prev.timestamp_ms) <= BURST_WINDOW_MS
        prev_was_short = len(normalize_text(prev.text).split()) <= SHORT_MESSAGE_WORD_LIMIT
        if same_sender and rapid and prev_was_short:
            bucket.append(cur)
        else:
            _flush()
            bucket = [cur]
    _flush()
    return out
