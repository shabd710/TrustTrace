"""
Canary rollout + automatic rollback for redistributed model updates.

Spec ref: PDF Section 4 (canary cohort, live monitoring of false-positive
rate + equity-sliced recall, automatic rollback on regression), 8.5 (1%
initial cohort), 10.4 (stratified, not purely random, canary sampling --
a flat random 1% can contain zero representation of an already-small
equity subgroup), 7.6 (client-side circuit breaker for crash loops, as a
complement to server-side canary/rollback).
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

CANARY_COHORT_FRACTION = 0.01
FALSE_POSITIVE_REGRESSION_THRESHOLD = 0.05  # >5% relative regression triggers rollback
EQUITY_SLICE_REGRESSION_THRESHOLD = 0.05    # matches the equity CI gate's own threshold, spec 7.7


class RolloutDecision(str, Enum):
    PROMOTE = "promote"
    ROLLBACK = "rollback"
    HOLD_MONITORING = "hold_monitoring"


@dataclass
class EquitySliceMetric:
    slice_name: str  # e.g. "age:65+", "language:hi", "accent:en-IN"
    recall: float


@dataclass
class CanaryMetrics:
    baseline_false_positive_rate: float
    canary_false_positive_rate: float
    baseline_equity_slices: list[EquitySliceMetric]
    canary_equity_slices: list[EquitySliceMetric]


def stratified_canary_cohort(all_devices: list[dict], equity_dimension: str, min_per_stratum: int = 3) -> list[dict]:
    """
    Spec 10.4's correction: a flat 1% random sample can plausibly contain
    zero representation of an already-small subgroup. Instead, groups
    devices by the given equity dimension (e.g. 'age_bracket') and pulls
    at least min_per_stratum from EVERY stratum, filling the rest of the
    1% budget proportionally.
    """
    strata: dict[str, list[dict]] = {}
    for device in all_devices:
        strata.setdefault(device.get(equity_dimension, "unknown"), []).append(device)

    cohort = []
    for stratum_devices in strata.values():
        take = min(len(stratum_devices), min_per_stratum)
        cohort.extend(stratum_devices[:take])

    target_size = max(len(cohort), int(len(all_devices) * CANARY_COHORT_FRACTION))
    remaining_budget = target_size - len(cohort)
    already_in = {id(d) for d in cohort}
    for device in all_devices:
        if remaining_budget <= 0:
            break
        if id(device) not in already_in:
            cohort.append(device)
            remaining_budget -= 1
    return cohort


def evaluate_canary(metrics: CanaryMetrics) -> tuple[RolloutDecision, list[str]]:
    """
    Automatic rollback per spec 4/9.4: an update that regresses
    false-positive rate OR any equity-sliced recall beyond threshold
    triggers rollback BEFORE wider rollout -- an update causing zero
    server errors can still be a worse or more biased model, so this
    check is independent of any infrastructure health signal.
    """
    reasons = []

    fp_baseline = max(metrics.baseline_false_positive_rate, 1e-6)
    fp_regression = (metrics.canary_false_positive_rate - fp_baseline) / fp_baseline
    if fp_regression > FALSE_POSITIVE_REGRESSION_THRESHOLD:
        reasons.append(f"False-positive rate regressed {fp_regression:.1%} (threshold {FALSE_POSITIVE_REGRESSION_THRESHOLD:.0%}).")

    baseline_by_slice = {s.slice_name: s.recall for s in metrics.baseline_equity_slices}
    for canary_slice in metrics.canary_equity_slices:
        baseline_recall = baseline_by_slice.get(canary_slice.slice_name)
        if baseline_recall is None or baseline_recall <= 0:
            continue
        recall_regression = (baseline_recall - canary_slice.recall) / baseline_recall
        if recall_regression > EQUITY_SLICE_REGRESSION_THRESHOLD:
            reasons.append(
                f"Equity slice '{canary_slice.slice_name}' recall regressed {recall_regression:.1%} "
                f"(threshold {EQUITY_SLICE_REGRESSION_THRESHOLD:.0%}) -- same release-blocking weight as battery/latency gates."
            )

    if reasons:
        return RolloutDecision.ROLLBACK, reasons
    return RolloutDecision.PROMOTE, []


@dataclass
class ClientCircuitBreaker:
    """Spec 7.6: local rollback if an update triggers crash loops --
    catches device-specific failures a canary sample might never see,
    independent of the server-side canary process above."""
    crash_count: int = 0
    crash_loop_threshold: int = 3

    def record_crash(self) -> bool:
        """Returns True if this crash trips the local circuit breaker
        (device should roll back to the previous model version NOW,
        without waiting for a server-side decision)."""
        self.crash_count += 1
        return self.crash_count >= self.crash_loop_threshold
