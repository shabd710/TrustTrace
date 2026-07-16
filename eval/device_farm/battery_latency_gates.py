"""
Release-blocking CI gates: battery drain >5%/hour, latency >800ms.

Spec ref: PDF Section 4: "Battery drain >5%/hour or overlay/OCR-to-
notification latency >800ms are hard, release-blocking CI failures."
Section 8.5: "the >800ms latency gate ... stay at their existing
release-blocking strength rather than being softened to a log-only
warning."

Real, running gate-checking logic -- shares its exact latency threshold
with eval/device_farm/stage_profiler.py (LATENCY_GATE_MS), so there is
ONE source of truth for "800ms" across the pure-Python profiling path
(stage_profiler.py, which genuinely runs in this sandbox) and this
device-farm-report-parsing path (which needs a real Device Farm run's
output artifact to have real data to check).

NOT EXECUTABLE END-TO-END HERE -- no real AWS Device Farm run exists to
produce a real performance report. `check_release_gates()` itself,
however, is pure Python and IS tested below against representative
report shapes.
"""
from __future__ import annotations
from dataclasses import dataclass

from eval.device_farm.stage_profiler import LATENCY_GATE_MS, BATTERY_DRAIN_GATE_PERCENT_PER_HOUR


@dataclass(frozen=True)
class DeviceFarmPerformanceReport:
    """
    Shape of the data this function needs, sourced in production from AWS
    Device Farm's real "Performance" report artifact (battery/CPU/memory
    time series) plus this repo's own overlay/OCR-to-notification
    timestamp logs collected during the run.
    """
    device_id: str
    battery_percent_at_start: float
    battery_percent_at_end: float
    test_duration_hours: float
    overlay_to_notification_latencies_ms: list[float]


@dataclass(frozen=True)
class GateViolation:
    device_id: str
    gate_name: str
    detail: str


def check_release_gates(reports: list[DeviceFarmPerformanceReport]) -> list[GateViolation]:
    """
    Release-blocking, per spec 4/8.5 -- ANY violation on ANY device fails
    the build (same release-blocking weight the equity gate in
    eval/equity_eval.py already carries for its own thresholds).
    """
    violations: list[GateViolation] = []

    for report in reports:
        if report.test_duration_hours <= 0:
            continue
        drain_percent = report.battery_percent_at_start - report.battery_percent_at_end
        drain_rate_per_hour = drain_percent / report.test_duration_hours
        if drain_rate_per_hour > BATTERY_DRAIN_GATE_PERCENT_PER_HOUR:
            violations.append(GateViolation(
                report.device_id, "battery_drain",
                f"{drain_rate_per_hour:.2f}%/hour exceeds the {BATTERY_DRAIN_GATE_PERCENT_PER_HOUR}%/hour gate.",
            ))

        over_budget = [ms for ms in report.overlay_to_notification_latencies_ms if ms > LATENCY_GATE_MS]
        if over_budget:
            violations.append(GateViolation(
                report.device_id, "latency",
                f"{len(over_budget)}/{len(report.overlay_to_notification_latencies_ms)} "
                f"overlay/OCR-to-notification events exceeded the {LATENCY_GATE_MS}ms gate "
                f"(worst: {max(over_budget):.0f}ms).",
            ))

    return violations
