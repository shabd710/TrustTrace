/**
 * Production detection suite: scam-family coverage + false-positive guards.
 *
 * Complements onDeviceCascade.test.ts (Python-parity corpus) by exercising
 * the expanded taxonomy (audit item #8) across the scam families the product
 * must cover, plus the honest tier-labeling fix. Every scam sample is written
 * the way real scams arrive -- multiple co-occurring signals -- because the
 * grounding gate deliberately refuses to surface a lone dual-use phrase (that
 * is what keeps legitimate bank/courier/job messages from false-flagging).
 *
 * Language note: cues are matched case-insensitively against Latin-script
 * text, so English, Hinglish, and transliterated SMS work. Pure Devanagari
 * Hindi is a known gap (no Devanagari cues yet) and is NOT asserted here.
 */
import { runOnDeviceCascade } from "../onDeviceCascade";

function surfaces(text: string): boolean {
  return runOnDeviceCascade(text).anySurfaced;
}

describe("scam families surface (expanded taxonomy)", () => {
  const SCAMS: Array<[string, string]> = [
    [
      "UPI/QR receive-scam",
      "To receive your prize, scan this QR and enter your UPI PIN immediately.",
    ],
    [
      "fake-police / digital arrest",
      "This is the police. There is an arrest warrant in your name for money " +
        "laundering. Pay immediately in Bitcoin or you will be arrested.",
    ],
    [
      "sextortion",
      "I have your videos. Send me money in Bitcoin now or I will leak your " +
        "photos to your family.",
    ],
    [
      "job scam (advance fee)",
      "Work from home job! Earn daily. Pay a registration fee via UPI right " +
        "now to start.",
    ],
    [
      "delivery / customs scam",
      "Your parcel is held at customs. Pay the customs fee via UPI immediately " +
        "or it will be returned.",
    ],
    [
      "bank-KYC scam (Hinglish SMS)",
      "Dear customer your account has been suspended, update your KYC now. " +
        "Share the OTP sent to your phone to verify your identity urgently.",
    ],
    [
      "tech-support refund scam",
      "Microsoft security team here. We refunded you too much. Install AnyDesk " +
        "and share the code so we can reverse the wire transfer.",
    ],
    [
      "crypto investment scam",
      "Guaranteed profit! High returns, risk-free. Send USDT to our crypto " +
        "wallet now and double your money. Don't tell anyone.",
    ],
  ];

  test.each(SCAMS)("surfaces: %s", (_name, text) => {
    expect(surfaces(text)).toBe(true);
  });
});

describe("benign / dual-use messages abstain (false-positive guards)", () => {
  const BENIGN: Array<[string, string]> = [
    [
      "benign UPI split (dual-use payment phrases only)",
      "Let's split the dinner bill -- send me a collect request on PhonePe.",
    ],
    [
      "legitimate KYC reminder (no solicitation)",
      "Reminder: please update your KYC at your nearest branch by Friday.",
    ],
    [
      "genuine job posting (no fee, no urgency)",
      "We have a work from home part-time job opening, no experience needed. " +
        "Apply on our careers page.",
    ],
    [
      "legit courier notice (dual-use, no payment ask)",
      "Your parcel is held at the depot; we will attempt redelivery tomorrow.",
    ],
    [
      "refund confirmation (no cues at all)",
      "A refund of 200 rupees has been credited to your account. Thanks!",
    ],
    [
      "family sharing a new number",
      "Hi it's me, this is my new number, save it. See you at dinner!",
    ],
  ];

  test.each(BENIGN)("abstains: %s", (_name, text) => {
    expect(surfaces(text)).toBe(false);
  });
});

describe("tier labeling is honest about model provenance", () => {
  const SCAM = "send gift cards now and do not tell your bank";

  test("pure-heuristic result (no native model) is Tier 0", () => {
    const s = runOnDeviceCascade(SCAM);
    expect(s.anySurfaced).toBe(true);
    // No model contributed -> must NOT claim Tier 1 provenance.
    expect(s.tierReached).toBe(0);
  });

  test("model-blended result is Tier 1", () => {
    const s = runOnDeviceCascade(SCAM, { payment_channel_funneling: 0.95 });
    expect(s.tierReached).toBe(1);
  });
});
