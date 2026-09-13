import { Outlet, ScrollRestoration } from "react-router-dom"
import { scrollRestorationKey } from "@/lib/nav/scrollRestorationKey"

/*
 * Packet B2a · the one pathless layout route wrapping every top-level route
 * in `routes.tsx`.
 *
 * `<ScrollRestoration>` must render inside a data-router route to work at
 * all — `main.tsx` renders above `<RouterProvider>`, so it has no route to
 * hang this on without a wrapper like this one. Mounted exactly once, here,
 * rather than in every portal layout: scroll restoration is a single
 * router-wide concern, not a per-portal one.
 */
export function RootOutlet() {
  return (
    <>
      <Outlet />
      <ScrollRestoration getKey={(location) => scrollRestorationKey(location)} />
    </>
  )
}
