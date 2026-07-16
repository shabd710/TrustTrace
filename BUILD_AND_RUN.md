# TrustTrace — Build, Run & Real-Model Guide

This is the final integration state: real detection (on-device primary +
backend fallback), real backend explain-more, full navigation, and a CI
that builds a real Android APK. It documents what was verified here and the
exact steps for the two things that require your hardware (device build +
multi-GB Llama weights).

---

## 1. What runs and is verified in this repo

| Layer | Command | Verified |
|---|---|---|
| Python detection + backend | `pytest tests/` | ✅ 78/78 |
| Optimization benchmarks | `python eval/benchmarks.py` | ✅ reproduces Section 11 numbers |
| Mobile TypeScript (strict) | `cd mobile && npm run typecheck` | ✅ 0 errors |
| On-device cascade parity | `cd mobile && npm test` | ✅ 12/12, matches Python cascade |
| Backend end-to-end (stdlib) | start server, curl endpoints | ✅ surfaces cited flags on real scams, silent on benign |

The on-device TypeScript cascade (`mobile/src/ml/onDeviceCascade.ts`) is a
faithful port of the Python cascade + grounding gate; the parity test proves
they agree output-for-output on a shared corpus. This is what makes
"on-device first, real detection" a verified property, not a claim.

---

## 2. Detection architecture (real, no stubs in the user flow)

```
PasteCheckScreen.scoreTranscript(text)
        │
        ▼
  scoring.ts ──1──► on-device cascade (onDeviceCascade.ts)   [DEFAULT, private, no network]
        │             └─ blends native Llama Tier 1/2 confidence when a
        │                GGUF runtime is registered (modelLoader seam)
        │
        └──2──► POST /v1/analyze-transcript (backend)   [FALLBACK only if on-device throws]
                     └─ same cascade + grounding gate, server-side

"Explain more" (opt-in, per-use, never automatic):
  App.onExplainMoreRequested ──► POST /v1/explain-more
        └─ backend llm_client: on-device Llama if weights present,
           else real Anthropic Messages API (needs ANTHROPIC_API_KEY),
           else explicit "unavailable" (never a fake answer)
```

The default on-device scorer is installed at startup via
`ensureOnDeviceScorer()` in `App.tsx`, so the private path is live from
first render. The backend is a true fallback.

---

## 3. Run the backend

```bash
pip install -r requirements.txt

# Full FastAPI service (needs network to pip install fastapi/uvicorn):
uvicorn backend.main:app --port 8000

# OR the zero-dependency stdlib dev server (works anywhere), port 8787:
python backend/dev_server_stdlib.py
```

Verify:
```bash
curl -X POST http://localhost:8000/v1/analyze-transcript \
  -H "Content-Type: application/json" \
  -d '{"session_id":"s1","sender":"pasted","text":"this is the irs pay immediately with gift card or face arrest"}'
# -> tier_reached + surfaced flags with cited evidence

curl -X POST http://localhost:8000/v1/explain-more \
  -H "Content-Type: application/json" \
  -d '{"session_id":"s1","transcript_excerpt":"wire money now, keep it secret"}'
# -> real explanation if a provider is configured, else explicit unavailable
```

To enable cloud explain-more, set:
```bash
export TRUSTTRACE_LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...        # your key
export TRUSTTRACE_ANTHROPIC_MODEL=claude-3-5-haiku-latest   # optional
```

---

## 4. Real on-device Llama models (Tier 1/2)

The heuristic cascade works with no weights. To add the real models the
spec names (Llama-3.2-1B Tier 1, Llama-3.2-3B Tier 2):

### Backend / server side (verifiable on a Linux+GPU box)
```bash
pip install llama-cpp-python           # compiles llama.cpp (needs a compiler + network)
mkdir -p ~/models
# Download GGUF weights (HuggingFace), e.g.:
#   Llama-3.2-1B-Instruct-Q4_K_M.gguf
#   Llama-3.2-3B-Instruct-Q4_K_M.gguf
export TRUSTTRACE_TIER1_GGUF=~/models/Llama-3.2-1B-Instruct-Q4_K_M.gguf
export TRUSTTRACE_TIER2_GGUF=~/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf
```
`detection/conversation/llm_runtime.py` auto-detects the weights and blends
a real forward pass into the cascade (0.5 heuristic + 0.5 model). When
absent, it returns `None` and the tested heuristic path runs — the cascade
never breaks.

