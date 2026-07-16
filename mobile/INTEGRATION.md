# TrustTrace mobile — frontend ↔ backend integration

This wires the mobile app to the detection stack. It replaces the former
`App.tsx` bridge stub and no-op explain-more with real paths, and adds the
API client and navigation that were previously absent.

## What was added / changed

| File | Status | Purpose |
|---|---|---|
| `src/config/env.ts` | **new** | Resolves the backend base URL (env → `app.json` extra → platform localhost default). Handles the Android-emulator `10.0.2.2` case. |
| `src/api/client.ts` | **new** | Typed client for `/v1/analyze-transcript`, `/v1/explain-more`, `/health`. Owns the shape adaptation between the backend's `AnalyzeTranscriptResponse` and the UI's `PasteCheckResult`. |
| `src/ml/scoring.ts` | **new** | The scoring bridge: **on-device first, backend fallback**. Reports `usedFallback` so the UI can disclose when a transcript left the device. |
| `src/ml/modelLoader.ts` | **extended** | Adds the on-device scoring seam (`registerEdgeRuntime` / `isEdgeRuntimeAvailable` / `getEdgeRuntime`). Returns *unavailable* until a native runtime registers — which routes scoring to the working backend fallback. |
| `src/navigation/RootNavigator.tsx` | **new** | React Navigation native-stack over all four screens. |
| `App.tsx` | **rewritten** | Real integration: on-device+fallback scoring, opt-in cloud explain-more, device-scan seam, navigator. |
| `src/types/external-modules.d.ts` | **new** | Strict-check shims for `expo-constants` + `@react-navigation/*` + `process.env`. Delete in a real project once the packages are installed. |
| `src/types/react-native.d.ts` | **extended** | Added `Alert` to the verification shim. |
| `app.json` | **extended** | `extra.trusttraceApiUrl` config field. |
| `package.json` | **extended** | Navigation + `expo-constants` deps. |

## Architecture (as chosen)

```
PasteCheckScreen.scoreTranscript(text)
        │
        ▼
  scoring.ts ──1──► on-device cascade (modelLoader → native llama.cpp/MLC/MLX)   [private, default]
        │
        └──2──► POST /v1/analyze-transcript (FastAPI)   [fallback; transcript leaves device]

PasteCheckScreen "Explain more" tap
        │
        ▼
  App.onExplainMoreRequested ──► POST /v1/explain-more   [opt-in, per-use, never automatic]
```

## Verification performed

- **`tsc --strict`**: all 17 TS/TSX files pass (0 errors), including every new file.
- **Python suite**: 78/78 still pass — nothing on the detection side was touched.

## The one honest remaining gap

The **real on-device cascade** needs a native LLM binding
(llama.cpp / MLC-LLM / MLX / MediaPipe) linked into a bare-workflow build,
plus quantized Tier 0/1/2 weights. That native module isn't in this repo
(it needs a device toolchain this environment doesn't have). Until it calls
`registerEdgeRuntime(...)` at startup, `isEdgeRuntimeAvailable()` returns
false **by design**, so scoring uses the backend fallback — a real, working
path — rather than pretending to score locally.

When you link the native runtime, implement `OnDeviceScorer` (from
`modelLoader.ts`) and call `registerEdgeRuntime(yourRuntime)` in the native
bootstrap. Nothing in `scoring.ts`, `App.tsx`, or the screens changes.

## Running it

```bash
# 1. Backend
uvicorn backend.main:app --port 8000

# 2. Point the app at the backend (physical device needs your LAN IP):
export EXPO_PUBLIC_TRUSTTRACE_API_URL="http://192.168.x.x:8000"
#    (emulator/simulator can skip this — the platform default works)

# 3. Install the new deps and run
cd mobile
npm install
npx expo run:android   # or run:ios
```
