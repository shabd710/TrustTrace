# Native On-Device LLM (Tier 1/2) — Setup

This completes the final architectural milestone: **true offline, on-device
Llama inference** blended into the detection cascade. The heuristic Tier-0
cascade already runs with zero setup; this adds the real Llama-3.2 model pass
on top, entirely on the phone.

```
User → Paste Check → scoreTranscript()
     → Native OnDeviceScorer (createNativeLlamaScorer)
     → llama.rn / llama.cpp  → GGUF model inference (Llama-3.2-1B)
     → blend 50/50 with heuristic cascade (runOnDeviceCascade)
     → PasteCheckResult
Backend is used ONLY if the native runtime never initialises.
```

## What was added (and where)

| File | Typechecked/tested here | Role |
|---|---|---|
| `src/ml/nativeLlamaScorer.ts` | ✅ yes | Engine-agnostic glue: grounding prompt, JSON parsing, 50/50 blend, graceful degradation. Implements `OnDeviceScorer`. |
| `src/ml/nativeLlamaBootstrap.ts` | ✅ yes | `kickoffNativeLlama()` — guarded startup hook (no-op on JS-only builds). |
| `src/ml/onDeviceCascade.ts` | ✅ yes | New `tier0Candidates()` export — the pre-gate tactic set the model refines. |
| `src/native-modules/registerNativeLlama.ts` | ⛔ device-build only | Real `llama.rn` engine + `EdgeRuntimeBinding`; calls `registerEdgeRuntime()`. |
| `src/native-modules/modelProvisioning.ts` | ⛔ device-build only | Resolves + provisions GGUF paths (env → internal → copy from external). |
| `src/native-modules/modelFs.ts` | ⛔ device-build only | JS bridge to the `TrustTraceModelFs` native module (app-uid file access). |
| `android/.../modelfs/TrustTraceModelFsModule.kt` | ⛔ device-build only | Kotlin `java.io.File` layer under the app uid; bypasses expo's read gate. |

`src/native-modules/` is excluded from `tsconfig.json` because it imports the
real `llama.rn` native package, which only exists in a device build. Every
piece of *logic* lives in the typechecked, unit-tested `src/ml/` files
(`nativeLlamaScorer.test.ts`, 12 tests with a fake engine).

**Design invariants preserved (nothing was redesigned):**
- The heuristic cascade stays a **floor** — the model can only re-weight
  tactics Tier 0 already surfaced, never introduce a new one.
- **Tier 2 is never the default path**: benign messages (no Tier-0
  escalation) never wake the model.
- **Never throws mid-session**: any inference/parse error degrades to the
  pure heuristic result. Only a failure to *initialise* leaves the scorer
  unregistered, and then the default TS scorer (and, if it throws, the
  backend) still applies.

## 1. Install the runtime

```bash
cd mobile
npm install --legacy-peer-deps        # pulls llama.rn + expo-file-system (now in package.json)
```

`llama.rn` is the maintained React Native binding for llama.cpp (Vulkan on
Android, Metal on iOS). It autolinks — no manual `MainApplication.kt` edits —
because autolinking + the New Architecture are already enabled in this repo.

## 2. Provision the GGUF weights

Weights are multi-GB, so they are **not** bundled in the APK. The resolver
(`modelProvisioning.ts`) uses the first tier model it finds, in this order:

1. `EXPO_PUBLIC_TRUSTTRACE_TIER{1,2}_GGUF` — explicit absolute path (loaded in place).
2. **Internal storage** — `<filesDir>/models/<name>` (`/data/user/0/com.trusttrace.app/files/models`).
   Canonical, always readable, no permission gate. This is where the model
   ends up and loads from steady-state.
3. **App external files dir** (adb-push staging) — resolved from the OS via
   `getExternalFilesDir()`, i.e. `/storage/emulated/0/Android/data/com.trusttrace.app/files/models`.
   On first run the app **copies** the model from here into internal storage
   (2) and loads it from there. After that, every launch hits internal directly.

