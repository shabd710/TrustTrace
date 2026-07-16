/**
 * JS bridge to the `TrustTraceModelFs` native module (device-build only --
 * excluded from the sandbox typecheck).
 *
 * This is the authoritative file layer for GGUF provisioning: it reaches
 * java.io.File directly under the app uid, the SAME access path llama.rn's
 * native initLlama uses. It exists specifically to bypass expo-file-system's
 * Android read gate, which throws "isn't readable" for the app's OWN external
 * files dir and produced the false-negative that kept the model from loading.
 *
 * Everything degrades gracefully: on any build where the native module is not
 * linked (Expo Go, the JS-only sandbox), `modelFs()` returns null and the
 * provisioning layer falls back to its expo-file-system path.
 */
// eslint-disable-next-line @typescript-eslint/no-var-requires
import { NativeModules } from "react-native";

export type ModelStat = {
  exists: boolean;
  isFile: boolean;
  canRead: boolean;
  /** Bytes. Double on the bridge (GGUF weights routinely exceed 2 GB). */
  size: number;
};

export interface ModelFsNative {
  /** …/Android/data/<pkg>/files, resolved from the OS. null if unavailable. */
  externalFilesDir(): Promise<string | null>;
  /** /data/user/0/<pkg>/files -- always readable by the app. */
  internalFilesDir(): Promise<string | null>;
  /** mkdir -p; resolves true if the path is a directory afterwards. */
  ensureDir(path: string): Promise<boolean>;
  /** Authoritative stat under the app uid. */
  stat(path: string): Promise<ModelStat>;
  /** Atomic stream copy under the app uid; resolves bytes written. */
  copyFile(src: string, dst: string): Promise<number>;
  /** SHA-256 lowercase hex, for optional integrity pinning. */
  sha256(path: string): Promise<string>;
  /** Usable free bytes on the filesystem backing `path` (for the parent dir
   *  when the file doesn't exist yet). Used to pre-check a large model copy. */
  usableSpace(path: string): Promise<number>;
  /** Delete a file if present; resolves true if it no longer exists. */
  deleteFile(path: string): Promise<boolean>;
}

const native =
  (NativeModules as { TrustTraceModelFs?: ModelFsNative }).TrustTraceModelFs ?? null;

/** The native file layer, or null if this build didn't link it. */
export function modelFs(): ModelFsNative | null {
  return native;
}
