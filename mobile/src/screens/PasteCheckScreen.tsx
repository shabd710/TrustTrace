/**
 * PasteCheckScreen -- the zero-permission entry point.
 *
 * Spec ref: PDF Section 6: "the app is useful immediately in a degraded
 * mode -- pasted-text manipulation checking (Tier 0/1 cascade) requires
 * no special permissions at all." Section 2.1 (paste/share transcript
 * input; below-threshold returns 'no strong manipulation pattern
 * detected' -- explicitly distinct from 'this is safe').
 *
 * REAL vs SIM: real, type-checked TSX (tsc --strict). The `scoreTranscript`
 * prop is the seam to the on-device cascade (mobile/src/ml/modelLoader.ts
 * bindings -> detection/ reference logic); this screen is pure
 * composition, exactly as the spec's layering intends.
 */
import React, { useCallback, useState } from "react";
import { View, Text, TextInput, Pressable, ScrollView, StyleSheet } from "react-native";
import { EvidenceCitation, CitedEvidence } from "../components/EvidenceCitation";
import { AnalysisProgress } from "../components/AnalysisProgress";

/** Result shape mirroring the cascade + NLI-gated grounding contract. */
export type PasteCheckResult =
  | {
      kind: "flag";
      findingLabel: string;                       // plain language, post-NLI-gate only
      evidence: [CitedEvidence, ...CitedEvidence[]];
    }
  | {
      /** Below-threshold: 'not enough signal', NEVER a safety verdict. */
      kind: "no_strong_pattern";
    };

export interface PasteCheckScreenProps {
  scoreTranscript: (text: string) => Promise<PasteCheckResult>;
  // opt-in cloud path, spec 5. The current on-device result is passed so the
  // handler can reuse any model rationale instead of recomputing it.
  onExplainMoreRequested: (text: string, result?: PasteCheckResult) => void;
}

export function PasteCheckScreen(props: PasteCheckScreenProps): React.ReactElement {
  const [text, setText] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const [result, setResult] = useState<PasteCheckResult | null>(null);
  const [failed, setFailed] = useState<boolean>(false);

  const runCheck = useCallback(() => {
    if (text.trim().length === 0 || busy) { return; }
    setBusy(true);
    setResult(null);
    setFailed(false);
    void props.scoreTranscript(text).then(
      (r) => { setResult(r); setBusy(false); },
      () => {
        // A failed check must NEVER look like "nothing found" -- same
        // discipline as DeviceScanScreen's unavailable state. Surface an
        // explicit "couldn't finish" card instead of silent dead air.
        setFailed(true);
        setBusy(false);
      }
    );
  }, [text, busy, props]);

  return (
    <ScrollView contentContainerStyle={styles.wrap}>
      <Text style={styles.h1}>Check a conversation</Text>
      <Text style={styles.sub}>
        Paste a message or conversation. Everything is checked on this
        phone -- nothing is sent anywhere unless you ask for it.
      </Text>
      <TextInput
        multiline
        value={text}
        onChangeText={setText}
        placeholder="Paste the conversation here"
        style={styles.input}
        textAlignVertical="top"
      />
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: text.trim().length === 0 || busy }}
        onPress={runCheck}
        style={[styles.btn, text.trim().length === 0 ? styles.btnDisabled : null]}
      >
        <Text style={styles.btnText}>Check it</Text>
      </Pressable>

      {busy ? <AnalysisProgress stage="local_check" /> : null}

      {failed ? (
        <View style={styles.neutralCard}>
          <Text style={styles.neutralTitle}>Couldn{"’"}t finish the check</Text>
          {/* Not a verdict: a failed check is explicitly distinct from both
              "flagged" and "no strong pattern" (spec 2.1 fail-closed). */}
          <Text style={styles.neutralBody}>
            The check didn{"’"}t complete, so this is not a result.
            Please try again. If money is involved, verify with the person
            or company through a channel you already trust.
          </Text>
        </View>
      ) : null}

      {result !== null && result.kind === "flag" ? (
        <>
          <EvidenceCitation findingLabel={result.findingLabel} evidence={result.evidence} />
          <Pressable
            accessibilityRole="button"
            onPress={() => props.onExplainMoreRequested(text, result)}
            style={styles.secondaryBtn}
          >
            <Text style={styles.secondaryText}>Explain more (sends this one conversation)</Text>
          </Pressable>
        </>
      ) : null}

      {result !== null && result.kind === "no_strong_pattern" ? (
        <View style={styles.neutralCard}>
          <Text style={styles.neutralTitle}>No strong manipulation pattern detected</Text>
          {/* Spec 2.1: explicitly distinct from "this is safe". */}
          <Text style={styles.neutralBody}>
            This means we didn{"\u2019"}t find enough signal -- it is not a
            guarantee the conversation is safe. If money is involved,
            verify with the person through a channel you already trust.
          </Text>
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  wrap: { padding: 20 },
  h1: { fontSize: 24, fontWeight: "700", color: "#0F172A", marginBottom: 6 },
  sub: { fontSize: 15, color: "#475569", marginBottom: 16 },
  input: { minHeight: 140, borderWidth: 1, borderColor: "#CBD5E1", borderRadius: 12, padding: 12, fontSize: 16, marginBottom: 12 },
  btn: { backgroundColor: "#0369A1", borderRadius: 10, paddingVertical: 14, alignItems: "center" },
  btnDisabled: { opacity: 0.4 },
  btnText: { color: "#FFFFFF", fontSize: 17, fontWeight: "600" },
  secondaryBtn: { marginTop: 8, alignItems: "center", paddingVertical: 12 },
  secondaryText: { color: "#0369A1", fontSize: 15, textDecorationLine: "underline" },
  neutralCard: { marginTop: 16, padding: 16, borderRadius: 12, backgroundColor: "#F1F5F9" },
  neutralTitle: { fontSize: 17, fontWeight: "700", color: "#0F172A", marginBottom: 6 },
  neutralBody: { fontSize: 15, color: "#334155" },
});
