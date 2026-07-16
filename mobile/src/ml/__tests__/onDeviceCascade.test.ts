/**
 * Parity + behavior tests for the real on-device Tier-0 cascade.
 * Confirms the TS on-device path agrees with the Python reference
 * (detection/conversation/model_cascade.py) on a shared corpus -- this is
 * what makes "on-device first, real detection" verifiable, not asserted.
 */
import { runOnDeviceCascade } from "../onDeviceCascade";

// Expected surfaced/not-surfaced from the Python reference, same inputs.
const PY_REFERENCE: Array<[string, boolean]> = [
  ["hey how are you doing today", false],
  ["send gift cards now and do not tell your bank", true],
  ["you have won a guaranteed risk-free investment double your money", true],
  ["this is the irs pay immediately with gift card or face arrest", true],
  ["no rush take your time whenever you can", false],
  ["i would never ask you to buy a gift card", false],
  ["wire transfer the money right now to this account, keep it a secret", true],
  ["what if someone asked me to wire money?", false],
];

describe("on-device cascade parity with Python reference", () => {
  test.each(PY_REFERENCE)("%s -> surfaced=%s", (text, expected) => {
    const score = runOnDeviceCascade(text);
    expect(score.anySurfaced).toBe(expected);
  });
});

describe("cascade invariants", () => {
  test("benign text reaches Tier 0 only, no flags", () => {
    const s = runOnDeviceCascade("thanks so much, talk tomorrow");
    expect(s.tierReached).toBe(0);
    expect(s.flags).toHaveLength(0);
    expect(s.anySurfaced).toBe(false);
  });

  test("surfaced flag always carries matched evidence (spec 2.5)", () => {
    const s = runOnDeviceCascade("send gift cards now and do not tell your bank");
    expect(s.anySurfaced).toBe(true);
    for (const f of s.flags) {
      expect(f.matchedSpans.length).toBeGreaterThan(0);
      expect(f.confidence).toBeGreaterThanOrEqual(0.35);
    }
  });

  test("native model confidence blends when provided (Tier 1)", () => {
    const withModel = runOnDeviceCascade(
      "send gift cards now and do not tell your bank",
      { payment_channel_funneling: 0.95, isolation_instruction: 0.9 },
    );
    // The per-message default blend uses the Tier-1 (1B) model, so tierReached
    // is 1. Tier 2 (3B speculative decoding) is never the default path
    // (spec 3.1). (Previously mislabeled Tier 2.)
    expect(withModel.tierReached).toBe(1);
    expect(withModel.anySurfaced).toBe(true);
  });

  test("native model rationale is attached to the surfaced flag", () => {
    const withModel = runOnDeviceCascade(
      "send gift cards now and do not tell your bank",
      { payment_channel_funneling: 0.95 },
      { payment_channel_funneling: "demands irreversible gift-card payment" },
    );
    const flag = withModel.flags.find((f) => f.tacticId === "payment_channel_funneling");
    expect(flag?.rationale).toBe("demands irreversible gift-card payment");
  });

  test("negation is not treated as a live instruction", () => {
    const s = runOnDeviceCascade("i would never ask you to buy a gift card");
    expect(s.anySurfaced).toBe(false);
  });
});

// Regression: short high-information cues (OTP, AnyDesk, Bitcoin, gift card)
// must no longer be filtered out as "fragmentary", and the expanded
// authority taxonomy must not turn benign bank notifications into warnings.
// Mirrors tests/test_nli_specificity_and_taxonomy.py so on-device and backend
// stay in agreement.
describe("information-weighted specificity + expanded authority taxonomy", () => {
  const SCAMS_SURFACE: Array<[string, string]> = [
    [
      "otp phishing (the reported screenshot)",
      "Your bank account has been locked due to suspicious activity. " +
        "Please tell me the OTP sent to your phone immediately to verify your identity.",
    ],
    [
      "bank phishing",
      "This is your bank's fraud department. Your account has been suspended. " +
        "Verify your identity now by confirming the verification code we sent.",
    ],
    [
      "tech-support scam",
      "Microsoft security team here. Your computer is infected with a virus. " +
        "Install AnyDesk so we can remove it immediately.",
    ],
    [
      "gift-card scam",
      "You've won a prize! To claim it, buy a gift card and send the code to us right now.",
    ],
    [
      "crypto scam",
      "Guaranteed profit! Send Bitcoin to our crypto wallet immediately and " +
        "double your money, risk-free. Don't tell anyone.",
    ],
    [
      "romance scam requesting money",
      "I've never felt this way about you. I need you to wire money for my flight, " +
        "but please don't tell your family, it is urgent.",
    ],
  ];

  test.each(SCAMS_SURFACE)("scam surfaces: %s", (_name, text) => {
    expect(runOnDeviceCascade(text).anySurfaced).toBe(true);
  });

  const BENIGN_ABSTAIN: Array<[string, string]> = [
    [
      "plain banking notification",
      "Your account balance is 2450 dollars. You have 3 recent transactions. Log in to view details.",
    ],
    [
      "bank security alert with dual-use phrases but no solicitation",
      "Security alert: we noticed a new login to your bank account from a new device. " +
        "If this was you, no action is needed.",
    ],
    [
      "benign family conversation",
      "Hey mom, can you send me the recipe for your soup? Also are we still on for dinner Sunday?",
    ],
    [
      "benign isolation-shaped family message",
      "Don't tell your brother but I'm planning a surprise party for his birthday next week.",
    ],
  ];

  test.each(BENIGN_ABSTAIN)("benign abstains: %s", (_name, text) => {
    expect(runOnDeviceCascade(text).anySurfaced).toBe(false);
  });

  test("OTP flag surfaces with cited evidence and clears the ceiling", () => {
    const s = runOnDeviceCascade(
      "Your bank account has been locked due to suspicious activity. " +
        "Please tell me the OTP sent to your phone immediately to verify your identity.",
    );
    expect(s.anySurfaced).toBe(true);
    const remote = s.flags.find((f) => f.tacticId === "remote_access_solicitation");
    expect(remote).toBeDefined();
    expect(remote!.matchedSpans).toContain("otp");
    for (const f of s.flags) {
      expect(f.confidence).toBeGreaterThanOrEqual(0.35);
    }
  });
});
