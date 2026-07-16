/**
 * Tests for the engine-agnostic native-Llama scorer glue. The real llama.rn
 * binding lives in src/native-modules/ and is not importable in this sandbox;
 * these tests inject a FAKE LlamaEngine so all the logic that matters --
 * prompt construction, JSON grounding, confidence blending, and graceful
 * degradation -- is verified here, output-for-output.
 */
import {
  createNativeLlamaScorer,
  buildGroundingPrompt,
  parseTacticConfidences,
  parseTacticAssessments,
  fitTranscriptToPrompt,
  MAX_PROMPT_TRANSCRIPT_CHARS,
  LlamaEngine,
} from "../nativeLlamaScorer";

class FakeEngine implements LlamaEngine {
  public calls: string[] = [];
  constructor(
    private ready: boolean,
    private responder: (prompt: string) => string | Promise<string>,
  ) {}
  isReady(): boolean {
    return this.ready;
  }
  modelId(): string {
    return "fake-llama";
  }
  async complete(prompt: string): Promise<string> {
    this.calls.push(prompt);
    return this.responder(prompt);
  }
}

const IRS_SCAM = "this is the irs pay immediately with gift card or face arrest";
const BENIGN = "hey how are you doing today";

describe("parseTacticConfidences", () => {
  const asked = ["payment_channel_funneling", "urgency_injection"];

  test("parses a plain JSON array and clamps to [0,1]", () => {
    const raw = JSON.stringify([
      { tactic_id: "payment_channel_funneling", confidence: 0.91, rationale: "gift card demanded" },
      { tactic_id: "urgency_injection", confidence: 1.7, rationale: "immediately" },
    ]);
    expect(parseTacticConfidences(raw, asked)).toEqual({
      payment_channel_funneling: 0.91,
      urgency_injection: 1,
    });
  });

  test("tolerates prose and a ```json fence around the JSON", () => {
    const raw =
      "Sure! Here is my assessment:\n```json\n" +
      JSON.stringify([{ tactic_id: "urgency_injection", confidence: 0.6 }]) +
      "\n```\nHope that helps.";
    expect(parseTacticConfidences(raw, asked)).toEqual({ urgency_injection: 0.6 });
  });

  test("accepts a {results:[...]} wrapper", () => {
    const raw = JSON.stringify({ results: [{ tactic_id: "payment_channel_funneling", confidence: 0.5 }] });
    expect(parseTacticConfidences(raw, asked)).toEqual({ payment_channel_funneling: 0.5 });
  });

  test("HEURISTIC FLOOR: a tactic not in the asked set is dropped", () => {
    // The model must never be able to introduce a tactic Tier 0 didn't surface.
    const raw = JSON.stringify([
      { tactic_id: "authority_impersonation", confidence: 0.99 },
      { tactic_id: "payment_channel_funneling", confidence: 0.8 },
    ]);
    expect(parseTacticConfidences(raw, asked)).toEqual({ payment_channel_funneling: 0.8 });
  });

  test("returns {} on unparseable output", () => {
    expect(parseTacticConfidences("the model said nothing useful", asked)).toEqual({});
    expect(parseTacticConfidences("{not: valid json,,,}", asked)).toEqual({});
  });
});

describe("parseTacticAssessments (rationale-carrying)", () => {
  const asked = ["payment_channel_funneling", "urgency_injection"];

  test("captures rationale alongside confidence and clamps", () => {
    const raw = JSON.stringify([
      { tactic_id: "payment_channel_funneling", confidence: 1.4, rationale: "gift card demanded" },
      { tactic_id: "urgency_injection", confidence: 0.6 },
    ]);
    expect(parseTacticAssessments(raw, asked)).toEqual({
      payment_channel_funneling: { confidence: 1, rationale: "gift card demanded" },
      urgency_injection: { confidence: 0.6 },
    });
  });

  test("empty/whitespace rationale is dropped", () => {
    const raw = JSON.stringify([
      { tactic_id: "urgency_injection", confidence: 0.5, rationale: "   " },
    ]);
    expect(parseTacticAssessments(raw, asked)).toEqual({
      urgency_injection: { confidence: 0.5 },
    });
  });

  test("parseTacticConfidences stays a confidence-only projection", () => {
    const raw = JSON.stringify([
      { tactic_id: "urgency_injection", confidence: 0.6, rationale: "acts now" },
    ]);
    expect(parseTacticConfidences(raw, asked)).toEqual({ urgency_injection: 0.6 });
  });
});

describe("fitTranscriptToPrompt", () => {
  test("passes short text through unchanged", () => {
    expect(fitTranscriptToPrompt("short scam text")).toBe("short scam text");
  });

  test("windows very long text to the budget with an elision marker", () => {
    const long = "a".repeat(MAX_PROMPT_TRANSCRIPT_CHARS + 5000);
    const fitted = fitTranscriptToPrompt(long);
    expect(fitted.length).toBeLessThan(long.length);
    expect(fitted).toContain("[...transcript truncated for length...]");
  });
});

