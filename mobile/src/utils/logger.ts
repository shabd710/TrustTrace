/**
 * Development-only diagnostic logger.
 *
 * Spec ref: PDF Section 5 (on-device-first; the transcript never leaves the
 * phone). Bring-up logging previously wrote transcript text and raw model
 * output to `console.log`, which on Android lands in logcat -- a device-wide
 * log readable via `adb` and some diagnostic tooling. That is an exfiltration
 * surface for exactly the sensitive content this app exists to protect.
 *
 * This logger makes every call a NO-OP in production (`__DEV__ === false`), so
 * production logs stay clean, while the same tagged diagnostics remain
 * available during development. Callers should still prefer logging lengths /
 * tactic ids over raw transcript content, even in dev.
 */

// `__DEV__` is a global boolean Metro injects at build time (true in dev, false
// in release). Guarded so this also behaves under plain `tsc` / jest.
const IS_DEV: boolean = typeof __DEV__ !== "undefined" ? __DEV__ : false;

/** Dev-only console.log. No-op in production. */
export function debugLog(...args: unknown[]): void {
  if (IS_DEV) {
    // eslint-disable-next-line no-console
    console.log(...args);
  }
}

/** Dev-only console.warn. No-op in production. */
export function debugWarn(...args: unknown[]): void {
  if (IS_DEV) {
    // eslint-disable-next-line no-console
    console.warn(...args);
  }
}

/** True in development builds; use to gate any dev-only behavior. */
export const isDev: boolean = IS_DEV;
