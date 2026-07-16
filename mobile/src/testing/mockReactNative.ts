/**
 * Minimal react-native mock for COMPONENT tests (jest moduleNameMapper).
 *
 * The sandbox jest runs under ts-jest/node; real react-native ships
 * untranspiled Flow that ts-jest cannot transform, so component tests map
 * "react-native" here instead. Each mock renders a plain host element with
 * its props preserved, which is exactly what the tests assert against:
 * render structure, conditional branches, and handler wiring -- NOT native
 * behaviour (that is the device build's job).
 *
 * Only the surface the app's components actually use is mocked; extend it
 * alongside new component imports.
 */
import React from "react";

type AnyProps = Record<string, unknown> & { children?: React.ReactNode };

function host(name: string): React.FC<AnyProps> {
  const C: React.FC<AnyProps> = (props) =>
    React.createElement(name, props, props.children);
  C.displayName = name;
  return C;
}

export const View = host("View");
export const Text = host("Text");
export const TextInput = host("TextInput");
export const Pressable = host("Pressable");
export const ScrollView = host("ScrollView");
export const ActivityIndicator = host("ActivityIndicator");

export const StyleSheet = {
  create<T>(styles: T): T {
    return styles;
  },
};

export const Alert = { alert: (): void => undefined };
export const Linking = { openURL: async (): Promise<void> => undefined };
export const Platform = { OS: "android" as const };
