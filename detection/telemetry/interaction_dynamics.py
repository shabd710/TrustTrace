"""
Interaction-dynamics telemetry.

Spec ref: PDF Section 3.1 / Strict Instruction Summary: "permanently scoped
to standard motion sensors and TrustTrace's own UI timing -- never
cross-app keystroke or text-input capture." This file's type signature is
itself part of the enforcement: there is no field anywhere in this module
for "other app's text input" or "system-wide keystroke event" -- only
accelerometer/gyroscope samples and this app's own UI interaction timing.
Reading keystrokes in another app would require becoming the device's
system keyboard (a "full access" trust category), which would make this
app the same class of invasive access module 2.4 exists to detect --
that's a permanent architectural boundary, not a current-version limit.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class MotionSample:
    """Standard accelerometer/gyroscope reading -- exactly what any app
    can read via platform motion-sensor APIs, nothing more."""
    timestamp_ms: int
    accel_magnitude: float  # combined x/y/z magnitude, m/s^2
    gyro_magnitude: float


@dataclass(frozen=True)
class UiTimingSample:
    """TrustTrace's OWN UI interaction timing only -- e.g. time between a
    warning overlay appearing and the user tapping a button on IT. Never
    another app's UI, never system-wide input capture."""
    timestamp_ms: int
    event: str  # "warning_shown", "button_tap", "screen_foreground", etc.
    elapsed_since_prev_ms: int
