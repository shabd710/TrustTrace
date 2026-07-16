"""
Sideload / installer-certificate check.

Spec ref: PDF Section 2.4 ("sideloaded-app detection") and 10.2 (Android
14+ Restricted Settings context -- a distribution consideration, not a
detection-logic change).

Real logic: pure comparison against a known-store installer allowlist.
Platform-specific data collection (PackageManager.getInstallerPackageName
on Android) is native-only; this is the portable comparison logic it
feeds into.
"""
from __future__ import annotations
from dataclasses import dataclass

KNOWN_STORE_INSTALLERS = frozenset({
    "com.android.vending",       # Google Play Store
    "com.sec.android.app.samsungapps",  # Samsung Galaxy Store
    "com.amazon.venezia",        # Amazon Appstore
})


@dataclass
class SideloadFinding:
    package_name: str
    installer_package: str | None
    is_sideloaded: bool


def check_installer(package_name: str, installer_package: str | None) -> SideloadFinding:
    is_sideloaded = installer_package is None or installer_package not in KNOWN_STORE_INSTALLERS
    return SideloadFinding(package_name, installer_package, is_sideloaded)
