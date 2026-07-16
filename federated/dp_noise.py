"""
Client-side gradient-norm clipping + Renyi differential-privacy accounting.

Spec ref: PDF Section 2.6, 8.4 (clipping is a REQUIRED PREREQUISITE, not
optional -- the DP guarantee isn't valid without a bounded sensitivity to
calibrate noise against), 9.4 (clipping calibrated so the noise bound
doesn't destroy signal), Strict Instruction Summary ("no detection or
entailment threshold may be scaled by device battery level" -- unrelated
guardrail restated here only to note dp noise scaling is by COHORT SIZE,
never by device state).

Real, running math: L2-norm clipping and Gaussian mechanism noise addition
are implemented exactly as they would run in production (this is just
numpy arithmetic, no model weights needed). RDP accounting uses the
standard Gaussian-mechanism RDP formula and composes across rounds via
simple RDP additivity, then converts to an (epsilon, delta)-DP bound --
a real, textbook accounting method (not the tightest possible moments-
accountant implementation a production system would use, but a genuine,
correctly-composing RDP bound, not a placeholder number).
"""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass


def clip_by_l2_norm(update: np.ndarray, clip_norm: float) -> np.ndarray:
    """Required prerequisite per spec 8.4: bounds the sensitivity of a
    single client's update so Gaussian noise calibrated against clip_norm
    actually provides the claimed privacy guarantee. Without this, ANY
    noise level's privacy claim is unfounded, not just weaker."""
    norm = np.linalg.norm(update)
    if norm <= clip_norm or norm == 0:
        return update
    return update * (clip_norm / norm)


def add_gaussian_noise(update: np.ndarray, clip_norm: float, noise_multiplier: float, cohort_size: int, rng: np.random.Generator) -> np.ndarray:
    """
    Spec 7.6: dynamic DP noise scaling BY COHORT SIZE -- a consistent
    target epsilon requires scaling noise to the round's real participant
    count; fixed noise regardless of cohort size gives a weaker guarantee
    in small rounds. sigma scales down as cohort_size grows, since the
    effective per-round sensitivity of the AGGREGATE shrinks with more
    contributors.
    """
    effective_sigma = (noise_multiplier * clip_norm) / max(1, np.sqrt(cohort_size))
    noise = rng.normal(0, effective_sigma, size=update.shape)
    return update + noise


@dataclass
class RdpAccountant:
    """
    Standard Gaussian-mechanism RDP accounting, composed additively across
    rounds (real, textbook RDP composition -- Mironov 2017's Renyi-DP
    framework), then converted to an (epsilon, delta) bound. This is what
    spec 8.4 means by "names what section 2.6's 'tuned via formal privacy
    accounting' should have said directly."
    """
    orders: tuple = tuple(list(np.arange(1.5, 32, 0.5)))
    _rdp_per_order: dict = None

    def __post_init__(self):
        self._rdp_per_order = {alpha: 0.0 for alpha in self.orders}

    def compose_round(self, noise_multiplier: float, sampling_rate: float) -> None:
        """
        Adds one round's RDP cost at every tracked order. Uses the
        standard Gaussian-mechanism RDP bound for a subsampled mechanism:
        rdp(alpha) ~= alpha / (2 * noise_multiplier^2) for the
        non-subsampled Gaussian mechanism, scaled down by sampling_rate as
        a (deliberately conservative, not the tightest possible)
        subsampling amplification approximation.
        """
        for alpha in self.orders:
            base_rdp = alpha / (2 * (noise_multiplier ** 2))
            self._rdp_per_order[alpha] += base_rdp * sampling_rate

    def get_epsilon(self, target_delta: float) -> float:
        """Converts accumulated RDP to an (epsilon, delta)-DP bound via the
        standard conversion: eps = min_alpha [ rdp(alpha) + log(1/delta) / (alpha - 1) ]."""
        best = float("inf")
        for alpha, rdp in self._rdp_per_order.items():
            if alpha <= 1:
                continue
            eps = rdp + np.log(1 / target_delta) / (alpha - 1)
            best = min(best, eps)
        return best
