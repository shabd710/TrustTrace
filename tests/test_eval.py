"""
Tests for eval/ -- corpus precision/recall, equity slicing, and the
device-farm stage profiler's degraded-mode contract.
"""
from eval.evaluate import evaluate_manipulation_detection, predict_is_manipulation
from eval.equity_eval import evaluate_by_slice, check_for_regression
from eval.device_farm.stage_profiler import profile_pipeline, degraded_mode_contract, ProfileResult, StageTiming


def test_corpus_precision_and_recall():
    metrics = evaluate_manipulation_detection()
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0


def test_adversarial_narrative_arc_limitation_is_honestly_documented():
    metrics_with_adversarial = evaluate_manipulation_detection(include_adversarial=True)
    assert metrics_with_adversarial.recall < 1.0  # spec 10.1's named single-message limitation


def test_equity_slices_computed_and_regression_detected():
    by_age = evaluate_by_slice("age_bracket")
    assert len(by_age) >= 2
    assert check_for_regression(by_age, by_age) == []


def test_pipeline_profiling_stays_under_latency_gate():
    result = profile_pipeline("send the money now, only accept gift card, do not tell your bank, this is the irs")
    assert result.exceeds_latency_gate is False
    assert degraded_mode_contract(result) is None


def test_degraded_mode_notice_fires_when_gate_exceeded():
    slow = ProfileResult(stages=[StageTiming("simulated_slow_stage", 950.0)], total_ms=950.0,
                          exceeds_latency_gate=True, degraded_mode_triggered=True)
    notice = degraded_mode_contract(slow)
    assert notice is not None
    assert "verify independently" in notice