describe("buildGroundingPrompt", () => {
  test("includes the message text and the exact tactics to assess", () => {
    const p = buildGroundingPrompt(IRS_SCAM, ["urgency_injection", "payment_channel_funneling"]);
    expect(p).toContain(IRS_SCAM);
    expect(p).toContain("urgency_injection, payment_channel_funneling");
    expect(p).toContain("<|start_header_id|>assistant<|end_header_id|>");
  });
});

describe("createNativeLlamaScorer", () => {
  const highConfResponder = (prompt: string): string => {
    // Echo a confident assessment for whatever tactics were asked about.
    const ids = /FLAGGED TACTICS TO ASSESS: ([^\n]+)/.exec(prompt)?.[1] ?? "";
    const rows = ids.split(",").map((t) => ({ tactic_id: t.trim(), confidence: 0.9 }));
    return JSON.stringify(rows);
  };

  test("benign text never wakes the model and returns no_strong_pattern", async () => {
    const engine = new FakeEngine(true, highConfResponder);
    const scorer = createNativeLlamaScorer(engine);
    const result = await scorer.scoreTranscriptOnDevice(BENIGN);
    expect(result.kind).toBe("no_strong_pattern");
    expect(engine.calls).toHaveLength(0); // Tier 2 is not the default path
  });

  test("scam text runs the model and surfaces a Tier-1 model-blended flag", async () => {
    const engine = new FakeEngine(true, highConfResponder);
    const scorer = createNativeLlamaScorer(engine);
    const result = await scorer.scoreTranscriptOnDevice(IRS_SCAM);
    expect(engine.calls).toHaveLength(1);
    expect(result.kind).toBe("flag");
    if (result.kind === "flag") {
      // The per-message default blend uses the Tier-1 (1B) model, so the
      // provenance label is Tier 1 -- Tier 2 (3B speculative decoding) is never
      // the default path (spec 3.1). (Was mislabeled "Tier 2".)
      expect(result.evidence.some((e) => e.sourceLabel.includes("Tier 1"))).toBe(true);
    }
  });

  test("carries the model's rationale into the UI evidence", async () => {
    const responder = (prompt: string): string => {
      const ids = /FLAGGED TACTICS TO ASSESS: ([^\n]+)/.exec(prompt)?.[1] ?? "";
      const rows = ids.split(",").map((t) => ({
        tactic_id: t.trim(),
        confidence: 0.9,
        rationale: `model note for ${t.trim()}`,
      }));
      return JSON.stringify(rows);
    };
    const scorer = createNativeLlamaScorer(new FakeEngine(true, responder));
    const result = await scorer.scoreTranscriptOnDevice(IRS_SCAM);
    expect(result.kind).toBe("flag");
    if (result.kind === "flag") {
      // At least one evidence item exposes the model's grounded reasoning.
      expect(
        result.evidence.some(
          (e) => typeof e.modelRationale === "string" && e.modelRationale.startsWith("model note for"),
        ),
      ).toBe(true);
    }
  });

  test("degrades to the heuristic result (never throws) when inference fails", async () => {
    const engine = new FakeEngine(true, () => {
      throw new Error("native inference crashed");
    });
    const scorer = createNativeLlamaScorer(engine);
    const result = await scorer.scoreTranscriptOnDevice(IRS_SCAM);
    // Still a flag from the heuristic cascade -- a model failure must not
    // silence a clear scam, and must not throw (which would drop scoring back
    // to the network path).
    expect(result.kind).toBe("flag");
  });

  test("degrades to the heuristic result when the model returns garbage", async () => {
    const engine = new FakeEngine(true, () => "I'm not sure, could be fine?");
    const scorer = createNativeLlamaScorer(engine);
    const result = await scorer.scoreTranscriptOnDevice(IRS_SCAM);
    expect(result.kind).toBe("flag");
  });

  test("does not call the model when the engine is not ready", async () => {
    const engine = new FakeEngine(false, highConfResponder);
    const scorer = createNativeLlamaScorer(engine);
    const result = await scorer.scoreTranscriptOnDevice(IRS_SCAM);
    expect(engine.calls).toHaveLength(0);
    expect(result.kind).toBe("flag"); // heuristic still stands
  });

  test("isReady reflects the underlying engine", () => {
    expect(createNativeLlamaScorer(new FakeEngine(true, highConfResponder)).isReady()).toBe(true);
    expect(createNativeLlamaScorer(new FakeEngine(false, highConfResponder)).isReady()).toBe(false);
  });
});
