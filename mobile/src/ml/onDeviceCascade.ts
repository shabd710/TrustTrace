/**
 * On-device detection cascade -- REAL implementation (not a stub).
 *
 * Spec ref: PDF Section 3.1-3.2 (Tier 0/1/2 cascade, on-device) and
 * Section 5 (on-device-first: the transcript never leaves the phone on
 * this path). This is a faithful TypeScript port of the tested Python
 * Tier-0 cascade (detection/conversation/model_cascade.py +
 * tactic_taxonomy.py + the grounding gate discipline), so the on-device
 * path genuinely runs real detection with zero network -- exactly the
 * privacy property the spec's default path promises.
 *
 * Layering:
 *   - Tier 0 (this file, pure TS): cue-phrase scan + compound boosting +
 *     mutual-exclusivity + negation/hypothetical grounding checks. Runs on
 *     every message, single-digit ms, no model, no network.
 *   - Tier 1/2 (optional native Llama via modelLoader's EdgeRuntimeBinding):
 *     when a native GGUF runtime is registered, its per-tactic confidence
 *     is blended in exactly as the Python cascade blends llm_runtime output
 *     (0.5 * heuristic + 0.5 * model). When absent, Tier 0 stands alone --
 *     the same tested degradation the Python path has.
 *
 * The gate ceiling and blend weights are kept identical to the Python
 * reference so on-device and backend verdicts agree on the same input.
 */

// ---- Taxonomy (ported verbatim from tactic_taxonomy.py) ----------------

interface TacticSpec {
  label: string;
  cuePhrases: string[];
  mutuallyExclusiveWith: string[];
  scoreable: boolean; // calming_reassurance is not a standalone risk
}

