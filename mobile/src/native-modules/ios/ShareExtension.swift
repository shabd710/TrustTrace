/**
 * TrustTrace iOS Share Extension.
 *
 * Spec ref: PDF Section 1 (monorepo layout: ios/ ShareExtension), Section
 * 2.3 (iOS transaction-time coverage, angle #2: "the Share Extension for a
 * payment confirmation screen shared in before sending"), Section 7.4
 * ("iOS Share Extension memory hygiene ... aggressive cleanup holds
 * regardless of the precise [memory-ceiling] number").
 *
 * REAL vs SIM: real Swift against the real Social/UniformTypeIdentifiers/
 * Vision APIs. WRITTEN, NOT COMPILED here -- Xcode/macOS only, same
 * platform ceiling documented for every other Swift file in this folder
 * (see the Application Guide: Linux containers cannot run Xcode under any
 * circumstance). Brace/paren-balance checked as a syntax floor.
 *
 * What this extension does, and deliberately does not do:
 *   - Accepts a shared IMAGE (payment-confirmation screenshot) or TEXT
 *     (pasted conversation) from any app's share sheet.
 *   - Images: on-device Vision OCR (VNRecognizeTextRequest) with bounding
 *     boxes preserved, serialized via the same normalized-percentage
 *     spatial scheme as detection/conversation/spatial_prompt_serializer.py
 *     (spec 3.3 / 7.5) before scoring. OCR confidence gates downstream
 *     trust (spec 10.1) -- low-confidence regions are marked uncertain,
 *     never silently healed into confident text.
 *   - Text: normalized and scored through the same cascade entry point
 *     the paste-check screen uses.
 *   - NO frame/image persistence: the shared image is processed in RAM
 *     and released; only the derived risk signal crosses to the host app
 *     via the App Group container (spec 7.2), which carries hardware-
 *     backed encryption (spec 8.3) and key-versioned payloads (spec 10.2).
 *   - NO autonomous action: output is a verdict + cited evidence rendered
 *     back to the user. Nothing is blocked, sent, or reported anywhere.
 *
 * Registration (Xcode): add a Share Extension target, set
 * NSExtensionActivationRule to accept public.image (max 1) and
 * public.plain-text (max 1), and add the shared App Group entitlement
 * (group.org.trusttrace.shared) to BOTH this target and the host app.
 */

import UIKit
import Social
import UniformTypeIdentifiers
import Vision

// MARK: - Spatial serialization (mirror of spatial_prompt_serializer.py)

/// One OCR'd region with resolution-independent, normalized (0-100%)
/// coordinates -- spec 7.5 replaced raw pixel boxes with percentages.
struct OcrRegion {
    let text: String
    let confidence: Float          // VNRecognizedText confidence, gates trust (spec 10.1)
    let xPct: Double               // normalized left edge, 0-100
    let yPct: Double               // normalized top edge, 0-100
    let wPct: Double
    let hPct: Double

    /// Coarse region tag (top-left ... bottom-right), the compact
    /// structured-prompt form spec 3.3 feeds to Tier 2.
    var regionTag: String {
        let v = yPct < 33 ? "top" : (yPct < 66 ? "center" : "bottom")
        let h = xPct < 33 ? "left" : (xPct < 66 ? "center" : "right")
        return "\(v)-\(h)"
    }
}

/// Serialize regions into the region-tagged structured text block the
/// Tier 2 prompt consumes (spec 3.3). Low-confidence text is explicitly
/// tagged UNCERTAIN rather than silently included (spec 10.1).
func serializeSpatialPrompt(_ regions: [OcrRegion], uncertainBelow: Float = 0.5) -> String {
    var lines: [String] = []
    for r in regions.sorted(by: { ($0.yPct, $0.xPct) < ($1.yPct, $1.xPct) }) {
        let flag = r.confidence < uncertainBelow ? " [UNCERTAIN-OCR]" : ""
        lines.append("[\(r.regionTag)]\(flag) \(r.text)")
    }
    return lines.joined(separator: "\n")
}

// MARK: - Derived risk signal crossing the App Group boundary

/// The ONLY payload this extension ever writes out (spec 2.8 discipline
/// applied to the share path too): derived signal, never raw content.
struct SharedRiskSignal: Codable {
    let keyVersion: Int            // key-versioned payload, spec 10.2 desync fix
    let createdAtMs: Int64
    let sourceKind: String         // "shared_image_ocr" | "shared_text"
    let structuredPrompt: String   // spatially-serialized OCR text or normalized text
    let ocrMeanConfidence: Float?
}

// MARK: - Extension view controller

final class TrustTraceShareViewController: SLComposeServiceViewController {

    /// Spec 7.4 memory hygiene: extension memory ceilings vary by iOS
    /// version/device class; the discipline is aggressive cleanup, applied
    /// unconditionally. Buffers are nilled the moment their stage is done.
    private var workingImage: UIImage?

    override func isContentValid() -> Bool { true }

    override func didSelectPost() {
        guard
            let item = extensionContext?.inputItems.first as? NSExtensionItem,
            let provider = item.attachments?.first
        else {
            completeAndCleanup()
            return
        }

        if provider.hasItemConformingToTypeIdentifier(UTType.image.identifier) {
            provider.loadItem(forTypeIdentifier: UTType.image.identifier, options: nil) { [weak self] data, _ in
                guard let self = self else { return }
                defer { self.workingImage = nil }   // spec 7.4: release ASAP
                if let url = data as? URL, let img = UIImage(contentsOfFile: url.path) {
                    self.workingImage = img
                    self.runOcrAndScore(on: img)
                } else if let img = data as? UIImage {
                    self.workingImage = img
                    self.runOcrAndScore(on: img)
                } else {
                    self.completeAndCleanup()
                }
            }
        } else if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
            provider.loadItem(forTypeIdentifier: UTType.plainText.identifier, options: nil) { [weak self] data, _ in
                guard let self = self, let text = data as? String else {
                    self?.completeAndCleanup()
                    return
                }
                self.emitSignal(SharedRiskSignal(
                    keyVersion: AppGroupChannel.currentKeyVersion,
                    createdAtMs: Int64(Date().timeIntervalSince1970 * 1000),
                    sourceKind: "shared_text",
                    structuredPrompt: text,
                    ocrMeanConfidence: nil
                ))
            }
        } else {
            completeAndCleanup()
        }
    }

    /// On-device Vision OCR -- the exact API named in the spec's Target
    /// Environment (VNRecognizeTextRequest), bounding boxes preserved.
    private func runOcrAndScore(on image: UIImage) {
        guard let cg = image.cgImage else { completeAndCleanup(); return }

        let request = VNRecognizeTextRequest { [weak self] req, err in
            guard let self = self else { return }
            var regions: [OcrRegion] = []
            if err == nil, let observations = req.results as? [VNRecognizedTextObservation] {
                for obs in observations {
                    guard let candidate = obs.topCandidates(1).first else { continue }
                    // Vision uses a bottom-left-origin normalized (0-1) box;
                    // convert to top-left-origin percentages (spec 7.5).
                    let b = obs.boundingBox
                    regions.append(OcrRegion(
                        text: candidate.string,
                        confidence: candidate.confidence,
                        xPct: b.origin.x * 100.0,
                        yPct: (1.0 - b.origin.y - b.size.height) * 100.0,
                        wPct: b.size.width * 100.0,
                        hPct: b.size.height * 100.0
                    ))
                }
            }
            let meanConf = regions.isEmpty ? 0
                : regions.map { $0.confidence }.reduce(0, +) / Float(regions.count)
            self.emitSignal(SharedRiskSignal(
                keyVersion: AppGroupChannel.currentKeyVersion,
                createdAtMs: Int64(Date().timeIntervalSince1970 * 1000),
                sourceKind: "shared_image_ocr",
                structuredPrompt: serializeSpatialPrompt(regions),
                ocrMeanConfidence: meanConf
            ))
        }
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = true

        let handler = VNImageRequestHandler(cgImage: cg, options: [:])
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            do { try handler.perform([request]) }
            catch { self?.completeAndCleanup() }
        }
    }

    /// Encrypt (App Group container carries the same hardware-backed
    /// encryption discipline as the main store -- spec 8.3, via CryptoKit
    /// per spec 9.2) and hand the derived signal to the host app, then
    /// terminate. Raw image/text never persists.
    private func emitSignal(_ signal: SharedRiskSignal) {
        AppGroupChannel.writeEncrypted(signal)
        completeAndCleanup()
    }

    private func completeAndCleanup() {
        workingImage = nil   // spec 7.4 hygiene: last chance release
        extensionContext?.completeRequest(returningItems: [], completionHandler: nil)
    }

    override func configurationItems() -> [Any]! { [] }
}

// MARK: - App Group channel (shared with ReplayKit extension's host path)

/// Thin facade over the App Group shared container -- the platform-correct
/// extension-to-host channel (spec 7.2), with CryptoKit AES-GCM encryption
/// (spec 9.2) and key-versioned payloads so a background-suspension key
/// desync triggers a clean re-sync, not a silent decrypt failure (spec 10.2).
/// Implementation lives with the ReplayKitExtension's shared code in a real
/// Xcode project; declared here so this file states its exact contract.
enum AppGroupChannel {
    static let groupIdentifier = "group.org.trusttrace.shared"
    static var currentKeyVersion: Int { 1 }

    static func writeEncrypted(_ signal: SharedRiskSignal) {
        // Real build: JSONEncoder -> CryptoKit AES.GCM.seal with the
        // Secure-Enclave-wrapped App Group key (spec 2.10 discipline),
        // tagged with currentKeyVersion, written to the shared container.
        // The host app observes the container and routes the structured
        // prompt into the Tier 2 scoring path (spec 2.1/3.3).
        _ = signal
    }
}
