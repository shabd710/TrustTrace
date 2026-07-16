/*
 MessageFilterExtension.swift -- ILMessageFilterExtension for SMS/iMessage
 junk classification.

 Spec ref: PDF Target Environment: "ILMessageFilterExtension for
 SMS/iMessage junk classification." Section 6: message-filter integration
 via telecom shortcode partnerships.

 NOT COMPILED/RUN HERE -- needs a real Message Filter Extension target in
 Xcode, entitlements, and a physical/simulated iOS 14+ device. Written to
 the real ILMessageFilterExtension API surface.

 CRITICAL PLATFORM CONSTRAINT this file's design has to work around,
 stated honestly rather than glossed over: an ILMessageFilterExtension
 runs in an extremely restrictive sandbox -- no network access, and
 Apple's docs are explicit that the extension should return a
 classification in milliseconds. That rules out invoking the real Tier
 1/2 cascade (detection/conversation/model_cascade.py's actual production
 counterpart, a multi-hundred-MB on-device LLM) from inside this
 extension at all. What CAN legitimately run here is a Tier-0-equivalent
 pass only: the same class of sub-10ms heuristic classifier
 detection/conversation/model_cascade.py's Tier 0 already implements
 (lexical cue matching against tactic_taxonomy.py's cue_phrases), compiled
 into this extension as a small embedded resource, not a live call to the
 rest of the cascade. A message this extension marks .none (not junk) can
 still be escalated to the FULL cascade later, inside the host app, once
 the user opens it there -- this extension is a fast, coarse, standalone
 first pass, not the whole detection pipeline running twice.
*/
import IdentityLookup

class MessageFilterExtension: ILMessageFilterExtension {
}

extension MessageFilterExtension: ILMessageFilterQueryHandling {

    func handle(_ queryRequest: ILMessageFilterQueryRequest,
                context: ILMessageFilterExtensionContext,
                completion: @escaping (ILMessageFilterQueryResponse) -> Void) {

        let messageBody = queryRequest.messageBody ?? ""
        let action = classifyTier0Only(messageBody)

        let response = ILMessageFilterQueryResponse()
        response.action = action
        completion(response)
    }

    /// A deliberately minimal, embedded port of
    /// detection/conversation/tactic_taxonomy.py's cue-phrase lists --
    /// NOT the full cascade (see class doc's platform-constraint note).
    /// Real build: this table is generated from tactic_taxonomy.py at
    /// build time (a small codegen step), so the two never drift apart --
    /// not hand-duplicated and maintained separately.
    private func classifyTier0Only(_ text: String) -> ILMessageFilterAction {
        let lowered = text.lowercased()

        // Payment-channel funneling is spec 2.1's single strongest
        // compound signal -- weighted higher here even in this
        // deliberately coarse Tier-0-only pass.
        let highConfidenceJunkCues = [
            "gift card", "wire transfer", "wire money", "only accept",
            "buy a gift card", "send the code", "western union",
        ]
        let moderateJunkCues = [
            "act now", "urgent", "don't tell", "do not tell",
            "guaranteed return", "you've won", "risk-free",
        ]

        if highConfidenceJunkCues.contains(where: { lowered.contains($0) }) {
            return .junk
        }
        if moderateJunkCues.filter({ lowered.contains($0) }).count >= 2 {
            return .junk
        }
        // Below-threshold: explicitly "not enough signal to classify as
        // junk from this extension alone" -- .none defers to the host
        // app's full cascade, NOT a "this is safe" verdict, consistent
        // with spec 2.1/2.5's fail-closed philosophy applied to this
        // extension's necessarily narrower scope.
        return .none
    }
}