const TACTICS: Record<string, TacticSpec> = {
  urgency_injection: {
    label: "Urgency Injection",
    cuePhrases: [
      "right now", "immediately", "act now", "urgent", "expires today",
      "final notice", "within the hour", "before it's too late",
      "last chance", "act fast", "time is running out",
    ],
    mutuallyExclusiveWith: ["calming_reassurance"],
    scoreable: true,
  },
  isolation_instruction: {
    label: "Isolation Instruction",
    cuePhrases: [
      "don't tell", "do not tell", "keep this between us", "don't tell your bank",
      "do not tell your bank", "don't tell your family", "do not tell your family",
      "this is confidential", "don't mention this to anyone", "do not mention this to anyone",
      "keep it a secret", "don't call anyone", "do not call anyone",
      "don't tell the police", "do not tell the police",
    ],
    mutuallyExclusiveWith: [],
    scoreable: true,
  },
  authority_impersonation: {
    label: "Authority Impersonation",
    cuePhrases: [
      "this is the irs",
      "this is your bank",
      "law enforcement",
      "federal agent",
      "your account has been compromised",
      "official notice",
      "case number",
      "i am calling from",
      "this is your ceo",
      "your boss",

    // Tech-support impersonation
      "microsoft",
      "microsoft security",
      "security team",
      "windows support",
      "tech support",
      "apple support",
      "your computer has been hacked",
      "your computer is infected",
      "virus detected",
      "we detected a virus",

    // Modern bank-phishing / account-security language (FTC bank
    // impersonation is now the top text-scam opener). Deliberately
    // over-inclusive for Tier 0 recall -- these are DUAL-USE (real banks
    // say them too), so the grounding gate treats them as
    // LOW_INFORMATION_CUES: they never surface alone, only when a genuine
    // solicitation (OTP / payment / remote-access) corroborates them. Kept
    // identical to detection/conversation/tactic_taxonomy.py.
      "your bank account",
      "account locked",
      "account has been locked",
      "account suspended",
      "account has been suspended",
      "security alert",
      "verify your identity",
      "confirm your identity",
      "fraud department",
      "unusual activity",
      "suspicious activity",

    // Fake-police / legal-threat impersonation (digital-arrest scams). The
    // explicit openers are strong; the softer "under investigation"-style
    // phrases are DUAL-USE (LOW_INFORMATION_CUES) and only surface when a
    // solicitation or threat corroborates them.
      "this is the police",
      "police department",
      "arrest warrant",
      "warrant for your arrest",
      "digital arrest",
      "cyber crime",
      "money laundering",
      "customs department",
      "income tax department",

    // Delivery / customs impersonation openers. Dual-use (real couriers say
    // them), so treated as LOW_INFORMATION_CUES below.
      "your parcel",
      "your package",
      "parcel is held",
      "package is held",

    // Bank-KYC impersonation (top India SMS-scam opener). Real banks also ask
    // for KYC, so these are LOW_INFORMATION_CUES: they surface only when an
    // OTP/link/remote-access solicitation corroborates them.
      "kyc",
      "update your kyc",
      "kyc verification",
      "kyc expired",
    ],
    mutuallyExclusiveWith: [],
    scoreable: true,
  },
  remote_access_solicitation: {
    label: "Remote-Access / One-Time-Code Solicitation",
    cuePhrases: [
      "anydesk",
      "install anydesk",
      "download anydesk",
      "teamviewer",
      "remote access",
      "remote support",
      "install the app",
      "give me access",
      "6-digit code",
      "six-digit code",
      "6 digit code",
      "one-time code",
      "one time code",
      "otp",
      "verification code",
      "read me the code",
      "share the code",
      "tell me the code",
    // Screen-mirroring variants of the remote-access ask.
      "screen share",
      "screen sharing",
      "quick support",
    ],
    mutuallyExclusiveWith: [],
    scoreable: true,
  },
  payment_channel_funneling: {
    label: "Payment-Channel Funneling",
    cuePhrases: [
      "gift card", "wire transfer", "wire money", "wire the money", "crypto", "bitcoin",
      "only accept", "buy a gift card", "send the code", "usdt",
      "western union", "money order", "only way to pay",
    // UPI / QR rails (dominant in India). Entering a UPI PIN is only ever
    // needed to SEND money, so "upi pin" is a strong receive-scam signal;
    // the app/brand names and "scan the qr" are DUAL-USE (used in benign
    // payments too) and are LOW_INFORMATION_CUES that need corroboration.
      "upi", "upi pin", "enter your upi pin", "upi id",
      "google pay", "phonepe", "paytm", "gpay",
      "collect request", "scan the qr", "scan this qr", "scan to pay", "qr code",
    // Advance-fee framing (job / delivery / refund scams). Dual-use, capped.
      "registration fee", "processing fee", "advance fee", "security deposit",
    ],
    mutuallyExclusiveWith: [],
    scoreable: true,
  },
  too_good_to_be_true: {
    label: "Too-Good-To-Be-True Framing",
    cuePhrases: [
      "guaranteed return", "double your money", "risk-free investment",
      "you've won", "guaranteed profit", "no risk", "act now to claim",
      "i've never felt this way", "soulmate", "guaranteed income",
    // Job-offer and investment bait. All DUAL-USE (legitimate offers use the
    // same words), so LOW_INFORMATION_CUES: they surface only when a fee
    // demand, urgency, or payment funnel corroborates them.
      "work from home", "part-time job", "part time job",
      "earn daily", "daily income", "no experience needed", "guaranteed job",
      "high returns", "investment opportunity", "trading tips",
    ],
    mutuallyExclusiveWith: [],
    scoreable: true,
  },
  coercion_threat: {
    label: "Threat / Coercion",
    cuePhrases: [
    // Sextortion / blackmail.
      "leak your photos", "leak your video", "expose you",
      "share your video", "share your photos", "intimate photos",
      "your private photos", "i have your videos", "send nudes",
      "post your pictures", "ruin your reputation",
    // Coercive legal / arrest threats (digital-arrest, fake-police scams).
      "pay or i will", "or i will post", "you will be arrested",
      "you will go to jail", "we will file a case",
    ],
    mutuallyExclusiveWith: [],
    scoreable: true,
  },
  calming_reassurance: {
    label: "Calming Reassurance",
    cuePhrases: [
      "no rush", "take your time", "there's no pressure", "whenever you can",
      "it's okay", "don't worry", "no hurry",
    ],
    mutuallyExclusiveWith: [],
    scoreable: false,
  },
};

// ---- Scoring constants (identical to the Python reference) -------------

const PER_CUE_BASE = 0.22;
const TIER0_ESCALATION_THRESHOLD = 0.28;
const TIER1_ESCALATION_THRESHOLD = 0.55;
const ENTAILMENT_CONFIDENCE_CEILING = 0.35;
const NEGATION_PENALTY = 0.15;
const HYPOTHETICAL_PENALTY = 0.55;

interface Candidate {
  tacticId: string;
  matchedSpans: string[];
  baseScore: number;
  context: string;
}

export interface OnDeviceFlag {
  tacticId: string;
  label: string;
  confidence: number;
  matchedSpans: string[];
  /**
   * Grounded, plain-language reasoning from the Tier-1 model for THIS tactic,
   * when a native runtime scored it (undefined on the pure-heuristic path).
   * Carried end-to-end so the UI can show the model's reasoning instead of
   * discarding it. Never used to introduce a tactic Tier 0 didn't surface.
   */
  rationale?: string;
}

