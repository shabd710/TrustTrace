/**
 * Minimal react-native type declarations -- SANDBOX VERIFICATION SHIM.
 *
 * Purpose: lets `tsc --strict` genuinely type-check the screens/ and
 * components/ code in an environment where installing the full
 * react-native package (which ships its own types) isn't practical.
 * Declares ONLY the strict subset of the real API surface these files
 * use, with signatures matching the real library.
 *
 * In a real Expo/React Native project, DELETE this file -- the actual
 * react-native package provides the complete, authoritative types, and
 * the app code here compiles against them unchanged.
 */
declare module "react-native" {
  import * as React from "react";

  export type StyleValue = { [key: string]: string | number | undefined } | null | undefined;
  export type StyleProp = StyleValue | StyleValue[];

  export interface AccessibilityState {
    checked?: boolean;
    disabled?: boolean;
    selected?: boolean;
  }

  export interface ViewProps {
    style?: StyleProp;
    accessibilityRole?: string;
    accessibilityState?: AccessibilityState;
    children?: React.ReactNode;
  }

  export interface TextProps extends ViewProps {}

  export interface PressableProps extends ViewProps {
    onPress?: () => void;
  }

  export interface ScrollViewProps extends ViewProps {
    contentContainerStyle?: StyleProp;
  }

  export interface TextInputProps extends ViewProps {
    multiline?: boolean;
    value?: string;
    onChangeText?: (text: string) => void;
    placeholder?: string;
    textAlignVertical?: "auto" | "top" | "bottom" | "center";
  }

  export interface ActivityIndicatorProps extends ViewProps {
    size?: "small" | "large" | number;
  }

  export const View: React.ComponentType<ViewProps>;
  export const Text: React.ComponentType<TextProps>;
  export const Pressable: React.ComponentType<PressableProps>;
  export const ScrollView: React.ComponentType<ScrollViewProps>;
  export const TextInput: React.ComponentType<TextInputProps>;
  export const ActivityIndicator: React.ComponentType<ActivityIndicatorProps>;

  export const StyleSheet: {
    create<T extends { [key: string]: { [key: string]: string | number } }>(styles: T): T;
  };

  export const Linking: {
    openURL(url: string): Promise<void>;
  };

  export const Platform: {
    OS: "ios" | "android" | "windows" | "macos" | "web";
  };

  export const Alert: {
    alert(title: string, message?: string): void;
  };
}
