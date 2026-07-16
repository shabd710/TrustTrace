/**
 * Minimal type declarations for external app dependencies -- SANDBOX
 * VERIFICATION SHIM (same purpose and lifecycle as react-native.d.ts).
 *
 * These let `tsc --strict` genuinely type-check the new integration code
 * (config/env.ts, navigation/RootNavigator.tsx) without installing the
 * full packages in this environment. Each declares ONLY the strict subset
 * of the real API surface the app actually uses, with signatures matching
 * the real libraries.
 *
 * In a real Expo/React Native project, DELETE this file and add the real
 * packages:
 *   expo install expo-constants
 *   npm i @react-navigation/native @react-navigation/native-stack \
 *         react-native-screens react-native-safe-area-context
 * The app code here compiles against their authoritative types unchanged.
 */

/**
 * Minimal `process.env` surface. In a real Expo build the bundler injects
 * EXPO_PUBLIC_* vars into process.env; this declares only that read shape
 * so tsc --strict resolves it without pulling all of @types/node. The real
 * project can add @types/node and delete this block.
 */
declare const process: {
  env: Record<string, string | undefined>;
};

/**
 * `__DEV__` is a global boolean Metro/React Native injects at build time
 * (true in development, false in release). Declared here so the dev-only
 * logger (src/utils/logger.ts) and config (src/config/env.ts) type-check under
 * `tsc --strict`. The real RN types provide this; delete with the shims.
 */
declare const __DEV__: boolean;

/**
 * Minimal CommonJS `require`, used only for the guarded, build-optional load
 * of the native Llama bootstrap (src/ml/nativeLlamaBootstrap.ts). The real
 * project has @types/node / RN's require typing and can delete this.
 */
declare function require(moduleName: string): unknown;

/**
 * The native Llama bootstrap lives in src/native-modules/ (excluded from the
 * sandbox typecheck because it imports the real llama.rn package). Declare
 * only the narrow, side-effecting entry point the app calls, so the guarded
 * require in nativeLlamaBootstrap.ts type-checks without the module present.
 */
declare module "*/native-modules/registerNativeLlama" {
  export function registerNativeLlamaScorerIfAvailable(): void | Promise<void>;
}

declare module "expo-constants" {
  interface Constants {
    expoConfig?: { extra?: Record<string, unknown> } | null;
    manifest?: { extra?: Record<string, unknown> } | null;
  }
  const Constants: Constants;
  export default Constants;
}

declare module "@react-navigation/native" {
  import * as React from "react";
  export const NavigationContainer: React.ComponentType<{
    children?: React.ReactNode;
  }>;
}

declare module "@react-navigation/native-stack" {
  import * as React from "react";

  export interface NativeStackNavigationOptions {
    title?: string;
    headerShown?: boolean;
    headerBackVisible?: boolean;
  }

  export interface NativeStackNavigationProp<
    ParamList,
    RouteName extends keyof ParamList = keyof ParamList,
  > {
    navigate(screen: keyof ParamList): void;
  }

  export interface ScreenProps<
    ParamList,
    RouteName extends keyof ParamList,
  > {
    name: RouteName;
    options?: NativeStackNavigationOptions;
    children: (props: {
      navigation: NativeStackNavigationProp<ParamList, RouteName>;
      route: { params: ParamList[RouteName] };
    }) => React.ReactElement;
  }

  export interface NavigatorProps<ParamList> {
    initialRouteName?: keyof ParamList;
    children?: React.ReactNode;
  }

  export interface NativeStackNavigator<ParamList> {
    Navigator: React.ComponentType<NavigatorProps<ParamList>>;
    Screen: <RouteName extends keyof ParamList>(
      props: ScreenProps<ParamList, RouteName>,
    ) => React.ReactElement;
  }

  export function createNativeStackNavigator<
    ParamList,
  >(): NativeStackNavigator<ParamList>;
}