export interface OnDeviceScore {
  tierReached: 0 | 1 | 2;
  flags: OnDeviceFlag[];
  anySurfaced: boolean;
}

// ---- Tier 0: cue scan --------------------------------------------------

function normalize(text: string): string {
  return text.toLowerCase().replace(/\s+/g, " ").trim();
}

function tier0Scan(text: string): Candidate[] {
  const lowered = normalize(text);
  const out: Candidate[] = [];
  for (const [tacticId, spec] of Object.entries(TACTICS)) {
    const spans: string[] = [];
    for (const cue of spec.cuePhrases) {
      if (lowered.includes(cue)) { spans.push(cue); }
    }
    if (spans.length > 0) {
      // base score grows with distinct cue hits, capped -- mirrors the
      // Python per-cue accumulation.
      const score = Math.min(1.0, PER_CUE_BASE * spans.length);
      out.push({ tacticId, matchedSpans: spans, baseScore: score, context: lowered });
    }
  }
  return out;
}

/**
 * The scoreable Tier-0 candidate tactics for a text, AFTER the escalation
 * gate (same diversity-weighted threshold runOnDeviceCascade uses). Returns
 * [] for the high-volume benign path (below escalation), so a caller can
 * cheaply decide whether it is even worth invoking a heavier Tier-1/2 model
 * -- Tier 2 must never be the default path (spec 3.1). This is the pre-gate
 * candidate set a native Llama refinement pass scores, so the model only
 * ever re-weights tactics the rule engine already surfaced (it can never
 * introduce a new one -- the heuristic stays a floor).
 */
export interface Tier0Candidate {
  tacticId: string;
  matchedSpans: string[];
}

export function tier0Candidates(text: string): Tier0Candidate[] {
  const all = tier0Scan(text);
  const scoreable = all.filter((c) => TACTICS[c.tacticId]?.scoreable);
  const distinctTactics = new Set(scoreable.map((c) => c.tacticId)).size;
  const totalHits = scoreable.reduce((n, c) => n + c.matchedSpans.length, 0);
  const tier0Score = Math.min(1.0, 0.18 * distinctTactics + 0.05 * totalHits);
  if (tier0Score < TIER0_ESCALATION_THRESHOLD || scoreable.length === 0) {
    return [];
  }
  return scoreable.map((c) => ({ tacticId: c.tacticId, matchedSpans: c.matchedSpans }));
}

// ---- Grounding checks (ported from nli_entailment_gate.py) -------------

function hasNegation(context: string, spans: string[]): boolean {
  // Proximity-scoped to match Python _has_negation: a negation cue counts
  // only within a 6-word window BEFORE a matched span, so unrelated
  // negation elsewhere in the sentence doesn't suppress a genuine flag.
  const negations = ["never", "not going to", "won't", "wouldn't", "did not", "didn't", "refuse to"];
  const words = context.split(/\s+/);
  for (const span of spans) {
    const first = span.split(/\s+/)[0] ?? "";
    const stem = first.slice(0, 4);
    if (!stem) { continue; }
    for (let i = 0; i < words.length; i++) {
      if (words[i].startsWith(stem)) {
        const window = words.slice(Math.max(0, i - 6), i).join(" ");
        if (negations.some((n) => window.includes(n))) { return true; }
      }
    }
  }
  return false;
}

function isHypothetical(context: string): boolean {
  // Matches Python _is_hypothetical: interrogative or explicit hypothetical
  // framing means the text is ABOUT a tactic, not an instance of it.
  const s = context.trim();
  return s.endsWith("?") || /^(what if|suppose|imagine if)/.test(s);
}

// ---- Information-weighted span specificity -----------------------------
//
// Ported verbatim from grounding/nli_entailment_gate.py. The old version
// scored a matched cue by TOKEN COUNT (words/3), which mislabels the
// strongest scam evidence as "fragmentary": the best indicators of whole
// scam families are one- or two-word terms of art ("OTP", "AnyDesk",
// "Bitcoin", "gift card"), so they scored ~0.33 and were dropped below the
// ENTAILMENT_CONFIDENCE_CEILING even when Tier 0 matched them cleanly. Weight
// a span by its evidentiary INFORMATION, not its length.
//
//   HIGH_INFORMATION_CUES -- short but near-unambiguous terms of art; a FLOOR
//     on specificity (never lowers a longer strong phrase). Safe: specificity
//     is a multiplier <=1 and a lone Tier 0 cue only carries base ~0.22, so a
//     short cue still surfaces only once corroborated (the scam signature).
//   LOW_INFORMATION_CUES -- dual-use phrases that also appear in benign
//     messages; CAPPED, so a genuine bank notification abstains while the
//     same phrases still corroborate a real solicitation. This is what lets
//     the authority-impersonation taxonomy expand WITHOUT new false positives.

