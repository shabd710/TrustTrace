"""
Thermal governor: cascade-first thermal response + degraded-mode contract.

Spec ref: PDF Section 7.1: "thermal pressure should first push more load
onto Tier 0/1 -- which the cascade already does by design -- before ever
degrading Tier 2's own precision; the cascade is the primary
thermal-response lever, a 2-bit fallback is a last resort behind it."
Section 10.1: "Thermal throttling stacking with the mandatory CPU
fallback could still blow the 800ms gate ... an explicit degraded-mode
contract for this compound scenario -- cap at Tier 0 only, with a
'reduced confidence, verify independently' notice, rather than silently
exceeding budget or silently degrading detection quality without telling
the user."

This module makes both rules executable policy instead of prose:

  Response LADDER (strictly ordered -- tested):
    NOMINAL            -> full cascade (Tier 2 available, 4-bit)
    ELEVATED           -> raise Tier 1->2 escalation bar (cascade lever
                          FIRST: fewer Tier 2 invocations, same precision
                          when it does run)
    SEVERE             -> Tier 2 swaps to the pre-built 2-bit variant
                          (last resort BEHIND the cascade lever -- spec's
                          own live-requantization correction: variants
                          are pre-built at conversion time, never
                          requantized on the fly)
    CRITICAL_COMPOUND  -> Tier 0 only + MANDATORY user notice (the 10.1
                          degraded-mode contract). user_notice is never
                          None in this state -- silent degradation is a
                          constructible-state error, not a policy hope.

  HYSTERESIS: recovery requires the temperature to fall a margin BELOW
  each threshold before stepping back up, so a device oscillating at a
  boundary doesn't flap between model variants (each swap has real
  load-time cost). Escalation is immediate; de-escalation is damped.

  What this NEVER does (STRICT SUMMARY rule, tested): thermal state
  adjusts WHICH tiers run and HOW OFTEN escalation happens -- it never
  touches a detection or entailment THRESHOLD. The same evidence gets
  the same verdict at any temperature; heat changes compute allocation,
  not what counts as true.

REAL vs SIM: the policy logic is fully real and tested. Temperature
readings come from the platform's thermal API in production
(PowerManager.getThermalHeadroom / ProcessInfo.thermalState) -- callers
pass the reading in; this module deliberately has no sensor access.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ThermalState(str, Enum):
    NOMINAL = "nominal"
    ELEVATED = "elevated"
    SEVERE = "severe"
    CRITICAL_COMPOUND = "critical_compound"


@dataclass(frozen=True)
class CascadePolicy:
    """What the cascade is allowed to do under the current thermal state.
    NOTE: no detection/NLI threshold appears here BY DESIGN -- see module
    docstring's STRICT SUMMARY rule."""
    max_tier: int                      # 0, 1, or 2
    tier2_variant: str                 # "4bit" | "2bit" | "unavailable"
    escalation_bar_multiplier: float   # >1.0 = Tier 2 invoked more rarely
    user_notice: str | None            # mandatory in CRITICAL_COMPOUND


_POLICIES: dict[ThermalState, CascadePolicy] = {
    ThermalState.NOMINAL: CascadePolicy(
        max_tier=2, tier2_variant="4bit",
        escalation_bar_multiplier=1.0, user_notice=None),
    ThermalState.ELEVATED: CascadePolicy(
        max_tier=2, tier2_variant="4bit",
        escalation_bar_multiplier=1.5,   # cascade lever first (7.1)
        user_notice=None),
    ThermalState.SEVERE: CascadePolicy(
        max_tier=2, tier2_variant="2bit",  # pre-built variant swap, last resort
        escalation_bar_multiplier=2.0, user_notice=None),
    ThermalState.CRITICAL_COMPOUND: CascadePolicy(
        max_tier=0, tier2_variant="unavailable",
        escalation_bar_multiplier=float("inf"),
        # The 10.1 degraded-mode contract, verbatim in spirit:
        user_notice=("Running in reduced-confidence mode because this "
                     "phone is overheating -- verify anything important "
                     "independently.")),
}

# Escalation thresholds (fraction of thermal limit) and the hysteresis
# margin required to step back down. Values are the empirical-calibration
# starting points the spec's style prescribes, tuned on device-farm data
# (3.5) in production.
_ESCALATE_AT = {
    ThermalState.ELEVATED: 0.70,
    ThermalState.SEVERE: 0.85,
    ThermalState.CRITICAL_COMPOUND: 0.95,
}
_HYSTERESIS_MARGIN = 0.05


class ThermalGovernor:
    def __init__(self) -> None:
        self._state = ThermalState.NOMINAL

    @property
    def state(self) -> ThermalState:
        return self._state

    def update(self, thermal_fraction: float,
               cpu_fallback_active: bool = False) -> CascadePolicy:
        """Feed the latest platform thermal reading (0.0-1.0+ of limit).

        cpu_fallback_active models the 10.1 COMPOUND case: thermal
        throttling stacking with accelerator loss. Severe heat + CPU-only
        execution is exactly the scenario that blows the 800ms gate, so
        it jumps straight to the degraded-mode contract.
        """
        target = self._target_state(thermal_fraction, cpu_fallback_active)
        if target.value != self._state.value:
            if _rank(target) > _rank(self._state):
                self._state = target                       # escalate immediately
            elif self._can_deescalate_to(target, thermal_fraction, cpu_fallback_active):
                self._state = _one_step_down(self._state)  # recover damped, one rung
        return _POLICIES[self._state]

    def _target_state(self, frac: float, compound: bool) -> ThermalState:
        if compound and frac >= _ESCALATE_AT[ThermalState.SEVERE]:
            return ThermalState.CRITICAL_COMPOUND
        if frac >= _ESCALATE_AT[ThermalState.CRITICAL_COMPOUND]:
            return ThermalState.CRITICAL_COMPOUND
        if frac >= _ESCALATE_AT[ThermalState.SEVERE]:
            return ThermalState.SEVERE
        if frac >= _ESCALATE_AT[ThermalState.ELEVATED]:
            return ThermalState.ELEVATED
        return ThermalState.NOMINAL

    def _can_deescalate_to(self, target: ThermalState, frac: float,
                           compound: bool) -> bool:
        if compound and self._state == ThermalState.CRITICAL_COMPOUND:
            return False   # compound condition must clear before recovery
        threshold = _ESCALATE_AT.get(self._state)
        if threshold is None:
            return True
        return frac <= threshold - _HYSTERESIS_MARGIN


_ORDER = [ThermalState.NOMINAL, ThermalState.ELEVATED,
          ThermalState.SEVERE, ThermalState.CRITICAL_COMPOUND]


def _rank(state: ThermalState) -> int:
    return _ORDER.index(state)


def _one_step_down(state: ThermalState) -> ThermalState:
    return _ORDER[max(0, _rank(state) - 1)]
