/**
 * On-device "explain more" -- REAL, network-free explanation generator.
 *
 * Spec ref: PDF Section 5 (on-device-first; any cloud call is opt-in and
 * must degrade gracefully) and 2.5 (every flag cites its exact tactic +
 * evidence). The cloud /v1/explain-more path is an ENHANCEMENT, not a
 * dependency: the app already computed the tactics, matched spans, and
 * confidences locally (onDeviceCascade.ts), so a genuinely useful,
 * plain-language explanation can always be produced on the phone with zero
 * network. This is what "Explain more" falls back to when the backend is
 * unreachable (e.g. the phone is on mobile data, not the dev LAN), so the
 * user never sees a raw "Network request failed" and never loses the
 * explanation entirely.
 *
 * The copy here is deliberately plain-language and action-oriented (spec 6's
 * accessibility posture): name the manipulation, quote the evidence we found,
 * and give one concrete safe next step.
 */
import { runOnDeviceCascade } from "./onDeviceCascade";
import { PasteCheckResult } from "../screens/PasteCheckScreen";

// One plain-language line per tactic: what the pattern IS and why it is used
// against a target. Keyed by the same tactic ids as tactic_taxonomy.py.
const TACTIC_EXPLANATIONS: Record<string, string> = {
  urgency_injection:
    "manufactures time pressure so you act before you can stop and check.",
  isolation_instruction:
    "tells you to keep this secret or not involve your bank or family -- cutting off the people who could warn you.",
  authority_impersonation:
    "claims to be a bank, government agency, or well-known company to make the demand feel official and hard to refuse.",
  remote_access_solicitation:
    "asks for a one-time code (OTP) or remote-access software -- handing that over gives a stranger control of your account or device.",
  payment_channel_funneling:
    "pushes you toward gift cards, wire transfers, or crypto -- payment methods that are almost impossible to reverse or trace once sent.",
  too_good_to_be_true:
    "dangles a guaranteed return, prize, job, or fast-moving romance that is implausibly good.",
  coercion_threat:
    "threatens to arrest you, leak private photos, or otherwise harm you unless you pay or comply -- fear used as leverage.",
};

// A single closing safety tip, chosen by the strongest tactic present so the
// advice is specific to what we actually saw.
const TACTIC_SAFETY_TIP: Record<string, string> = {
  remote_access_solicitation:
    "A real bank or company will NEVER ask you to read back a one-time code or install remote-access software. Do not share the code.",
  payment_channel_funneling:
    "No legitimate business is paid only in gift cards, wire transfers, or crypto. Being told to pay that way is itself the warning sign.",
  authority_impersonation:
    "Don't trust the contact details in this message. Reach the company using a number from their official website or the back of your card.",
  isolation_instruction:
    "Anyone telling you to hide a payment from your bank or family is protecting the scam, not you. Talk to someone you trust first.",
  urgency_injection:
    "Slow down -- urgency is the tool. A real request will still be valid after you take time to verify it independently.",
  too_good_to_be_true:
    "If it sounds too good to be true, it is. Guaranteed returns, surprise winnings, and pay-a-fee-to-earn jobs are classic bait.",
  coercion_threat:
    "Real police never demand payment over a call or text, and paying a blackmailer invites more demands. Do not pay. Save the evidence and contact your local police or a trusted person.",
};

const DEFAULT_SAFETY_TIP =
  "If money or account access is involved, stop and verify with the person or company through a channel you already trust -- not one from this message.";

function quoteSpans(spans: string[]): string {
  // De-duplicate while preserving order, then quote each matched cue.
  const seen = new Set<string>();
  const unique = spans.filter((s) => (seen.has(s) ? false : (seen.add(s), true)));
  return unique.map((s) => `“${s}”`).join(", ");
}

/**
 * Build a plain-language explanation for a transcript, entirely on-device.
 * Re-runs the (microsecond) Tier-0 cascade so it needs nothing but the text.
 *
 * When a prior model-blended `result` is passed (the flag the user is asking
 * about), its per-tactic model rationale is REUSED for the "why" line rather
 * than recomputing a generic heuristic sentence -- so the richer on-device
 * model reasoning, if it exists, is what the user sees. Without a result (or
 * on the pure-heuristic path) it falls back to the taxonomy explanations
 * exactly as before, keeping the single-argument callers unchanged.
 */
export function buildOnDeviceExplanation(text: string, result?: PasteCheckResult): string {
  const score = runOnDeviceCascade(text);

  // Correlate any model rationale from the result with each tactic id.
  const rationaleByTactic = new Map<string, string>();
  if (result !== undefined && result.kind === "flag") {
    for (const ev of result.evidence) {
      if (
        typeof ev.tacticId === "string" &&
        typeof ev.modelRationale === "string" &&
        ev.modelRationale.length > 0
      ) {
        rationaleByTactic.set(ev.tacticId, ev.modelRationale);
      }
    }
  }

  if (!score.anySurfaced || score.flags.length === 0) {
    // Defensive: "Explain more" is only offered after a flag surfaces, but
    // never fabricate a verdict if somehow called with none.
    return (
      "We didn't find a strong manipulation pattern in this message on your " +
      "phone. That is not a guarantee it is safe. " +
      DEFAULT_SAFETY_TIP
    );
  }

  // Strongest first, so the most important pattern leads.
  const flags = [...score.flags].sort((a, b) => b.confidence - a.confidence);

  const intro =
    flags.length === 1
      ? "This message shows a pattern commonly used in scams:"
      : `This message shows ${flags.length} patterns commonly used in scams:`;

  const bullets = flags.map((f) => {
    // Prefer the model's grounded rationale when we have it; otherwise the
    // deterministic taxonomy explanation.
    const why =
      rationaleByTactic.get(f.tacticId) ??
      TACTIC_EXPLANATIONS[f.tacticId] ??
      "matches a known manipulation tactic.";
    const evidence = f.matchedSpans.length > 0 ? ` We saw: ${quoteSpans(f.matchedSpans)}.` : "";
    return `• ${f.label} -- ${why}${evidence}`;
  });

  const tip = TACTIC_SAFETY_TIP[flags[0].tacticId] ?? DEFAULT_SAFETY_TIP;

  return `${intro}\n\n${bullets.join("\n\n")}\n\nWhat to do: ${tip}`;
}
