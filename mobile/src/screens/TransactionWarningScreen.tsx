/**
 * TransactionWarningScreen -- the intervention overlay content.
 *
 * Spec ref: PDF Section 2.3: "an overlay warning appears -- what was
 * flagged, why, and an explicit 'I understand, continue anyway' tap
 * required to proceed. ... Hard rule: this module produces a warning
 * screen ONLY. No code path can cancel, delay, or reverse a transaction."
 * Section 10.3: warning state keyed per triggering event (warningStore.ts).
 *
 * Platform-security notes that live in the NATIVE layer, not here (stated
 * so nobody re-implements them in JS where they can't work):
 *   - FLAG_SECURE on the Android overlay window (spec 7.4, hard req).
 *   - Elevated window layer vs tapjacking overlays (spec 8.3).
 *   - setFilterTouchesWhenObscured(true) on the native view hosting the
 *     override button (spec 10.2 -- the precise API for tapjacking).
 * See native-modules/android/TrustTraceAccessibilityService.kt.
 *
 * Structural rule enforced here: the ONLY actions this screen can emit
 * are `i_understand_continue_anyway` and `go_back` -- the WarningState
 * type in state/warningStore.ts has no third option, and neither does
 * this component. There is no cancel/block/report-to-bank path to wire
 * up even by accident.
 *
 * REAL vs SIM: real, type-checked TSX (tsc --strict); not device-executed
 * here.
 */
import React from "react";
import { View, Text, Pressable, ScrollView, StyleSheet } from "react-native";
import { WarningState } from "../state/warningStore";
import { EvidenceCitation, CitedEvidence } from "../components/EvidenceCitation";

export interface TransactionWarningScreenProps {
  warning: WarningState;
  /** Evidence resolved for this warning's eventId -- non-empty by contract. */
  evidence: [CitedEvidence, ...CitedEvidence[]];
  onAction: (eventId: string, action: WarningState["availableActions"][number]) => void;
}

export function TransactionWarningScreen(props: TransactionWarningScreenProps): React.ReactElement {
  const { warning } = props;
  return (
    <ScrollView contentContainerStyle={styles.wrap}>
      <Text style={styles.h1}>{warning.headline}</Text>
      <Text style={styles.sub}>
        TrustTrace does not block or cancel anything. This is a pause to
        show you what it noticed, and the choice stays yours.
      </Text>

      <EvidenceCitation findingLabel="What was noticed, and the exact evidence" evidence={props.evidence} />

      <Pressable
        accessibilityRole="button"
        onPress={() => props.onAction(warning.eventId, "go_back")}
        style={[styles.btn, styles.goBack]}
      >
        <Text style={styles.goBackText}>Go back and verify first</Text>
      </Pressable>

      {/* Explicit, deliberate override -- required by spec 2.3. The native
          view hosting this rejects obscured touches (spec 10.2). */}
      <Pressable
        accessibilityRole="button"
        onPress={() => props.onAction(warning.eventId, "i_understand_continue_anyway")}
        style={[styles.btn, styles.override]}
      >
        <Text style={styles.overrideText}>I understand, continue anyway</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  wrap: { padding: 20 },
  h1: { fontSize: 24, fontWeight: "800", color: "#7C2D12", marginBottom: 8 },
  sub: { fontSize: 16, color: "#334155", marginBottom: 12 },
  btn: { borderRadius: 12, paddingVertical: 16, alignItems: "center", marginTop: 10 },
  goBack: { backgroundColor: "#0369A1" },
  goBackText: { color: "#FFFFFF", fontSize: 18, fontWeight: "700" },
  override: { backgroundColor: "#F1F5F9", borderWidth: 1, borderColor: "#CBD5E1" },
  overrideText: { color: "#334155", fontSize: 16, fontWeight: "600" },
});
