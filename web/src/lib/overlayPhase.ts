import { useEffect, useRef, useState } from "react"
import { prefersReducedMotion } from "@/lib/celebration"

/*
 * Packet B2b · the exit-phase state machine `Modal` and `NavDrawer` share.
 *
 * Both used to unmount the instant their `open` prop went false
 * (`if (!open) return null`), which is correct for the entrance but drops a
 * dismissible overlay off the page with no exit at all — DESIGN.md §9.2's
 * "Exits" clause. The fix needs a state between "open" and "closed" that
 * keeps the panel mounted (and the scroll lock, focus trap and history entry
 * live) for exactly as long as its exit animation runs, then lets go on
 * `animationend` rather than on a fixed timer that would drift from the CSS.
 *
 * `overlayPhase` is the pure transition table, independently testable under
 * vitest's Node environment (D3.20). `useOverlayPhase` is the thin React
 * wiring both components share, rather than each re-deriving it — see
 * `nav-drawer.tsx`'s own header on why sharing beats a second, subtly
 * different implementation.
 */

export type OverlayState = "closed" | "open" | "closing"
export type OverlayEvent = "open" | "close" | "animationend"

/**
 * `open` always wins outright — including a re-open mid-`closing`, which
 * snaps straight back to `open` rather than finishing the exit first: the
 * reader asked for the overlay again, and playing its own exit under them
 * before opening back up would read as a glitch, not an animation.
 *
 * `close` from `open` starts the exit (`closing`) unless `reducedMotion`,
 * which skips straight to `closed` — there is no animation to wait for.
 * `close` from anything else is a no-op: `closed` stays `closed`, and a
 * second `close` while already `closing` does not restart or skip the exit
 * already in flight.
 *
 * `animationend` only ever matters from `closing`, where it is the exit
 * animation reporting it has actually finished; from any other state it is
 * a stray event (an overlay that finished closing, or was reopened, before
 * its own listener detached) and changes nothing.
 */
export function overlayPhase(
  state: OverlayState,
  event: OverlayEvent,
  reducedMotion: boolean,
): OverlayState {
  if (event === "open") return "open"
  if (event === "close") {
    if (state !== "open") return state
    return reducedMotion ? "closed" : "closing"
  }
  // animationend
  return state === "closing" ? "closed" : state
}

/**
 * Wires `overlayPhase` to a component's `open` prop. Reads
 * `prefersReducedMotion()` fresh on every open/close transition rather than
 * once at mount, for the same reason `prefersReducedMotion`'s own doc gives:
 * the setting can change mid-session.
 */
export function useOverlayPhase(open: boolean): {
  phase: OverlayState
  onAnimationEnd: () => void
} {
  const [phase, setPhase] = useState<OverlayState>(open ? "open" : "closed")
  const prevOpenRef = useRef(open)

  useEffect(() => {
    if (open === prevOpenRef.current) return
    prevOpenRef.current = open
    setPhase((current) => overlayPhase(current, open ? "open" : "close", prefersReducedMotion()))
  }, [open])

  function onAnimationEnd() {
    setPhase((current) => overlayPhase(current, "animationend", prefersReducedMotion()))
  }

  return { phase, onAnimationEnd }
}
