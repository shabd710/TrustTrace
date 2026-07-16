/**
 * Startup hook that lights up the native Llama on-device scorer when this
 * build actually linked it.
 *
 * Spec ref: PDF Section 5 / 3.1-3.2. The pure-TS Tier-0 scorer
 * (defaultScorer.ts) is registered synchronously at startup so the app is
 * useful from first render. Loading multi-GB GGUF weights is slow and
 * hardware-dependent, so the native Tier-1 model is brought up ASYNCHRONOUSLY
 * and only SUPERSEDES the default scorer once its weights are resident and it
 * can actually run (registerEdgeRuntime is last-writer-wins, and
 * isEdgeRuntimeAvailable() gates on isReady()).
 *
 * Design guarantees:
 *   - A build WITHOUT the native module (this sandbox, Expo Go, any JS-only
 *     build) bundles and runs unchanged: the require() is guarded, so its
 *     absence is a no-op and the default TS scorer stays.
 *   - The native bootstrap module (src/native-modules/registerNativeLlama.ts)
 *     imports the real llama.rn package and therefore lives OUTSIDE the
 *     sandbox typecheck (tsconfig excludes src/native-modules). This file
 *     only touches it through the narrow, side-effecting entry point below.
 */

// The build-only native bootstrap contract. Kept here (typechecked) so this
// file stays strict; the implementation is in src/native-modules/.
import { debugWarn } from "../utils/logger";

interface NativeLlamaBootstrapModule {
  registerNativeLlamaScorerIfAvailable?: () => void | Promise<void>;
}

/**
 * Attempt to register the native Llama scorer. Safe to call once at startup.
 * Never throws: a missing native module, or any bootstrap error, leaves the
 * already-registered default TS scorer in place (backend fallback still
 * applies only if that scorer itself throws).
 */
export function kickoffNativeLlama(): void {
  try {
    // Literal require (not a static import) so Metro bundles the module when
    // it exists and this file still compiles/bundles when it does not.
    const mod = require("../native-modules/registerNativeLlama") as NativeLlamaBootstrapModule;
    const start = mod?.registerNativeLlamaScorerIfAvailable;
    if (typeof start === "function") {
      // Fire-and-forget: model load is async and must not block first render.
      void Promise.resolve(start()).catch((err) => {
        // native model failed to initialise -- default TS scorer stays.
        // Surfaced in dev, not silently swallowed.
        debugWarn("[TrustTrace] native Llama init rejected:", err);
      });
    }
  } catch {
    /* native module not linked in this build -- expected on JS-only builds */
  }
}
