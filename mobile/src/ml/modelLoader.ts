/**
 * On-device model loader: edge runtime bindings.
 *
 * Spec ref: PDF Target Environment ("a mature, already-optimized mobile
 * LLM runtime -- llama.cpp (Metal/Vulkan backend), MLC-LLM, Apple MLX, or
 * Google's AI Edge / MediaPipe LLM Inference API -- rather than
 * hand-rolled hardware orchestration"), Section 7.1 (zero-copy tokenizer
 * sharing depends on React Native's JSI/New Architecture, not the legacy
 * bridge; Tier 1 pre-warming gated through the wake-gate signal set only).
 *
 * NOT EXECUTABLE HERE -- needs a real React Native/Expo bare-workflow
 * project with a linked native llama.cpp/MLC-LLM/MLX/MediaPipe binding.
 * This file is the thin TS-side interface such a binding would implement;
 * the actual quantization/GQA/speculative-decoding work happens inside
 * the chosen mature runtime (spec 3.4's explicit preference), not here.
 */

export type CascadeTier = 0 | 1 | 2;

export interface ModelLoadResult {
  tier: CascadeTier;
  modelId: string;      // e.g. "llama-3.2-1b-q4", "llama-3.2-3b-q4"
  residentInMemory: boolean;
}

export interface EdgeRuntimeBinding {
  /** Loads (or confirms already-resident) weights for a tier. Tier 0
   * is always resident (spec: "scores every message in single-digit
   * milliseconds" -- must have zero cold-start). Tier 1/2 load lazily,
   * gated by the wake gate (see wakeGateBridge below), never eagerly. */
  loadTier(tier: CascadeTier): Promise<ModelLoadResult>;

  /** Cross-tier speculative decoding entry point (spec 3.4): Tier 1
   * serves as the resident draft model when Tier 2 is invoked. The
   * runtime itself owns acceptance sampling / abort-on-divergence
   * (>40% draft-token rejection over 4 consecutive turns falls back to
   * standard single-model Tier 2 decoding, per spec 10.1) -- this
   * binding only exposes the high-level call, not the decode loop
   * internals, consistent with spec 3.4's "handled by the chosen mobile
   * inference runtime rather than a bespoke pipeline."
   */
  runTier2WithSpeculativeDecoding(prompt: string): Promise<string>;
}

/**
 * Tier 1 pre-warming: gated STRICTLY through the same wake-gate signal
 * set the Python reference implementation's WakeGate class exposes
 * (detection/telemetry/wake_gate.py, already implemented + tested in
 * this repo) -- never a new independent trigger, per spec 7.1's explicit
 * warning that a broader trigger set "quietly defeats the 'heavy
 * pipelines stay dormant' rule."
 */
export function shouldPrewarmTier1(wakeReasons: string[]): boolean {
  const ALLOWED_PREWARM_REASONS = new Set(["payment_app_foreground", "flagged_incoming_call"]);
  return wakeReasons.some((r) => ALLOWED_PREWARM_REASONS.has(r));
}

/**
 * ---------------------------------------------------------------------
 * On-device scoring seam
 * ---------------------------------------------------------------------
 *
 * Spec ref: PDF Section 3.1-3.2 (Tier 0/1/2 cascade is the on-device
 * default path) and Section 5 (on-device-first: the transcript never
 * leaves the phone on this path). This is the concrete entry point the
 * scoring bridge (mobile/src/ml/scoring.ts) calls.
 *
 * REAL vs SIM -- stated plainly: activating the REAL on-device cascade
 * requires a native binding (llama.cpp / MLC-LLM / MLX / MediaPipe) linked
 * into a bare-workflow build, plus the quantized Tier 0/1/2 weights. That
 * native module is NOT present in this repo (it needs a device compiler
 * this build environment doesn't have -- the same ceiling documented for
 * the Kotlin/Swift modules). Therefore `isEdgeRuntimeAvailable()` returns
 * false here BY DESIGN, which makes scoring.ts route to the backend
 * fallback -- a real, working path -- instead of silently pretending to
 * score on-device. When the native module IS linked, it registers itself
 * via `registerEdgeRuntime()` at app startup and this seam lights up with
 * zero changes to scoring.ts, App.tsx, or the screens.
 */
import { PasteCheckResult } from "../screens/PasteCheckScreen";

/**
 * A transcript scorer that runs entirely on-device. This is the ONLY
 * capability scoring.ts requires -- deliberately decoupled from the native
 * EdgeRuntimeBinding so a pure-TS Tier-0 cascade (no native module, no
 * network) is a first-class on-device scorer, not a second-class stub.
 *
 * A native llama.cpp runtime may ALSO implement EdgeRuntimeBinding for
 * Tier 1/2 model management and register a richer scorer that blends model
 * confidence -- but a scorer is not REQUIRED to own native weights.
 */
export interface OnDeviceScorer {
  /** True when this scorer can score right now (Tier 0 is always ready). */
  isReady(): boolean;
  /**
   * Run the on-device cascade + grounding gate and return the UI result
   * contract directly. Returns the below-threshold "no_strong_pattern"
   * state when nothing survives the gates -- never a "safe" verdict
   * (spec 2.1).
   */
  scoreTranscriptOnDevice(text: string): Promise<PasteCheckResult>;
}

let _registeredRuntime: OnDeviceScorer | null = null;

/**
 * Register the active on-device scorer. Called at startup: defaultScorer.ts
 * installs the always-available pure-TS cascade; a native bootstrap may
 * instead install a Llama-backed scorer that supersedes it.
 */
export function registerEdgeRuntime(runtime: OnDeviceScorer): void {
  _registeredRuntime = runtime;
}

/** True iff an on-device scorer has registered AND is ready. */
export function isEdgeRuntimeAvailable(): boolean {
  return _registeredRuntime !== null && _registeredRuntime.isReady();
}

/**
 * Returns the registered scorer. Throws if none is available -- callers
 * must gate on isEdgeRuntimeAvailable() first (scoring.ts does), so this
 * throw only fires on a programming error, never on the normal path.
 */
export function getEdgeRuntime(): OnDeviceScorer {
  if (_registeredRuntime === null) {
    throw new Error(
      "No on-device scorer is registered. Call ensureOnDeviceScorer() at " +
        "startup, or gate on isEdgeRuntimeAvailable().",
    );
  }
  return _registeredRuntime;
}
