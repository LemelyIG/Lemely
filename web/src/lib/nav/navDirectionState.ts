/*
 * A navigation that is a PUSH in the router but reads as "back" to the person, such as re-tapping
 * the active tab to pop a drilled-in page to its root, says so in its location state. A tab-bar
 * tap to another section says "tab", so the native frame can cross-fade it instead of pushing.
 * RootOutlet reads either when it sets `html[data-direction]`. The router-action mapping itself
 * stays in `navigationDirection.ts`.
 */
export interface NavDirectionState {
  navDirection: "back" | "tab"
}

export function stateDirection(state: unknown): "back" | "tab" | undefined {
  const direction = (state as Partial<NavDirectionState> | null | undefined)?.navDirection
  return direction === "back" || direction === "tab" ? direction : undefined
}
