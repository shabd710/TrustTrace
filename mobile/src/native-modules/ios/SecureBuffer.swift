/*
 SecureBuffer.swift -- native, manually-zeroed byte buffer via memset_s.

 Spec ref: PDF Section 2.12 / Strict Instruction Summary: sensitive
 rolling-context text lives in a native mutable byte buffer, wiped via
 memset_s (never plain memset, which the compiler is permitted to elide
 immediately before a deallocation it can prove is dead code -- memset_s
 is specified to never be optimized away). Section 10.1: register-level
 remnants in hot paths get explicit clearing; cache-line remnants are an
 accepted, named limitation requiring hardware secure compute (unavailable
 to third-party apps), not something this file claims to solve.

 NOT COMPILED/RUN HERE -- needs Xcode + a real/simulated iOS 16+ target.
 Written to the real Swift/Foundation/Darwin API surface.
*/
import Foundation
import Darwin

final class SecureBuffer {
    private var pointer: UnsafeMutableRawPointer?
    private let length: Int
    private var wiped: Bool = false

    /// Allocates from plaintext, converting to UTF-8 bytes immediately.
    /// The caller's Swift String should be discarded as soon as possible
    /// -- this class cannot reach back and wipe a String the caller still
    /// holds (Swift String, like Kotlin/Java String, offers no reliable
    /// wipe guarantee once other references may exist).
    init(plaintext: String) {
        let utf8 = Array(plaintext.utf8)
        self.length = utf8.count
        self.pointer = UnsafeMutableRawPointer.allocate(byteCount: length, alignment: 1)
        utf8.withUnsafeBytes { src in
            self.pointer!.copyMemory(from: src.baseAddress!, byteCount: length)
        }
    }

    /// Returns a COPY for active use (handed to the cascade's scoring
    /// call). Same honest boundary as the Kotlin equivalent: no
    /// technique defends against a real-time read during legitimate
    /// active use (spec 2.12).
    func readForScoring() -> [UInt8] {
        guard let ptr = pointer, !wiped else {
            fatalError("SecureBuffer already wiped -- caller bug, not a recoverable state")
        }
        let buf = UnsafeRawBufferPointer(start: ptr, count: length)
        return Array(buf)
    }

    /// Explicit wipe via memset_s -- called on wake-gate dormancy or
    /// session timeout, BEFORE the compacted structured summary is
    /// written to SQLCipher (spec 2.12). memset_s is specified (C11
    /// Annex K) to never be optimized away by the compiler, unlike plain
    /// memset/bzero right before a deallocation.
    func wipe() {
        guard let ptr = pointer, !wiped else { return }
        _ = memset_s(ptr, length, 0, length)
        ptr.deallocate()
        pointer = nil
        wiped = true
    }

    deinit {
        // Defense-in-depth only, same caveat as the Kotlin finalize()
        // note: real wipe timing MUST be the wake-gate/session-timeout
        // call site, not ARC deinit timing.
        wipe()
    }
}
