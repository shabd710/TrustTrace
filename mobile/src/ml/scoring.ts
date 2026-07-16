/**
 * Transcript scoring bridge -- on-device first, backend fallback.
 *
 * Spec ref: PDF Section 5 (on-device-first by default for every detection
 * module; any cloud/server call is the exception, not the rule) and
 * Section 3.1-3.2 (the Tier 0/1/2 cascade is the primary path). This is
 * the seam that App.tsx / PasteCheckScreen call through.
 *
 * Resolution order, per the chosen architecture ("on-device with backend
 * fallback"):
 *   1. On-device cascade via the native EdgeRuntimeBinding
 *      (mobile/src/ml/modelLoader.ts). This is the DEFAULT and keeps the
 *      transcript on the phone -- nothing leaves the device.
 *   2. If (and only if) the native runtime is unavailable on this build/
 *      device -- e.g. Expo Go with no linked llama.cpp binding, or a
 *      device where model load failed -- fall back to the backend
 *      /v1/analyze-transcript endpoint, which runs the exact same
 *      cascade -> NLI gate -> confidence gate pipeline server-side.
 *
 * HONEST BOUNDARY: the fallback sends the transcript text to the backend.
 * That is a privacy tradeoff the on-device path specifically avoids, so it
 * is (a) only used when on-device genuinely can't run, and (b) reported to
 * the caller via `usedFallback` so the UI can disclose it if it chooses.
 * The default on-device path never sets that flag.
 */
import { PasteCheckResult } from "../screens/PasteCheckScreen";
import { getEdgeRuntime, isEdgeRuntimeAvailable } from "./modelLoader";
import { api as defaultApi, TrustTraceApi } from "../api/client";
import { debugWarn } from "../utils/logger";

export interface ScoreOutcome {
  result: PasteCheckResult;
  /** true iff scoring fell back to the backend (transcript left device). */
  usedFallback: boolean;
}

export interface ScoreDeps {
  api?: TrustTraceApi;
  sessionId: string;
  sender?: string;
}

/**
 * Score a pasted transcript. Tries on-device first; falls back to backend.
 * Throws only if BOTH paths fail -- the screen already handles a thrown
 * error by clearing its busy state.
 */
export async function scoreTranscript(
  text: string,
  deps: ScoreDeps,
): Promise<ScoreOutcome> {
  // --- Path 1: on-device cascade (default, private) ---
  if (isEdgeRuntimeAvailable()) {
    try {
      const runtime = getEdgeRuntime();
      const result = await runtime.scoreTranscriptOnDevice(text);
      return { result, usedFallback: false };
    } catch (err) {
      // On-device attempted but errored -- fall through to backend rather than
      // failing the user's check outright. Surfaced (dev only), not silently
      // swallowed. In practice the on-device scorer never throws, so this
      // branch is a defensive backstop, not the normal path.
      debugWarn("edge runtime error, falling back to backend:", err);
    }
  }

  // --- Path 2: backend fallback (transcript leaves device) ---
  const api = deps.api ?? defaultApi;
  const result = await api.analyzeTranscript({
    sessionId: deps.sessionId,
    sender: deps.sender ?? "pasted",
    text,
  });
  return { result, usedFallback: true };
}
