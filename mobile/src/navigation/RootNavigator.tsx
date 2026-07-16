/**
 * Root navigation for TrustTrace.
 *
 * Spec ref: PDF Section 6 (progressive onboarding -- the app is useful
 * immediately in a zero-permission mode; permission-gated screens are
 * reached contextually, not via an upfront wall). This replaces the
 * two-route useState shell with a real stack covering all four screens:
 * Onboarding, PasteCheck, DeviceScan, TransactionWarning.
 *
 * Navigation is intentionally a plain native-stack -- no deep-link surface
 * is exposed for the transaction-warning route from outside the app, since
 * a warning is always raised by in-app detection, never by an external
 * caller (which would be an injection vector for a fake warning).
 */
import React, { useCallback } from "react";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { NavigationContainer } from "@react-navigation/native";

import { OnboardingScreen, ProtectionInterest } from "../screens/OnboardingScreen";
import { PasteCheckScreen, PasteCheckResult } from "../screens/PasteCheckScreen";
import { DeviceScanScreen, DeviceScanFinding } from "../screens/DeviceScanScreen";
import { TransactionWarningScreen } from "../screens/TransactionWarningScreen";
import { WarningState } from "../state/warningStore";
import { CitedEvidence } from "../components/EvidenceCitation";

export type RootStackParamList = {
  Onboarding: undefined;
  PasteCheck: undefined;
  DeviceScan: undefined;
  TransactionWarning: {
    warning: WarningState;
    evidence: [CitedEvidence, ...CitedEvidence[]];
  };
};

const Stack = createNativeStackNavigator<RootStackParamList>();

export interface RootNavigatorProps {
  /** On-device-first scoring (falls back to backend). Wired in App.tsx. */
  scoreTranscript: (text: string) => Promise<PasteCheckResult>;
  /** Opt-in cloud explain-more. Wired in App.tsx. The current on-device
   *  result is forwarded so the handler can reuse model rationale. */
  onExplainMoreRequested: (text: string, result?: PasteCheckResult) => void;
  /** Owner-initiated device scan. Wired in App.tsx. */
  runOwnDeviceScan: () => Promise<DeviceScanFinding[]>;
  /** Discreet-exit + resources for the DV-context scan screen (spec 2.4). */
  onDiscreetExit: () => void;
  resourcesUrl: string;
  /** Resolve a transaction warning action (continue / go back only). */
  onWarningAction: (
    eventId: string,
    action: WarningState["availableActions"][number],
  ) => void;
}

export function RootNavigator(props: RootNavigatorProps): React.ReactElement {
  const OnboardingRoute = useCallback(
    ({ navigation }: { navigation: { navigate: (r: keyof RootStackParamList) => void } }) => (
      <OnboardingScreen
        onDone={(_interests: ProtectionInterest[]) => navigation.navigate("PasteCheck")}
        onTryPasteCheckNow={() => navigation.navigate("PasteCheck")}
      />
    ),
    [],
  );

  const PasteCheckRoute = useCallback(
    () => (
      <PasteCheckScreen
        scoreTranscript={props.scoreTranscript}
        onExplainMoreRequested={props.onExplainMoreRequested}
      />
    ),
    [props.scoreTranscript, props.onExplainMoreRequested],
  );

  const DeviceScanRoute = useCallback(
    () => (
      <DeviceScanScreen
        runOwnDeviceScan={props.runOwnDeviceScan}
        onDiscreetExit={props.onDiscreetExit}
        resourcesUrl={props.resourcesUrl}
      />
    ),
    [props.runOwnDeviceScan, props.onDiscreetExit, props.resourcesUrl],
  );

  const TransactionWarningRoute = useCallback(
    ({ route }: { route: { params: RootStackParamList["TransactionWarning"] } }) => (
      <TransactionWarningScreen
        warning={route.params.warning}
        evidence={route.params.evidence}
        onAction={props.onWarningAction}
      />
    ),
    [props.onWarningAction],
  );

  return (
    <NavigationContainer>
      <Stack.Navigator initialRouteName="Onboarding">
        <Stack.Screen
          name="Onboarding"
          options={{ title: "Welcome to TrustTrace", headerShown: false }}
        >
          {OnboardingRoute}
        </Stack.Screen>
        <Stack.Screen
          name="PasteCheck"
          options={{ title: "Check a conversation" }}
        >
          {PasteCheckRoute}
        </Stack.Screen>
        <Stack.Screen
          name="DeviceScan"
          options={{ title: "Scan this device" }}
        >
          {DeviceScanRoute}
        </Stack.Screen>
        <Stack.Screen
          name="TransactionWarning"
          options={{ title: "Before you send", headerBackVisible: false }}
        >
          {TransactionWarningRoute}
        </Stack.Screen>
      </Stack.Navigator>
    </NavigationContainer>
  );
}
