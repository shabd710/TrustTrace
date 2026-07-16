"""
Shortcode SMS gateway: no-install risk check for feature-phone / low-
connectivity users.

Spec ref: PDF Section 2.9, 7.4 (no end-user PKI -- shortcode SMS carries no
meaningful sender-signature mechanism by design, since anonymous people
with no app and no keys must be able to text in; real protection is
carrier-level sender verification + rate-limiting/abuse throttling), 9.4
(token-bucket rate limiting against denial-of-wallet flooding), 9.4 (TRAI
DLT template matching as ONE weighted input, never an automatic spoofing
determination).

Real, running logic: token-bucket rate limiting is genuinely implemented
and tested. The actual carrier shortcode connection (Twilio or a telecom
partner API) is a network integration seam, same honest treatment as
threat-intel/ingest_public_feeds.py's fetch step.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field

from detection.conversation.model_cascade import route
from grounding.nli_entailment_gate import gate_candidates
from grounding.confidence_gate import apply as apply_confidence_gate, any_surfaced


@dataclass
class TokenBucket:
    """Real token-bucket rate limiter -- defends the paid shortcode
    against denial-of-wallet flooding (spec 9.4), independent of any
    sender-identity mechanism (which doesn't exist for this channel by
    design)."""
    capacity: int
    refill_per_second: float
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)

    def __post_init__(self):
        self._tokens = float(self.capacity)
        self._last_refill = time.time()

    def _refill(self, now: float) -> None:
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_second)
        self._last_refill = now

    def try_consume(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        self._refill(now)
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


@dataclass
class TraiDltMatch:
    """Spec 9.4: one weighted input, never a standalone verdict. A
    registered sender's message deviating from its OWN approved template
    is a red flag; the large majority of legitimate personal messages
    simply won't match any DLT template at all, which is NOT itself
    evidence of fraud."""
    matched_registered_template: bool
    is_from_registered_commercial_sender: bool

    @property
    def is_meaningful_signal(self) -> bool:
        """Only a REGISTERED sender deviating from ITS OWN template is
        informative -- an unregistered/personal sender not matching is
        expected and uninformative, per spec 9.4's explicit correction."""
        return self.is_from_registered_commercial_sender and not self.matched_registered_template


@dataclass
class SmsRiskReply:
    accepted: bool
    reply_text: str


PER_SENDER_BUCKETS: dict[str, TokenBucket] = {}


def _bucket_for(sender_phone: str) -> TokenBucket:
    if sender_phone not in PER_SENDER_BUCKETS:
        PER_SENDER_BUCKETS[sender_phone] = TokenBucket(capacity=5, refill_per_second=1 / 60)  # 5 msgs, refill 1/min
    return PER_SENDER_BUCKETS[sender_phone]


def handle_incoming_sms(sender_phone: str, body: str, trai_match: TraiDltMatch | None = None) -> SmsRiskReply:
    """
    Entry point a real carrier webhook calls per inbound shortcode
    message. Runs the SAME cascade + NLI + confidence gate the main app
    uses (detection/, grounding/) -- one detection core, two channels
    (spec's "single, no-secondary-framework" discipline extended to
    detection logic reuse, not just the web framework).
    """
    if not _bucket_for(sender_phone).try_consume():
        return SmsRiskReply(accepted=False, reply_text="")  # silently rate-limited, no reply sent

    cascade_result = route(body)
    survivors, entailment_results = gate_candidates(cascade_result.candidates)
    gated = apply_confidence_gate(entailment_results)

    trai_note = ""
    if trai_match is not None and trai_match.is_meaningful_signal:
        trai_note = " Note: this message claims to be from a registered sender but doesn't match their approved template."

    if any_surfaced(gated):
        tactics = ", ".join(sorted({g.tactic_id for g in gated if g.verdict.value == "surfaced"}))
        reply = f"CAUTION: This message matches known scam patterns ({tactics}). Do not send money or personal info.{trai_note} Reply STOP to opt out."
    else:
        reply = f"No strong scam pattern detected -- but if you're unsure, don't send money or personal info.{trai_note} Reply STOP to opt out."

    return SmsRiskReply(accepted=True, reply_text=reply)
