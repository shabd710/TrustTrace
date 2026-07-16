"""
Manipulation-tactic taxonomy.

Spec ref: PDF Section 2.1. This is the shared vocabulary every other module
in detection/conversation/ and grounding/ is built against: Tier 0/1/2's
candidate flags, the NLI gate's hypothesis templates, and the eval corpus's
labels all key off TACTIC_ID here. Keeping the taxonomy in one place is what
makes "every flag cites the exact tactic + evidence" (PDF non-negotiable
philosophy) enforceable instead of aspirational.

Cross-layer security note: this file is pure data, not scored input, so it
carries no injection risk from user text -- but it IS the attack surface for
a *taxonomy-blind-spot* evasion (PDF Section 10.1): if a real manipulation
tactic has no entry here, no amount of downstream NLI rigor will catch it.
Extending this list is a product/eval decision (needs new labeled corpus
examples in eval/ground_truth/), not just a code change.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Tactic:
    id: str
    label: str
    description: str
    # Tier 0/1 lexical + pattern cues. Deliberately over-inclusive: Tier 0's
    # job is cheap recall, not precision -- precision is the NLI gate's job.
    cue_phrases: tuple
    # Fixed, pre-validated paraphrase templates for the NLI entailment gate
    # (PDF 7.3's determinism correction: no randomized template injection --
    # a security-relevant gate has to be reproducible and auditable).
    hypothesis_templates: tuple
    # Tactics that are semantically incompatible with this one firing at
    # high confidence in the same turn (PDF 8.2's mutual-exclusivity check,
    # e.g. simultaneous high-urgency + calming-reassurance is a contradiction
    # worth dropping rather than trusting either flag).
    mutually_exclusive_with: tuple = field(default_factory=tuple)


TACTICS: dict[str, dict] = {
    "urgency_injection": {
        "label": "Urgency Injection",
        "description": "Manufactured time pressure meant to short-circuit deliberation.",
        "cue_phrases": (
            "right now", "immediately", "act now", "urgent", "expires today",
            "final notice", "within the hour", "before it's too late",
            "last chance", "act fast", "time is running out",
        ),
        "hypothesis_templates": (
            "The speaker is pressuring the listener to act immediately without time to think.",
            "The message creates artificial time pressure to rush a decision.",
            "The sender is telling the recipient there is no time to verify or wait.",
        ),
        "mutually_exclusive_with": ("calming_reassurance",),
    },
    "isolation_instruction": {
        "label": "Isolation Instruction",
        "description": "Instructing the target to hide the interaction from people who could intervene.",
        "cue_phrases": (
            "don't tell", "do not tell", "keep this between us", "don't tell your bank",
            "do not tell your bank", "don't tell your family", "do not tell your family",
            "this is confidential", "don't mention this to anyone", "do not mention this to anyone",
            "keep it a secret", "don't call anyone", "do not call anyone",
            "don't tell the police", "do not tell the police",
        ),
        "hypothesis_templates": (
            "The speaker is instructing the listener to hide this conversation from family, friends, or their bank.",
            "The message tells the recipient not to tell anyone else about this.",
            "The sender is asking the listener to keep the interaction secret from people who could help them.",
        ),
    },
    "authority_impersonation": {
        "label": "Authority Impersonation",
        "description": "Claiming to be a bank, government agency, law enforcement, or executive to compel compliance.",
        "cue_phrases": (
            "this is the irs", "this is your bank", "law enforcement", "federal agent",
            "your account has been compromised", "official notice", "case number",
            "i am calling from", "this is your ceo", "your boss",
            # Tech-support / brand-impersonation vector (FTC/IC3 top category):
            # posing as a platform's security desk to manufacture authority.
            "microsoft", "microsoft security", "security team", "windows support",
            "tech support", "apple support", "your computer has been hacked",
            "your computer is infected", "virus detected", "we detected a virus",
            # Modern bank-phishing / account-security language (FTC "bank
            # impersonation" is now the single most-reported text-scam
            # opener). Deliberately over-inclusive for Tier 0 recall -- these
            # are DUAL-USE (real banks say them too), so the NLI gate treats
            # them as LOW_INFORMATION_CUES: they never surface alone, only
            # when a genuine solicitation (OTP / payment / remote-access)
            # corroborates them. See grounding/nli_entailment_gate.py.
            "your bank account", "account locked", "account has been locked",
            "account suspended", "account has been suspended", "security alert",
            "verify your identity", "confirm your identity", "fraud department",
            "unusual activity", "suspicious activity",
            # Fake-police / legal-threat impersonation (digital-arrest scams);
            # the softer ones are dual-use (LOW_INFORMATION_CUES in the gate).
            "this is the police", "police department", "arrest warrant",
            "warrant for your arrest", "digital arrest", "cyber crime",
            "money laundering", "customs department", "income tax department",
            # Delivery / customs impersonation openers (dual-use).
            "your parcel", "your package", "parcel is held", "package is held",
            # Bank-KYC impersonation (top India SMS-scam opener; dual-use).
            "kyc", "update your kyc", "kyc verification", "kyc expired",
        ),
        "hypothesis_templates": (
            "The speaker is claiming to represent a bank, government agency, or law enforcement to compel compliance.",
            "The message asserts institutional authority to make a request feel mandatory.",
            "The sender is impersonating someone in a position of authority over the recipient.",
        ),
    },
    "remote_access_solicitation": {
        "label": "Remote-Access / One-Time-Code Solicitation",
        "description": "Directing the target to install remote-control software or hand over a one-time code/OTP that grants the sender control of their device or account.",
        "cue_phrases": (
            "anydesk", "install anydesk", "download anydesk", "teamviewer",
            "remote access", "remote support", "install the app", "give me access",
            "6-digit code", "six-digit code", "6 digit code", "one-time code",
            "one time code", "otp", "verification code", "read me the code",
            "share the code", "tell me the code",
            # Screen-mirroring variants of the remote-access ask.
            "screen share", "screen sharing", "quick support",
        ),
        "hypothesis_templates": (
            "The speaker is directing the listener to install remote-access software or hand over a one-time code that grants the sender control of their device or account.",
            "The message is trying to obtain remote control of the recipient's device or a verification code sent to them.",
            "The sender is soliciting a one-time passcode or remote-access session under a pretext.",
        ),
    },
    "payment_channel_funneling": {
        "label": "Payment-Channel Funneling",
        "description": "Pivoting toward gift cards, wire transfer, or crypto as the sole accepted payment method -- the strongest compound signal per spec.",
        "cue_phrases": (
            "gift card", "wire transfer", "wire money", "wire the money", "crypto", "bitcoin", "only accept",
            "buy a gift card", "send the code", "usdt", "wire the money",
            "western union", "money order", "only way to pay",
            # UPI / QR rails (dominant in India). "upi pin" is a strong
            # receive-scam signal; brand names + "scan the qr" are dual-use.
            "upi", "upi pin", "enter your upi pin", "upi id",
            "google pay", "phonepe", "paytm", "gpay",
            "collect request", "scan the qr", "scan this qr", "scan to pay", "qr code",
            # Advance-fee framing (job / delivery / refund scams; dual-use).
            "registration fee", "processing fee", "advance fee", "security deposit",
        ),
        "hypothesis_templates": (
            "The speaker is directing the listener to pay using gift cards, wire transfer, or cryptocurrency as the only accepted method.",
            "The message insists on an unconventional, hard-to-reverse payment channel.",
            "The sender is funneling the recipient toward a specific payment method that resists reversal or tracing.",
        ),
    },
    "too_good_to_be_true": {
        "label": "Too-Good-To-Be-True Framing",
        "description": "Guaranteed high returns, unearned windfalls, or romance framed with implausible speed/perfection.",
        "cue_phrases": (
            "guaranteed return", "double your money", "risk-free investment",
            "you've won", "guaranteed profit", "no risk", "act now to claim",
            "i've never felt this way", "soulmate", "guaranteed income",
            # Job-offer and investment bait (all dual-use, need corroboration).
            "work from home", "part-time job", "part time job",
            "earn daily", "daily income", "no experience needed", "guaranteed job",
            "high returns", "investment opportunity", "trading tips",
        ),
        "hypothesis_templates": (
            "The message promises an unrealistic guaranteed financial return or windfall.",
            "The speaker is describing an outcome that is implausibly positive with no acknowledged risk.",
            "The sender is offering something of high value with no credible justification for why.",
        ),
    },
    "coercion_threat": {
        "label": "Threat / Coercion",
        "description": "Threatening arrest, exposure of private material, or other harm unless the target pays or complies -- fear used as leverage.",
        "cue_phrases": (
            # Sextortion / blackmail.
            "leak your photos", "leak your video", "expose you",
            "share your video", "share your photos", "intimate photos",
            "your private photos", "i have your videos", "send nudes",
            "post your pictures", "ruin your reputation",
            # Coercive legal / arrest threats (digital-arrest, fake-police).
            "pay or i will", "or i will post", "you will be arrested",
            "you will go to jail", "we will file a case",
        ),
        "hypothesis_templates": (
            "The speaker is threatening to harm, expose, or arrest the recipient unless they pay or comply.",
            "The message uses fear of arrest, legal action, or public exposure as leverage to force compliance.",
            "The sender is coercing the recipient with a threat rather than a request.",
        ),
    },
    # Not a manipulation tactic -- a benign-language marker used by the
    # mutual-exclusivity check (8.2) and the false-positive-avoidance path
    # (a real family emergency reads as urgent but should not compound into
    # a manipulation verdict on its own).
    "calming_reassurance": {
        "label": "Calming Reassurance",
        "description": "Explicit reassurance / de-escalation language -- used only as a contradiction check against urgency_injection, never scored as a standalone risk.",
        "cue_phrases": (
            "no rush", "take your time", "there's no pressure", "whenever you can",
            "it's okay", "don't worry", "no hurry",
        ),
        "hypothesis_templates": (
            "The speaker is explicitly telling the listener there is no time pressure.",
        ),
    },
}


def tactic_ids() -> list[str]:
    return list(TACTICS.keys())


def is_scoreable_tactic(tactic_id: str) -> bool:
    """calming_reassurance is a contradiction-check signal only, never a
    user-facing flag on its own -- see grounding/confidence_gate.py."""
    return tactic_id in TACTICS and tactic_id != "calming_reassurance"
