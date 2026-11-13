/*
 * A navigation that is a PUSH in the router but reads as "back" to the person, such as re-tapping
 * the active tab to pop a drilled-in page to its root, says so in its location state. RootOutlet
 * reads it when it sets `html[data-direction]`. The router-action mapping itself stays in
 * `navigationDirection.ts`.
 */
export interface NavDirectionState {
  navDirection: "back"
}

export function stateDirection(state: unknown): "back" | undefined {
  return (state as Partial<NavDirectionState> | null | undefined)?.navDirection === "back" ? "back" : undefined
}
