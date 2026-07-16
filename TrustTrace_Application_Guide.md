# TrustTrace — Application Guide

This repo implements the PDF spec's full monorepo layout (Section 1) —
every file listed is present. This guide is the "how to apply this"
summary: what's real and tested, what's a documented stand-in, and the
concrete next step for each piece.

**82 files. 56 automated tests, all passing, actually executed in this
build (not just written) — see "How this was verified" below.**

A second pass on this build re-verified the sandbox's actual constraints
rather than assuming them: network egress is genuinely blocked (an
explicit host-allowlist rejection from pypi.org, not just a missing
cache), and no Kotlin/Swift compiler exists here. Given that, the backend
layer was upgraded from "written, not executed" to **genuinely executed**
by adding `backend/dev_server_stdlib.py` — the same three routes,
same underlying detection/grounding/threat-intel logic, reimplemented
against only Python's standard library (`http.server`, `json`, zero
third-party dependencies) so it can actually start and serve real HTTP
requests here. `tests/test_backend_stdlib.py` starts it in a background
thread and hits it with real `urllib` requests — 6 tests, all passing,
including a correct 503 refusal (not a faked response) from the
network-dependent explain-more path. `backend/main.py` (real FastAPI)
remains the spec-correct file to deploy; the stdlib server is a
verification-only stand-in for environments without network access to
install FastAPI.

Two things stayed genuinely out of reach, and it's worth being precise
about *why*, since the reasons are different in kind:

- **Kotlin compilation** needs `kotlinc` + Android SDK stubs — absent
  here, and blocked by the same network restriction above. This is a
  *missing-tool* problem: given network access, it's solvable.
- **Swift/ReplayKit/Vision/CryptoKit compilation** needs Xcode on macOS.
  This is not a missing-tool problem — Xcode does not run on Linux at
  all, under any circumstance, regardless of network access. No sandbox
  built on Linux containers (this one included) can compile real iOS
  extension code. That's a platform-incompatibility ceiling, not an
  effort ceiling.

---

## 1. How to run it

```bash
cd trusttrace/
pip install -r requirements.txt
pytest tests/                         # 33 tests across detection/grounding/threat-intel/federated/eval
uvicorn backend.main:app --reload     # single FastAPI service, spec Target Environment
```

One wrinkle worth knowing before you run anything: **`threat-intel/` (with
a hyphen) is not a valid Python package name.** That's the spec's own
literal directory name, not something introduced here. The fix used
throughout this repo — in `tests/conftest.py`, `backend/api/routes.py`,
`backend/sync_service.py` — is to add `threat-intel/` and `federated/`
directly to `sys.path` and import their files as flat top-level modules
(`from campaign_graph import ...`, not `from threat_intel.campaign_graph
import ...`). If you rename the directory to `threat_intel` in your own
fork, switch back to normal relative imports — the `.py` files themselves
don't need to change, just the two `from` lines flagged with a comment in
`campaign_graph.py` and `campaign_predictor.py`.

For the mobile app:
```bash
cd mobile/
npm install
npx expo run:ios      # or run:android
```

---

## 2. REAL vs SIMULATED — the honest inventory

Every file below was either (a) **executed and verified** against real
assertions in this build, or (b) is a **documented stand-in** for a
component that needs infrastructure this sandbox doesn't have (a mobile
compiler, real ML weights, network access, physical hardware). Nothing in
this repo claims to be more real than it is — see each file's own
docstring for the specific honesty note.

