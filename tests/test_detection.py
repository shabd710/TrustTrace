"""
Tests for detection/ -- cascade routing, memory compaction, transaction
risk, device stalkerware checks, telemetry wake gate.

Run with: pip install -r requirements.txt && pytest tests/test_detection.py
(NOT executed via pytest in the sandbox this repo was built in -- no
network access to install pytest there; every assertion below was
independently verified via plain `python3 -c` during development. See
TrustTrace_Application_Guide.md for the full verification log.)
"""
import time
import random

from detection.conversation.model_cascade import route
from detection.conversation.memory_compaction import ConversationMemory
from detection.conversation.transcript_normalizer import normalize_text, reassemble_turns, RawTurn
from detection.conversation.spatial_prompt_serializer import serialize, OcrBox
from detection.conversation.voice_clone_detector import score_call, AcousticScore
from detection.transaction.payee_novelty_check import check, PayeeHistory
from detection.transaction.risk_scorer import build_warning
from detection.device.permission_graph import scan_own_device, InstalledAppPermissions
from detection.device.stalkerware_signatures import StalkerwareSignatureIndex
from detection.device.sideload_cert_check import check_installer
from detection.telemetry.wake_gate import WakeGate, EwmaChangepointDetector


def test_cascade_benign_stays_tier0():
    assert route("hey how are you doing today").tier_reached == 0


def test_cascade_multi_tactic_escalates():
    r = route("this is urgent, act now, do not tell your bank")
    assert r.tier_reached >= 1
    tactic_ids = {c.tactic_id for c in r.candidates}
    assert "urgency_injection" in tactic_ids
    assert "isolation_instruction" in tactic_ids


def test_cascade_high_stakes_reaches_tier2():
    r = route("send the money now, only accept gift card, do not tell your bank, this is the irs")
    assert r.tier_reached == 2


def test_cascade_calming_language_not_flagged():
    r = route("take your time, no rush at all, whenever you can get to it")
    assert r.tier_reached == 0


def test_memory_compaction_retains_flags_after_window_ages_out():
    mem = ConversationMemory(session_id="s1")
    for i in range(15):
        text = "act now, this is urgent" if i == 2 else "just chatting, how are you"
        r = route(text, session_prior_flags=mem.session_prior_flag_ids())
        mem.add_turn("scammer", text, r)
    assert len(mem.raw_window) <= 12
    summary = mem.structured_summary()
    assert any(f["tactic"] == "urgency_injection" for f in summary["risk_flags"])
    raw_turn_indices = {t["turn_index"] for t in mem.raw_window}
    assert 3 not in raw_turn_indices  # aged out of raw window, but flag survives permanently


def test_transcript_normalizer_burst_reassembly():
    turns = [
        RawTurn("scammer", "send", 1000), RawTurn("scammer", "me", 1500),
        RawTurn("scammer", "the", 1900), RawTurn("scammer", "money now", 2300),
        RawTurn("victim", "ok", 9000),
    ]
    reassembled = reassemble_turns(turns)
    assert reassembled[0].text == "send me the money now"
    assert reassembled[0].source_message_count == 4


def test_spatial_serializer_flags_low_confidence():
    boxes = [OcrBox(text="SPECIAL OFFER", confidence=0.42, x_pct=5, y_pct=2, w_pct=25, h_pct=6)]
    assert "[low-confidence]" in serialize(boxes)


def test_voice_clone_compound_beats_acoustic_alone():
    high_risk_cascade = route("send the money now, only accept gift card, do not tell your bank, this is the irs")
    benign_cascade = route("how is the weather")
    compound = score_call(AcousticScore(spoof_probability=0.85, codec_prefiltered=True), high_risk_cascade)
    acoustic_only = score_call(AcousticScore(spoof_probability=0.85, codec_prefiltered=True), benign_cascade)
    assert compound.compound_confidence > acoustic_only.compound_confidence


def test_payee_novelty_requires_compound_factors():
    single_factor = check("payee_new_1", 50.0, PayeeHistory(known_payees=set(), last_manipulation_flag_epoch=None))
    assert single_factor.compound_risk is False

    compound = check("payee_new_2", 800.0, PayeeHistory(known_payees=set(), last_manipulation_flag_epoch=time.time() - 60))
    assert compound.compound_risk is True


def test_risk_scorer_never_offers_cancel_action():
    compound = check("payee_new_2", 800.0, PayeeHistory(known_payees=set(), last_manipulation_flag_epoch=time.time() - 60))
    warning = build_warning(compound, [("do not tell your bank", 3)])
    assert warning.should_warn is True
    assert set(warning.available_actions) == {"i_understand_continue_anyway", "go_back"}


def test_permission_graph_catches_canonical_triad_only():
    apps = [
        InstalledAppPermissions("com.evil.spy", "System Update",
                                 frozenset({"ACCESSIBILITY_SERVICE", "BIND_DEVICE_ADMIN", "SYSTEM_ALERT_WINDOW", "CAMERA"})),
        InstalledAppPermissions("com.bank.legit", "MyBank", frozenset({"ACCESSIBILITY_SERVICE", "INTERNET"})),
    ]
    findings = scan_own_device(apps)
    assert len(findings) == 1
    assert findings[0].package_name == "com.evil.spy"


def test_stalkerware_bloom_prefilter_requires_exact_match():
    idx = StalkerwareSignatureIndex(["sig_abc123", "sig_def456"])
    assert idx.check("sig_abc123").exact_match_confirmed is True
    assert idx.check("sig_totally_unrelated_xyz") is None


def test_sideload_check():
    assert check_installer("com.bank.legit", "com.android.vending").is_sideloaded is False
    assert check_installer("com.evil.spy", None).is_sideloaded is True


def test_wake_gate_ignores_steady_baseline_but_catches_real_anomaly():
    random.seed(42)
    det = EwmaChangepointDetector()
    triggers = sum(det.update(9.8 + random.gauss(0, 0.05)) for _ in range(200))
    assert triggers <= 3

    anomaly_triggers = 0
    for i in range(20):
        v = 9.8 + random.gauss(0, 0.05) + (5.0 if i > 2 else 0)
        if det.update(v):
            anomaly_triggers += 1
    assert anomaly_triggers >= 1


def test_wake_gate_combines_signals():
    gate = WakeGate()
    assert gate.should_wake() is False
    gate.on_payment_app_foreground(True)
    assert gate.should_wake() is True
    assert gate.wake_reasons() == ["payment_app_foreground"]
