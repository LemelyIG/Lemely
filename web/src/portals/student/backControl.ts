import { useLayoutEffect, useReducer } from "react"
import { useLocation } from "react-router-dom"
import type { Crumb } from "@/components/ui/breadcrumbs"
import { backTarget } from "@/lib/nav/backTarget"

/*
 * The student phone's one back control.
 *
 * A drilled-in page whose trail has a linked ancestor draws that ancestor as a
 * "‹ Parent" link under the bar (Breadcrumbs, below `sm`). The bar's own Back
 * button used to sit beside it, so a phone showed two back controls and the bar
 * title was squeezed. The trail position keeps the single control, and it keeps
 * the bar Back's behaviour (history back, else the parent), so a page reached
 * from somewhere other than its parent still goes back to where the student came
 * from. The label says where it leads. The rule reads the trail only: no route
 * list, so a page that gains a linked parent gets the control for free.
 */

export type BackPlan =
  /** No linked ancestor: today's markup, the bar's Back button and the plain trail. */
  | { control: "bar" }
  | {
      control: "trail"
      /** Visible text: the parent's name when the control leads there, else "Back". */
      label: string
      /** Accessible name, naming the destination ("Back to Practice" / "Back"). */
      ariaLabel: string
      /** "history" goes back through in-app history; "route" is the deep-link fallback. */
      action: "history" | "route"
      /** The nearest linked ancestor: the fallback `useBackAction` navigates to without history. */
      parentTo: string
    }

/** The nearest ancestor that has a route, the one Breadcrumbs draws on a phone. */
export function linkedParent(trail: readonly Crumb[]): (Crumb & { to: string }) | null {
  for (let i = trail.length - 2; i >= 0; i -= 1) {
    const crumb = trail[i]
    if (crumb.to !== undefined) return { ...crumb, to: crumb.to }
  }
  return null
}

const pathOf = (to: string) => to.split(/[?#]/)[0].replace(/\/+$/, "") || "/"

/**
 * Which control a student detail page shows on a phone.
 *
 * @param previousPath the in-app page one step back in history, when known
 * @param hasHistory   whether this tab has an earlier entry to go back to (`backTarget`'s "history")
 */
export function decideBackPlan(input: {
  trail: readonly Crumb[]
  previousPath: string | null
  hasHistory: boolean
}): BackPlan {
  const parent = linkedParent(input.trail)
  if (!parent) return { control: "bar" }
  const toParent = { label: parent.label, ariaLabel: `Back to ${parent.label}`, parentTo: parent.to }
  if (!input.hasHistory) return { control: "trail", action: "route", ...toParent }
  // History back lands on the parent only when the previous page is the parent. Unknown (a reload keeps the
  // entry index but not this memory) is not known to be the parent, so it is the plain "Back".
  if (input.previousPath !== null && pathOf(input.previousPath) === pathOf(parent.to)) {
    return { control: "trail", action: "history", ...toParent }
  }
  return { control: "trail", action: "history", label: "Back", ariaLabel: "Back", parentTo: parent.to }
}

/** The router's index of the current entry in this tab's history, null outside a browser. */
export function currentHistoryIdx(): number | null {
  if (typeof window === "undefined") return null
  const idx = (window.history.state as { idx?: unknown } | null)?.idx
  return typeof idx === "number" ? idx : null
}

/**
 * Remembers the page shown at each history index, so the page one entry back is
 * known after a push, a pop or a replace alike. In memory only: a reload forgets it.
 */
export function previousPathAt(seen: ReadonlyMap<number, string>, idx: number | null): string | null {
  return idx === null ? null : (seen.get(idx - 1) ?? null)
}

export interface HistoryMemory {
  key: string | null
  idx: number | null
  seen: ReadonlyMap<number, string>
}

/** Record only committed router locations; a push or replace overwrites its index. */
export function recordHistoryLocation(state: HistoryMemory, event: { key: string; idx: number | null; pathname: string }): HistoryMemory {
  const seen = new Map(state.seen)
  if (event.idx !== null) seen.set(event.idx, event.pathname)
  return { key: event.key, idx: event.idx, seen }
}

/** The trail follows the page beneath a dialog; history records the actual URL. */
export function useStudentBackPlan(pathname: string, trail: readonly Crumb[]): BackPlan {
  const { key } = useLocation()
  const [history, record] = useReducer(recordHistoryLocation, { key: null, idx: null, seen: new Map<number, string>() })
  useLayoutEffect(() => {
    record({ key, idx: currentHistoryIdx(), pathname })
  }, [key, pathname])
  const committed = history.key === key
  return decideBackPlan({
    trail,
    previousPath: committed ? previousPathAt(history.seen, history.idx) : null,
    hasHistory: !committed || backTarget(history.idx, "/").kind === "history",
  })
}
