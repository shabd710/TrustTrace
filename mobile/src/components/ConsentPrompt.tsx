/**
 * ConsentPrompt -- contextual, plain-language permission request.
 *
 * Spec ref: PDF Section 6 ("Progressive onboarding, not an upfront
 * permission wall ... permissions are requested contextually, at the
 * moment their specific protection is about to matter"), Target
 * Environment (AccessibilityService "with a plain-language permission
 * explanation before grant"), Section 5 (every cloud call opt-in per use).
 *
 * The component enforces two structural rules:
 *   1. It must state WHAT protection this permission enables RIGHT NOW
 *      (`whyNow` is required) -- no context-free permission walls.
 *   2. Decline is always a first-class, equally-prominent path, and the
 *      caller receives it as an explicit outcome, never a silent drop.
 *
 * REAL vs SIM: real, type-checked TSX (tsc --strict); not device-executed
 * here.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";

export type ConsentPermission =
  | "accessibility_service"
  | "microphone_live_call"
  | "replaykit_screen_session"
  | "cloud_explain_more"
  | "community_report_share";

export interface ConsentPromptProps {
  permission: ConsentPermission;
  /** Plain-language: what protection this enables at THIS moment. */
  whyNow: string;
  /** Plain-language: what is NOT collected/done -- honesty boundary. */
  whatItNeverDoes: string;
  onAllow: () => void;
  onDecline: () => void;
}

const TITLE: Record<ConsentPermission, string> = {
  accessibility_service: "Watch for risky payment screens?",
  microphone_live_call: "Listen for AI-cloned voices on this call?",
  replaykit_screen_session: "Watch your screen for the next 5 minutes?",
  cloud_explain_more: "Send this one conversation for a fuller explanation?",
  community_report_share: "Share an anonymized report to protect others?",
};

export function ConsentPrompt(props: ConsentPromptProps): React.ReactElement {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>{TITLE[props.permission]}</Text>
      <Text style={styles.body}>{props.whyNow}</Text>
      <Text style={styles.never}>{props.whatItNeverDoes}</Text>
      <View style={styles.row}>
        {/* Decline first and equally prominent -- consent-first design. */}
        <Pressable
          accessibilityRole="button"
          onPress={props.onDecline}
          style={[styles.btn, styles.decline]}
        >
          <Text style={styles.declineText}>Not now</Text>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          onPress={props.onAllow}
          style={[styles.btn, styles.allow]}
        >
          <Text style={styles.allowText}>Allow this time</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { padding: 20, borderRadius: 16, backgroundColor: "#F8FAFC" },
  title: { fontSize: 20, fontWeight: "700", color: "#0F172A", marginBottom: 8 },
  body: { fontSize: 16, color: "#334155", marginBottom: 8 },
  never: { fontSize: 14, color: "#64748B", marginBottom: 16 },
  row: { flexDirection: "row", justifyContent: "space-between" },
  btn: { flex: 1, paddingVertical: 14, borderRadius: 10, alignItems: "center" },
  decline: { backgroundColor: "#E2E8F0", marginRight: 8 },
  allow: { backgroundColor: "#0369A1", marginLeft: 8 },
  declineText: { fontSize: 16, fontWeight: "600", color: "#0F172A" },
  allowText: { fontSize: 16, fontWeight: "600", color: "#FFFFFF" },
});
