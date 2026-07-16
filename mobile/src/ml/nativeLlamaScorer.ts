/**
 * Native-Llama on-device scorer -- the REAL Tier-1 model-blended path.
 *
 * Spec ref: PDF Target Environment (Tier 1 = Llama-3.2-1B quantized, run
 * through a mature mobile runtime -- llama.cpp/MLC/MediaPipe), Section 3.1-3.2
 * (the on-device cascade is the default path; Tier 2 is never the default),
 * and Section 5 (on-device-first: the transcript never leaves the phone).
 *
 * This module is the ENGINE-AGNOSTIC glue that turns a loaded on-device LLM
 * into an `OnDeviceScorer`. It deliberately depends only on a tiny
 * `LlamaEngine` interface, NOT on any specific native package, so:
 *   - all the real logic (prompt construction, JSON grounding, confidence
 *     blending, graceful degradation) is unit-tested here with a fake engine,
 *     and
 *   - the actual llama.cpp binding (llama.rn) lives in the build-only
 *     `src/native-modules/` folder that implements this interface.
 *
 * How it blends (identical contract to the Python reference,
 * detection/conversation/llm_runtime.py):
 *   1. Run the tested TS Tier-0 cascade to get the candidate tactics. If none
 *      escalate, this is the benign majority -- return the heuristic result
 *      WITHOUT waking the model (battery + latency; Tier 2 is not default).
 *   2. Ask the model, grounded and at temperature 0, to score ONLY those
 *      already-surfaced tactics against the quoted text. It can down-weight a
 *      weak match or confirm a strong one, but it can never introduce a
 *      tactic Tier 0 didn't surface -- the rule engine stays a floor.
 *   3. Blend 50/50 into the cascade via runOnDeviceCascade(text, confidences)
 *      -- the exact seam that file already exposes -- and map to the UI
 *      result.
 *
 * Fail-safe: any engine/inference/parse failure degrades to the pure
 * heuristic result. scoreTranscriptOnDevice NEVER throws for a transcript, so
 * a transient model error can never knock scoring back to the network path
 * mid-session -- only a failure to INITIALISE (the model never loads) leaves
 * this scorer unregistered, and the default TS scorer stays in place.
 */
import { PasteCheckResult } from "../screens/PasteCheckScreen";
import { OnDeviceScorer } from "./modelLoader";
import { toPasteCheckResult } from "./defaultScorer";
import { runOnDeviceCascade, tier0Candidates } from "./onDeviceCascade";
import { debugLog, debugWarn } from "../utils/logger";

/**
 * The minimal capability this scorer needs from a native runtime: a loaded
 * model that can complete a prompt. The llama.rn binding (or any other
 * mature runtime) implements this in src/native-modules/.
 */


export interface LlamaEngine {
  /** True once weights are resident and the engine can run a completion. */
  isReady(): boolean;
  /** A short, greedy (temperature 0) completion of `prompt`. Returns the raw
   *  generated text; the caller is responsible for extracting JSON. */
  complete(prompt: string, opts?: { maxTokens?: number }): Promise<string>;
  /** Human-readable id for evidence labelling, e.g. "llama-3.2-1b-q4". */
  modelId(): string;
}

// System + user prompt mirror detection/conversation/llm_runtime.py's
// _SYSTEM_PROMPT / _build_user_prompt so the on-device and backend models are
// asked the exact same grounded question and their outputs stay comparable.
const SYSTEM_PROMPT =
  "You are a careful fraud-analysis assistant. You are given message text and " +
  "a list of manipulation tactics to assess. For EVERY tactic in the list, " +
  "judge ONLY whether the quoted message text actually supports that tactic.\n" +
  "Output rules (follow exactly):\n" +
  "1. Output STRICT JSON and NOTHING else -- no prose, no markdown, no code " +
  "fence, before or after.\n" +
  "2. Output a JSON ARRAY containing EXACTLY ONE object per tactic in the " +
  "list, in the SAME ORDER. Never merge tactics; never omit one; never add a " +
  "tactic that is not in the list.\n" +
  '3. Each object is {"tactic_id": string, "confidence": number 0.0-1.0, ' +
  '"rationale": string}. Include a tactic even when confidence is 0.0.\n' +
  "4. confidence = how strongly the QUOTED TEXT supports the tactic, not " +
  "general suspicion. rationale is under 20 words, grounded in the quoted " +
  "text. Never invent text that is not present.";

