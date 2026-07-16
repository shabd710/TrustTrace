"""
Sliding window + structured compaction memory architecture.

Spec ref: PDF Section 3.2. Three real, running pieces of this file's job:

  1. A short raw-turn sliding window (full-fidelity recent context).
  2. Periodic compaction of aged-out turns into a compact structured record
     (entities, prior flags, key facts) -- NOT raw token/cache state.
  3. Recency decay on general entity salience, with the Strict Instruction
     Summary's exemption: a previously flagged risk indicator NEVER decays,
     because narrative-arc detection depends on a week-1 grooming signal
     still mattering when the payment ask lands in week 3.

NOT implemented here, and why: Grouped-Query-Attention KV-cache sharing and
token-importance-weighted KV-cache quantization (PDF 3.2's other two
techniques) are properties of the on-device LLM runtime's actual attention
mechanism during a real forward pass -- there is no KV cache to quantize in
a rule-based Tier 0/1/2 stand-in, since no attention computation is
happening. Wiring this file's structured record into a real Llama-3.2
context window (as the periodic "compact structured summary" fed back in as
a system-style preamble) is the integration point once TASK B's real model
loader exists.

Cross-layer security note: this is exactly the data structure that gets
wrapped by security/key_storage.py before touching disk, and is exactly the
data the "sensitive rolling-context text lives in a native mutable byte
buffer, never a Python/JS/Kotlin immutable string" rule (Strict Instruction
Summary) governs on the mobile side -- this Python module is the algorithmic
reference implementation the native SecureBuffer wraps, not a claim that
Python string immutability itself satisfies that rule.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field

from .model_cascade import CascadeResult

SLIDING_WINDOW_MAX_TURNS = 12
ENTITY_RECENCY_HALF_LIFE_SECONDS = 60 * 60 * 24 * 3  # 3 days


@dataclass
class RiskFlagRecord:
    tactic_id: str
    turn_index: int
    confidence: float
    cited_span: str
    first_seen_epoch: float
    # Strict Instruction Summary: a confirmed flag never decays out of the
    # narrative-arc record. This field exists precisely so no future code
    # path can accidentally apply decay to it -- it is structurally
    # separate from EntityRecord.salience below, not just conventionally
    # exempted.
    permanent: bool = True


@dataclass
class EntityRecord:
    kind: str  # "payee", "amount", "phone_number", "platform", etc.
    value: str
    first_seen_epoch: float
    last_seen_epoch: float
    salience: float = 1.0  # subject to recency decay -- general context only


@dataclass
class ConversationMemory:
    session_id: str
    raw_window: list[dict] = field(default_factory=list)   # full-fidelity recent turns
    entities: list[EntityRecord] = field(default_factory=list)
    risk_flags: list[RiskFlagRecord] = field(default_factory=list)
    turn_count: int = 0

    def add_turn(self, sender: str, text: str, cascade_result: CascadeResult | None = None) -> None:
        now = time.time()
        self.turn_count += 1
        self.raw_window.append({"sender": sender, "text": text, "turn_index": self.turn_count, "epoch": now})

        if cascade_result:
            for candidate in cascade_result.candidates:
                self.risk_flags.append(RiskFlagRecord(
                    tactic_id=candidate.tactic_id,
                    turn_index=self.turn_count,
                    confidence=candidate.base_score,
                    cited_span=", ".join(candidate.matched_spans) or candidate.sentence_context[:80],
                    first_seen_epoch=now,
                ))

        if len(self.raw_window) > SLIDING_WINDOW_MAX_TURNS:
            self._compact_oldest()

    def _compact_oldest(self) -> None:
        """Pop the oldest raw turn out of full-fidelity storage. Its risk
        flags already live permanently in self.risk_flags (never decayed);
        this only discards the raw text, matching spec 3.2's "not held as
        raw token history indefinitely"."""
        self.raw_window.pop(0)

    def session_prior_flag_ids(self) -> set[str]:
        """Feeds model_cascade.route()'s session_prior_flags argument --
        this is the mechanism that lets a recurring tactic compound across
        turns without holding a full raw transcript."""
        return {f.tactic_id for f in self.risk_flags}

    def decayed_entity_salience(self, entity: EntityRecord, now: float | None = None) -> float:
        """Exponential recency decay on GENERAL entity salience only.
        Never applied to risk_flags -- see RiskFlagRecord.permanent."""
        now = now if now is not None else time.time()
        age = max(0.0, now - entity.last_seen_epoch)
        return entity.salience * (0.5 ** (age / ENTITY_RECENCY_HALF_LIFE_SECONDS))

    def structured_summary(self) -> dict:
        """The 'compact structured record' spec 3.2 describes: what
        actually gets encrypted and written to SQLCipher (via
        security/key_storage.py) once a turn ages out of the raw window,
        and what would be serialized back into a real Tier 2 model's
        context as a system-style preamble on the next invocation."""
        return {
            "session_id": self.session_id,
            "turn_count": self.turn_count,
            "risk_flags": [
                {
                    "tactic": f.tactic_id, "turn": f.turn_index,
                    "confidence": round(f.confidence, 3), "evidence": f.cited_span,
                }
                for f in self.risk_flags
            ],
            "entities": [
                {"kind": e.kind, "value": e.value, "salience": round(self.decayed_entity_salience(e), 3)}
                for e in self.entities
            ],
        }
