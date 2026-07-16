/**
 * TrustTrace backend API client.
 *
 * Spec ref: PDF Section 5 (on-device-first; the ONLY automatic-eligible
 * server route from mobile is nothing -- every backend call here is either
 * (a) the opt-in "explain more" cloud path, user-initiated per use, or
 * (b) an explicit fallback for transcript scoring when the on-device
 * cascade is unavailable). Section 7.2: these types mirror the backend's
 * Pydantic models (backend/schemas.py) -- the single source of truth.
 *
 * IMPORTANT SHAPE NOTE: the backend's AnalyzeTranscriptResponse
 * (tactic_id / verdict / confidence / explanation) is NOT the same shape
 * the UI consumes (PasteCheckResult: kind / findingLabel / evidence[]).
 * This client owns that adaptation in `toPasteCheckResult` so the screen
 * contract stays clean and identical whether the result came from the
 * device or the server.
 */
import { API_BASE_URL, API_TIMEOUT_MS } from "../config/env";
import { PasteCheckResult } from "../screens/PasteCheckScreen";
import { CitedEvidence } from "../components/EvidenceCitation";

// ---- Backend wire types (mirror backend/schemas.py exactly) ------------

export interface AnalyzeTranscriptRequestWire {
  session_id: string;
  sender: string;
  text: string;
}

export interface GatedFlagWire {
  tactic_id: string;
  verdict: string;
  confidence: number;
  explanation: string;
}

export interface AnalyzeTranscriptResponseWire {
  tier_reached: number;
  flags: GatedFlagWire[];
  any_surfaced: boolean;
}

export interface ExplainMoreRequestWire {
  session_id: string;
  transcript_excerpt: string;
}

export interface ExplainMoreResponseWire {
  explanation: string;
  provider_used: string;
}

// ---- Errors ------------------------------------------------------------

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// ---- Low-level fetch with timeout -------------------------------------

async function postJson<TReq, TRes>(
  path: string,
  body: TReq,
  fetchImpl: typeof fetch,
): Promise<TRes> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    const res = await fetchImpl(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) {
      // Read a short detail if the backend sent one (FastAPI HTTPException
      // returns {"detail": "..."}), but never surface a raw body blindly.
      let detail = `HTTP ${res.status}`;
      try {
        const j = (await res.json()) as { detail?: unknown };
        if (typeof j.detail === "string") { detail = j.detail; }
      } catch {
        /* non-JSON error body -- keep the status-only message */
      }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as TRes;
  } finally {
    clearTimeout(timer);
  }
}

// ---- Shape adaptation: backend flags -> UI PasteCheckResult -----------

/**
 * Map the backend's already-NLI-gated, already-confidence-gated flags into
 * the UI result contract. A key invariant from PasteCheckScreen: a "flag"
 * result MUST carry at least one cited evidence item, and below-threshold
 * is "no_strong_pattern", NEVER a safety verdict.
 *
 * The backend does not (in this build) return per-flag transcript spans,
 * so we cite the flag's own explanation as a transcript-derived finding
 * and label its source honestly as coming from the server-side cascade.
 * When the backend is later extended to return spans, only this function
 * changes -- the screen and the rest of the app do not.
 */
export function toPasteCheckResult(
  wire: AnalyzeTranscriptResponseWire,
): PasteCheckResult {
  if (!wire.any_surfaced || wire.flags.length === 0) {
    return { kind: "no_strong_pattern" };
  }

  const evidence = wire.flags.map<CitedEvidence>((f) => ({
    kind: "transcript_span",
    quotedText: f.explanation,
    sourceLabel: `on-device cascade tier ${wire.tier_reached} \u00b7 ${f.tactic_id} (confidence ${f.confidence.toFixed(2)})`,
  }));

  // Non-empty by the guard above, so the tuple contract holds.
  const [first, ...rest] = evidence;
  const primaryLabel = wire.flags[0].verdict || "Possible manipulation pattern";

  return {
    kind: "flag",
    findingLabel: primaryLabel,
    evidence: [first, ...rest],
  };
}

// ---- Public API --------------------------------------------------------

export interface TrustTraceApi {
  analyzeTranscript(
    args: { sessionId: string; sender: string; text: string },
  ): Promise<PasteCheckResult>;
  explainMore(
    args: { sessionId: string; transcriptExcerpt: string },
  ): Promise<ExplainMoreResponseWire>;
  health(): Promise<boolean>;
}

export function createApiClient(
  fetchImpl: typeof fetch = fetch,
): TrustTraceApi {
  // fetchImpl is threaded through every request so this client is
  // unit-testable with an injected fetch; production passes the global.
  return {
    async analyzeTranscript({ sessionId, sender, text }) {
      const wire = await postJson<
        AnalyzeTranscriptRequestWire,
        AnalyzeTranscriptResponseWire
      >(
        "/v1/analyze-transcript",
        { session_id: sessionId, sender, text },
        fetchImpl,
      );
      return toPasteCheckResult(wire);
    },

    async explainMore({ sessionId, transcriptExcerpt }) {
      return postJson<ExplainMoreRequestWire, ExplainMoreResponseWire>(
        "/v1/explain-more",
        { session_id: sessionId, transcript_excerpt: transcriptExcerpt },
        fetchImpl,
      );
    },

    async health() {
      try {
        const res = await fetchImpl(`${API_BASE_URL}/health`, { method: "GET" });
        return res.ok;
      } catch {
        return false;
      }
    },
  };
}

/** Default singleton the app wires in (see App.tsx / scoring.ts). */
export const api: TrustTraceApi = createApiClient();
