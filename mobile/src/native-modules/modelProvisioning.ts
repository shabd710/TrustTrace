/**
 * On-device GGUF model provisioning + path resolution (device-build only --
 * excluded from the sandbox typecheck).
 *
 * WHY THIS WAS REDESIGNED
 * -----------------------
 * The previous resolver checked model existence through expo-file-system
 * (getInfoAsync / readDirectoryAsync). On Android 13/14 those run a permission
 * gate that only whitelists Expo's OWN internal dirs, so they THROW
 * "isn't readable" for the app's own external files dir -- even though the OS
 * grants the app full access there and llama.rn's native initLlama (fopen/mmap
 * under the app uid) could load the file fine. The result was a false negative:
 * the GGUF was present, `adb shell ls` showed it, but modelFileExists()
 * returned false and initLlama() never ran, so the app stayed on the heuristic
 * scorer forever.
 *
 * THE FIX
 * -------
 * Provisioning now goes through the `TrustTraceModelFs` native module
 * (src/native-modules/modelFs.ts), which talks to java.io.File directly under
 * the app uid -- the SAME access path initLlama uses -- so its answers are
 * authoritative. The resolver:
 *
 *   1. Resolves the app-owned dirs from the OS (getExternalFilesDir / filesDir),
 *      never hardcoding /storage/emulated/0/Android/data/...
 *   2. Treats INTERNAL storage (<filesDir>/models) as the canonical, gate-free
 *      load location.
 *   3. On first run, if the model is only staged in the (adb-pushed) EXTERNAL
 *      dir, COPIES it into internal storage, then loads from internal. This is
 *      the "Model Copy -> documentDirectory/models -> initLlama" flow: after the
 *      one-time copy every later launch finds it internally and just works.
 *   4. Verifies size (sanity floor) and, if a checksum is pinned via env,
 *      SHA-256 before handing the path to initLlama.
 *
 * If the native module is not linked (Expo Go / JS-only sandbox), every step
 * degrades to the old expo-file-system path so nothing regresses.
 *
 * Mirrors the backend's env-driven model resolution
 * (detection/conversation/llm_runtime.py: TRUSTTRACE_TIER1_GGUF /
 * TRUSTTRACE_TIER2_GGUF) so the same filenames and override mechanism work on
 * both sides.
 */
import { modelFs, type ModelStat } from "./modelFs";

const TIER1_FILENAME = "Llama-3.2-1B-Instruct-f16.gguf";
const TIER2_FILENAME = "Llama-3.2-3B-Instruct-Q8_0.gguf";

// Fallback external files dir, used ONLY when the native module is absent and
// we can't resolve the real path from the OS. Matches android build.gradle
// applicationId. The native path (getExternalFilesDir) supersedes this whenever
// the module is linked.
const ANDROID_PACKAGE = "com.trusttrace.app";
const EXTERNAL_FILES_DIR_FALLBACK = `/storage/emulated/0/Android/data/${ANDROID_PACKAGE}/files`;

// Sanity floor: a real Llama-3.2 GGUF is well over 1 GB. Anything smaller is a
// truncated/partial push, not a loadable model -- never hand it to initLlama.
const MIN_GGUF_BYTES = 200 * 1024 * 1024;

const TAG = "[TrustTrace/model-provisioning]";
function log(...args: unknown[]): void {
  // eslint-disable-next-line no-console
  console.log(TAG, ...args);
}

