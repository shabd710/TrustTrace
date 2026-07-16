"""
Dangerous permission-combination detector.

Spec ref: PDF Section 2.4: "dangerous permission combinations
(Accessibility Service + Device Admin + draw-over-other-apps together is
the canonical stalkerware/RAT pattern)". Section 7.4 explicitly notes the
irony: this checker's own app requests Accessibility Service (spec 2.3),
which is exactly why spec 2.3's implementation is scoped to a hardcoded
payment-app whitelist -- an unrestricted Accessibility Service is
indistinguishable from what this file exists to catch.

Consent boundary, restated because it's load-bearing here specifically:
this function only ever runs against the CALLING device's own installed-app
permission list, on that device owner's initiation. There is no remote or
cross-device variant of this function anywhere in this codebase, by design
(Strict Instruction Summary: "No scanning any device without that device's
owner actively consenting.").

Real, running logic: this is a pure graph/set-membership check over
whatever permission data the platform provides (Android's PackageManager,
in production) -- the checking logic itself has no platform dependency and
is fully real here.
"""
from __future__ import annotations
from dataclasses import dataclass

# The canonical stalkerware/RAT triad per spec 2.4/7.4.
CANONICAL_STALKERWARE_PATTERN = frozenset({
    "ACCESSIBILITY_SERVICE", "BIND_DEVICE_ADMIN", "SYSTEM_ALERT_WINDOW",  # draw-over-other-apps
})


@dataclass
class InstalledAppPermissions:
    package_name: str
    display_name: str
    granted_permissions: frozenset[str]


@dataclass
class PermissionGraphFinding:
    package_name: str
    display_name: str
    matched_pattern: frozenset[str]
    citation_permissions: list[str]


def scan_own_device(installed_apps: list[InstalledAppPermissions]) -> list[PermissionGraphFinding]:
    """
    Consent precondition: caller (the mobile app's device-scanner screen)
    must only ever invoke this with `installed_apps` sourced from the
    SAME device, gathered only after the user explicitly initiated a scan.
    This function has no side channel to fetch that data itself -- it is
    pure data-in, findings-out, which is what makes the consent boundary
    enforceable at the call site rather than trusted to this file's
    internal discipline alone.
    """
    findings = []
    for app in installed_apps:
        overlap = app.granted_permissions & CANONICAL_STALKERWARE_PATTERN
        if overlap == CANONICAL_STALKERWARE_PATTERN:
            findings.append(PermissionGraphFinding(
                package_name=app.package_name,
                display_name=app.display_name,
                matched_pattern=overlap,
                citation_permissions=sorted(overlap),
            ))
    return findings