const HIGH_INFO_WEIGHT = 0.9;
const LOW_INFO_WEIGHT = 0.25;

const HIGH_INFORMATION_CUES: string[] = [
  // One-time-code / OTP solicitation
  "otp", "verification code", "one-time code", "one time code",
  "6-digit code", "six-digit code", "6 digit code",
  "read me the code", "share the code", "tell me the code", "send the code",
  // Remote-access tooling (brand names are terms of art)
  "anydesk", "teamviewer", "remote access", "remote support",
  // Irreversible payment rails
  "gift card", "buy a gift card", "wire transfer", "wire money",
  "wire the money", "western union", "money order",
  // Crypto rails
  "bitcoin", "crypto", "usdt", "crypto wallet",
  // Explicit authority-impersonation openers (strong, not dual-use)
  "this is the irs", "this is your bank", "this is your ceo",
  "federal agent", "law enforcement", "this is the police",
  "arrest warrant", "digital arrest",
  // UPI PIN is only ever entered to SEND money -- an unambiguous receive-scam
  // signal, unlike the dual-use app/brand names.
  "upi pin", "enter your upi pin",
  // Sextortion / coercion terms of art.
  "leak your photos", "leak your video", "expose you", "intimate photos",
  "i have your videos", "send nudes", "pay or i will",
];

const LOW_INFORMATION_CUES = new Set<string>([
  "your bank account", "account locked", "account has been locked",
  "account suspended", "account has been suspended", "security alert",
  "verify your identity", "confirm your identity", "fraud department",
  "unusual activity", "suspicious activity",
  // Delivery / customs / KYC impersonation (real couriers and banks say these)
  "your parcel", "your package", "parcel is held", "package is held",
  "kyc", "update your kyc", "kyc verification", "kyc expired",
  "customs department", "income tax department",
  // UPI / QR rails used in benign payments too -- capped, need corroboration
  "upi", "upi id", "google pay", "phonepe", "paytm", "gpay",
  "collect request", "scan the qr", "scan this qr", "scan to pay", "qr code",
  // Advance-fee framing and job/investment bait -- dual-use, need corroboration
  "registration fee", "processing fee", "advance fee", "security deposit",
  "work from home", "part-time job", "part time job", "earn daily",
  "daily income", "no experience needed", "guaranteed job",
  "high returns", "investment opportunity", "trading tips",
]);

function informationWeight(span: string): number {
  const s = span.toLowerCase().trim();
  if (!s) { return 0.0; }
  if (LOW_INFORMATION_CUES.has(s)) { return LOW_INFO_WEIGHT; }
  const wordBased = Math.min(1.0, s.split(/\s+/).length / 3.0);
  const high = HIGH_INFORMATION_CUES.some((cue) => s.includes(cue)) ? HIGH_INFO_WEIGHT : 0.0;
  return Math.min(1.0, Math.max(wordBased, high));
}

function specificity(spans: string[]): number {
  // Specificity = the information weight of the STRONGEST single matched cue.
  // A candidate is only as grounded as its best piece of evidence; that best
  // piece is a discriminative term of art when present, a capped dual-use
  // phrase otherwise. Corroboration across tactics is added separately.
  if (spans.length === 0) { return 0.0; }
  return Math.min(1.0, Math.max(...spans.map(informationWeight)));
}

function gateConfidence(c: Candidate): number {
  const spec = specificity(c.matchedSpans);
  const hyp = isHypothetical(c.context) ? HYPOTHETICAL_PENALTY : 1.0;
  const neg = hasNegation(c.context, c.matchedSpans) ? NEGATION_PENALTY : 1.0;
  return Math.min(1.0, c.baseScore * spec * hyp * neg);
}

// ---- Compound boosting + mutual exclusivity ----------------------------

function applyCompoundBoost(cands: Candidate[]): Candidate[] {
  const intraTurnCompounding = cands.filter((c) => TACTICS[c.tacticId]?.scoreable).length >= 2;
  return cands.map((c) => {
    let boost = 0;
    if (c.tacticId === "payment_channel_funneling" && intraTurnCompounding) { boost += 0.2; }
    else if (intraTurnCompounding) { boost += 0.1; }
    return { ...c, baseScore: Math.min(1.0, c.baseScore + boost) };
  });
}

