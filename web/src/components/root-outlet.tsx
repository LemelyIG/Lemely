/* Hallmark · pre-emit critique: P5 H4 E5 S5 R4 V4 */
import { useEffect, useLayoutEffect } from "react"
import { Outlet, ScrollRestoration, useLocation, useNavigationType } from "react-router-dom"
import { createScrollKeyer } from "@/lib/nav/scrollRestorationKey"
import { navigationDirection } from "@/lib/nav/navigationDirection"
import { stateDirection } from "@/lib/nav/navDirectionState"
import { consumeSwipeNav } from "@/lib/nav/edgeSwipeBack"
import { installSnapshotSessionGuard, dropSnapshotsFrom } from "@/lib/nav/pageSnapshotCapture"

/*
 * Packet B2a · the one pathless layout route wrapping every top-level route
 * in `routes.tsx`.
 *
 * `<ScrollRestoration>` must render inside a data-router route to work at
 * all — `main.tsx` renders above `<RouterProvider>`, so it has no route to
 * hang this on without a wrapper like this one. Mounted exactly once, here,
 * rather than in every portal layout: scroll restoration is a single
 * router-wide concern, not a per-portal one.
 *
 * Packet B2b adds `html[data-direction]`, read by `index.css`'s
 * `::view-transition-*` rules to pick which way a screen slides. A layout
 * effect, not a plain effect: it must land before the browser paints the
 * transition's new frame, which a passive effect (queued after paint) can
 * race. Set on `<html>` rather than kept in React state because
 * `document.startViewTransition` (react-router's `viewTransition` prop
 * triggers it) reads the DOM synchronously when it captures the "before"
 * snapshot — a value that only exists in a React tree is invisible to it.
 */
/** One keyer for the app's lifetime: it remembers the last page key so an
 * overlay route keys as the page underneath (`createScrollKeyer`). */
const scrollKey = createScrollKeyer()

export function RootOutlet() {
  const navigationType = useNavigationType()
  const { key, state } = useLocation()
  // A PUSH that means "back" (re-tapping a tab to pop to its root) says so in its location state.
  const explicit = stateDirection(state)

  // Keyed on the location key so the one-shot swipe flag is read (and cleared) on every
  // navigation, even a replace to the same navigation type; it cannot go stale. The
  // explicit direction comes from the location state, which only changes with the key.
  useLayoutEffect(() => {
    document.documentElement.dataset.direction = consumeSwipeNav() ? "swipe" : (explicit ?? navigationDirection(navigationType))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigationType, key])

  // Native frame Task 12b: the swipe-back underlay shows the page being left, cloned in the router's
  // navigate middleware (registered in App.tsx). Here: a push overwrites the forward history,
  // and snapshots never outlive the session.
  useEffect(() => installSnapshotSessionGuard(), [])
  useLayoutEffect(() => {
    if (navigationType !== "PUSH") return
    const idx = window.history.state?.idx
    if (typeof idx === "number") dropSnapshotsFrom(idx)
  }, [navigationType, key])

  return (
    <>
      <Outlet />
      <ScrollRestoration getKey={scrollKey} />
    </>
  )
}