**Why the redesign:** the old code checked existence through
`expo-file-system`, whose Android layer runs a `canRead()` gate that only
whitelists Expo's own internal dirs. For the app's *own* external files dir it
throws `"… isn't readable."` — a **false negative**: `adb shell ls` shows the
file, but the resolver returned `null` and `initLlama()` never ran. The new
`TrustTraceModelFs` native module reads `java.io.File` directly under the app
uid (the same access path `initLlama` uses), so its answers are authoritative
and no path is hardcoded.

Recommended (dev): push into the external files dir — the app stages it inward.

```bash
adb shell mkdir -p /sdcard/Android/data/com.trusttrace.app/files/models
adb push Llama-3.2-1B-Instruct-f16.gguf /sdcard/Android/data/com.trusttrace.app/files/models/
# optional, for the Tier-2 escalation path:
adb push Llama-3.2-3B-Instruct-Q8_0.gguf /sdcard/Android/data/com.trusttrace.app/files/models/
```

> The app must have been launched at least once so its external dir exists.
> `adb push` **cannot** write internal app storage on a non-rooted device
> (permission denied) — that's why the external dir is the staging path.
>
> The one-time internal copy needs free space ≈ the model size (the external
> copy can be deleted afterward: `adb shell rm .../files/models/<name>`). To
> pin integrity, set `EXPO_PUBLIC_TRUSTTRACE_TIER{1,2}_SHA256` and the copy is
> verified before use.
>
> **Android 13/14:** if a freshly-pushed file still reads back as absent, do a
> full **cold restart** of the app process
> (`adb shell am force-stop com.trusttrace.app`, then relaunch) — a Metro `r`
> reload does NOT refresh the process's FUSE view of the external dir.
>
> **Alternative (skip external entirely):** push straight into internal on a
> debuggable build —
> `adb push <name> /data/local/tmp/ && adb shell run-as com.trusttrace.app cp /data/local/tmp/<name> files/models/`.

Default filenames (override via `EXPO_PUBLIC_TRUSTTRACE_TIER{1,2}_GGUF`):
`Llama-3.2-1B-Instruct-f16.gguf` (Tier 1) and `Llama-3.2-3B-Instruct-Q8_0.gguf`
(Tier 2). Grab the GGUFs from Hugging Face (e.g.
`bartowski/Llama-3.2-1B-Instruct-GGUF`).

After pushing, reload the app (press `r` in Metro). Watch the Metro log for:
```
[TrustTrace/native-llama] loading Tier-1 model: /storage/emulated/0/Android/data/com.trusttrace.app/files/models/Llama-3.2-1B-Instruct-f16.gguf
[TrustTrace/native-llama] READY -- native model-blended scorer registered (supersedes TS Tier 0).
```
If the model isn't found you'll instead see the candidate paths it checked,
followed by a `[TrustTrace/model-provisioning]` diagnostic dump that lists what
the app's own process can actually see in each candidate directory. If a
directory logs as `UNREADABLE by app process`, do the cold-restart above (or
`adb shell chmod 644 …/models/*.gguf`).

## 3. Build & run on a device

```bash
cd mobile
npm run typecheck                       # tsc --strict, must be clean
npm test                                # 39 tests incl. native-scorer logic
npx expo prebuild --platform android --clean
npx expo run:android                    # or: cd android && ./gradlew assembleDebug
```

On launch, `kickoffNativeLlama()` (in `App.tsx`) loads the 1B model
asynchronously; once its weights are resident it calls `registerEdgeRuntime()`
and **supersedes the default TS scorer**. Until then (and on any device
without weights) the app runs the tested heuristic cascade — it is never
broken, only enhanced.

### Verify it's actually using the model
Detection flags for a scam will read **“on-device Tier 2 · …”** (the blended
path) instead of “Tier 1”. Benign messages still won’t wake the model.

## 4. Gradle notes (only if the linker complains)

`llama.rn` ships prebuilt `.so`s per ABI. If a duplicate-`.so` packaging error
appears, add to `android/gradle.properties`:

```
android.packagingOptions.pickFirsts=**/libllama.so,**/libggml.so
```

Ensure `minSdkVersion >= 24` (llama.rn requirement) — set via
`expo-build-properties` in `app.json` if needed.

## iOS
The same JS path works; `llama.rn` uses Metal. `npx pod-install` after
`npm install`, then `npx expo run:ios`. Weights go in the app’s Documents dir
or an absolute path via the same env vars.
