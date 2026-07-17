package com.trusttrace.app.modelfs

import com.facebook.react.ReactPackage
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.uimanager.ViewManager

/**
 * Registers [TrustTraceModelFsModule]. This is a local module (not an npm
 * package), so it is wired in manually via MainApplication.getPackages()
 * rather than autolinked. Under the New Architecture it is reached through the
 * TurboModule interop layer, so no codegen spec is required.
 */
class TrustTraceModelFsPackage : ReactPackage {
  override fun createNativeModules(reactContext: ReactApplicationContext): List<NativeModule> =
    listOf(TrustTraceModelFsModule(reactContext))

  override fun createViewManagers(reactContext: ReactApplicationContext): List<ViewManager<*, *>> =
    emptyList()
}
