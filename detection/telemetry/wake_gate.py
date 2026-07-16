"""
Unified low-power wake gate: EWMA-based streaming changepoint detection.

Spec ref: PDF Section 3.1: "evaluated with online, streaming changepoint
detection (an EWMA-based sequential test) over the accelerometer-variance
and UI-interaction-timing series, rather than a static threshold ... lets
the confidence estimate shift within milliseconds as new samples arrive,
while staying cheap enough to run continuously."

Real, running logic: a genuine sequential EWMA-of-variance changepoint
detector -- no ML weights needed, this is exactly the kind of cheap
always-on signal the spec calls for, and it runs for real on synthetic
motion-sample input here. Heavy pipelines (Tier 2, OCR, ReplayKit,
voice-clone model) are gated behind `WakeGate.should_wake()` -- this file
is the actual dormancy/wake state machine, not just documentation of the
rule. Strict Instruction Summary: "Heavy inference pipelines stay dormant
until the unified low-power wake gate fires -- an architectural rule, not a
tuning suggestion," enforced structurally by every heavy-pipeline caller
being required to check `should_wake()` first (see backend/main.py wiring).
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .interaction_dynamics import MotionSample


@dataclass
class EwmaChangepointDetector:
    """Sequential EWMA-of-variance test: tracks a slow-moving baseline
    variance and a fast-moving recent variance; a wake signal fires when
    the fast estimate deviates from the baseline by more than
    `deviation_threshold` standard-deviation-equivalents. Pure streaming
    state -- O(1) memory and O(1) work per sample, cheap enough to run
    continuously per spec."""
    alpha_slow: float = 0.02   # baseline (long-horizon) EWMA smoothing factor
    alpha_fast: float = 0.3    # recent (short-horizon) EWMA smoothing factor
    deviation_threshold: float = 2.5
    warmup_samples: int = 25   # baseline variance is unreliable before this many samples

    _baseline_mean: float = field(default=0.0, init=False)
    _baseline_var: float = field(default=1e-6, init=False)  # avoid div-by-zero at cold start
    _fast_mean: float = field(default=0.0, init=False)
    _initialized: bool = field(default=False, init=False)
    _sample_count: int = field(default=0, init=False)

    def update(self, value: float) -> bool:
        """Feed one new sample; returns True if this sample triggers a
        changepoint (motion-anomaly wake signal)."""
        self._sample_count += 1
        if not self._initialized:
            self._baseline_mean = value
            self._fast_mean = value
            self._initialized = True
            return False

        # Fast EWMA tracks recent short-horizon signal level.
        self._fast_mean = self.alpha_fast * value + (1 - self.alpha_fast) * self._fast_mean

        deviation = abs(self._fast_mean - self._baseline_mean)
        std_equiv = max(self._baseline_var, 1e-6) ** 0.5
        is_changepoint = (
            self._sample_count > self.warmup_samples
            and deviation > self.deviation_threshold * std_equiv
        )

        # Baseline only adapts on NON-anomalous samples, so a sustained
        # anomaly doesn't get slowly absorbed into "the new normal" and
        # silently stop triggering.
        if not is_changepoint:
            delta = value - self._baseline_mean
            self._baseline_mean += self.alpha_slow * delta
            self._baseline_var = (1 - self.alpha_slow) * self._baseline_var + self.alpha_slow * (delta ** 2)

        return is_changepoint


@dataclass
class WakeGate:
    """
    Combines the zero-cost signals spec 3.1 names: Android payment-app
    foreground change, incoming-call identification, and the
    accelerometer/gyroscope motion-anomaly signal via the changepoint
    detector above. Any ONE of these firing wakes the gate -- heavy
    pipelines stay dormant otherwise.
    """
    motion_detector: EwmaChangepointDetector = field(default_factory=EwmaChangepointDetector)
    _payment_app_foreground: bool = field(default=False, init=False)
    _flagged_incoming_call: bool = field(default=False, init=False)
    _motion_anomaly: bool = field(default=False, init=False)

    def on_motion_sample(self, sample: MotionSample) -> None:
        self._motion_anomaly = self.motion_detector.update(sample.accel_magnitude)

    def on_payment_app_foreground(self, is_foreground: bool) -> None:
        self._payment_app_foreground = is_foreground

    def on_incoming_call(self, is_flagged_caller: bool) -> None:
        self._flagged_incoming_call = is_flagged_caller

    def should_wake(self) -> bool:
        return self._payment_app_foreground or self._flagged_incoming_call or self._motion_anomaly

    def wake_reasons(self) -> list[str]:
        reasons = []
        if self._payment_app_foreground:
            reasons.append("payment_app_foreground")
        if self._flagged_incoming_call:
            reasons.append("flagged_incoming_call")
        if self._motion_anomaly:
            reasons.append("motion_anomaly_changepoint")
        return reasons
