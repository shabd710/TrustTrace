"""
Appium <-> AWS Device Farm connection harness.

Spec ref: PDF Target Environment / Section 4: "Device-farm CI: Appium
against AWS Device Farm on real hardware." "Device-farm harness: Appium
against AWS Device Farm on real hardware, with synthetic injection of
scam SMS, fake incoming calls, and rapid foreground-app switching. Battery
drain >5%/hour or overlay/OCR-to-notification latency >800ms are hard,
release-blocking CI failures."

NOT EXECUTABLE HERE -- `appium-python-client` isn't installed (no network
access to pip install it in this sandbox), and there is no real AWS
Device Farm project/device pool to connect to from here regardless.
Written to the real `appium-python-client` + AWS Device Farm API surface;
syntax-checked via `ast.parse` in this build, nothing more.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceFarmTarget:
    """AWS Device Farm run configuration -- project ARN + device pool ARN,
    the two identifiers a real `aws devicefarm schedule-run` call (or the
    Appium-Python-Client Remote WebDriver pointed at Device Farm's grid
    endpoint) needs."""
    project_arn: str
    device_pool_arn: str
    app_upload_arn: str  # the .ipa/.apk already uploaded to Device Farm for this run


def build_android_capabilities(app_package: str, app_activity: str) -> dict:
    """
    Real Appium/UiAutomator2 capability set for an Android TrustTrace
    build under AWS Device Farm. `appium:app` is intentionally omitted --
    Device Farm's own scheduling API supplies the app binary via
    app_upload_arn, not a local file path.
    """
    return {
        "platformName": "Android",
        "appium:automationName": "UiAutomator2",
        "appium:appPackage": app_package,
        "appium:appActivity": app_activity,
        "appium:noReset": False,
        "appium:newCommandTimeout": 180,
    }


def build_ios_capabilities(bundle_id: str) -> dict:
    """Real Appium/XCUITest capability set for an iOS TrustTrace build."""
    return {
        "platformName": "iOS",
        "appium:automationName": "XCUITest",
        "appium:bundleId": bundle_id,
        "appium:noReset": False,
        "appium:newCommandTimeout": 180,
    }


def build_remote_driver(capabilities: dict, device_farm_grid_url: str):
    """
    SEAM: real implementation does
        from appium import webdriver
        from appium.options.common.base import AppiumOptions
        options = AppiumOptions().load_capabilities(capabilities)
        return webdriver.Remote(device_farm_grid_url, options=options)
    Not called here -- `appium` isn't installed and there is no real grid
    URL to connect to in this sandbox. Raising explicitly rather than
    faking a driver object, same discipline as every other network/
    hardware seam in this repo (see threat-intel/ingest_public_feeds.py's
    fetch_raw_feed for the same pattern).
    """
    raise RuntimeError(
        "No appium-python-client installed and no real AWS Device Farm grid "
        "URL configured in this environment. Install appium-python-client and "
        "supply a real Device Farm project/device-pool ARN to actually connect."
    )