/**
 * Character budget for the transcript embedded in the grounding prompt. The
 * Tier-1 context is small (n_ctx 2048); the system prompt + tactic list +
 * generated JSON already consume part of it. ~6000 chars (roughly 1500
 * tokens) leaves headroom so a long pasted conversation never overflows the
 * context (which would make llama.rn error and silently drop the model pass).
 * Tier 0 has already scanned the FULL text for candidates, so the model only
 * needs enough surrounding context to judge them.
 */
export const MAX_PROMPT_TRANSCRIPT_CHARS = 6000;

/**
 * Fit `text` into the prompt budget. Short texts pass through unchanged. Long
 * texts keep the head and the tail (scam cues cluster at the opener and the
 * ask), with an explicit elision marker, so the judgement stays grounded in
 * real quoted text and the transform is deterministic.
 */
export function fitTranscriptToPrompt(text: string): string {
  if (text.length <= MAX_PROMPT_TRANSCRIPT_CHARS) {
    return text;
  }
  const headLen = Math.floor(MAX_PROMPT_TRANSCRIPT_CHARS * 0.7);
  const tailLen = MAX_PROMPT_TRANSCRIPT_CHARS - headLen;
  const head = text.slice(0, headLen);
  const tail = text.slice(text.length - tailLen);
  return `${head}\n[...transcript truncated for length...]\n${tail}`;
}

export function buildGroundingPrompt(text: string, tacticIds: string[]): string {
  // Llama-3.2 instruct chat template. A GGUF instruct model applies its own
  // template when given roles, but llama.rn's raw completion path wants a
  // formatted string, so we emit the canonical Llama-3 header format here.
  // The "FLAGGED TACTICS TO ASSESS: <ids>" line is kept on its own line and in
  // this exact shape because it is the grounding contract the parser and the
  // tests key off. The count + one-shot exemplar below steer the 1B model to
  // emit one object PER tactic (its default failure mode is collapsing to a
  // single object) without ever anchoring a confidence value.
  const user =
    `MESSAGE TEXT:\n${fitTranscriptToPrompt(text)}\n\n` +
    `FLAGGED TACTICS TO ASSESS: ${tacticIds.join(", ")}\n` +
    `Return EXACTLY ${tacticIds.length} object(s), one per tactic id above, in that order.\n` +
    "Respond with ONLY a JSON array, shaped like this example (use the real " +
    "tactic ids and your own values):\n" +
    '[{"tactic_id":"example_high","confidence":0.9,"rationale":"quoted text directly states it"},' +
    '{"tactic_id":"example_low","confidence":0.1,"rationale":"quoted text barely supports it"}]\n\n' +
    "Return the JSON array now.";
  return (
    "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n" +
    SYSTEM_PROMPT +
    "<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n" +
    user +
    "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
  );
}

/** One model judgement for a single tactic: score plus grounded reasoning. */
export interface TacticAssessment {
  confidence: number;
  /** Model's grounded rationale for this tactic, if it supplied one. */
  rationale?: string;
}

/**
 * Parse the model's raw output into {tacticId -> {confidence, rationale}},
 * keeping only the tactics we asked about and clamping confidence to [0,1].
 * Robust to the model wrapping the JSON in prose or a ```json fence: we
 * extract the first JSON array/object substring. Returns {} on anything
 * unparseable -- the caller treats {} as "no model signal" and falls back to
 * the heuristic. This is the single source of truth; parseTacticConfidences
 * is a thin confidence-only projection kept for backward compatibility.
 */
export function parseTacticAssessments(
  raw: string,
  requestedTacticIds: string[],
): Record<string, TacticAssessment> {
  const allowed = new Set(requestedTacticIds);
  const out: Record<string, TacticAssessment> = {};

  const json = extractJson(raw);
  if (json === null) {
    return out;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    return out;
  }

  let rows: unknown[];

  if (Array.isArray(parsed)) {
    // Model returned: [ {...}, {...} ]
    rows = parsed;
  } else if (
    typeof parsed === "object" &&
    parsed !== null &&
    Array.isArray((parsed as { results?: unknown[] }).results)
  ) {
    // Model returned: { results: [ ... ] }
    rows = (parsed as { results: unknown[] }).results;
  } else if (
    typeof parsed === "object" &&
    parsed !== null &&
    "tactic_id" in parsed
  ) {
    // Model returned: { tactic_id: "...", confidence: ... }
    rows = [parsed];
  } else {
    rows = [];
  }

  for (const row of rows) {
    if (typeof row !== "object" || row === null) {
      continue;
    }
    const r = row as { tactic_id?: unknown; confidence?: unknown; rationale?: unknown };
    const tid = typeof r.tactic_id === "string" ? r.tactic_id : "";
    if (!allowed.has(tid)) {
      continue;
    }
    const confNum = typeof r.confidence === "number" ? r.confidence : Number(r.confidence);
    if (!Number.isFinite(confNum)) {
      continue;
    }
    const rationale =
      typeof r.rationale === "string" && r.rationale.trim().length > 0
        ? r.rationale.trim()
        : undefined;
    out[tid] = {
      confidence: Math.max(0, Math.min(1, confNum)),
      ...(rationale !== undefined ? { rationale } : {}),
    };
  }
  return out;
}

