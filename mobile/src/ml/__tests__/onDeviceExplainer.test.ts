/**
 * Tests for the network-free on-device "explain more" fallback. This is what
 * keeps the Explain-more feature useful when the backend is unreachable (the
 * "TypeError: Network request failed" case): the explanation is derived from
 * the on-device flags, so it always names the tactics, cites the evidence,
 * and gives a safe next step -- no network required.
 */
import { buildOnDeviceExplanation } from "../onDeviceExplainer";

const AMAZON_GIFT_CARD_SCAM =
  "This is Amazon Security. Your account has been compromised. " +
  "To protect your money, buy $500 Apple gift cards immediately and send me the codes. " +
  "Do not tell your bank or your family.";

describe("on-device explanation fallback", () => {
  test("explains the flagged scam with tactics, cited evidence, and a next step", () => {
    const explanation = buildOnDeviceExplanation(AMAZON_GIFT_CARD_SCAM);

    // Names the tactics we detect in this message.
    expect(explanation).toContain("Authority Impersonation");
    expect(explanation).toContain("Payment-Channel Funneling");
    expect(explanation).toContain("Urgency Injection");
    expect(explanation).toContain("Isolation Instruction");

    // Cites at least one concrete matched span (spec 2.5: evidence, not just
    // a verdict).
    expect(explanation).toContain("gift card");

    // Gives an actionable safety tip.
    expect(explanation.toLowerCase()).toContain("what to do");
  });

  test("otp phishing explanation warns specifically about the one-time code", () => {
    const explanation = buildOnDeviceExplanation(
      "Your bank account has been locked due to suspicious activity. " +
        "Please tell me the OTP sent to your phone immediately to verify your identity.",
    );
    expect(explanation).toContain("Remote-Access / One-Time-Code Solicitation");
    expect(explanation.toLowerCase()).toContain("one-time code");
  });

  test("never fabricates a verdict when nothing surfaced", () => {
    const explanation = buildOnDeviceExplanation("hey are we still on for lunch tomorrow?");
    expect(explanation).toContain("didn't find a strong manipulation pattern");
    // Explicitly not a safety guarantee (spec 2.1).
    expect(explanation.toLowerCase()).toContain("not a guarantee");
  });

  test("is deterministic and self-contained (no network, pure function of text)", () => {
    const a = buildOnDeviceExplanation(AMAZON_GIFT_CARD_SCAM);
    const b = buildOnDeviceExplanation(AMAZON_GIFT_CARD_SCAM);
    expect(a).toBe(b);
  });
});
