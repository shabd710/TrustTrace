/**
 * Component tests for EvidenceCitation -- the UI-side enforcement of
 * "every flag cites exact evidence" (spec 2.5). Rendered against the
 * minimal react-native mock (see src/testing/mockReactNative.ts).
 */
import React from "react";
import { EvidenceCitation, CitedEvidence, EvidenceCitationProps } from "../EvidenceCitation";

// React 18 requires this opt-in for act() outside a browser-like env.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// react-test-renderer ships no bundled types and @types/react-test-renderer
// is not installed; declare the narrow surface these tests use.
// eslint-disable-next-line @typescript-eslint/no-var-requires
const TestRenderer = require("react-test-renderer") as {
  create: (el: React.ReactElement) => { toJSON: () => unknown; unmount: () => void };
  act: (cb: () => void | Promise<void>) => Promise<void>;
};

/** Render the component, return its serialized output (read AFTER act commits). */
async function renderToText(props: EvidenceCitationProps): Promise<string> {
  let renderer!: { toJSON: () => unknown; unmount: () => void };
  await TestRenderer.act(() => {
    renderer = TestRenderer.create(<EvidenceCitation {...props} />);
  });
  const out = JSON.stringify(renderer.toJSON());
  renderer.unmount();
  return out;
}

const BASE_EVIDENCE: CitedEvidence = {
  kind: "transcript_span",
  quotedText: "gift card, do not tell",
  sourceLabel: "on-device Tier 1 · Payment-Channel Funneling (confidence 0.78)",
  tacticId: "payment_channel_funneling",
};

describe("EvidenceCitation", () => {
  test("renders the finding, quoted evidence, and source label", async () => {
    const out = await renderToText({
      findingLabel: "Payment-Channel Funneling",
      evidence: [BASE_EVIDENCE],
    });
    expect(out).toContain("Payment-Channel Funneling");
    expect(out).toContain("gift card, do not tell");
    expect(out).toContain("confidence 0.78");
    expect(out).toContain("From the conversation");
  });

  test("shows the on-device model rationale when present", async () => {
    const out = await renderToText({
      findingLabel: "Payment-Channel Funneling",
      evidence: [{ ...BASE_EVIDENCE, modelRationale: "demands irreversible gift-card payment" }],
    });
    expect(out).toContain("On-device model:");
    expect(out).toContain("demands irreversible gift-card payment");
  });

  test("omits the rationale line entirely on the pure-heuristic path", async () => {
    const out = await renderToText({
      findingLabel: "Payment-Channel Funneling",
      evidence: [BASE_EVIDENCE],
    });
    expect(out).not.toContain("On-device model:");
  });

  test("marks uncertain OCR evidence as uncertain, never hides it (spec 10.1)", async () => {
    const out = await renderToText({
      findingLabel: "Seen on screen",
      evidence: [{ ...BASE_EVIDENCE, kind: "ocr_region", uncertain: true }],
    });
    expect(out).toContain("treat as uncertain");
  });
});
