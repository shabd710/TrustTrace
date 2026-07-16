"""
Tests for federated/ -- DP noise/RDP accounting, secure aggregation
(pairwise-mask cancellation + Byzantine-robust trimmed mean + k>=50
floor), sync scheduler abort behavior, canary rollout/rollback.
"""
import numpy as np

from dp_noise import clip_by_l2_norm, RdpAccountant
from secure_aggregation import (
    apply_pairwise_masks, coordinate_wise_trimmed_mean, run_secure_aggregation_round,
    ClientContribution, K_ANONYMITY_FLOOR,
)
from sync_scheduler import run_sync_with_continuous_verification, DeviceStateProvider
from model_distribution import stratified_canary_cohort, evaluate_canary, CanaryMetrics, EquitySliceMetric, RolloutDecision


def test_l2_clipping_bounds_norm():
    update = np.array([10.0, 10.0, 10.0])
    clipped = clip_by_l2_norm(update, clip_norm=5.0)
    assert abs(np.linalg.norm(clipped) - 5.0) < 1e-6


def test_rdp_privacy_cost_accumulates_across_rounds():
    acc = RdpAccountant()
    for _ in range(50):
        acc.compose_round(noise_multiplier=4.0, sampling_rate=0.01)
    eps_50 = acc.get_epsilon(target_delta=1e-5)
    for _ in range(50):
        acc.compose_round(noise_multiplier=4.0, sampling_rate=0.01)
    eps_100 = acc.get_epsilon(target_delta=1e-5)
    assert eps_100 > eps_50


def test_pairwise_masks_cancel_across_full_cohort():
    rng = np.random.default_rng(1)
    client_ids = [f"c{i}" for i in range(6)]
    true_updates = {cid: rng.normal(0, 1, size=(4,)) for cid in client_ids}
    pairwise_seeds = {
        tuple(sorted((client_ids[i], client_ids[j]))): hash((client_ids[i], client_ids[j])) % (2**31)
        for i in range(len(client_ids)) for j in range(i + 1, len(client_ids))
    }
    masked = {cid: apply_pairwise_masks(cid, true_updates[cid], pairwise_seeds, client_ids) for cid in client_ids}

    assert np.linalg.norm(masked["c0"] - true_updates["c0"]) > 100  # individually hidden
    cancellation_error = np.linalg.norm(sum(masked.values()) - sum(true_updates.values()))
    assert cancellation_error < 1e-8  # but cancels exactly when summed over the cohort


def test_trimmed_mean_rejects_byzantine_outlier():
    normal = np.random.default_rng(2).normal(0, 0.1, size=(20, 3))
    poisoned = normal.copy()
    poisoned[0] = [1000.0, -1000.0, 1000.0]
    trimmed = coordinate_wise_trimmed_mean(poisoned, trim_fraction=0.1)
    assert abs(trimmed[0]) < 5
    assert abs(poisoned.mean(axis=0)[0]) > 40  # sanity check: naive mean IS dragged


def test_k_floor_blocks_without_padding():
    few = [ClientContribution(f"c{i}", np.zeros(3), True) for i in range(K_ANONYMITY_FLOOR - 1)]
    assert run_secure_aggregation_round(few).success is False

    enough = [ClientContribution(f"c{i}", np.ones(3) * i * 0.01, True) for i in range(K_ANONYMITY_FLOOR + 10)]
    result = run_secure_aggregation_round(enough)
    assert result.success is True
    assert result.cohort_size == K_ANONYMITY_FLOOR + 10


def test_sync_aborts_immediately_on_mid_transfer_unplug():
    state = {"charging": True, "chunk_count": 0}

    def is_charging():
        state["chunk_count"] += 1
        if state["chunk_count"] > 4:
            state["charging"] = False
        return state["charging"]

    provider = DeviceStateProvider(is_charging_fn=is_charging, is_unmetered_wifi_fn=lambda: True)
    outcome = run_sync_with_continuous_verification(total_chunks=10, provider=provider)
    assert outcome.completed is False
    assert outcome.aborted_reason == "unplugged_mid_transfer"
    assert outcome.chunks_transferred < 10


def test_stratified_canary_includes_minority_stratum():
    devices = [{"id": i, "age_bracket": "18-64"} for i in range(970)] + [{"id": i, "age_bracket": "65+"} for i in range(970, 1000)]
    cohort = stratified_canary_cohort(devices, equity_dimension="age_bracket", min_per_stratum=3)
    elderly = [d for d in cohort if d["age_bracket"] == "65+"]
    assert len(elderly) >= 3


def test_canary_rollback_on_regression():
    bad = CanaryMetrics(
        baseline_false_positive_rate=0.02, canary_false_positive_rate=0.05,
        baseline_equity_slices=[EquitySliceMetric("age:65+", 0.85)],
        canary_equity_slices=[EquitySliceMetric("age:65+", 0.60)],
    )
    decision, reasons = evaluate_canary(bad)
    assert decision == RolloutDecision.ROLLBACK
    assert len(reasons) == 2

    good = CanaryMetrics(
        baseline_false_positive_rate=0.02, canary_false_positive_rate=0.0202,
        baseline_equity_slices=[EquitySliceMetric("age:65+", 0.85)],
        canary_equity_slices=[EquitySliceMetric("age:65+", 0.84)],
    )
    decision2, _ = evaluate_canary(good)
    assert decision2 == RolloutDecision.PROMOTE
