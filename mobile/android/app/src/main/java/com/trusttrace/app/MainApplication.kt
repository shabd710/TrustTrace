package com.trusttrace.app

import android.app.Application
import android.content.res.Configuration
import android.util.Log
import java.io.File

import com.facebook.react.PackageList
import com.facebook.react.ReactApplication
import com.facebook.react.ReactNativeHost
import com.facebook.react.ReactPackage
import com.facebook.react.ReactHost
import com.facebook.react.defaults.DefaultNewArchitectureEntryPoint.load
import com.facebook.react.defaults.DefaultReactNativeHost
import com.facebook.soloader.SoLoader

import expo.modules.ApplicationLifecycleDispatcher
import expo.modules.ReactNativeHostWrapper

class MainApplication : Application(), ReactApplication {

  override val reactNativeHost: ReactNativeHost = ReactNativeHostWrapper(
        this,
        object : DefaultReactNativeHost(this) {
          override fun getPackages(): List<ReactPackage> {
            val packages = PackageList(this).packages
            // Local module (not an npm package) -> not autolinked; wire it in
            // manually. Gives the JS provisioning layer authoritative, app-uid
            // file access that bypasses expo-file-system's read gate.
            packages.add(com.trusttrace.app.modelfs.TrustTraceModelFsPackage())
            return packages
          }

          override fun getJSMainModuleName(): String = ".expo/.virtual-metro-entry"

          override fun getUseDeveloperSupport(): Boolean = BuildConfig.DEBUG

          override val isNewArchEnabled: Boolean = BuildConfig.IS_NEW_ARCHITECTURE_ENABLED
          override val isHermesEnabled: Boolean = BuildConfig.IS_HERMES_ENABLED
      }
  )

  override val reactHost: ReactHost
    get() = ReactNativeHostWrapper.createReactHost(applicationContext, reactNativeHost)

  override fun onCreate() {
    super.onCreate()

    // Debug-only provisioning diagnostics. Gated on BuildConfig.DEBUG so
    // release builds never log model paths/state. (No transcript content here,
    // but keep production logs clean.)
    if (BuildConfig.DEBUG) {
      val model = File(
          getExternalFilesDir(null),
          "models/Llama-3.2-1B-Instruct-f16.gguf"
      )
      Log.d("TrustTraceTest", "Path = ${model.absolutePath}")
      Log.d("TrustTraceTest", "Exists = ${model.exists()}")
      Log.d("TrustTraceTest", "Readable = ${model.canRead()}")
      Log.d("TrustTraceTest", "Size = ${model.length()}")
    }

    SoLoader.init(this, false)
    if (BuildConfig.IS_NEW_ARCHITECTURE_ENABLED) {
      // If you opted-in for the New Architecture, we load the native entry point for this app.
      load()
    }
    ApplicationLifecycleDispatcher.onApplicationCreate(this)
  }

  override fun onConfigurationChanged(newConfig: Configuration) {
    super.onConfigurationChanged(newConfig)
    ApplicationLifecycleDispatcher.onConfigurationChanged(this, newConfig)
  }
}
