/**
 * Runtime configuration for the mobile app.
 *
 * Spec ref: PDF Section 5 (on-device-first; any cloud call is opt-in per
 * use, never automatic) and Section 2.9/6 (the backend exists primarily
 * for the SMS-lite gateway and the opt-in "explain more" path, not as the
 * default mobile scoring path).
 *
 * The base URL is resolved in priority order:
 *   1. EXPO_PUBLIC_TRUSTTRACE_API_URL   (env, injected at build time)
 *   2. expo.extra.trusttraceApiUrl      (app.json / app.config.js)
 *   3. a platform-aware localhost default for dev
 *
 * On Android emulators, 127.0.0.1 refers to the emulator itself, not the
 * host machine running FastAPI -- the host is reachable at 10.0.2.2. That
 * asymmetry is handled here so a developer doesn't silently hit a dead
 * address.
 */
import { Platform } from "react-native";
import Constants from "expo-constants";

const IS_DEV: boolean = typeof __DEV__ !== "undefined" ? __DEV__ : false;

/** 1. Build-time env override (EXPO_PUBLIC_* is inlined by the bundler). */
function readEnvUrl(): string | undefined {
  const v = process.env.EXPO_PUBLIC_TRUSTTRACE_API_URL;
  return typeof v === "string" && v.length > 0 ? v : undefined;
}

function readExtra(): string | undefined {
  // expoConfig is the modern field; fall back to the legacy manifest
  // shape so this resolves across Expo SDK versions without throwing.
  const anyConstants = Constants as unknown as {
    expoConfig?: { extra?: Record<string, unknown> };
    manifest?: { extra?: Record<string, unknown> };
  };
  const extra =
    anyConstants.expoConfig?.extra ?? anyConstants.manifest?.extra ?? {};
  const val = extra["trusttraceApiUrl"];
  return typeof val === "string" && val.length > 0 ? val : undefined;
}

function defaultLocalhost(): string {
  // Android emulator -> host loopback is 10.0.2.2; iOS simulator shares
  // the host's localhost. A physical device needs an explicit LAN URL via
  // env/extra above (localhost would point at the phone itself).
  if (Platform.OS === "android") {
    return "http://10.0.2.2:8000";
  }
  return "http://localhost:8000";
}

function trimTrailingSlash(u: string): string {
  return u.replace(/\/+$/, "");
}

function isLoopback(u: string): boolean {
  return /^https?:\/\/(localhost|127\.0\.0\.1|10\.0\.2\.2)(:|\/|$)/i.test(u);
}

/**
 * Fully-resolved API base URL, no trailing slash.
 *
 * Resolution order (as documented in the module header):
 *   1. EXPO_PUBLIC_TRUSTTRACE_API_URL   (build-time env)
 *   2. expo.extra.trusttraceApiUrl      (app.json / app.config.js)
 *   3. platform-aware localhost default  (dev only)
 *
 * PRODUCTION SECURITY: a non-loopback URL MUST be HTTPS. The opt-in cloud
 * paths carry a transcript excerpt, so shipping a cleartext (http://) URL
 * would leak it in transit. In a release build we FAIL CLOSED -- an unset or
 * cleartext URL resolves to "" so the cloud calls simply fail and the app
 * degrades to the on-device explanation, rather than transmitting in the
 * clear. Loopback dev addresses stay allowed only while __DEV__ is true.
 */
function resolveApiBaseUrl(): string {
  const candidate = readEnvUrl() ?? readExtra() ?? defaultLocalhost();
  const url = trimTrailingSlash(candidate);

  const isHttps = /^https:\/\//i.test(url);
  if (isHttps) {
    return url;
  }
  // Cleartext is only acceptable for a loopback address during development.
  if (IS_DEV && isLoopback(url)) {
    return url;
  }
  // eslint-disable-next-line no-console
  console.error(
    "[TrustTrace] Refusing insecure API base URL in production " +
      "(set EXPO_PUBLIC_TRUSTTRACE_API_URL to an https:// endpoint). " +
      "Cloud calls are disabled; the app uses the on-device path only.",
  );
  return "";
}

export const API_BASE_URL: string = resolveApiBaseUrl();
/**
 * Whether the opt-in cloud "explain more" path is permitted to reach the
 * backend at all. Defaults to true, but a build/policy layer can force it
 * off (e.g. in a jurisdiction or enterprise config where no cloud call is
 * allowed) -- the on-device path never depends on this.
 */
export const CLOUD_EXPLAIN_ENABLED: boolean =
  process.env.EXPO_PUBLIC_TRUSTTRACE_CLOUD_EXPLAIN !== "false";

/**
 * Network timeout for the (rare, opt-in) backend calls, in ms. These are
 * INTERACTIVE -- the user is waiting on an "Explain more" tap -- so a long
 * hang is a bad experience. 30s comfortably covers a cloud LLM round-trip
 * while still falling back to the on-device explanation promptly when the
 * backend is unreachable. (Was 120s, which stalled the UI up to two minutes.)
 */
export const API_TIMEOUT_MS = 30_000;
