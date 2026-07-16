# Changelog

All notable changes to TrustTrace are documented here. Versioning follows [SemVer](https://semver.org/).

## [1.0.0] — 2026-07-16

First production release. **Android-only** — see "Platform status" in the README; iOS bring-up (Xcode project generation, device validation) is the 1.1 track.

### Added
- On-device detection pipeline: Tier-0 TS cascade + optional Tier-1 Llama-3.2-1B (GGUF via llama.rn) confidence blend, with grounded per-tactic model rationale surfaced in the UI.
- Expanded scam-family taxonomy (both TS and Python pipelines, kept in parity): UPI/QR payment scams, fake-police / digital-arrest, sextortion & coercion threats (`coercion_threat` tactic), bank-KYC, delivery/customs, job/investment bait — layered on the existing urgency / isolation / authority / remote-access / payment-funneling / too-good-to-be-true tactics.
- Explicit failure state on PasteCheck ("couldn't finish the check" — never mistakable for a clean result).
- UI component test suite (EvidenceCitation, PasteCheckScreen) alongside the cascade parity, scorer, explainer, and detection-family suites (69 Jest tests; 94 pytest tests).
- Release machinery: env-driven upload-keystore signing, tag-triggered signed-AAB CI job, Proguard keep rules for llama.rn/Expo/model-fs (pre-staged for minification).
- Root README, this changelog.

### Fixed
- Removed a production `console.log` that wrote transcript-derived matched spans to logcat.
- Tier provenance labels are honest: heuristic-only results report Tier 0, model-blended results Tier 1.
- Grounding prompt hardened for structured-output reliability on the 1B model (exactly one JSON object per requested tactic, array-only, temperature 0).
- "Explain more" degrades gracefully to an on-device explanation when the cloud is unreachable.
- CI builds the committed `android/` project (previously `expo prebuild --clean` regenerated it, silently dropping the native model-fs module from the CI artifact).
- Backend explain-more errors return a generic detail and log the underlying cause server-side.

### Release checklist (remaining, user-side)
- [ ] Generate the upload keystore and set the four `UPLOAD_*` repository secrets (see README → Release).
- [ ] Choose and add a `LICENSE` file.
- [ ] Store listing assets: screenshots, feature graphic, privacy-policy URL.

### iOS track (1.1)
- [ ] On a Mac: `npm run prebuild:ios`, build in Xcode, validate llama.rn Metal init on a device.
- [ ] Validate GGUF drop-in via Finder → Documents/models (file sharing enabled in Info.plist as of 1.0.0).
- [ ] Wire the Swift extension sources (Share/MessageFilter/CallDirectory/ReplayKit) into Xcode extension targets.
- [ ] Apple Developer account, signing certs, TestFlight distribution.
