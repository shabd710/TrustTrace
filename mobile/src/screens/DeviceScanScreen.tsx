/**
 * DeviceScanScreen -- owner-initiated stalkerware/spyware scan flow.
 *
 * Spec ref: PDF Section 2.4: "Strictly consent-gated: scans only the
 * device the app is installed on, only on the owner's initiation. ...
 * Domestic-violence-context results use a discreet exit and a link to
 * support resources rather than an alarming pop-up. Nothing is
 * auto-shared, auto-deleted, or auto-flagged to anyone."
 *
 * Structural rules enforced here:
 *   - The scan runs only from an explicit in-screen tap (owner
 *     initiation); there is no auto-start path.
 *   - Results carry NO share/delete/report actions -- findings are shown
 *     with their exact evidence (permission names, signature matches) and
 *     the user decides everything that happens next, off-screen.
 *   - The DiscreetExitBar is pinned on the results view.
 *
 * REAL vs SIM: real, type-checked TSX (tsc --strict). `runOwnDeviceScan`
 * is the seam to detection/device/* (permission_graph, stalkerware
 * signatures with Bloom-prefilter + exact-match confirmation, sideload
 * cert check) via the native bridge.
 */
import React, { useCallback, useState } from "react";
import { View, Text, Pressable, ScrollView, StyleSheet } from "react-native";
import { EvidenceCitation, CitedEvidence } from "../components/EvidenceCitation";
import { AnalysisProgress } from "../components/AnalysisProgress";
import { DiscreetExitBar } from "../components/DiscreetExitBar";

export interface DeviceScanFinding {
  findingLabel: string;   // plain language, e.g. "App with a stalkerware-pattern permission set"
  evidence: [CitedEvidence, ...CitedEvidence[]];   // exact permission names / signature IDs
}

export interface DeviceScanScreenProps {
  runOwnDeviceScan: () => Promise<DeviceScanFinding[]>;
  onDiscreetExit: () => void;
  resourcesUrl: string;   // e.g. Coalition Against Stalkerware resources
}

type ScanPhase = "idle" | "scanning" | "done" | "unavailable";

export function DeviceScanScreen(props: DeviceScanScreenProps): React.ReactElement {
  const [phase, setPhase] = useState<ScanPhase>("idle");
  const [findings, setFindings] = useState<DeviceScanFinding[]>([]);

  const startScan = useCallback(() => {
    if (phase === "scanning") { return; }
    setPhase("scanning");
    void props.runOwnDeviceScan().then(
      (f) => { setFindings(f); setPhase("done"); },
      (err: unknown) => {
        // A rejected scan must NEVER look like a clean device (dangerous
        // false negative in a stalkerware context). Surface an explicit
        // "couldn't check" state instead of silently returning to idle.
        const unavailable =
          err instanceof Error && err.name === "DeviceScanUnavailableError";
        setPhase(unavailable ? "unavailable" : "idle");
      },
    );
  }, [phase, props]);

  return (
    <View style={styles.root}>
      <ScrollView contentContainerStyle={styles.wrap}>
        <Text style={styles.h1}>Check this phone</Text>
        <Text style={styles.sub}>
          This checks only this phone, only when you start it. Nothing is
          shared with anyone, and nothing is changed or deleted.
        </Text>

        {phase === "idle" ? (
          <Pressable accessibilityRole="button" onPress={startScan} style={styles.btn}>
            <Text style={styles.btnText}>Start the check</Text>
          </Pressable>
        ) : null}

        {phase === "scanning" ? <AnalysisProgress stage="local_check" /> : null}

        {phase === "unavailable" ? (
          <View style={styles.neutralCard}>
            <Text style={styles.neutralTitle}>Couldn{"\u2019"}t run the check on this device</Text>
            <Text style={styles.neutralBody}>
              The on-device scanner isn{"\u2019"}t available in this build, so
              no check was performed. This is not a clean result -- nothing
              was scanned. If something feels wrong, the resources link below
              can help.
            </Text>
          </View>
        ) : null}

        {phase === "done" && findings.length === 0 ? (
          <View style={styles.neutralCard}>
            <Text style={styles.neutralTitle}>Nothing matched the known patterns</Text>
            <Text style={styles.neutralBody}>
              No known stalkerware signatures or dangerous permission
              combinations were found. This can{"\u2019"}t rule out
              everything -- if something still feels wrong, the resources
              link below can help.
            </Text>
          </View>
        ) : null}

        {phase === "done"
          ? findings.map((f, i) => (
              <EvidenceCitation key={i} findingLabel={f.findingLabel} evidence={f.evidence} />
            ))
          : null}
      </ScrollView>

      {/* Always available -- spec 2.4's shared-device scenario handling. */}
      <DiscreetExitBar onDiscreetExit={props.onDiscreetExit} resourcesUrl={props.resourcesUrl} />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  wrap: { padding: 20 },
  h1: { fontSize: 24, fontWeight: "700", color: "#0F172A", marginBottom: 6 },
  sub: { fontSize: 15, color: "#475569", marginBottom: 16 },
  btn: { backgroundColor: "#0369A1", borderRadius: 10, paddingVertical: 14, alignItems: "center" },
  btnText: { color: "#FFFFFF", fontSize: 17, fontWeight: "600" },
  neutralCard: { marginTop: 8, padding: 16, borderRadius: 12, backgroundColor: "#F1F5F9" },
  neutralTitle: { fontSize: 17, fontWeight: "700", color: "#0F172A", marginBottom: 6 },
  neutralBody: { fontSize: 15, color: "#334155" },
});
