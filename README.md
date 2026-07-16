# TrustTrace

**Consent-first mobile scam, fraud & spyware defense — on-device first.**

TrustTrace detects manipulation tactics in conversations (romance scams, fake tech support, digital-arrest threats, UPI/QR payment scams, sextortion, and more) **entirely on the phone**. Reputation databases answer "is this file or link known-bad"; TrustTrace answers the question that actually loses people money: *is this conversation manipulating me?*

## Non-negotiables

- **Every flag cites its exact evidence** — a quoted transcript span, a permission name, a screen region. No unexplained risk scores.
- **Below-threshold means "not enough signal," never "this is safe."**
- **No autonomous action, ever** — TrustTrace never blocks, cancels, or reports anything on your behalf. Friction and explanation only.
- **On-device by default** — the transcript never leaves the phone on the default path. The only cloud calls are the opt-in per-tap "Explain more" and an explicit backend fallback, both disclosed.
- **False positives are a first-class failure mode**, tracked with the same rigor as missed scams.

## Architecture

```
PasteCheckScreen ──► scoreTranscript() ──► EdgeRuntime (modelLoader.ts)
                                              │
                             ┌────────────────┴───────────────┐
                             ▼                                ▼
                   NativeLlamaScorer                 defaultScorer (pure TS)
                   (llama.rn / llama.cpp,            Tier-0 cascade, always
                    Llama-3.2-1B GGUF, temp 0)       available, no native dep
                             │                                │
                             └────────► runOnDeviceCascade() ◄┘
                                        Tier-0 cues + grounding gate
                                        + 50/50 model-confidence blend
                                              │
                                              ▼
                                     EvidenceCitation (UI)
                              evidence · confidence · model rationale
```

- **Tier 0** (pure TS + Python parity): cue-phrase scan, compound boosting, negation/hypothetical grounding, information-weighted specificity. Single-digit ms, no model, no network.
- **Tier 1** (Llama-3.2-1B GGUF via [llama.rn](https://github.com/mybigday/llama.rn)): grounded, temperature-0 JSON re-scoring of **only** the tactics Tier 0 surfaced — the model can down-weight or confirm, never introduce a tactic. Any model failure degrades to the heuristic result.
- **Backend** (single FastAPI service): opt-in "Explain more", SMS-lite gateway, k-anonymized campaign graph. Never the default scoring path.
- **Dual-pipeline rule:** the TypeScript cascade (`mobile/src/ml/onDeviceCascade.ts`) and the Python reference (`detection/conversation/` + `grounding/`) implement the same detection and are kept in lock-step; change both or neither.

## Monorepo layout

| Path | What it is |
|---|---|
| `mobile/` | React Native (Expo bare) app; `src/ml/` is the on-device detection pipeline |
| `backend/` | Single FastAPI service (explain-more, SMS gateway, campaign graph API) |
| `detection/`, `grounding/` | Python reference detection: cascade, taxonomy, NLI gate, confidence gate |
| `threat-intel/` | k-anonymized campaign graph, GraphSAGE/HNSW correlation |
| `federated/` | DP-noised, Byzantine-robust federated learning stack |
| `eval/` | Evaluation harness, benchmarks, device-farm gates, equity slices |
| `tests/` | Python test suite (pytest) |
| `dashboard/` | Researcher dashboard (React) — k-anonymized aggregates only |
| `docs/` | Model provisioning: [REAL_MODELS_SETUP.md](docs/REAL_MODELS_SETUP.md) |

## Quick start

**Backend** (Python 3.11+):
```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload      # http://localhost:8000/health
```

**Mobile** (Node 20, Android SDK; see [BUILD_AND_RUN.md](BUILD_AND_RUN.md) and, on Windows, [README_WINDOWS.md](README_WINDOWS.md) — note the MAX_PATH constraint):
```bash
cd mobile
npm install --legacy-peer-deps
npm run android          # dev build on device/emulator
```

**On-device model**: the app runs fully without weights (pure-TS Tier-0 scorer). To enable the Tier-1 model blend, provision the Llama-3.2-1B GGUF per [docs/REAL_MODELS_SETUP.md](docs/REAL_MODELS_SETUP.md).

## Platform status

| Platform | Status |
|---|---|
| **Android** | Release-ready: committed `android/` project, native model-fs module, signed-AAB CI pipeline. |
| **iOS** | **Not brought up yet.** No `ios/` project has been generated (requires macOS + Xcode). The JS/TS layer is already iOS-aware — llama.rn supports iOS/Metal, the `memoryWarning` lifecycle is wired, and model provisioning falls back to `Documents/models/` (the Android read-gate bug does not exist on iOS; no native module is required). Bring-up on a Mac: `npm run prebuild:ios`, open `ios/TrustTrace.xcworkspace`, build; drop the GGUF into the app's Documents/models via Finder (file sharing is enabled in Info.plist). The `ios-build` CI job (macOS, simulator, no signing) verifies compilation on demand. The Swift extension sources in `src/native-modules/ios/` (Share/MessageFilter/CallDirectory/ReplayKit) are written but not yet wired to Xcode extension targets — post-bring-up work. |

## Testing

```bash
pytest tests/ -q                 # Python detection/backend suite
cd mobile && npm run typecheck   # tsc --strict
cd mobile && npm test            # Jest: cascade parity, scorer, explainer, UI
```

CI (`.github/workflows/ci.yml`) runs all three plus a real Android APK build of the **committed** `android/` project; tagged `v*` releases additionally build a signed AAB.

## Release

1. Generate an upload keystore once (never commit it):
   ```bash
   keytool -genkeypair -v -keystore trusttrace-upload.keystore \
     -alias trusttrace -keyalg RSA -keysize 2048 -validity 10000
   ```
2. Set repository secrets: `UPLOAD_KEYSTORE_B64` (base64 of the keystore), `UPLOAD_STORE_PASSWORD`, `UPLOAD_KEY_ALIAS`, `UPLOAD_KEY_PASSWORD`.
3. Tag `vX.Y.Z` — CI produces the signed AAB artifact. Locally, the same env vars (`TRUSTTRACE_UPLOAD_*`) drive `./gradlew bundleRelease`.

Without the keystore env, release builds fall back to debug signing for local smoke tests only — a debug-signed artifact is not Play-Store-uploadable by design.

## Privacy posture (summary)

Single `INTERNET` permission; `allowBackup=false`; cleartext allowed only in debug builds against loopback; production cloud URLs must be HTTPS or the app fails closed to on-device-only; no transcript content is ever logged; the researcher dashboard has no code path returning an individual report. Full detail: [TrustTrace_Application_Guide.md](TrustTrace_Application_Guide.md).

## License

No license has been chosen yet — see `CHANGELOG.md` release checklist. Until one is added, all rights reserved.
