/* Hallmark · pre-emit critique: P5 H4 E5 S5 R4 V4 */
import { useLayoutEffect } from "react"
import { Outlet, ScrollRestoration, useNavigationType } from "react-router-dom"
import { scrollRestorationKey } from "@/lib/nav/scrollRestorationKey"
import { navigationDirection } from "@/lib/nav/navigationDirection"

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
export function RootOutlet() {
  const navigationType = useNavigationType()

  useLayoutEffect(() => {
    document.documentElement.dataset.direction = navigationDirection(navigationType)
  }, [navigationType])

  return (
    <>
      <Outlet />
      <ScrollRestoration getKey={(location) => scrollRestorationKey(location)} />
    </>
  )
}