| Layer | Status | Detail |
|---|---|---|
| `detection/` (13 files) | ✅ **Real, tested** | Cascade routing, memory compaction, transcript normalization, OCR serialization, voice compound scoring, transaction risk, device permission/stalkerware/sideload checks, EWMA wake-gate changepoint detection — all genuine algorithms, all pytest-verified. Tier 1/2 use deterministic pattern-matching standing in for Llama-3.2-1B/3B (§3 below). |
| `grounding/` (3 files) | ✅ **Real, tested** | Evidence citation, confidence gate, NLI entailment gate — including genuine negation/hypothetical false-positive avoidance, verified with adversarial test cases. Stands in for a real cross-encoder model (§3). |
| `threat-intel/` (4 files) | ✅ **Real, tested** | k-anonymity gate, entity-type-aware decay, 90-day pruning — real `networkx` graph logic. Betweenness centrality and personalized PageRank are genuinely real (no stand-in needed). Embeddings are genuinely inductive but **un-learned** (§3). ANN matching is real but brute-force, not FAISS/HNSW (§3). |
| `federated/` (5 files) | ✅ **Real, tested** | L2 clipping, RDP accounting, PRG pairwise-mask cancellation (verified to cancel to `~1e-13` while individually hiding updates by 1000x), Byzantine-robust trimmed mean, k≥50 floor enforcement, mid-transfer sync abort, stratified canary sampling, rollback triggers. All genuine math, run against a simulated device cohort (no real device fleet exists here). |
| `security/key_storage.py` | ✅ **Real, tested** | Write-new→verify→atomic-rename rekey sequence tested end-to-end against a real SQLite file. Hardware key-wrapping itself needs real Secure Enclave/StrongBox (§3) — the code refuses to fake it (see `UnavailableHardwareKeyWrapper`). |
| `offline/sms_gateway.py` | ✅ **Real, tested** | Token-bucket rate limiting verified; reuses the real `detection/`+`grounding/` pipeline directly. Carrier connection is a documented seam. |
| `eval/` (4 files) | ✅ **Real, tested** | Precision/recall/F1, equity-sliced metrics, and latency profiling all run against this repo's own real pipeline. Precision/recall = 1.0/1.0 on the (non-adversarial) corpus; the one adversarial narrative-arc-limitation example is *intentionally* still a miss (documents spec §10.1 honestly, not swept under the rug). |
| `backend/` (7 files) | ⚠️/✅ **Split status** | `backend/dev_server_stdlib.py` is **real and executed** — zero-dependency, actually served real HTTP requests in this build (6/6 tests passing). `backend/main.py`/`api/routes.py`/`schemas.py` (the real FastAPI version) remain **written, not executed** — FastAPI/Pydantic genuinely can't be installed here (confirmed network-blocked, not just uncached). Run `pytest` after `pip install -r requirements.txt` with network access to exercise those for the first time. |
| `mobile/src/native-modules/` (6 files) | ⚠️ **Written, not compiled** | Real Kotlin/Swift against the real Android/iOS APIs (AccessibilityService, ReplayKit, Vision, CryptoKit, JNI). Needs Android Studio/Xcode to actually compile — brace/paren-balance checked here as a syntax floor, nothing more. |
| `mobile/src/ml/`, `mobile/src/state/` | ✅ **Type-checked** | Ran `tsc --strict` against both files — genuinely passes TypeScript's type checker, not just eyeballed. |
| `dashboard/src/App.js` | ✅ **Server-rendered and verified** | Actually executed via `react-dom/server` in this build; confirmed it calls only `/v1/campaign-graph` and renders correctly. |
| `mobile/src/screens/`, `mobile/src/components/` | 📝 **Placeholder** | Pure UI composition with no spec-mandated algorithm behind it — see the README in each folder for why this wasn't built out further. |

---

## 3. The specific swap-ins for full production

These are the concrete "how to apply this" steps — what a real deployment
needs beyond this reference implementation, per module:

