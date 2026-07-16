"""
Profiling-first discipline: per-stage latency measurement.

Spec ref: PDF Section 3.5: "Every pipeline stage is profiled independently
... before any further hardware-level optimization is adopted." Section 4:
">800ms is a hard, release-blocking CI failure." Section 10.1: thermal/CPU-
fallback degraded-mode contract (cap at Tier 0 only with a "reduced
confidence, verify independently" notice, rather than silently exceeding
budget).

REAL vs SIM: real device-farm hardware (Appium against AWS Device Farm) is
obviously not available here. What IS real: this actually measures wall-
clock latency of THIS repo's own cascade/NLI/confidence-gate pipeline on
whatever CPU this code runs on, stage by stage, using time.perf_counter --
genuine profiling data about genuine code, just not on a real mobile
device's silicon. The 800ms gate logic itself is real and exercised.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field

from detection.conversation.model_cascade import route
from grounding.nli_entailment_gate import gate_candidates
from grounding.confidence_gate import apply as apply_confidence_gate

LATENCY_GATE_MS = 800.0
BATTERY_DRAIN_GATE_PERCENT_PER_HOUR = 5.0  # spec 4 -- not measurable without real hardware; documented threshold only


@dataclass
class StageTiming:
    stage_name: str
    duration_ms: float


@dataclass
class ProfileResult:
    stages: list[StageTiming]
    total_ms: float
    exceeds_latency_gate: bool
    degraded_mode_triggered: bool


def profile_pipeline(text: str) -> ProfileResult:
    stages: list[StageTiming] = []

    t0 = time.perf_counter()
    cascade_result = route(text)
    t1 = time.perf_counter()
    stages.append(StageTiming("cascade_tier0_1_2", (t1 - t0) * 1000))

    survivors, entailment_results = gate_candidates(cascade_result.candidates)
    t2 = time.perf_counter()
    stages.append(StageTiming("nli_entailment_gate", (t2 - t1) * 1000))

    gated = apply_confidence_gate(entailment_results)
    t3 = time.perf_counter()
    stages.append(StageTiming("confidence_gate", (t3 - t2) * 1000))

    total_ms = (t3 - t0) * 1000
    exceeds = total_ms > LATENCY_GATE_MS

    return ProfileResult(stages=stages, total_ms=total_ms, exceeds_latency_gate=exceeds,
                          degraded_mode_triggered=exceeds)


def degraded_mode_contract(profile: ProfileResult) -> str | None:
    """
    Spec 10.1: if thermal throttling + CPU fallback stacking blows the
    800ms gate, cap at Tier 0 only with an explicit "reduced confidence,
    verify independently" notice -- never silently exceed budget or
    silently degrade quality without telling the user.
    """
    if not profile.exceeds_latency_gate:
        return None
    return "Reduced confidence: full analysis unavailable right now, verify independently."
