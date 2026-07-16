"""
Synthetic scenario injection: scam SMS, fake incoming calls, rapid
foreground-app switching.

Spec ref: PDF Section 4: "synthetic injection of scam SMS, fake incoming
calls, and rapid foreground-app switching."

Honest technical note, worth stating plainly rather than papering over
with a fake API call: AWS Device Farm's REAL, physical device pool does
NOT support arbitrary externally-triggered SMS delivery or incoming-call
simulation on real hardware -- both are gated by the carrier network, not
something Appium or Device Farm's automation layer can inject into a
physical phone from outside. This is a genuine platform constraint, not
a gap in this repo. The three scenarios below are handled with the
REAL, supported mechanism for each, not a uniform fake:

  - Rapid foreground-app switching: FULLY supported by Appium on real
    Device Farm hardware (`activate_app`/`terminate_app` or the
    `mobile: activateApp` execute-script form) -- implemented for real
    below.
  - Scam SMS: on a physical device, delivered via a debug-build-only
    "test injection" deep link/intent that feeds synthetic text directly
    into the SAME code path a real shared/pasted transcript would use
    (detection/conversation/model_cascade.py's real entry point) --
    exercising the detection logic without needing carrier-level SMS
    delivery. On an EMULATOR (a separate, ADB-controlled test lane, not
    Device Farm's real-device pool), `adb emu sms send` genuinely works
    and is used for the message-filter-extension-adjacent UI flow instead.
  - Fake incoming calls: same split -- a debug-build test hook drives the
    wake-gate/CallDirectory code path directly on real Device Farm
    hardware; `adb emu gsm call` is the emulator-lane equivalent for the
    full ringing-UI flow.

NOT EXECUTABLE HERE -- see appium_harness.py's note.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class InjectionLane(str, Enum):
    REAL_DEVICE_TEST_HOOK = "real_device_test_hook"  # debug-build intent/deep-link, works on AWS Device Farm hardware
    EMULATOR_ADB = "emulator_adb"                      # adb emu ..., emulator-only, NOT AWS Device Farm's real-device pool


@dataclass(frozen=True)
class InjectionScenario:
    name: str
    lane: InjectionLane
    detail: str


SCAM_SMS_SCENARIOS: list[InjectionScenario] = [
    InjectionScenario(
        "irs_gift_card_scam_sms", InjectionLane.REAL_DEVICE_TEST_HOOK,
        "Debug-build deep link `trusttrace-test://inject-sms?body=...` feeds the same "
        "text into detection/conversation/model_cascade.route() the real paste/share flow uses.",
    ),
    InjectionScenario(
        "irs_gift_card_scam_sms_emulator_lane", InjectionLane.EMULATOR_ADB,
        "`adb emu sms send +15550001111 \"...\"` -- exercises the actual "
        "ILMessageFilterExtension-adjacent SMS-received UI flow, emulator-only.",
    ),
]

FAKE_CALL_SCENARIOS: list[InjectionScenario] = [
    InjectionScenario(
        "flagged_caller_id_wake_gate_trigger", InjectionLane.REAL_DEVICE_TEST_HOOK,
        "Debug-build intent directly invokes WakeGate.on_incoming_call(is_flagged_caller=True) "
        "(detection/telemetry/wake_gate.py's real, tested method) without needing a real ringing call.",
    ),
    InjectionScenario(
        "flagged_caller_id_emulator_lane", InjectionLane.EMULATOR_ADB,
        "`adb emu gsm call +15550001111` -- exercises the full CallKit/CallDirectory "
        "ringing-UI flow, emulator-only.",
    ),
]


def rapid_foreground_app_switch(driver, app_ids: list[str], switch_count: int, delay_seconds: float = 0.2) -> list[float]:
    """
    FULLY REAL on actual AWS Device Farm hardware -- `driver` is a real
    `appium.webdriver.Remote` instance (see appium_harness.py). Returns
    the wall-clock timestamp of each switch, which the caller correlates
    against WakeGate/AccessibilityService log output to confirm the
    detection pipeline doesn't miss or duplicate-trigger under rapid
    switching (spec 8.3's debounce requirement,
    detection/telemetry/wake_gate.py's EVENT_DEBOUNCE_MS-equivalent).
    """
    import time
    timestamps = []
    for i in range(switch_count):
        app_id = app_ids[i % len(app_ids)]
        driver.execute_script("mobile: activateApp", {"appId": app_id})
        timestamps.append(time.time())
        time.sleep(delay_seconds)
    return timestamps