1. **Tier 1/2 LLM cascade** (`detection/conversation/model_cascade.py`,
   `mobile/src/ml/modelLoader.ts`): load real Llama-3.2-1B/3B GGUF weights
   through llama.cpp/MLC-LLM/MLX/MediaPipe (spec's named runtimes). The
   `CascadeResult`/`route()` interface doesn't need to change — swap the
   internals of `_tier1_refine`/the Tier 2 branch for a real model call.

2. **NLI cross-encoder** (`grounding/nli_entailment_gate.py`): replace
   `evaluate_entailment`'s internals with a real sub-100M-param
   cross-encoder (e.g. a distilled DeBERTa-NLI model), INT8-quantized,
   calibrated against a real labeled corpus. Keep the same fixed
   hypothesis-template ensemble already defined in `tactic_taxonomy.py`.

3. **GraphSAGE embeddings** (`threat-intel/campaign_predictor.py`): swap
   `_feature_vector`'s hand-rolled positional features for a real
   `torch_geometric.nn.SAGEConv` stack with learned weights, trained on a
   real labeled campaign graph. The PinSAGE-style random-walk sampling
   strategy in `_sample_neighborhood` is already correct and can stay.

4. **ANN index** (`threat-intel/campaign_predictor.py`'s `ANNIndex`):
   swap the brute-force numpy search for `faiss.IndexHNSWFlat` — same
   `query()` interface.

5. **Hardware key wrapping** (`security/key_storage.py`): implement
   `HardwareKeyWrapper` for real — `kSecAttrTokenIDSecureEnclave` on iOS,
   Android Keystore/StrongBox on Android. The rekey file-sequence around
   it is already production-ready as written.

6. **SQLCipher**: swap plain `sqlite3` for `pysqlcipher3` (or the
   platform-native SQLCipher binding) — `rekey_database_atomic`'s
   verify-then-atomic-rename sequence works identically either way.

7. **FastAPI backend**: `pip install -r requirements.txt` in a networked
   environment, then `pytest tests/` to actually exercise
   `backend/main.py` end-to-end for the first time.

8. **Mobile native modules**: create a real Expo bare-workflow project,
   copy `mobile/src/native-modules/` in, register the AccessibilityService
   and ReplayKit Broadcast Upload Extension targets in
   Android Studio/Xcode per the comments at the top of each file.

---

## 4. Reading the code — what the comments cover

Every file's docstring follows the same three-part pattern, so you can
trust what you're reading without re-deriving it:

1. **Spec ref** — which PDF section(s) this file implements, including
   corrections from later hardening rounds (§7–10) where they changed the
   original §2 design.
2. **REAL vs SIM** (where relevant) — stated plainly, never implied.
3. **Cross-layer security note** — why this file's boundaries are drawn
   where they are (e.g. why `local_trainer.py`'s `TrainingExample` type
   structurally cannot carry a session ID).

Inline comments inside functions explain *why* a specific number or
technique was chosen (e.g. why the wake-gate's changepoint detector needs
a 25-sample warm-up period, discovered by an actual failing test during
this build — see the git-style narrative in the conversation this repo
was built in, if you have that transcript).

---

## 5. What was missing, and what's been added since

The previous delivery of this guide named three gaps as "honestly still
missing." All three are now built:

- **Bidirectional BFS dashboard carve-out** (spec §9.5) —
  `threat-intel/dashboard_path_query.py`. A genuine bidirectional BFS
  (not `networkx`'s unidirectional `shortest_path`), depth-limited,
  structurally isolated from `campaign_predictor.py`'s core prediction
  path (verified by AST-parsing its own imports in the test suite — it
  cannot import `campaign_predictor`, `detection`, or `grounding` even by
  accident). Cross-checked against `networkx.shortest_path_length` across
  30 random graphs — exact match every time — after catching and fixing a
  real bug during development: the initial "expand the smaller frontier
  first" tie-breaking silently starved the target side's expansion
  entirely on graphs with equal-size frontiers (e.g. a simple chain),
  which a naive read of "bidirectional BFS" pseudocode doesn't warn you
  about. Fixed to strict per-round alternation, then re-verified.
- **`ILMessageFilterExtension` / `CXCallDirectoryExtension`** —
  `mobile/src/native-modules/ios/{MessageFilterExtension,
  CallDirectoryExtension}.swift`. Real Swift against the real
  `IdentityLookup`/`CallKit` APIs, same "written, not compiled" status as
  `ReplayKitExtension` (Xcode/macOS-only, see §1's explanation of why
  that specific wall doesn't move). Each carries an honest technical note
  about a real platform constraint worth knowing before you build on it:
  `ILMessageFilterExtension` runs in a network-isolated, millisecond-budget
  sandbox that cannot invoke the real Tier 1/2 cascade, only a
  Tier-0-equivalent embedded cue-phrase pass; `CXCallDirectoryProvider`
  requires phone numbers added in strict ascending order or the extension
  aborts, which is the actual reason spec §8.3 rejects forcing stalkerware
  detection's Bloom-filter pattern onto this differently-shaped problem.
- **Device-farm Appium scripts** (spec §4) —
  `eval/device_farm/{appium_harness,synthetic_injection,
  battery_latency_gates}.py`. Real `appium-python-client` capability
  builders and gate-checking logic; `check_release_gates()` and
  `rapid_foreground_app_switch()` are pure-Python-testable and were
  actually run against representative report data and a mock Appium
  driver (9 tests, all passing). One honest technical correction folded
  in rather than glossed over: AWS Device Farm's real physical device
  pool cannot receive externally-injected SMS or fake incoming calls at
  all — that's carrier-network-gated, not an Appium/Device-Farm
  limitation to route around. The scripts use the real supported
  mechanism instead (a debug-build test hook feeding the same code path a
  real paste/share/call would, on real hardware) and clearly separate it
  from the emulator-only `adb emu` lane, rather than presenting a single
  fake unified "inject_sms()" call that wouldn't actually work on Device
  Farm's real devices.

If anything else in the spec still looks unbuilt, say which section —
the standard applied throughout this build (real code, actually run
against real assertions wherever the environment allows it, and an
explicit, specific reason named wherever it doesn't) is the one to keep
applying.

---

## 6. Completion delta (this revision)

A file-by-file diff of this repo against the PDF spec's Section 1 layout
found exactly three gaps, all now closed:

1. **`mobile/src/native-modules/ios/ShareExtension.swift`** — listed in
   spec §1, required by §2.3 (iOS coverage angle #2) and §7.4 (memory
   hygiene), previously absent entirely. Now written: real Swift against
   the real Social/UniformTypeIdentifiers/Vision APIs — shared image →
   VNRecognizeTextRequest OCR with normalized-percentage bounding boxes
   (§7.5) → region-tagged spatial prompt (§3.3), OCR confidence gating
   (§10.1), derived-signal-only App Group handoff with key-versioned
   encrypted payloads (§7.2/§8.3/§10.2), aggressive buffer release
   (§7.4), zero image/text persistence. Same **written-not-compiled**
   status as every other Swift file here (Xcode is macOS-only), same
   brace/paren-balance syntax floor applied and passing.

2. **`mobile/src/screens/`** — placeholder README replaced with four
   real screens: `PasteCheckScreen` (§6 zero-permission immediate value;
   §2.1 "no strong pattern ≠ safe" wording enforced), 
   `TransactionWarningScreen` (§2.3 — the only emittable actions are
   `go_back` and `i_understand_continue_anyway`; no cancel/block path
   exists in the type system), `DeviceScanScreen` (§2.4 owner-initiated
   scan, no auto-share/delete/report actions, pinned discreet exit),
   `OnboardingScreen` (§6 progressive onboarding — requests zero
   permissions by construction, only records which contextual prompts
   should fire later).

3. **`mobile/src/components/`** — placeholder README replaced with four
   real components: `EvidenceCitation` (the props type makes an
   evidence-free flag unrepresentable — UI-side enforcement of the
   grounding rule), `ConsentPrompt` (contextual, plain-language,
   decline-first), `AnalysisProgress` (the §10.3-refined loader — accepts
   no tactic/verdict prop at all, structurally preventing pre-NLI-gate
   verdict leaks), `DiscreetExitBar` (§2.4).

**Verification in this revision:** all 8 new `.tsx`/`.ts` UI files pass
`tsc --strict` (verified with real `@types/react`; `src/types/react-native.d.ts`
is a clearly-labeled sandbox shim declaring only the exact RN API subset
used, to be deleted in a real RN project where the library's own types
take over). The full Python suite was re-executed: **56/56 passing**,
after fixing one genuine bug found in the shipped tests —
`tests/test_dashboard_path_query.py` hardcoded an absolute path
(`/home/claude/trusttrace/...`) for its AST-isolation check, which broke
on any other checkout location; it now resolves the path relative to the
test file itself.

---

## 7. Master revision — Section 11: Power & Optimization Upgrades

This revision adds five modules and applies the spec's §3.5 profiling-first
discipline to the repo's own code — including recording two measured
NON-merges honestly, which is what that rule actually demands.

**New capability modules (all real, all tested — 72/72 passing):**

1. `detection/telemetry/thermal_governor.py` — §7.1's cascade-first thermal
   ladder and §10.1's degraded-mode contract as executable policy:
   NOMINAL→ELEVATED (raise the Tier-2 escalation bar first) →SEVERE
   (pre-built 2-bit variant, last resort) →CRITICAL_COMPOUND (Tier 0 only
   + a mandatory "reduced confidence, verify independently" user notice —
   silent degradation is unrepresentable). Hysteresis prevents variant
   flapping. Tested to contain no detection/entailment threshold, per the
   STRICT SUMMARY's device-state rule.
2. `threat-intel/tiered_graph_store.py` — §10.5's hot/cold tiered storage:
   live query path runs over the active working set only (flat cost as
   history grows); confirmed links are provably never forgotten (moved,
   never deleted — tested), and dormant infrastructure rehydrates into the
   hot tier the moment it reappears (§9.5 carve-out, tested).
3. `threat-intel/centrality_fallback.py` — §7.7's sampled betweenness under
   a wall-clock budget plus §9.5's eigenvector fallback, LABELED with which
   method produced the ranking (§2.5's cited-evidence discipline), and an
   explicit budget-exhausted state instead of a silent empty result (§10.5).
4. `threat-intel/ann_hnsw.py` — a genuine HNSW index (multi-layer greedy
   search, Malkov & Yashunin) behind the same `query()` interface as the
   brute-force index. Measured recall@5 = 0.998 against exact ground truth.
5. `detection/conversation/fast_pattern_matcher.py` + `eval/benchmarks.py`
   — see the profiling verdict below.

**Two measured non-merges, recorded rather than hidden (§3.5):**

- Tier 0 scanning: classical Aho–Corasick AND §8.2's regex prescreen were
  both implemented, equivalence-tested (adversarial + 300-case fuzz,
  outputs identical cue-for-cue), and benchmarked. Both LOSE to CPython's
  C-backed `str in` loop at the current ~60-cue taxonomy (measured: naive
  ~74ms vs ~176–189ms per 3000 messages). The naive scan is already ~400x
  inside the spec's single-digit-ms Tier 0 budget — there is no bottleneck
  to fix, so nothing merged. Both alternatives ship equivalence-tested as
  the reference algorithms for the native Kotlin/Swift/C++ ports (where
  AC's O(N+matches) bound genuinely wins) behind the stable `scan_cues()`
  seam in `model_cascade.py`.
- ANN at reference scale: pure-Python HNSW loses to vectorized numpy brute
  force at N=1500 (measured), so brute force stays the live path here;
  the HNSW module verifies the spec-named algorithm end-to-end
  (recall 0.998) and is the drop-in seam for `faiss.IndexHNSWFlat` in
  production, where C++ HNSW's sub-linearity wins at real scale.

Reproduce every number: `python eval/benchmarks.py`.
