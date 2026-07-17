# Add project specific ProGuard rules here.
# By default, the flags in this file are appended to flags specified
# in /usr/local/Cellar/android-sdk/24.3.3/tools/proguard/proguard-android.txt
# You can edit the include path and order by changing the proguardFiles
# directive in build.gradle.
#
# For more details, see
#   http://developer.android.com/guide/developing/tools/proguard.html

# react-native-reanimated
-keep class com.swmansion.reanimated.** { *; }
-keep class com.facebook.react.turbomodule.** { *; }

# llama.rn -- its classes are invoked from JNI/native code, call sites R8
# cannot see. Stripping them breaks model init at runtime only (release-only
# crash class). Required before android.enableProguardInReleaseBuilds is
# ever enabled.
-keep class com.rnllama.** { *; }

# Expo modules core -- packages/modules are instantiated reflectively.
-keep class expo.modules.** { *; }

# TrustTrace native model-fs module (registered by reflection via the
# ReactPackage list).
-keep class com.trusttrace.app.modelfs.** { *; }

# Add any project specific keep options here:
