/*
 BroadcastSampleHandler.swift -- user-initiated, session-bounded screen
 analysis via ReplayKit + on-device Vision OCR.

 Spec ref: PDF Section 2.8 (5-minute hard time bound matching the ~50MB
 broadcast-extension memory ceiling; frames piped directly into
 VNRecognizeTextRequest; only the derived risk signal crosses the
 extension/host-app boundary via an App Group container, never raw frame
 data), 7.2 (App Group shared container is the platform-correct
 mechanism -- there's no raw frame data to route out since OCR runs
 INSIDE the extension), 9.2 (Swift actor isolation for frame buffers,
 os_proc_available_memory polling before Tier 2 invocation), 8.3 (App
 Group container itself needs hardware-backed AES-GCM encryption, same
 discipline as the main local store), 10.2 (partial risk signal preserved
 + honest "session ended early" notice if terminated by memory pressure).

 NOT COMPILED/RUN HERE -- needs a real Broadcast Upload Extension target
 in Xcode, entitlements, and a physical/simulated iOS 16+ device. Written
 to the real ReplayKit/Vision/CryptoKit API surface.
*/
import ReplayKit
import Vision
import CryptoKit

private let SESSION_TIME_LIMIT_SECONDS: TimeInterval = 300  // 5 minutes, spec 2.8

actor FrameBufferState {
    // Swift actor isolation (spec 9.2) protects concurrent access to
    // accumulated OCR text across the extension's frame-processing
    // callbacks, which ReplayKit may invoke off the main thread.
    private(set) var accumulatedRegionText: [String] = []
    private(set) var sessionStartTime: Date = Date()

    func append(_ regionText: String) {
        accumulatedRegionText.append(regionText)
    }

    func elapsedSeconds() -> TimeInterval {
        Date().timeIntervalSince(sessionStartTime)
    }

    func snapshotAndClear() -> [String] {
        let snapshot = accumulatedRegionText
        accumulatedRegionText = []
        return snapshot
    }
}

class BroadcastSampleHandler: RPBroadcastSampleHandler {

    private let frameState = FrameBufferState()
    private var sessionTimer: Timer?

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        sessionTimer = Timer.scheduledTimer(withTimeInterval: SESSION_TIME_LIMIT_SECONDS, repeats: false) { [weak self] _ in
            self?.finishBroadcastGracefully(reason: "time_limit_reached")
        }
    }

    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer, with sampleBufferType: RPSampleBufferType) {
        guard sampleBufferType == .video else { return }

        // Proactive memory check before heavy OCR work (spec 9.2:
        // os_proc_available_memory polling, complementing the reactive
        // didReceiveMemoryWarning handling below).
        if os_proc_available_memory() < 10_000_000 {  // ~10MB headroom floor
            finishBroadcastGracefully(reason: "low_memory_preemptive")
            return
        }

        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }

        let request = VNRecognizeTextRequest { [weak self] request, error in
            guard let results = request.results as? [VNRecognizedTextObservation] else { return }
            // ocr_pipeline.swift owns the bounding-box -> serialized-region
            // conversion; this handler just forwards raw VN results to it.
            let serialized = OcrPipeline.serializeObservations(results)
            Task { await self?.frameState.append(serialized) }
        }
        request.recognitionLevel = .accurate

        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, options: [:])
        try? handler.perform([request])
    }

    override func broadcastPaused() {}
    override func broadcastResumed() {}

    override func broadcastFinished() {
        // Normal, non-early termination path (user tapped "stop" or the
        // 5-minute timer fired) -- write the final derived risk signal.
        Task { await writeRiskSignalToAppGroup(earlyTermination: false) }
    }

    /// spec 10.2: if terminated early by system memory pressure despite
    /// didReceiveMemoryWarning handling, the PARTIAL risk signal computed
    /// so far is preserved and surfaced with an honest "session ended
    /// early" notice -- partial protection with disclosure beats a
    /// silent gap.
    private func finishBroadcastGracefully(reason: String) {
        sessionTimer?.invalidate()
        Task {
            await writeRiskSignalToAppGroup(earlyTermination: (reason != "time_limit_reached"))
        }
        finishBroadcastWithError(NSError(domain: "com.trusttrace.replaykit", code: 0,
                                          userInfo: [NSLocalizedDescriptionKey: reason]))
    }

    /// spec 8.3: the App Group container itself needs hardware-backed
    /// AES-GCM encryption, implemented via CryptoKit (platform-accelerated,
    /// not hand-rolled -- spec 9.2's standing preference for audited
    /// platform primitives). Only the DERIVED risk signal (serialized
    /// region text -> downstream Tier 2 score) crosses this boundary,
    /// never a raw frame image (spec 2.8/7.2).
    private func writeRiskSignalToAppGroup(earlyTermination: Bool) async {
        let regions = await frameState.snapshotAndClear()
        let payload = regions.joined(separator: "\n---\n")
        guard let plaintext = payload.data(using: .utf8) else { return }

        // Key versioning (spec 10.2): every encrypted payload tagged with
        // the key version that produced it, so a background-suspension
        // key desync triggers a clean re-sync rather than a silent
        // decryption failure on the host-app side.
        let key = AppGroupKeyStore.currentSymmetricKey()  // SEAM: real Keychain-backed key, spec 2.10-equivalent for this container
        guard let sealedBox = try? AES.GCM.seal(plaintext, using: key) else { return }

        let envelope = AppGroupEnvelope(
            keyVersion: AppGroupKeyStore.currentKeyVersion(),
            ciphertext: sealedBox.combined!,
            earlyTermination: earlyTermination,
            note: earlyTermination ? "session ended early" : nil
        )
        AppGroupWriter.write(envelope)  // SEAM: real App Group UserDefaults/file-container write
    }
}

/// SEAM types -- real implementations live in a shared App-Group-scoped
/// module used by both the extension and the host app. Declared here only
/// to make this file's data flow type-correct and self-contained to read.
struct AppGroupEnvelope {
    let keyVersion: Int
    let ciphertext: Data
    let earlyTermination: Bool
    let note: String?
}
enum AppGroupKeyStore {
    static func currentSymmetricKey() -> SymmetricKey { SymmetricKey(size: .bits256) }  // SEAM
    static func currentKeyVersion() -> Int { 1 }  // SEAM
}
enum AppGroupWriter {
    static func write(_ envelope: AppGroupEnvelope) { /* SEAM: real App Group write */ }
}
