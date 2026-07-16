"""
Regression tests for the information-weighted specificity fix and the
expanded authority-impersonation taxonomy.

Context: the NLI entailment gate previously scored a matched cue almost
entirely by its TOKEN COUNT (grounding/nli_entailment_gate._specificity),
so the strongest evidence for whole scam families -- short terms of art like
"OTP", "AnyDesk", "Bitcoin", "gift card" -- was labelled "fragmentary" and
dropped below ENTAILMENT_CONFIDENCE_CEILING even when Tier 0/1 matched it
cleanly. These tests pin the corrected behaviour: high-information short cues
carry proportionate weight (better recall), while the gate stays conservative
(dual-use bank language and benign chat still abstain -- no new false
positives).

Runs the full production path per example (route -> gate_candidates ->
confidence_gate.apply -> any_surfaced), identical to eval/evaluate.py and the
backend.
"""
from detection.conversation.model_cascade import route
from detection.conversation.tactic_taxonomy import TACTICS
from grounding.nli_entailment_gate import (
    evaluate_entailment, gate_candidates, _specificity, _information_weight,
    HIGH_INFO_WEIGHT, LOW_INFO_WEIGHT,
)
from grounding.confidence_gate import apply as apply_confidence_gate, any_surfaced


def _surfaces(text: str) -> bool:
    """End-to-end: does this message reach the user as a warning?"""
    r = route(text)
    _, entailment_results = gate_candidates(r.candidates)
    return any_surfaced(apply_confidence_gate(entailment_results))


# --------------------------------------------------------------------------
# Recall: short high-information scam cues must no longer be filtered out.
# --------------------------------------------------------------------------

def test_otp_phishing_surfaces():
    # The exact reported regression: authority (dual-use) + OTP solicitation
    # + urgency. Previously abstained_entailment_failed on every tactic.
    assert _surfaces(
        "Your bank account has been locked due to suspicious activity. "
        "Please tell me the OTP sent to your phone immediately to verify your identity."
    )


def test_bank_phishing_surfaces():
    assert _surfaces(
        "This is your bank's fraud department. Your account has been suspended. "
        "Verify your identity now by confirming the verification code we sent."
    )


def test_tech_support_scam_surfaces():
    assert _surfaces(
        "Microsoft security team here. Your computer is infected with a virus. "
        "Install AnyDesk so we can remove it immediately."
    )


def test_gift_card_scam_surfaces():
    assert _surfaces(
        "You've won a prize! To claim it, buy a gift card and send the code to us right now."
    )


def test_crypto_scam_surfaces():
    assert _surfaces(
        "Guaranteed profit! Send Bitcoin to our crypto wallet immediately and "
        "double your money, risk-free. Don't tell anyone."
    )


def test_romance_scam_requesting_money_surfaces():
    assert _surfaces(
        "I've never felt this way about you. I need you to wire money for my flight, "
        "but please don't tell your family, it is urgent."
    )


# --------------------------------------------------------------------------
# Precision: the fix must NOT turn benign messages into warnings, including
# ones that legitimately use the newly-added dual-use bank phrases.
# --------------------------------------------------------------------------

def test_benign_banking_notification_does_not_surface():
    # Plain transactional notification -- no manipulation cue at all.
    assert not _surfaces(
        "Your account balance is 2450 dollars. You have 3 recent transactions. Log in to view details."
    )


def test_benign_bank_security_alert_does_not_surface():
    # Contains the NEW dual-use cues ("security alert", "your bank account")
    # but no solicitation -- the low-information cap must keep it abstained,
    # proving the taxonomy expansion did not create a false positive.
    assert not _surfaces(
        "Security alert: we noticed a new login to your bank account from a new device. "
        "If this was you, no action is needed."
    )


def test_benign_family_conversation_does_not_surface():
    assert not _surfaces(
        "Hey mom, can you send me the recipe for your soup? Also are we still on for dinner Sunday?"
    )


def test_benign_family_isolation_shaped_but_harmless_does_not_surface():
    # "don't tell" is an isolation cue, but a single un-corroborated benign
    # use must not fire (fail-closed the other way: no false alarm).
    assert not _surfaces(
        "Don't tell your brother but I'm planning a surprise party for his birthday next week."
    )


# --------------------------------------------------------------------------
# Unit-level: the specificity function itself.
# --------------------------------------------------------------------------

def test_short_high_information_cue_is_not_treated_as_fragmentary():
    # The core bug: "otp" is one word but maximally discriminative. Old code
    # gave it ~0.33; it must now clear a meaningful specificity floor.
    assert _information_weight("otp") == HIGH_INFO_WEIGHT
    assert _information_weight("anydesk") == HIGH_INFO_WEIGHT
    assert _information_weight("bitcoin") == HIGH_INFO_WEIGHT
    assert _specificity(["otp"]) == HIGH_INFO_WEIGHT
    assert _specificity(["gift card"]) >= HIGH_INFO_WEIGHT


def test_dual_use_bank_phrase_is_capped_low():
    # "your bank account" is 3 words (old code -> 1.0) but appears verbatim
    # in benign messages, so it must be capped, needing corroboration.
    assert _information_weight("your bank account") == LOW_INFO_WEIGHT
    assert _information_weight("security alert") == LOW_INFO_WEIGHT
    assert _specificity(["your bank account", "security alert"]) == LOW_INFO_WEIGHT


def test_high_information_floor_never_lowers_a_long_strong_phrase():
    # max(word_based, high_floor): a 3+ word strong phrase keeps its full
    # word-count specificity rather than being pulled down to the floor.
    assert _specificity(["wire the money"]) == 1.0


def test_empty_spans_give_zero_specificity():
    assert _specificity([]) == 0.0


# --------------------------------------------------------------------------
# Taxonomy: the expanded authority-impersonation cues actually fire in Tier 0.
# --------------------------------------------------------------------------

def test_expanded_authority_taxonomy_matches_modern_phishing_phrases():
    for phrase in ("your bank account", "account locked", "security alert",
                   "verify your identity", "fraud department", "unusual activity"):
        assert phrase in TACTICS["authority_impersonation"]["cue_phrases"], phrase

    # And they surface as an authority candidate from real Tier 0 routing.
    r = route("This is your bank. There is unusual activity and your account has been locked.")
    assert "authority_impersonation" in {c.tactic_id for c in r.candidates}


def test_negation_still_suppresses_even_high_information_cue():
    # Guard against the fix over-firing: a negated strong cue must still be
    # dropped (the information floor raises specificity, but the negation
    # penalty still closes the gate).
    from detection.conversation.model_cascade import TacticCandidate
    negated = TacticCandidate("payment_channel_funneling", ["gift card"], 0.9,
                              "I would never send a gift card to someone I just met.")
    assert evaluate_entailment(negated).survived is False
