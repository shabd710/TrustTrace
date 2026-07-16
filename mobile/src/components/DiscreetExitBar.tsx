/**
 * DiscreetExitBar -- instant, unremarkable exit from a sensitive screen.
 *
 * Spec ref: PDF Section 2.4: "Domestic-violence-context results use a
 * discreet exit and a link to support resources rather than an alarming
 * pop-up, since a shared-device scenario means the result screen itself
 * needs careful handling."
 *
 * Design constraints encoded here:
 *   - The exit control is always visible, large, and labeled neutrally
 *     ("Leave this screen"), never "PANIC" or anything that draws a
 *     shoulder-surfer's eye.
 *   - `onDiscreetExit` is expected to navigate to an innocuous screen AND
 *     clear this screen from the navigation back-stack (caller's job --
 *     documented contract, since navigation wiring is app-level).
 *   - The resources link is plain text, not an alarming banner.
 *
 * REAL vs SIM: real, type-checked TSX (tsc --strict); not device-executed
 * here.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet, Linking } from "react-native";

export interface DiscreetExitBarProps {
  /** Must navigate away AND remove this screen from the back-stack. */
  onDiscreetExit: () => void;
  /** Support-resources URL, e.g. Coalition Against Stalkerware. */
  resourcesUrl: string;
}

export function DiscreetExitBar(props: DiscreetExitBarProps): React.ReactElement {
  return (
    <View style={styles.bar}>
      <Pressable
        accessibilityRole="button"
        onPress={props.onDiscreetExit}
        style={styles.exitBtn}
      >
        <Text style={styles.exitText}>Leave this screen</Text>
      </Pressable>
      <Pressable
        accessibilityRole="link"
        onPress={() => { void Linking.openURL(props.resourcesUrl); }}
      >
        <Text style={styles.link}>Support resources</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 12 },
  exitBtn: { paddingVertical: 12, paddingHorizontal: 20, borderRadius: 10, backgroundColor: "#E2E8F0" },
  exitText: { fontSize: 16, fontWeight: "600", color: "#0F172A" },
  link: { fontSize: 14, color: "#0369A1", textDecorationLine: "underline" },
});
