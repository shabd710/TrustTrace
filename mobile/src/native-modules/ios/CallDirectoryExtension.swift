/*
 CallDirectoryExtension.swift -- CXCallDirectoryProvider for scam-call
 identification (and, separately, stalkerware-adjacent number blocking).

 Spec ref: PDF Target Environment: "CXCallDirectoryExtension for scam-call
 identification." Section 8.3: "The sorted/segmented local CallKit
 blocklist format is adopted as proposed -- CallKit's own
 directory-provisioning format favors this structure; there's no need to
 force the Bloom-filter pattern used for stalkerware signatures onto a
 differently-constrained problem." Section 3.1: incoming-call
 identification feeds the unified wake gate as one of its zero-cost
 trigger signals.

 NOT COMPILED/RUN HERE -- needs a real Call Directory Extension target in
 Xcode + entitlements + a physical/simulated iOS device, and the host app
 must prompt the user to enable it via CXCallDirectoryManager. Written to
 the real CallKit API surface.

 CRITICAL PLATFORM CONSTRAINT, stated honestly: CXCallDirectoryProvider's
 contract REQUIRES phone numbers to be added in strictly ascending order
 -- the API throws/aborts the extension if given an unsorted or duplicate
 sequence. This is exactly why spec 8.3 rejects forcing the
 Bloom-filter-plus-exact-match pattern (detection/device/
 stalkerware_signatures.py's real, tested pattern for THAT differently-
 shaped problem) onto this one: a Bloom filter has no inherent ordering,
 and retrofitting sort discipline onto it would be solving a problem this
 API doesn't actually have. The source data feeding this extension (a
 locally cached, periodically-synced list of scam/reported phone numbers
 -- e.g. threat-intel/campaign_graph.py's PHONE_NUMBER-kind nodes that
 clear the k-anonymity floor) is sorted ONCE at cache-write time, not
 inside this extension's tight completion-handler budget.
*/
import CallKit

class CallDirectoryExtension: CXCallDirectoryProvider {

    override func beginRequest(with context: CXCallDirectoryExtensionContext) {
        context.delegate = self

        // Real build: reads a pre-sorted local cache file (written by the
        // host app after a threat-intel sync, per spec 8.3's
        // "sorted/segmented local CallKit blocklist format"), NOT a live
        // network call -- CXCallDirectoryProvider extensions run with the
        // same tight, largely offline execution budget as
        // ILMessageFilterExtension (see MessageFilterExtension.swift's
        // doc). addBlockingEntry/addIdentificationEntry calls below MUST
        // be strictly ascending by phone number or CallKit aborts the
        // extension outright.
        let sortedBlockedNumbers = loadSortedBlockedNumbersFromLocalCache()
        for entry in sortedBlockedNumbers {
            context.addBlockingEntry(withNextSequentialPhoneNumber: entry.phoneNumberCLDR)
        }

        let sortedIdentifiedNumbers = loadSortedIdentifiedScamNumbersFromLocalCache()
        for entry in sortedIdentifiedNumbers {
            // Identification only (caller-ID label), not blocking --
            // spec's "Hard rule: no autonomous action" applies here too:
            // this extension NEVER silently blocks a call the user hasn't
            // consented to blocking. Blocking entries above are limited
            // to numbers the user has explicitly added to their own
            // block list via the host app; identification entries here
            // are the passive "this number matches a reported scam
            // pattern" caller-ID label, which is the friction-and-
            // explanation posture spec's non-negotiable philosophy
            // requires -- surfaced information, not an autonomous block.
            context.addIdentificationEntry(withNextSequentialPhoneNumber: entry.phoneNumberCLDR, label: entry.label)
        }

        context.completeRequest()
    }

    /// SEAM: reads a local, pre-sorted cache file written by the host app.
    /// The sort happens once at write time (see class doc) -- this
    /// function's contract is "already sorted in", not "sorts on read".
    private func loadSortedBlockedNumbersFromLocalCache() -> [BlockedNumberEntry] {
        return []  // SEAM: real implementation reads from the App-Group-shared cache file
    }

    private func loadSortedIdentifiedScamNumbersFromLocalCache() -> [IdentifiedNumberEntry] {
        return []  // SEAM: real implementation reads from the App-Group-shared cache file
    }
}

extension CallDirectoryExtension: CXCallDirectoryExtensionContextDelegate {
    func requestFailed(for extensionContext: CXCallDirectoryExtensionContext, withError error: Error) {
        // Real build: logs locally for the next host-app-triggered sync
        // to retry -- no network call from inside the extension itself.
    }
}

private struct BlockedNumberEntry {
    let phoneNumberCLDR: CXCallDirectoryPhoneNumber
}

private struct IdentifiedNumberEntry {
    let phoneNumberCLDR: CXCallDirectoryPhoneNumber
    let label: String
}
