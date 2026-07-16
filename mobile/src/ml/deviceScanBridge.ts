/**
 * On-device stalkerware/spyware scan bridge.
 *
 * Spec ref: PDF Section 2.4 (owner-initiated, on-device-only scan;
 * dangerous-permission-combination + sideload + signature checks) and the
 * grounding discipline (every finding cites exact evidence -- permission
 * names, signature IDs). Section 7.4: Bloom pre-filter then exact match;
 * an unconfirmed probabilistic hit must NEVER surface as "detected".
 *
 * REAL vs SIM -- and why this is NOT a silent stub:
 * The actual scan requires native platform APIs (Android PackageManager /
 * queryable installed packages + granted permissions; iOS has no
 * equivalent, so device scan is Android-only per the spec's platform
 * honesty). That native module is registered via `registerDeviceScanner`
 * at native bootstrap. When it is NOT linked, this bridge does NOT return
 * an empty "clean device" array -- that would be a dangerous false
 * negative in a stalkerware context, telling an at-risk user they're safe
 * when nothing was actually checked. Instead it throws
 * `DeviceScanUnavailableError`, and the screen shows an honest
 * "scan unavailable on this build" state.
 */
import { DeviceScanFinding } from "../screens/DeviceScanScreen";

export class DeviceScanUnavailableError extends Error {
  constructor() {
    super(
      "On-device scanning requires the native scanner module, which is not " +
        "linked in this build. No scan was performed -- this is not a clean result.",
    );
    this.name = "DeviceScanUnavailableError";
  }
}

/**
 * The native scanner contract. A native Android module implements this and
 * registers it; it inspects installed packages, their granted permission
 * sets, sideload/cert status, and matches against the stalkerware
 * signature feed (Bloom pre-filter -> exact confirm), returning only
 * confirmed, evidence-carrying findings.
 */
export interface NativeDeviceScanner {
  isAvailable(): boolean;
  scanThisDevice(): Promise<DeviceScanFinding[]>;
}

let _scanner: NativeDeviceScanner | null = null;

export function registerDeviceScanner(scanner: NativeDeviceScanner): void {
  _scanner = scanner;
}

export function isDeviceScannerAvailable(): boolean {
  return _scanner !== null && _scanner.isAvailable();
}

/**
 * Run the owner-initiated scan. Throws DeviceScanUnavailableError when no
 * native scanner is linked -- callers surface that honestly rather than
 * presenting an unchecked device as clean.
 */
export async function runOwnDeviceScan(): Promise<DeviceScanFinding[]> {
  if (!isDeviceScannerAvailable() || _scanner === null) {
    throw new DeviceScanUnavailableError();
  }
  return _scanner.scanThisDevice();
}
