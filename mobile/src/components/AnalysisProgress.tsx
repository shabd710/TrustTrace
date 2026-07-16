/**
 * AnalysisProgress -- the loading state shown during scoring or the
 * opt-in "explain more" cloud call.
 *
 * Spec ref: PDF Section 9.1 (tactic-mapped skeleton loaders NARROWED) as
 * refined by Section 10.3: show "general, reassuring progress ('reviewing
 * the conversation for common warning signs') WITHOUT naming the specific
 * suspected tactic" -- naming a tactic before the NLI gate (spec 2.5) has
 * confirmed the flag would show the user an ungrounded preliminary
 * verdict, violating the fail-closed discipline.
 *
 * Enforcement is structural: this component accepts NO tactic/verdict
 * prop at all. There is nothing a caller could pass that would leak a
 * pre-gate verdict through this UI.
 *
 * REAL vs SIM: real, type-checked TSX (tsc --strict); not device-executed
 * here.
 */
import React from "react";
import { View, Text, ActivityIndicator, StyleSheet } from "react-native";

export interface AnalysisProgressProps {
  /** Which stage is running -- phrased generically by construction. */
  stage: "local_check" | "cloud_explain_more";
}

const STAGE_TEXT: Record<AnalysisProgressProps["stage"], string> = {
  local_check: "Reviewing the conversation for common warning signs\u2026",
  cloud_explain_more: "Preparing a fuller plain-language explanation\u2026",
};

export function AnalysisProgress(props: AnalysisProgressProps): React.ReactElement {
  return (
    <View style={styles.wrap} accessibilityRole="progressbar">
      <ActivityIndicator size="large" />
      <Text style={styles.text}>{STAGE_TEXT[props.stage]}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: "center", padding: 24 },
  text: { marginTop: 12, fontSize: 16, color: "#334155", textAlign: "center" },
});