function applyMutualExclusivity(cands: Candidate[], all: Candidate[]): Candidate[] {
  const byTactic = new Map(all.map((c) => [c.tacticId, c.baseScore]));
  return cands.filter((c) => {
    const spec = TACTICS[c.tacticId];
    if (!spec) { return false; }
    for (const other of spec.mutuallyExclusiveWith) {
      if ((byTactic.get(other) ?? 0) >= c.baseScore * 0.7) { return false; }
    }
    return true;
  });
}

// ---- Public: the real on-device cascade --------------------------------

/**
 * Optional native model blend. `nativeConfidences` maps tacticId -> model
 * confidence from a registered llama.cpp runtime; when provided it blends
 * 50/50 with the heuristic exactly as the Python cascade does. When
 * undefined (no native runtime linked), Tier 0 stands alone.
 */
export function runOnDeviceCascade(
  text: string,
  nativeConfidences?: Record<string, number>,
  nativeRationales?: Record<string, string>,
): OnDeviceScore {
  const allCands = tier0Scan(text);
  const scoreable = allCands.filter((c) => TACTICS[c.tacticId]?.scoreable);

  // Escalation score matches the Python reference EXACTLY:
  //   0.18 * distinct_scoreable_tactics + 0.05 * total_cue_hits
  // (diversity-weighted, so one phrase repeated doesn't outweigh several
  // distinct weak signals compounding). NOT the per-candidate base score.
  const distinctTactics = new Set(scoreable.map((c) => c.tacticId)).size;
  const totalHits = scoreable.reduce((n, c) => n + c.matchedSpans.length, 0);
  const tier0Score = Math.min(1.0, 0.18 * distinctTactics + 0.05 * totalHits);

  if (tier0Score < TIER0_ESCALATION_THRESHOLD || scoreable.length === 0) {
    return { tierReached: 0, flags: [], anySurfaced: false };
  }

  let refined = applyCompoundBoost(scoreable);
  refined = applyMutualExclusivity(refined, allCands);

  // Blend native model confidence if a runtime provided it. The per-message
  // default blend uses the Tier-1 (1B) model, so a model-blended result is
  // Tier 1 -- Tier 2 (the 3B speculative-decoding escalation) is never the
  // default path (spec 3.1). When NO native runtime contributed (the pure-TS
  // default scorer, or a model pass that returned nothing usable), this is an
  // honest Tier-0 heuristic result and must be labelled as such -- reporting
  // "Tier 1" for a result no model ever touched would mis-cite the evidence
  // provenance the UI shows (spec 2.5).
  const tierReached: 0 | 1 | 2 = nativeConfidences ? 1 : 0;
  if (nativeConfidences) {
    refined = refined.map((c) => {
      const nc = nativeConfidences[c.tacticId];
      if (typeof nc === "number") {
        return { ...c, baseScore: Math.min(1.0, 0.5 * c.baseScore + 0.5 * nc) };
      }
      return c;
    });
  }

  // Grounding gate: only candidates whose confidence clears the ceiling
  // surface. Below-ceiling = dropped as ungrounded (never a safety verdict).
  //
  // Compound corroboration (spec 2.2/2.5): multiple independent tactics
  // co-occurring in one turn is itself evidence -- mirrors the Python
  // gate_candidates boost so on-device and backend verdicts agree. Bounded,
  // deterministic, derived only from other real matched spans; a lone weak
  // flag still fails closed.
  const distinctForCorroboration = new Set(refined.map((c) => c.tacticId)).size;
  const corroboration = Math.min(0.3, 0.15 * Math.max(0, distinctForCorroboration - 1));

  const flags: OnDeviceFlag[] = [];
  for (const c of refined) {
    let conf = gateConfidence(c);
    if (corroboration > 0 && conf < ENTAILMENT_CONFIDENCE_CEILING) {
      conf = Math.min(1.0, conf + corroboration);
    }
    if (conf >= ENTAILMENT_CONFIDENCE_CEILING) {
      const rationale = nativeRationales?.[c.tacticId];
      flags.push({
        tacticId: c.tacticId,
        label: TACTICS[c.tacticId].label,
        confidence: Number(conf.toFixed(4)),
        matchedSpans: c.matchedSpans,
        ...(typeof rationale === "string" && rationale.length > 0
          ? { rationale }
          : {}),
      });
    }
  }

  return { tierReached, flags, anySurfaced: flags.length > 0 };
}
