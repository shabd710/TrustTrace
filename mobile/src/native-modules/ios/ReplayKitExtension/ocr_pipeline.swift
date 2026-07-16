/*
 ocr_pipeline.swift -- VNRecognizeTextRequest observation -> serialized,
 region-tagged, percentage-coordinate text block.

 Spec ref: PDF Section 2.8/3.3 (bounding-box layout preserved via
 structured prompt serialization), 7.5 (normalized percentage-based
 coordinates, resolution-independent), 10.1 (OCR confidence gates
 downstream trust -- low-confidence region marked uncertain, never
 silently healed into confident text), 9.3 (token-healing at bounding-box
 boundaries -- adjacent-region text can concatenate mid-word).

 This Swift file's job is narrow and specific: convert native
 VNRecognizedTextObservation results (normalized 0..1 Vision coordinates,
 already resolution-independent by Apple's own API design) into the exact
 wire format detection/conversation/spatial_prompt_serializer.py expects
 as input (percentage 0..100 coordinates) -- the REAL region-bucketing and
 text-block assembly logic itself lives in that Python file (spec's own
 file split: native OCR capture vs. portable serialization logic), and was
 already implemented and tested there. This file is the bridge between
 them, not a duplicate implementation.

 NOT COMPILED/RUN HERE -- see BroadcastSampleHandler.swift's note.
*/
import Vision

private let LOW_CONFIDENCE_THRESHOLD: Float = 0.55  // matches spatial_prompt_serializer.py's OCR_LOW_CONFIDENCE_THRESHOLD

enum OcrPipeline {

    /// Converts one frame's VN observations into the wire-format string
    /// this codebase's Python spatial_prompt_serializer.serialize()
    /// consumes (via the bridged OcrBox JSON shape below) -- this
    /// function performs simple coordinate normalization ONLY; the real
    /// region-bucketing/serialization algorithm is the Python
    /// implementation already tested in this repo.
    static func serializeObservations(_ observations: [VNRecognizedTextObservation]) -> String {
        let boxes: [OcrBoxWire] = observations.compactMap { observation in
            guard let candidate = observation.topCandidates(1).first else { return nil }
            guard candidate.confidence >= LOW_CONFIDENCE_THRESHOLD || true else { return nil }
            // Low-confidence regions are NOT dropped here -- spec 10.1
            // requires they still be cited as uncertain evidence, not
            // silently discarded OR silently upgraded to confident text.
            // The confidence value is passed through; the Python
            // serializer's OCR_LOW_CONFIDENCE_THRESHOLD gate applies the
            // "[low-confidence]" tag at render time.

            // Vision's boundingBox is ALREADY normalized 0..1 with
            // origin at bottom-left -- convert to 0..100 percentage with
            // origin at top-left (the convention spatial_prompt_serializer.py
            // expects) by flipping the y-axis.
            let bb = observation.boundingBox
            let xPct = Float(bb.origin.x * 100)
            let yPct = Float((1.0 - bb.origin.y - bb.height) * 100)  // flip: Vision's y=0 is bottom
            let wPct = Float(bb.width * 100)
            let hPct = Float(bb.height * 100)

            return OcrBoxWire(text: candidate.string, confidence: candidate.confidence,
                               xPct: xPct, yPct: yPct, wPct: wPct, hPct: hPct)
        }

        // Token-healing (spec 9.3): adjacent-region text that
        // concatenates mid-word at a boundary (e.g. "Sen" + "d $500" ->
        // "Send $500") is corrected here, BEFORE handoff to the Python
        // serializer, since it's a property of how Vision splits text
        // into observation boxes -- an OCR-capture-layer concern, not a
        // region-bucketing concern.
        let healedBoxes = healAdjacentTokenBoundaries(boxes)

        // Bridge format: a compact line-based wire encoding consumed on
        // the Python side (in a real build, JSON over the JS bridge /
        // JNI-equivalent channel -- kept simple here since this file's
        // job is documenting the conversion, not defining a full bridge
        // protocol).
        return healedBoxes.map { box in
            "\(box.xPct),\(box.yPct),\(box.wPct),\(box.hPct),\(box.confidence)|\(box.text)"
        }.joined(separator: "\n")
    }

    /// Real, if simplified, token-healing: merges two adjacent boxes on
    /// the same visual row whose horizontal gap is small enough to
    /// indicate a single word was split across two OCR observations.
    private static func healAdjacentTokenBoundaries(_ boxes: [OcrBoxWire]) -> [OcrBoxWire] {
        guard boxes.count > 1 else { return boxes }
        var result: [OcrBoxWire] = []
        var sorted = boxes.sorted { ($0.yPct, $0.xPct) < ($1.yPct, $1.xPct) }
        var i = 0
        while i < sorted.count {
            var current = sorted[i]
            while i + 1 < sorted.count {
                let next = sorted[i + 1]
                let sameRow = abs(next.yPct - current.yPct) < 1.5
                let smallGap = (next.xPct - (current.xPct + current.wPct)) < 0.8
                let looksSplitWord = !current.text.hasSuffix(" ") && !next.text.hasPrefix(" ")
                if sameRow && smallGap && looksSplitWord {
                    current = OcrBoxWire(text: current.text + next.text, confidence: min(current.confidence, next.confidence),
                                          xPct: current.xPct, yPct: current.yPct,
                                          wPct: (next.xPct + next.wPct) - current.xPct, hPct: max(current.hPct, next.hPct))
                    i += 1
                } else {
                    break
                }
            }
            result.append(current)
            i += 1
        }
        return result
    }
}

private struct OcrBoxWire {
    let text: String
    let confidence: Float
    let xPct: Float
    let yPct: Float
    let wPct: Float
    let hPct: Float
}
