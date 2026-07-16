"""
Tests for eval/device_farm/{appium_harness,synthetic_injection,battery_latency_gates}.py.

appium_harness.py's capability builders and battery_latency_gates.py's
check_release_gates() are pure Python with no external dependency --
genuinely tested here. build_remote_driver() is confirmed to honestly
refuse (not fake a connection) since no real appium/Device Farm exists.
"""
import pytest

from eval.device_farm.appium_harness import build_android_capabilities, build_ios_capabilities, build_remote_driver
from eval.device_farm.battery_latency_gates import check_release_gates, DeviceFarmPerformanceReport
from eval.device_farm.stage_profiler import LATENCY_GATE_MS, BATTERY_DRAIN_GATE_PERCENT_PER_HOUR
from eval.device_farm.synthetic_injection import rapid_foreground_app_switch, SCAM_SMS_SCENARIOS, FAKE_CALL_SCENARIOS, InjectionLane


class _MockAppiumDriver:
    """Stands in for a real appium.webdriver.Remote instance -- lets
    rapid_foreground_app_switch's real call sequence be verified without
    a live Device Farm connection."""
    def __init__(self):
        self.calls = []

    def execute_script(self, script, params):
        self.calls.append((script, params))


def test_rapid_foreground_app_switch_calls_real_appium_api_correctly():
    driver = _MockAppiumDriver()
    timestamps = rapid_foreground_app_switch(driver, ["com.trusttrace.app", "com.bank.legit"], switch_count=6, delay_seconds=0.01)
    assert len(driver.calls) == 6
    assert all(c[0] == "mobile: activateApp" for c in driver.calls)
    apps_used = [c[1]["appId"] for c in driver.calls]
    assert apps_used == ["com.trusttrace.app", "com.bank.legit"] * 3
    assert timestamps == sorted(timestamps)


def test_injection_scenarios_cover_both_lanes_honestly():
    assert len(SCAM_SMS_SCENARIOS) == 2
    assert len(FAKE_CALL_SCENARIOS) == 2
    assert any(s.lane == InjectionLane.REAL_DEVICE_TEST_HOOK for s in SCAM_SMS_SCENARIOS)
    assert any(s.lane == InjectionLane.EMULATOR_ADB for s in SCAM_SMS_SCENARIOS)


def test_android_capabilities_shape():
    caps = build_android_capabilities("com.trusttrace.app", ".MainActivity")
    assert caps["platformName"] == "Android"
    assert caps["appium:automationName"] == "UiAutomator2"
    assert caps["appium:appPackage"] == "com.trusttrace.app"


def test_ios_capabilities_shape():
    caps = build_ios_capabilities("com.trusttrace.app")
    assert caps["platformName"] == "iOS"
    assert caps["appium:automationName"] == "XCUITest"


def test_remote_driver_honestly_refuses_without_real_grid():
    with pytest.raises(RuntimeError, match="No appium-python-client"):
        build_remote_driver({}, "https://fake-grid-url")


def test_release_gates_pass_on_clean_run():
    reports = [DeviceFarmPerformanceReport(
        device_id="pixel_8_pro", battery_percent_at_start=100.0, battery_percent_at_end=97.0,
        test_duration_hours=1.0, overlay_to_notification_latencies_ms=[120, 340, 210],
    )]
    assert check_release_gates(reports) == []


def test_release_gates_catch_battery_drain_violation():
    reports = [DeviceFarmPerformanceReport(
        device_id="pixel_8_pro", battery_percent_at_start=100.0, battery_percent_at_end=88.0,  # 12%/hour
        test_duration_hours=1.0, overlay_to_notification_latencies_ms=[120],
    )]
    violations = check_release_gates(reports)
    assert len(violations) == 1
    assert violations[0].gate_name == "battery_drain"
    assert f"{BATTERY_DRAIN_GATE_PERCENT_PER_HOUR}" in violations[0].detail


def test_release_gates_catch_latency_violation():
    reports = [DeviceFarmPerformanceReport(
        device_id="iphone_15", battery_percent_at_start=100.0, battery_percent_at_end=98.0,
        test_duration_hours=1.0, overlay_to_notification_latencies_ms=[120, 950, 340],  # 950ms > 800ms gate
    )]
    violations = check_release_gates(reports)
    assert len(violations) == 1
    assert violations[0].gate_name == "latency"
    assert f"{LATENCY_GATE_MS}" in violations[0].detail


def test_release_gates_check_every_device_independently():
    reports = [
        DeviceFarmPerformanceReport("good_device", 100.0, 97.0, 1.0, [200]),
        DeviceFarmPerformanceReport("bad_device", 100.0, 80.0, 1.0, [900]),
    ]
    violations = check_release_gates(reports)
    device_ids_with_violations = {v.device_id for v in violations}
    assert device_ids_with_violations == {"bad_device"}
    assert len(violations) == 2  # bad_device violates BOTH gates
