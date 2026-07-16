/**
 * Default on-device scorer registration -- REAL, always-available.
 *
 * Spec ref: PDF Section 5 (on-device-first for every detection module) and
 * 3.1-3.2 (Tier 0 runs on every message, no model, single-digit ms).
 *
 * This closes the gap where the on-device path only worked if a NATIVE
 * llama.cpp runtime was linked. The pure-TS Tier-0 cascade
 * (onDeviceCascade.ts) needs no native module and no network, so the
 * private on-device path is ALWAYS the default -- the backend is a true
 * fallback, used only if this scorer itself throws.
 *
 * When a native GGUF runtime IS linked, it registers a richer
 * OnDeviceScorer that blends Tier 1/2 model confidence; that registration
 * (via modelLoader.registerEdgeRuntime) takes precedence over this default.
 * Both satisfy the same OnDeviceScorer contract, so scoring.ts is unchanged.
 */
import { PasteCheckResult } from "../screens/PasteCheckScreen";
import { CitedEvidence } from "../components/EvidenceCitation";
import {
  registerEdgeRuntime,
  isEdgeRuntimeAvailable,
  OnDeviceScorer,
} from "./modelLoader";
import { runOnDeviceCascade, OnDeviceScore } from "./onDeviceCascade";

/** Map the cascade's structured score into the UI result contract. */
export function toPasteCheckResult(score: OnDeviceScore): PasteCheckResult {
  if (!score.anySurfaced || score.flags.length === 0) {
    return { kind: "no_strong_pattern" };
  }
  const evidence = score.flags.map<CitedEvidence>((f) => ({
    kind: "transcript_span",
    quotedText: f.matchedSpans.join(", "),
    sourceLabel: `on-device Tier ${score.tierReached} \u00b7 ${f.label} (confidence ${f.confidence.toFixed(2)})`,
    tacticId: f.tacticId,
    // Carry the model's grounded reasoning through to the UI when present,
    // instead of discarding it. Undefined on the pure-heuristic path.
    ...(f.rationale !== undefined ? { modelRationale: f.rationale } : {}),
  }));
  const [first, ...rest] = evidence;
  return {
    kind: "flag",
    findingLabel: score.flags[0].label,
    evidence: [first, ...rest],
  };
}

/**
 * The always-available on-device scorer. Runs the real TS Tier-0 cascade.
 * If a native runtime later registers with model confidences, this is
 * superseded -- but until then, this is a genuine on-device detection path,
 * not a stub.
 */
const defaultScorer: OnDeviceScorer = {
  isReady: () => true,
  async scoreTranscriptOnDevice(text: string): Promise<PasteCheckResult> {
    const score = runOnDeviceCascade(text);
    return toPasteCheckResult(score);
  },
};

/**
 * Install the default on-device scorer if nothing richer has registered.
 * Call once at app startup (App.tsx does this). Idempotent-safe: if a
 * native runtime already registered, this does not overwrite it.
 */
export function ensureOnDeviceScorer(): void {
  if (!isEdgeRuntimeAvailable()) {
    registerEdgeRuntime(defaultScorer);
  }
}
