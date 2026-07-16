/**
 * EvidenceCitation -- renders the exact cited evidence behind a flag.
 *
 * Spec ref: PDF non-negotiable philosophy + Section 2.5: "Every flag cites
 * the exact evidence that produced it -- a transcript span, a permission
 * name, a header field, an OCR'd screen region. No unexplained risk
 * scores." This component is the UI-side enforcement of that rule: it has
 * NO render path for a flag without evidence -- the props type makes an
 * evidence-free flag unrepresentable, mirroring how local_trainer.py's
 * TrainingExample structurally cannot carry a session ID.
 *
 * REAL vs SIM: real, type-checked React Native TSX (tsc --strict). Not
 * executed on a device here -- no iOS/Android runtime exists in this
 * sandbox (see Application Guide).
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";

export type EvidenceKind =
  | "transcript_span"
  | "permission_name"
  | "header_field"
  | "ocr_region";

export interface CitedEvidence {
  kind: EvidenceKind;
  /** The literal quoted span/name/field/region text. Required, non-empty. */
  quotedText: string;
  /** Where it came from, e.g. "message from +91-98xxxx, Tue 14:02" or
   *  "top-right screen region". */
  sourceLabel: string;
  /** Low-confidence OCR is shown AS uncertain (spec 10.1), never hidden. */
  uncertain?: boolean;
  /** Tactic id this evidence supports, when known (used to correlate the
   *  model's rationale with the Explain-more copy). Optional. */
  tacticId?: string;
  /** Grounded, plain-language reasoning from the on-device Tier-1 model for
   *  this finding, when a model scored it. Shown to the user (spec 2.5: no
   *  unexplained risk scores) instead of being discarded. Optional. */
  modelRationale?: string;
}

export interface EvidenceCitationProps {
  /** Plain-language name of what was detected. */
  findingLabel: string;
  /** Non-empty by contract -- an evidence-free flag must never render. */
  evidence: [CitedEvidence, ...CitedEvidence[]];
}

const KIND_LABEL: Record<EvidenceKind, string> = {
  transcript_span: "From the conversation",
  permission_name: "Permission on this device",
  header_field: "Message header",
  ocr_region: "Seen on screen",
};

export function EvidenceCitation(props: EvidenceCitationProps): React.ReactElement {
  return (
    <View style={styles.card} accessibilityRole="summary">
      <Text style={styles.finding}>{props.findingLabel}</Text>
      {props.evidence.map((ev, i) => (
        <View key={`${ev.kind}-${i}`} style={styles.evidenceRow}>
          <Text style={styles.kind}>
            {KIND_LABEL[ev.kind]}
            {ev.uncertain === true ? " (text may be misread -- treat as uncertain)" : ""}
          </Text>
          <Text style={styles.quote}>{"\u201C"}{ev.quotedText}{"\u201D"}</Text>
          <Text style={styles.source}>{ev.sourceLabel}</Text>
          {typeof ev.modelRationale === "string" && ev.modelRationale.length > 0 ? (
            <Text style={styles.rationale}>On-device model: {ev.modelRationale}</Text>
          ) : null}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { padding: 16, borderRadius: 12, backgroundColor: "#FFF7ED", marginVertical: 8 },
  finding: { fontSize: 18, fontWeight: "700", marginBottom: 8, color: "#7C2D12" },
  evidenceRow: { marginBottom: 10 },
  kind: { fontSize: 13, color: "#9A3412", marginBottom: 2 },
  quote: { fontSize: 16, fontStyle: "italic", color: "#1C1917" },
  source: { fontSize: 12, color: "#78716C", marginTop: 2 },
  rationale: { fontSize: 14, color: "#374151", marginTop: 4 },
});