/**
 * Backward-compatible {tacticId -> confidence} projection of
 * parseTacticAssessments. Retained so existing callers/tests are unchanged.
 */
export function parseTacticConfidences(
  raw: string,
  requestedTacticIds: string[],
): Record<string, number> {
  const assessments = parseTacticAssessments(raw, requestedTacticIds);
  const out: Record<string, number> = {};
  for (const [tid, a] of Object.entries(assessments)) {
    out[tid] = a.confidence;
  }
  return out;
}

/** Extract the first balanced JSON array or object from arbitrary text. */
function extractJson(raw: string): string | null {
  const start = raw.search(/[[{]/);
  if (start === -1) {
    return null;
  }
  const open = raw[start];
  const close = open === "[" ? "]" : "}";
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < raw.length; i++) {
    const ch = raw[i];
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (ch === "\\") {
        escaped = true;
      } else if (ch === '"') {
        inString = false;
      }
      continue;
    }
    if (ch === '"') {
      inString = true;
    } else if (ch === open) {
      depth++;
    } else if (ch === close) {
      depth--;
      if (depth === 0) {
        return raw.slice(start, i + 1);
      }
    }
  }
  return null;
}

export interface NativeLlamaScorerOptions {
  /** Cap generated tokens for the refinement pass (JSON is short). */
  maxTokens?: number;
}

/**
 * Build an OnDeviceScorer backed by a native Llama engine. Pure factory --
 * inject any LlamaEngine (the real llama.rn one, or a fake in tests).
 */
export function createNativeLlamaScorer(
  engine: LlamaEngine,
  options: NativeLlamaScorerOptions = {},
): OnDeviceScorer {
  const maxTokens = options.maxTokens ?? 256;

  return {
    isReady(): boolean {
      return engine.isReady();
    },

    async scoreTranscriptOnDevice(text: string): Promise<PasteCheckResult> {
      // 1. Cheap Tier-0 pass: what, if anything, is worth escalating?
      const candidates = tier0Candidates(text);

      // Dev-only diagnostics: log tactic ids only, never transcript text.
      debugLog("candidate tactics:", candidates.map((c) => c.tacticId));
      if (candidates.length === 0) {
        // Benign majority -- do not wake the model (spec 3.1).
        return toPasteCheckResult(runOnDeviceCascade(text));
      }

      // 2. Grounded Tier-1 model pass over ONLY the surfaced tactics.
      const tacticIds = Array.from(new Set(candidates.map((c) => c.tacticId)));
      let confidences: Record<string, number> = {};
      let rationales: Record<string, string> = {};
      try {
        if (engine.isReady()) {
          debugLog("calling engine.complete() for", tacticIds);

          const raw = await engine.complete(buildGroundingPrompt(text, tacticIds), {
            maxTokens,
          });

          const assessments = parseTacticAssessments(raw, tacticIds);
          confidences = {};
          rationales = {};
          for (const [tid, a] of Object.entries(assessments)) {
            confidences[tid] = a.confidence;
            if (a.rationale !== undefined) {
              rationales[tid] = a.rationale;
            }
          }
          debugLog("parsed model confidences for", Object.keys(confidences));
        }
      } catch (err) {
        // Inference failed -- degrade to heuristic-only, never throw (a thrown
        // error would drop scoring to the network path mid-session). The
        // failure is surfaced in dev logs, not silently swallowed.
        debugWarn("engine.complete failed:", err);
        confidences = {};
        rationales = {};
      }

      // 3. Blend (or, if the model gave nothing usable, run heuristic-only).
      //    Rationales are carried through so the UI can show the model's
      //    reasoning instead of discarding it.
      const score =
        Object.keys(confidences).length > 0
          ? runOnDeviceCascade(text, confidences, rationales)
          : runOnDeviceCascade(text);
      debugLog("final tier:", score.tierReached, "flags:", score.flags.length);

      return toPasteCheckResult(score);
    },
  };
}
