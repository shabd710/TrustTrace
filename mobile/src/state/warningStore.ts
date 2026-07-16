/**
 * Warning-overlay state slices.
 *
 * Spec ref: PDF Section 9.1 (narrowed from a blanket global-state-freeze
 * proposal: the warning overlay renders from an ISOLATED, scoped state
 * slice, not a freeze of shared app state -- an in-flight payee-novelty
 * check elsewhere in the app must not be starved). Section 10.3: warning
 * state slices are keyed PER TRIGGERING EVENT, not a single shared
 * "current warning" slot, so a second rapid app-switch doesn't overwrite
 * an unresolved first warning.
 *
 * NOT EXECUTABLE HERE -- a real build wires this into Zustand/Redux; the
 * KEYING STRATEGY itself (the actual spec-mandated correction) is real,
 * plain TypeScript logic, testable independent of any state-library
 * choice.
 */

export interface WarningState {
  eventId: string;         // unique per triggering event -- see module doc
  headline: string;
  citedEvidence: string[];
  availableActions: ("i_understand_continue_anyway" | "go_back")[];  // no third "cancel_transaction" option, ever
  createdAtMs: number;
}

/** Keyed by eventId, NOT a single shared slot -- this is the literal
 * enforcement of spec 10.3's correction. */
export type WarningRegistry = Record<string, WarningState>;

export function addWarning(registry: WarningRegistry, warning: WarningState): WarningRegistry {
  return { ...registry, [warning.eventId]: warning };
}

export function resolveWarning(registry: WarningRegistry, eventId: string): WarningRegistry {
  const { [eventId]: _removed, ...rest } = registry;
  return rest;
}

export function unresolvedWarningCount(registry: WarningRegistry): number {
  return Object.keys(registry).length;
}
