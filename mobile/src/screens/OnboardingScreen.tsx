/**
 * OnboardingScreen -- progressive onboarding, not a permission wall.
 *
 * Spec ref: PDF Section 6: "the app is useful immediately in a degraded
 * mode ... AccessibilityService, microphone, and ReplayKit permissions
 * are requested contextually, at the moment their specific protection is
 * about to matter (e.g. the AccessibilityService prompt appears when the
 * user first opens a banking app through TrustTrace's onboarding flow,
 * not on first launch)."
 *
 * Structural enforcement: this screen requests ZERO permissions. Its only
 * job is (a) letting the person start using the zero-permission paste
 * check immediately, and (b) letting them *declare* which protections
 * they care about, so the matching ConsentPrompt fires later at the
 * contextual moment -- the declaration itself grants nothing.
 *
 * REAL vs SIM: real, type-checked TSX (tsc --strict); not device-executed
 * here.
 */
import React, { useState } from "react";
import { View, Text, Pressable, ScrollView, StyleSheet } from "react-native";

export type ProtectionInterest =
  | "payment_screen_watch"     // -> AccessibilityService prompt at first banking-app open
  | "call_voice_check"         // -> microphone prompt at first opted-in call
  | "screen_session_check";    // -> ReplayKit prompt at first "watch my screen" tap

export interface OnboardingScreenProps {
  /** Persist declared interests; NO permission is requested here. */
  onDone: (interests: ProtectionInterest[]) => void;
  onTryPasteCheckNow: () => void;
}

const OPTIONS: { key: ProtectionInterest; label: string; detail: string }[] = [
  {
    key: "payment_screen_watch",
    label: "Warn me before risky payments",
    detail: "You'll be asked for screen-watch permission the first time you open a banking app -- not now.",
  },
  {
    key: "call_voice_check",
    label: "Check calls for AI-cloned voices",
    detail: "You'll be asked for microphone access the first time you turn it on during a call -- not now.",
  },
  {
    key: "screen_session_check",
    label: "Watch my screen when I ask",
    detail: "A 5-minute, you-initiated session. You'll be asked at that moment -- not now.",
  },
];

export function OnboardingScreen(props: OnboardingScreenProps): React.ReactElement {
  const [selected, setSelected] = useState<ProtectionInterest[]>([]);

  const toggle = (k: ProtectionInterest): void => {
    setSelected((prev) => (prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]));
  };

  return (
    <ScrollView contentContainerStyle={styles.wrap}>
      <Text style={styles.h1}>TrustTrace works right away</Text>
      <Text style={styles.sub}>
        You can check a suspicious conversation immediately -- no
        permissions needed. Pick anything else you{"\u2019"}d like it to
        help with; you{"\u2019"}ll only be asked for access at the moment
        it actually matters.
      </Text>

      <Pressable accessibilityRole="button" onPress={props.onTryPasteCheckNow} style={styles.primary}>
        <Text style={styles.primaryText}>Check a conversation now</Text>
      </Pressable>

      {OPTIONS.map((opt) => {
        const on = selected.includes(opt.key);
        return (
          <Pressable
            key={opt.key}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: on }}
            onPress={() => toggle(opt.key)}
            style={[styles.option, on ? styles.optionOn : null]}
          >
            <Text style={styles.optionLabel}>{on ? "\u2713 " : ""}{opt.label}</Text>
            <Text style={styles.optionDetail}>{opt.detail}</Text>
          </Pressable>
        );
      })}

      <Pressable accessibilityRole="button" onPress={() => props.onDone(selected)} style={styles.done}>
        <Text style={styles.doneText}>Done</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  wrap: { padding: 20 },
  h1: { fontSize: 24, fontWeight: "700", color: "#0F172A", marginBottom: 6 },
  sub: { fontSize: 15, color: "#475569", marginBottom: 16 },
  primary: { backgroundColor: "#0369A1", borderRadius: 10, paddingVertical: 14, alignItems: "center", marginBottom: 20 },
  primaryText: { color: "#FFFFFF", fontSize: 17, fontWeight: "600" },
  option: { borderWidth: 1, borderColor: "#CBD5E1", borderRadius: 12, padding: 14, marginBottom: 10 },
  optionOn: { borderColor: "#0369A1", backgroundColor: "#F0F9FF" },
  optionLabel: { fontSize: 16, fontWeight: "600", color: "#0F172A", marginBottom: 4 },
  optionDetail: { fontSize: 13, color: "#64748B" },
  done: { marginTop: 8, alignItems: "center", paddingVertical: 12 },
  doneText: { color: "#0369A1", fontSize: 16, fontWeight: "600" },
});