function stripScheme(p: string): string {
  return p.replace(/^file:\/\//, "");
}
function trimSlash(p: string): string {
  return p.replace(/\/+$/, "");
}
function dirname(rawPath: string): string {
  const i = rawPath.lastIndexOf("/");
  return i <= 0 ? "/" : rawPath.slice(0, i);
}

function envValue(key: string): string | null {
  const v = (process.env as Record<string, string | undefined>)[key];
  return typeof v === "string" && v.length > 0 ? v : null;
}
function envPath(key: string): string | null {
  const v = envValue(key);
  return v !== null ? stripScheme(v) : null;
}

// ---------------------------------------------------------------------------
// expo-file-system fallback (only when the native module isn't linked)
// ---------------------------------------------------------------------------

type ExpoFs = {
  documentDirectory?: string | null;
  getInfoAsync?: (uri: string) => Promise<{ exists?: boolean; size?: number }>;
  makeDirectoryAsync?: (uri: string, opts?: { intermediates?: boolean }) => Promise<void>;
};
function expoFs(): ExpoFs | null {
  try {
    return require("expo-file-system") as ExpoFs;
  } catch {
    return null;
  }
}
function expoInternalFilesDir(): string | null {
  const dir = expoFs()?.documentDirectory ?? null;
  return typeof dir === "string" && dir.length > 0 ? trimSlash(stripScheme(dir)) : null;
}

// ---------------------------------------------------------------------------
// Authoritative filesystem layer (native module first, expo fallback)
// ---------------------------------------------------------------------------

/** stat under the app uid, or via expo, or a definitive "absent" if neither works. */
async function statPath(rawPath: string): Promise<ModelStat> {
  const fsn = modelFs();
  if (fsn) {
    try {
      return await fsn.stat(rawPath);
    } catch (err) {
      log(`native stat threw for ${rawPath}:`, String(err));
      return { exists: false, isFile: false, canRead: false, size: 0 };
    }
  }
  // Fallback: expo. Note this reintroduces the read gate, so it only reliably
  // works for internal (documentDirectory) paths -- which is exactly where the
  // native-module-less path can still read.
  const fs = expoFs();
  if (fs && typeof fs.getInfoAsync === "function") {
    try {
      const info = await fs.getInfoAsync(`file://${rawPath}`);
      const exists = info?.exists === true;
      return { exists, isFile: exists, canRead: exists, size: info?.size ?? 0 };
    } catch (err) {
      log(`expo getInfoAsync threw for ${rawPath} (read gate?):`, String(err));
    }
  }
  return { exists: false, isFile: false, canRead: false, size: 0 };
}

async function ensureDir(rawPath: string): Promise<boolean> {
  const fsn = modelFs();
  if (fsn) {
    try {
      return await fsn.ensureDir(rawPath);
    } catch (err) {
      log(`native ensureDir failed for ${rawPath}:`, String(err));
      return false;
    }
  }
  const fs = expoFs();
  if (fs && typeof fs.makeDirectoryAsync === "function") {
    try {
      await fs.makeDirectoryAsync(`file://${rawPath}`, { intermediates: true });
      return true;
    } catch (err) {
      log(`expo makeDirectoryAsync failed for ${rawPath}:`, String(err));
    }
  }
  return false;
}

/** App-owned external models dir, resolved from the OS (not hardcoded). */
async function externalModelsDir(): Promise<string | null> {
  const fsn = modelFs();
  if (fsn) {
    try {
      const base = await fsn.externalFilesDir();
      if (typeof base === "string" && base.length > 0) {
        return `${trimSlash(base)}/models`;
      }
    } catch (err) {
      log("native externalFilesDir failed, using fallback path:", String(err));
    }
  }
  return `${EXTERNAL_FILES_DIR_FALLBACK}/models`;
}

/** App-owned internal models dir (gate-free canonical load location). */
async function internalModelsDir(): Promise<string | null> {
  const fsn = modelFs();
  if (fsn) {
    try {
      const base = await fsn.internalFilesDir();
      if (typeof base === "string" && base.length > 0) {
        return `${trimSlash(base)}/models`;
      }
    } catch (err) {
      log("native internalFilesDir failed, trying expo documentDirectory:", String(err));
    }
  }
  const internal = expoInternalFilesDir();
  return internal !== null ? `${internal}/models` : null;
}

// ---------------------------------------------------------------------------
// Integrity checks
// ---------------------------------------------------------------------------

function sizeOk(stat: ModelStat): boolean {
  return stat.size >= MIN_GGUF_BYTES;
}

/** Optional SHA-256 pin via env (EXPO_PUBLIC_..._SHA256). No pin => pass. */
async function checksumOk(rawPath: string, shaEnvKey: string): Promise<boolean> {
  const expected = envValue(shaEnvKey);
  if (expected === null) {
    return true; // no pin configured
  }
  const fsn = modelFs();
  if (!fsn) {
    log(`checksum pinned (${shaEnvKey}) but native module absent -- skipping verification`);
    return true;
  }
  try {
    const actual = await fsn.sha256(rawPath);
    const match = actual.toLowerCase() === expected.trim().toLowerCase();
    if (!match) {
      log(`checksum MISMATCH for ${rawPath}: expected ${expected}, got ${actual}`);
    }
    return match;
  } catch (err) {
    log(`checksum computation failed for ${rawPath}:`, String(err));
    return false;
  }
}

/** True only if the file exists, is readable, big enough, and (if pinned) matches. */
async function isUsableModel(rawPath: string, shaEnvKey: string): Promise<boolean> {
  const stat = await statPath(rawPath);
  if (!stat.exists || !stat.canRead) {
    return false;
  }
  if (!sizeOk(stat)) {
    log(`ignoring ${rawPath}: size ${stat.size} < floor ${MIN_GGUF_BYTES} (partial push?)`);
    return false;
  }
  return checksumOk(rawPath, shaEnvKey);
}

// ---------------------------------------------------------------------------
// Provisioning: stage external -> internal, then resolve
// ---------------------------------------------------------------------------

/**
 * Copy an external-staged GGUF into internal storage. Returns the internal path
 * on success (verified size + optional checksum), or null on any failure.
 */
async function copyIntoInternal(
  externalPath: string,
  internalPath: string,
  expectedSize: number,
  shaEnvKey: string,
): Promise<string | null> {
  const fsn = modelFs();
  if (!fsn) {
    return null;
  }
  try {
    await ensureDir(dirname(internalPath));

    // Storage pre-check: don't start a multi-GB copy that can't fit (it would
    // fail partway and waste I/O). Require the model size plus a small margin.
    try {
      const free = await fsn.usableSpace(internalPath);
      if (free > 0 && free < expectedSize * 1.05) {
        log(
          `insufficient internal storage for copy: need ~${Math.ceil(
            expectedSize * 1.05,
          )} bytes, have ${free}. Will load external in place instead.`,
        );
        return null;
      }
    } catch (err) {
      // usableSpace is best-effort; proceed if it isn't available.
      log("usableSpace check unavailable, proceeding with copy:", String(err));
    }

    log(
      `staging model into internal storage (one-time): ${externalPath} -> ${internalPath} ` +
        `(${expectedSize} bytes)`,
    );
    const written = await fsn.copyFile(externalPath, internalPath);
    if (written !== expectedSize) {
      log(`copy size mismatch: wrote ${written}, expected ${expectedSize}`);
      return null;
    }
    if (!(await checksumOk(internalPath, shaEnvKey))) {
      return null;
    }
    log(`staged OK -- future launches load directly from ${internalPath}`);
    return internalPath;
  } catch (err) {
    log(`copy into internal failed:`, String(err));
    return null;
  }
}

/**
 * Resolve a loadable GGUF path for one tier, provisioning as needed.
 *
 * Priority:
 *   1. Env override (explicit absolute path) -- loaded in place if usable.
 *   2. Internal <filesDir>/models/<name> -- canonical, gate-free.
 *   3. External <extFilesDir>/models/<name> (adb-pushed) -- copied into
 *      internal, then internal is returned. If the copy can't happen but the
 *      external file is readable under the app uid, it's loaded in place.
 */
async function resolveModel(
  envPathKey: string,
  shaEnvKey: string,
  filename: string,
): Promise<string | null> {
  // 1. Explicit env override.
  const override = envPath(envPathKey);
  if (override !== null && (await isUsableModel(override, shaEnvKey))) {
    log(`using env-override model: ${override}`);
    return override;
  }

  // 2. Internal (canonical). Always readable when present -> load in place.
  const internalDir = await internalModelsDir();
  const internalPath = internalDir !== null ? `${internalDir}/${filename}` : null;
  if (internalPath !== null && (await isUsableModel(internalPath, shaEnvKey))) {
    log(`using internal model: ${internalPath}`);
    return internalPath;
  }

  // 3. External staging (adb push lands here). Copy into internal, then load it.
  const externalDir = await externalModelsDir();
  const externalPath = externalDir !== null ? `${externalDir}/${filename}` : null;
  if (externalPath !== null) {
    const stat = await statPath(externalPath);
    if (stat.exists && stat.canRead && sizeOk(stat) && (await checksumOk(externalPath, shaEnvKey))) {
      if (internalPath !== null) {
        const staged = await copyIntoInternal(externalPath, internalPath, stat.size, shaEnvKey);
        if (staged !== null) {
          return staged;
        }
      }
      // Copy unavailable/failed, but the app uid can read the external file --
      // initLlama loads it directly (it doesn't consult expo's gate).
      log(`loading external model in place (copy unavailable): ${externalPath}`);
      return externalPath;
    }
  }

  return null;
}

// ---------------------------------------------------------------------------
// Diagnostics + public API (signatures unchanged for registerNativeLlama.ts)
// ---------------------------------------------------------------------------

/**
 * Whether a usable GGUF exists at `rawPath` (authoritative under the app uid).
 * Retained for callers/tools; the resolvers use the richer isUsableModel path.
 */
export async function modelFileExists(rawPath: string): Promise<boolean> {
  const stat = await statPath(rawPath);
  return stat.exists && stat.canRead && sizeOk(stat);
}

/** Best-effort Tier-1 candidate paths for logging (sync; the async resolver is authoritative). */
export function tier1CandidatePaths(): string[] {
  const out: string[] = [];
  const env = envPath("EXPO_PUBLIC_TRUSTTRACE_TIER1_GGUF");
  if (env !== null) {
    out.push(env);
  }
  const internal = expoInternalFilesDir();
  if (internal !== null) {
    out.push(`${internal}/models/${TIER1_FILENAME}`);
  }
  out.push(`${EXTERNAL_FILES_DIR_FALLBACK}/models/${TIER1_FILENAME}`);
  return out;
}

/**
 * One-shot diagnostic dump using the AUTHORITATIVE native layer: for each tier,
 * logs the resolved internal/external dirs and a real app-uid stat of each
 * candidate. Call this when resolution comes back empty so `adb logcat` shows
 * exactly what the app's OWN process can see -- not expo's gated view.
 */
export async function diagnoseModelProvisioning(): Promise<void> {
  const usingNative = modelFs() !== null;
  log(`file layer: ${usingNative ? "native TrustTraceModelFs (app-uid, authoritative)" : "expo-file-system fallback (read-gated)"}`);
  const internalDir = await internalModelsDir();
  const externalDir = await externalModelsDir();
  log("internal models dir =", internalDir);
  log("external models dir  =", externalDir);

  const tiers: Array<[string, string]> = [
    [TIER1_FILENAME, "Tier-1"],
    [TIER2_FILENAME, "Tier-2"],
  ];
  for (const [filename, label] of tiers) {
    for (const dir of [internalDir, externalDir]) {
      if (dir === null) {
        continue;
      }
      const p = `${dir}/${filename}`;
      const s = await statPath(p);
      log(
        `  ${label} candidate ${p} -> exists=${s.exists} canRead=${s.canRead} ` +
          `size=${s.size}${s.exists && !sizeOk(s) ? " (BELOW SIZE FLOOR)" : ""}`,
      );
    }
  }
  if (!usingNative) {
    log(
      "NOTE: native module not linked in this build -- external-dir reads go through " +
        "expo's gate and may false-negative. Rebuild with the TrustTraceModelFs module.",
    );
  }
}

/** First usable Tier-1 GGUF path (provisioned into internal when needed), or null. */
export async function resolveExistingTier1ModelPath(): Promise<string | null> {
  return resolveModel(
    "EXPO_PUBLIC_TRUSTTRACE_TIER1_GGUF",
    "EXPO_PUBLIC_TRUSTTRACE_TIER1_SHA256",
    TIER1_FILENAME,
  );
}

/** First usable Tier-2 GGUF path (escalation path only), or null. */
export async function resolveExistingTier2ModelPath(): Promise<string | null> {
  return resolveModel(
    "EXPO_PUBLIC_TRUSTTRACE_TIER2_GGUF",
    "EXPO_PUBLIC_TRUSTTRACE_TIER2_SHA256",
    TIER2_FILENAME,
  );
}
