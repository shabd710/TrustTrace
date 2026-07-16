/*
 * SecureBuffer.kt -- native, mutable byte-buffer-backed sensitive text
 * storage with explicit wipe.
 *
 * Spec ref: PDF Section 2.12 / Strict Instruction Summary: "Sensitive
 * rolling-context text is handled in native mutable byte buffers with
 * explicit zeroing on session end, never as JS strings or Kotlin/Java
 * String objects, which cannot be reliably wiped." Section 9.2: mlock()
 * pinning adopted with an honest boundary -- Android leans on zRAM
 * compression and process termination more than traditional disk swap,
 * so this is defense-in-depth, not a categorical guarantee.
 *
 * NOT COMPILED/RUN HERE: this file needs the Android SDK, Gradle, and a
 * JNI toolchain to build and link against libc's mlock()/explicit_bzero
 * equivalents -- none of which exist in this sandbox. Written to the real
 * Android/Kotlin/JNI API surface; the wipe-on-dormancy call path mirrors
 * the exact lifecycle described in spec 2.12 (wake-gate dormancy callback
 * or session timeout -> zero the buffer -> THEN write the compacted
 * summary to SQLCipher).
 *
 * Cross-layer security note: this class is what memory_compaction.py's
 * raw_window conceptually maps onto at the native layer -- the Python
 * reference implementation models the algorithm; sensitive plaintext in
 * the real mobile app must never actually live in a Kotlin String at all,
 * which is precisely why this class exists as a ByteArray wrapper instead
 * of just using String.
 */
package com.trusttrace.security

import java.nio.charset.StandardCharsets
import java.util.Arrays

/**
 * JNI bridge to native mlock()/wipe primitives. Implemented in a
 * companion C++ file (not included here -- out of scope for a
 * Kotlin-only reference) via System.loadLibrary("trusttrace_secure").
 */
private object NativeMemory {
    init {
        // Real build: System.loadLibrary("trusttrace_secure")
        // Left un-called here since no native .so exists in this sandbox.
    }

    /** JNI: calls mlock(ptr, len) on the backing array's native memory
     * region. Best-effort on Android -- OEM kernels (MIUI, ColorOS) may
     * ignore it; that is an accepted, documented limitation (spec 9.2/10.2),
     * not a bug to "fix" here. */
    external fun nativeMlock(buffer: ByteArray): Boolean

    /** JNI: explicit, non-elidable zeroing of the buffer's backing native
     * memory -- NOT plain Arrays.fill(), which the JIT/AOT compiler is
     * permitted to optimize away if it can prove the array is about to be
     * discarded. This must call an explicit_bzero()-equivalent that the
     * compiler is barred from eliding. */
    external fun nativeExplicitWipe(buffer: ByteArray)
}

class SecureBuffer private constructor(private var backing: ByteArray?) {

    companion object {
        /** Allocates a SecureBuffer from plaintext, converting it to UTF-8
         * bytes immediately -- the caller's String reference should be
         * discarded as soon as possible after this call; this class
         * cannot reach back and wipe a String the caller still holds
         * (JVM String immutability -- see spec 2.12's platform-reality
         * note). */
        fun fromPlaintext(plaintext: String): SecureBuffer {
            val bytes = plaintext.toByteArray(StandardCharsets.UTF_8)
            val buf = SecureBuffer(bytes)
            NativeMemory.nativeMlock(bytes)
            return buf
        }
    }

    /** Returns a COPY of the current bytes for active use (e.g. handing to
     * the cascade's scoring call). The caller is responsible for not
     * retaining this copy beyond the scoring call's lifetime -- this is
     * the honest boundary spec 2.12 names explicitly: no technique
     * defends against a real-time read of data during its legitimate
     * active use. */
    fun readForScoring(): ByteArray {
        val current = backing ?: throw IllegalStateException("SecureBuffer already wiped")
        return current.copyOf()
    }

    /** Explicit wipe -- called on wake-gate dormancy callback or session
     * timeout, per spec 2.12, BEFORE the compacted structured summary is
     * written to SQLCipher. Idempotent: safe to call multiple times. */
    fun wipe() {
        backing?.let { NativeMemory.nativeExplicitWipe(it) }
        backing = null
    }

    protected fun finalize() {
        // Defense-in-depth only -- relying on finalize() for security is
        // explicitly NOT sufficient (finalization timing is unspecified
        // in the JVM/ART spec); the real wipe MUST happen at the
        // wake-gate/session-timeout call site above. This exists only to
        // catch a caller bug, not as the primary mechanism.
        wipe()
    }
}