### On-device (native mobile) — IMPLEMENTED
The mobile on-device cascade runs the TS Tier 0 by default, and the native
Llama Tier-1 blend is now implemented against llama.cpp via `llama.rn`:
`mobile/src/native-modules/registerNativeLlama.ts` loads the GGUF weights,
implements the `OnDeviceScorer` interface (`mobile/src/ml/modelLoader.ts`),
and calls `registerEdgeRuntime()` at startup — superseding the default scorer
automatically once weights are resident. `scoring.ts`, `App.tsx`, and the
screens are unchanged. Provision the weights and do a device build per
**`mobile/NATIVE_LLM_SETUP.md`**.

---

## 5. Android build

> A Linux CI sandbox without the Android SDK cannot run `gradlew`. Two real
> ways to get a working APK:

### A. CI (recommended — this is where "Android build succeeds" is proven)
`.github/workflows/ci.yml` runs on every push:
1. Python 78-test suite + benchmarks
2. Mobile `tsc --strict` + on-device parity tests
3. **Android APK build**: `expo prebuild` → `gradlew assembleDebug` on a
   runner with JDK 17 + Android SDK, then uploads the APK as an artifact.

Push the repo to GitHub and the APK appears under the workflow run's
Artifacts as `trusttrace-debug-apk`.

### B. Local build (on your machine with Android Studio)
```bash
cd mobile
npm install --legacy-peer-deps       # peer-deps flag: see note below
npm run typecheck                    # tsc --strict, must be clean
npm test                             # on-device parity tests

# Generate the native android/ project and build:
npx expo prebuild --platform android --clean
cd android && ./gradlew assembleDebug
# APK -> mobile/android/app/build/outputs/apk/debug/app-debug.apk

# Or run on a connected device/emulator:
cd .. && npx expo run:android
```

Point the app at your backend (physical device needs your LAN IP):
```bash
export EXPO_PUBLIC_TRUSTTRACE_API_URL="http://192.168.x.x:8000"
# emulator/simulator can skip this; the platform default (10.0.2.2 on
# Android emulator) is used automatically.
```

**Peer-deps note:** `@testing-library/react-native` currently resolves a
newer `react-test-renderer` than React 18.2; `--legacy-peer-deps` (and the
pinned `react-test-renderer@18.2.0` in package.json) resolves it. The CI
uses the same flag.

---

## 6. What is verified here vs. what needs your hardware

| Requirement | Here | Your machine / CI |
|---|---|---|
| Real detection (not placeholder) | ✅ built + parity-tested | — |
| On-device primary, backend fallback | ✅ built + tested | — |
| Backend running, mobile↔backend contract | ✅ verified via curl + typed client | — |
| Explain-more real (Anthropic HTTP + local Llama) | ✅ code + safe-path tested | needs API key or weights to call live |
| No stubs/TODOs in user flow | ✅ audited | — |
| **Android APK build succeeds** | ❌ no SDK in sandbox | ✅ CI builds it / local gradlew |
| **Native on-device Llama on phone** | ✅ binding implemented (`llama.rn`) + glue logic tested | provision GGUF weights + device build |

The remaining ❌ (APK build) is a physical-environment ceiling, not missing
code. The native on-device Llama layer is now **implemented**, not just an
interface: `src/native-modules/registerNativeLlama.ts` brings up llama.cpp via
`llama.rn`, and the engine-agnostic scoring/blending glue
(`src/ml/nativeLlamaScorer.ts`) is unit-tested with a fake engine
(`nativeLlamaScorer.test.ts`). It registers itself over the existing
`registerEdgeRuntime()` seam and supersedes the default TS scorer once the
weights load. Running it needs only a device build + the GGUF weights —
see **`mobile/NATIVE_LLM_SETUP.md`** for the exact steps.
