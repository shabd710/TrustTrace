package com.trusttrace.app.modelfs

import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.bridge.WritableMap
import java.io.File
import java.io.FileInputStream
import java.security.MessageDigest

/**
 * Authoritative, app-uid file access for on-device GGUF model provisioning.
 *
 * WHY THIS EXISTS
 * ----------------
 * expo-file-system's Android layer runs a permission gate (canRead() over a
 * whitelist of Expo's OWN internal dirs) BEFORE any op. The app's own
 * external files dir (…/Android/data/<pkg>/files) is NOT on that whitelist, so
 * getInfoAsync()/readDirectoryAsync() THROW "isn't readable" even though the
 * OS grants the app full read/write there. That false negative is what kept
 * resolveExistingTier1ModelPath() returning null and initLlama() from ever
 * running.
 *
 * This module talks to java.io.File directly under the app uid -- the SAME
 * access path llama.rn's native initLlama (fopen/mmap) uses -- so:
 *   - existence/size/readability answers are AUTHORITATIVE for whether the
 *     model will actually load, and
 *   - it can COPY a large GGUF from the (adb-pushed) external staging dir into
 *     gate-free internal storage, where every later load just works.
 *
 * All I/O methods are Promise-based so they work identically under the legacy
 * bridge and the New Architecture interop layer, and never block the JS thread
 * (a multi-GB copy/checksum runs on the bridge's background executor).
 */
class TrustTraceModelFsModule(private val reactContext: ReactApplicationContext) :
  ReactContextBaseJavaModule(reactContext) {

  override fun getName(): String = NAME

  /**
   * App-private external files dir (…/Android/data/<pkg>/files). Resolved from
   * the OS -- never hardcoded. May be null if external storage is unavailable.
   */
  @ReactMethod
  fun externalFilesDir(promise: Promise) {
    try {
      promise.resolve(reactContext.getExternalFilesDir(null)?.absolutePath)
    } catch (e: Exception) {
      promise.reject(ERR, e)
    }
  }

  /** App-private internal files dir (/data/user/0/<pkg>/files) -- always readable. */
  @ReactMethod
  fun internalFilesDir(promise: Promise) {
    try {
      promise.resolve(reactContext.filesDir.absolutePath)
    } catch (e: Exception) {
      promise.reject(ERR, e)
    }
  }

  /** Create a directory (and parents) if missing. Resolves true if it is a dir afterwards. */
  @ReactMethod
  fun ensureDir(path: String, promise: Promise) {
    try {
      val d = File(path)
      if (!d.exists()) {
        d.mkdirs()
      }
      promise.resolve(d.isDirectory)
    } catch (e: Exception) {
      promise.reject(ERR, e)
    }
  }

  /**
   * Authoritative stat under the app uid: { exists, isFile, canRead, size }.
   * size is a Double because the RN bridge has no 64-bit int and GGUF weights
   * routinely exceed 2 GB.
   */
  @ReactMethod
  fun stat(path: String, promise: Promise) {
    try {
      val f = File(path)
      val exists = f.exists()
      val m: WritableMap = Arguments.createMap()
      m.putBoolean("exists", exists)
      m.putBoolean("isFile", exists && f.isFile)
      m.putBoolean("canRead", exists && f.canRead())
      m.putDouble("size", if (exists) f.length().toDouble() else 0.0)
      promise.resolve(m)
    } catch (e: Exception) {
      promise.reject(ERR, e)
    }
  }

  /**
   * Stream-copy src -> dst under the app uid (works where expo copyAsync's gate
   * fails on the external dir). Writes to a .part sidecar and atomically renames
   * on success, so a killed copy never leaves a truncated GGUF that could crash
   * initLlama. Resolves the number of bytes written.
   */
  @ReactMethod
  fun copyFile(src: String, dst: String, promise: Promise) {
    try {
      val s = File(src)
      if (!s.exists() || !s.canRead()) {
        promise.reject(ERR, "source not readable: $src")
        return
      }
      val d = File(dst)
      d.parentFile?.mkdirs()
      val tmp = File("$dst.part")
      if (tmp.exists()) {
        tmp.delete()
      }
      s.inputStream().use { input ->
        tmp.outputStream().use { output ->
          input.copyTo(output, DEFAULT_BUFFER)
        }
      }
      if (d.exists()) {
        d.delete()
      }
      if (!tmp.renameTo(d)) {
        tmp.delete()
        promise.reject(ERR, "rename failed: $tmp -> $d")
        return
      }
      promise.resolve(d.length().toDouble())
    } catch (e: Exception) {
      promise.reject(ERR, e)
    }
  }

  /**
   * Usable free bytes on the filesystem backing `path`. If the file itself
   * doesn't exist yet, we measure its parent dir (the copy target). Used to
   * pre-check that a multi-GB model copy will fit before starting it.
   */
  @ReactMethod
  fun usableSpace(path: String, promise: Promise) {
    try {
      var f = File(path)
      if (!f.exists()) {
        f = f.parentFile ?: f
      }
      promise.resolve(f.usableSpace.toDouble())
    } catch (e: Exception) {
      promise.reject(ERR, e)
    }
  }

  /** Delete a file if present. Resolves true if the path no longer exists. */
  @ReactMethod
  fun deleteFile(path: String, promise: Promise) {
    try {
      val f = File(path)
      if (f.exists()) {
        f.delete()
      }
      promise.resolve(!f.exists())
    } catch (e: Exception) {
      promise.reject(ERR, e)
    }
  }

  /** SHA-256 of the file at path, lowercase hex. For optional integrity pinning. */
  @ReactMethod
  fun sha256(path: String, promise: Promise) {
    try {
      val md = MessageDigest.getInstance("SHA-256")
      FileInputStream(path).use { fis ->
        val buf = ByteArray(DEFAULT_BUFFER)
        while (true) {
          val n = fis.read(buf)
          if (n < 0) break
          md.update(buf, 0, n)
        }
      }
      promise.resolve(md.digest().joinToString("") { "%02x".format(it.toInt() and 0xff) })
    } catch (e: Exception) {
      promise.reject(ERR, e)
    }
  }

  companion object {
    const val NAME = "TrustTraceModelFs"
    private const val ERR = "TrustTraceModelFs"
    private const val DEFAULT_BUFFER = 1 shl 20 // 1 MiB
  }
}
