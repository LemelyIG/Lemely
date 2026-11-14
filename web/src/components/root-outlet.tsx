/* Hallmark · pre-emit critique: P5 H4 E5 S5 R4 V4 */
import { useEffect, useLayoutEffect } from "react"
import { Outlet, ScrollRestoration, useLocation, useNavigationType } from "react-router-dom"
import { createScrollKeyer } from "@/lib/nav/scrollRestorationKey"
import { navigationDirection } from "@/lib/nav/navigationDirection"
import { stateDirection } from "@/lib/nav/navDirectionState"
import { consumeSwipeNav } from "@/lib/nav/edgeSwipeBack"
import { captureCurrentPage, pageSnapshots, snapshotsEnabled } from "@/lib/nav/pageSnapshotCapture"

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

/** How long a page is left to load its data before it is cloned. */
const SETTLE_MS = 400

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

  // Native frame Task 12b: file the page under its history index for the swipe-back underlay.
  // The new location is already in the DOM here, so the page is cloned once it has settled; a
  // link click refreshes the entry just before the page leaves (below).
  useLayoutEffect(() => {
    if (navigationType === "PUSH") {
      const idx = window.history.state?.idx
      if (typeof idx === "number") pageSnapshots.dropFrom(idx)
    }
    if (!snapshotsEnabled()) return
    let raf = 0
    const timer = window.setTimeout(() => {
      raf = requestAnimationFrame(captureCurrentPage)
    }, SETTLE_MS)
    return () => {
      window.clearTimeout(timer)
      cancelAnimationFrame(raf)
    }
  }, [navigationType, key])

  useEffect(() => {
    const beforeLeave = (event: MouseEvent) => {
      if (event.target instanceof Element && event.target.closest("a[href]")) captureCurrentPage()
    }
    document.addEventListener("click", beforeLeave, true)
    return () => document.removeEventListener("click", beforeLeave, true)
  }, [])

  return (
    <>
      <Outlet />
      <ScrollRestoration getKey={scrollKey} />
    </>
  )
}
