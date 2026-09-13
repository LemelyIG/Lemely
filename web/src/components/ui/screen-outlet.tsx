import type { ReactNode } from "react"
import { Outlet, useLocation } from "react-router-dom"

/*
 * Packet B2b · gives a screen its entrance (`.lm-screen`'s `lm-in`,
 * DESIGN.md §9) on navigation, and nothing else.
 *
 * Keyed by `location.key`, so the wrapper — and therefore the CSS animation
 * — remounts exactly on navigation, never on an in-screen state change. That
 * is the whole reason this moved off each screen's own root `<div
 * className="lm-screen">`: a screen that swaps its own content (a tab, a
 * filter, a query resolving) does not touch `location.key`, so it no longer
 * replays an entrance meant for "you arrived here", not "something on this
 * page changed".
 *
 * Two exports, not one:
 *
 * - `ScreenOutlet` renders its own `<Outlet/>`, for the four portal layouts
 *   (student, teacher, admin, parent), whose Outlet already sits at one
 *   fixed spot inside a `Suspense`/`ErrorBoundary` stack — a straight
 *   `<Outlet />` → `<ScreenOutlet />` swap there.
 * - `ScreenFrame` takes `children` instead, for the two places that are not
 *   an Outlet host at all: `SettingsFrame`'s content slot (a prop, not a
 *   route match), and the second pathless layout route in `routes.tsx` that
 *   groups every top-level auth/marketing/misc/settings route (the four
 *   portals get their entrance from `ScreenOutlet` inside their own layout
 *   instead, so they are not part of that group).
 */

export function ScreenOutlet() {
  const location = useLocation()
  return (
    <div key={location.key} className="lm-screen" data-screen>
      <Outlet />
    </div>
  )
}

export function ScreenFrame({ children }: { children: ReactNode }) {
  const location = useLocation()
  return (
    <div key={location.key} className="lm-screen" data-screen>
      {children}
    </div>
  )
}
