/**
 * Component tests for PasteCheckScreen -- the zero-permission entry point.
 *
 * Covers the three result states and the fail-closed contract:
 *   - flag        -> evidence card + Explain-more affordance
 *   - no pattern  -> "not a safety verdict" copy (spec 2.1)
 *   - FAILURE     -> explicit "couldn't finish" card, never dead air and
 *                    never mistakable for "nothing found"
 *
 * Rendered against the minimal react-native mock (src/testing/
 * mockReactNative.ts): asserts render branches and handler wiring, not
 * native behaviour.
 */
import React from "react";
import { PasteCheckScreen, PasteCheckResult } from "../PasteCheckScreen";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Narrow typing for react-test-renderer (no bundled/installed types).
interface TestNode {
  props: Record<string, unknown>;
  findAll(predicate: (n: TestNode) => boolean): TestNode[];
}
// eslint-disable-next-line @typescript-eslint/no-var-requires
const TestRenderer = require("react-test-renderer") as {
  create: (el: React.ReactElement) => { root: TestNode; toJSON: () => unknown; unmount: () => void };
  act: (cb: () => void | Promise<void>) => Promise<void>;
};

const FLAG_RESULT: PasteCheckResult = {
  kind: "flag",
  findingLabel: "Payment-Channel Funneling",
  evidence: [
    {
      kind: "transcript_span",
      quotedText: "gift card",
      sourceLabel: "on-device Tier 0 · Payment-Channel Funneling (confidence 0.42)",
      tacticId: "payment_channel_funneling",
    },
  ],
};

/** Render, type text, press "Check it", and settle the scoring promise. */
async function runCheckWith(
  scoreTranscript: (text: string) => Promise<PasteCheckResult>,
): Promise<{ text: () => string; unmount: () => void }> {
  const onExplainMoreRequested = jest.fn();
  let renderer!: ReturnType<typeof TestRenderer.create>;
  await TestRenderer.act(() => {
    renderer = TestRenderer.create(
      <PasteCheckScreen
        scoreTranscript={scoreTranscript}
        onExplainMoreRequested={onExplainMoreRequested}
      />,
    );
  });
  // Type into the input.
  await TestRenderer.act(() => {
    const input = renderer.root.findAll((n) => typeof n.props.onChangeText === "function")[0];
    (input.props.onChangeText as (t: string) => void)("send gift cards now");
  });
  // Press "Check it" and flush the scoring promise.
  await TestRenderer.act(async () => {
    const pressables = renderer.root.findAll((n) => typeof n.props.onPress === "function");
    (pressables[0].props.onPress as () => void)();
    await Promise.resolve();
  });
  return {
    text: () => JSON.stringify(renderer.toJSON()),
    unmount: () => renderer.unmount(),
  };
}

describe("PasteCheckScreen", () => {
  test("a flag renders the evidence card and the Explain-more affordance", async () => {
    const r = await runCheckWith(() => Promise.resolve(FLAG_RESULT));
    expect(r.text()).toContain("Payment-Channel Funneling");
    expect(r.text()).toContain("gift card");
    expect(r.text()).toContain("Explain more");
    r.unmount();
  });

  test("below-threshold renders 'no strong pattern' copy that is NOT a safety verdict", async () => {
    const r = await runCheckWith(() => Promise.resolve({ kind: "no_strong_pattern" }));
    expect(r.text()).toContain("No strong manipulation pattern detected");
    expect(r.text()).toContain("not a");   // "...it is not a guarantee..."
    r.unmount();
  });

  test("a REJECTED check surfaces an explicit failure card, never dead air", async () => {
    const r = await runCheckWith(() => Promise.reject(new Error("both paths down")));
    expect(r.text()).toContain("finish the check");
    expect(r.text()).toContain("not a result");
    // Must not be mistakable for a clean result.
    expect(r.text()).not.toContain("No strong manipulation pattern detected");
    r.unmount();
  });
});
