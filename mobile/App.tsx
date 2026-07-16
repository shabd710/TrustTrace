/**
 * TrustTrace mobile app root.
 *
 * Spec ref: PDF Section 5 (on-device-first; opt-in cloud "explain more"),
 * Section 6 (progressive onboarding), Section 2.1/2.4/2.3 (paste check,
 * owner-initiated device scan, transaction warning).
 *
 * This root is now REAL integration, not a demo shell:
 *  - Transcript scoring runs on-device first (mobile/src/ml/scoring.ts),
 *    falling back to the FastAPI backend (/v1/analyze-transcript) only when
 *    no native runtime is linked on this build. See scoring.ts for the
 *    honest privacy boundary on that fallback.
 *  - "Explain more" is the opt-in cloud path (spec 5): it calls the backend
 *    /v1/explain-more ONLY when the user taps it, per use, never
 *    automatically.
 *  - Navigation is a real @react-navigation native stack over all four
 *    screens (see mobile/src/navigation/RootNavigator.tsx).
 *
 * The one honest gap that remains, documented not hidden: the REAL
 * on-device cascade needs a native llama.cpp/MLC/MLX/MediaPipe binding
 * linked in a bare-workflow build (see modelLoader.ts). Until that module
 * registers itself, scoring uses the working backend fallback rather than
 * pretending to score locally.
 */
import React, { useCallback, useEffect, useMemo, useRef } from "react";
import { Alert, Linking } from "react-native";

import { RootNavigator } from "./src/navigation/RootNavigator";
import { scoreTranscript as scoreTranscriptBridge } from "./src/ml/scoring";
import { ensureOnDeviceScorer } from "./src/ml/defaultScorer";
import { kickoffNativeLlama } from "./src/ml/nativeLlamaBootstrap";
import { buildOnDeviceExplanation } from "./src/ml/onDeviceExplainer";
import { runOwnDeviceScan as runOwnDeviceScanBridge } from "./src/ml/deviceScanBridge";
import { api } from "./src/api/client";
import { CLOUD_EXPLAIN_ENABLED } from "./src/config/env";
import { PasteCheckResult } from "./src/screens/PasteCheckScreen";
import { DeviceScanFinding } from "./src/screens/DeviceScanScreen";
import { WarningState } from "./src/state/warningStore";
import { debugLog } from "./src/utils/logger";

/** Coalition Against Stalkerware resources (spec 2.4). */
const STALKERWARE_RESOURCES_URL = "https://stopstalkerware.org/";

function newSessionId(): string {
  // Ephemeral per-app-run id; not tied to any account (spec 5: no
  // individual report leaves the device except by explicit user action).
  return `sess_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export default function App(): React.ReactElement {
  const sessionIdRef = useRef<string>(newSessionId());

  // Startup side effects belong in an effect, not the render body, so they run
  // once after mount (and not on a discarded render under concurrent mode).
  useEffect(() => {
    // Install the always-available on-device Tier-0 cascade as the default
    // scorer so the private path is live immediately.
    ensureOnDeviceScorer();
    // If this build linked the native Llama runtime, bring it up
    // asynchronously; once its GGUF weights are resident it supersedes the
    // default scorer with the real Tier-1 model-blended path. No-op on
    // JS-only builds. Either way the backend stays a true fallback. (spec 5)
    kickoffNativeLlama();
  }, []);

  // --- Transcript scoring: on-device first, backend fallback ---
  const scoreTranscript = useCallback(
    async (text: string): Promise<PasteCheckResult> => {
      const outcome = await scoreTranscriptBridge(text, {
        api,
        sessionId: sessionIdRef.current,
        sender: "pasted",
      });

      // Dev-only: never log transcript content (privacy, spec 5).
      debugLog("scoreTranscript finished; usedFallback =", outcome.usedFallback);

      return outcome.result;
    },
    [],
  );

 // --- Explain more: opt-in cloud enhancement, with on-device fallback ---
// The tactics, evidence, and confidences were already computed on-device,
// so a useful explanation never REQUIRES the network (spec 5). Tapping
// "Explain more" opts into a richer cloud explanation, but if the backend
// is unreachable (e.g. the phone is on mobile data, not the dev LAN) we
// fall back to an on-device explanation instead of surfacing a raw network
// error -- the user always gets an answer, and it never leaves the phone on
// the fallback path.
const onExplainMoreRequested = useCallback((text: string, result?: PasteCheckResult) => {
  // Reuse the model's rationale from the on-device result when present, rather
  // than recomputing a generic heuristic explanation.
  const onDeviceExplanation = buildOnDeviceExplanation(text, result);

  if (!CLOUD_EXPLAIN_ENABLED) {
    // Cloud disabled by policy: the on-device explanation is the answer,
    // not a dead-end apology.
    Alert.alert("Why this was flagged", onDeviceExplanation);
    return;
  }

  // Fire-and-forward: the screen's contract is a void callback, so we
  // present the explanation via an Alert.
  void api
    .explainMore({
      sessionId: sessionIdRef.current,
      transcriptExcerpt: text.slice(0, 4000),
    })
    .then(
      (res) => {
        Alert.alert("Why this was flagged", res.explanation);
      },
      () => {
        // Backend unreachable/errored -- degrade gracefully to the
        // on-device explanation rather than showing a technical error.
        Alert.alert(
          "Why this was flagged",
          onDeviceExplanation +
            "\n\n(We couldn't reach the online service for extra detail, so " +
            "this explanation was generated on your phone.)",
        );
      },
    );
}, []);
  // --- Owner-initiated device scan (spec 2.4) ---
  const runOwnDeviceScan = useCallback(async (): Promise<DeviceScanFinding[]> => {
    // Runs the real on-device scanner bridge. When a native scanner module
    // is linked it returns confirmed, evidence-carrying findings; when it
    // is NOT linked the bridge THROWS DeviceScanUnavailableError, and the
    // screen surfaces an honest "couldn't check" state -- never an empty
    // array that would falsely imply a clean device (spec 2.4/2.5).
    return runOwnDeviceScanBridge();
  }, []);

  const onDiscreetExit = useCallback(() => {
    void Linking.openURL("https://www.weather.com/").catch(() => {
      /* discreet exit is best-effort; never surfaces an error banner */
    });
  }, []);

  const onWarningAction = useCallback(
    (eventId: string, action: WarningState["availableActions"][number]) => {
      // No cancel/block path exists by design (spec: no autonomous action).
      // Both actions simply dismiss the warning; the transaction itself is
      // never touched by TrustTrace.
      void eventId;
      void action;
    },
    [],
  );

  const navProps = useMemo(
    () => ({
      scoreTranscript,
      onExplainMoreRequested,
      runOwnDeviceScan,
      onDiscreetExit,
      resourcesUrl: STALKERWARE_RESOURCES_URL,
      onWarningAction,
    }),
    [
      scoreTranscript,
      onExplainMoreRequested,
      runOwnDeviceScan,
      onDiscreetExit,
      onWarningAction,
    ],
  );

  return <RootNavigator {...navProps} />;
}
