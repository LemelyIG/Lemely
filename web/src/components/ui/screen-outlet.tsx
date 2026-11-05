/* Hallmark · pre-emit critique: P5 H4 E4 S4 R3 V4 */
import { Suspense, useEffect, useRef, type ReactNode } from "react"
import {
  Outlet,
  UNSAFE_RouteContext,
  useLocation,
  useNavigate,
  useResolvedPath,
  useRoutes,
  type RouteObject,
} from "react-router-dom"
import { screenKey } from "@/lib/nav/screenKey"
import {
  backgroundState,
  isWithinBase,
  readBackgroundLocation,
  resolveBackground,
  type BackgroundLocation,
} from "@/lib/nav/backgroundLocation"

/*
 * Packet B2b · gives a screen its entrance (`.lm-screen`'s `lm-in`,
 * DESIGN.md §9) on navigation, and nothing else.
 *
 * Keyed by `screenKey` — the URL, not `location.key` — so the wrapper (and
 * therefore the CSS animation) remounts exactly on navigation, never on an
 * in-screen state change. That is the whole reason this moved off each
 * screen's own root `<div className="lm-screen">`: a screen that swaps its own
 * content (a tab, a filter, a query resolving) does not change the URL, so it
 * no longer replays an entrance meant for "you arrived here", not "something
 * on this page changed".
 *
 * Not `location.key`: that is fresh per history *entry*, and an overlay
 * opening pushes one at the URL the reader is already on — which remounted
 * this subtree and destroyed the screen state holding the dialog open. See
 * `lib/nav/screenKey.ts`.
 *
 * Two exports, not one:
 *
 * - `ScreenOutlet` renders its own `<Outlet/>`, for the four portal layouts
 *   (student, teacher, admin, parent), whose Outlet already sits at one
 *   fixed spot inside a `Suspense`/`ErrorBoundary` stack — a straight
 *   `<Outlet />` → `<ScreenOutlet />` swap there. With `overlay`, it also
 *   hosts one route-backed dialog over the current page (the teacher
 *   portal's Settings).
 * - `ScreenFrame` takes `children` instead, for the two places that are not
 *   an Outlet host at all: `SettingsFrame`'s content slot (a prop, not a
 *   route match), and the second pathless layout route in `routes.tsx` that
 *   groups every top-level auth/marketing/misc/settings route (the four
 *   portals get their entrance from `ScreenOutlet` inside their own layout
 *   instead, so they are not part of that group).
 */

/** A route-backed overlay a portal layout hosts (Settings, for the teacher
 * portal): see `OverlayScreenOutlet` below. */
export interface ScreenOverlay {
  /** The layout's child routes, minus the overlay route itself. */
  routes: RouteObject[]
  /** Paths at and under this render as the overlay. */
  overlayBase: string
  /** The page underneath on a direct load. */
  fallbackPath: string
}

export function ScreenOutlet({ overlay }: { overlay?: ScreenOverlay } = {}) {
  if (overlay) return <OverlayScreenOutlet {...overlay} />
  return <PlainScreenOutlet />
}

function PlainScreenOutlet() {
  const location = useLocation()
  return (
    <div key={screenKey(location)} className="lm-screen" data-screen>
      <Outlet />
    </div>
  )
}

/*
 * A portal layout's screen slot that knows about one route-backed overlay.
 *
 * Outside `overlayBase` it is exactly `ScreenOutlet`: the matched screen in a
 * keyed `lm-screen` wrapper. Inside it (e.g. `/teacher/settings/*`), it
 * renders the page the reader came from in that same slot, matched from
 * `routes` against the background location, and the overlay route (the
 * real `<Outlet />`) on top.
 *
 * Which page sits underneath is `resolveBackground`'s call: router state
 * first, then the last page shown in this session, then `fallbackPath`.
 * Links that open the overlay do not have to know about any of this. When a
 * plain link opens it, the remembered page is written back into the entry's
 * state (a replace, same URL), so a refresh keeps the same page underneath
 * and closing can step back to it.
 */
function OverlayScreenOutlet({ routes, overlayBase, fallbackPath }: ScreenOverlay) {
  const location = useLocation()
  const navigate = useNavigate()
  const inOverlay = isWithinBase(location.pathname, overlayBase)
  const remembered = useRef<BackgroundLocation | null>(null)
  // The layout's own path ("/teacher"), which `routes` are relative to.
  const layoutPath = useResolvedPath("").pathname

  if (!inOverlay) {
    remembered.current = {
      pathname: location.pathname,
      search: location.search,
      hash: location.hash,
    }
  }

  const background = resolveBackground({
    state: location.state,
    remembered: remembered.current,
    overlayBase,
    fallbackPath,
  })

  useEffect(() => {
    if (!inOverlay || background.source !== "remembered") return
    if (readBackgroundLocation(location.state)) return
    navigate(
      { pathname: location.pathname, search: location.search, hash: location.hash },
      { replace: true, state: backgroundState(background.location) },
    )
  }, [inOverlay, background.source, background.location, location, navigate])

  return (
    <>
      <div
        key={screenKey(inOverlay ? background.location : location)}
        className="lm-screen"
        data-screen
      >
        {inOverlay ? (
          <BackgroundScreen
            routes={routes}
            basePath={layoutPath}
            location={background.location}
          />
        ) : (
          <Outlet />
        )}
      </div>
      {inOverlay ? (
        // Its own boundary, so loading the dialog's chunk never blanks the
        // page underneath it.
        <Suspense fallback={null}>
          <Outlet />
        </Suspense>
      ) : null}
    </>
  )
}


export function ScreenFrame({ children }: { children: ReactNode }) {
  const location = useLocation()
  return (
    <div key={screenKey(location)} className="lm-screen" data-screen>
      {children}
    </div>
  )
}

/**
 * The page underneath an overlay, matched from the layout's child routes.
 *
 * Matched from a clean route context with the routes mounted under the
 * layout's absolute path, rather than from inside the layout's own match:
 * `useRoutes` there would treat the layout as a parent route whose path
 * lacks a trailing `*` and warn on every overlay open, though the match
 * itself is the same.
 */
function BackgroundScreen({
  routes,
  basePath,
  location,
}: {
  routes: RouteObject[]
  basePath: string
  location: BackgroundLocation
}) {
  return (
    <UNSAFE_RouteContext.Provider value={{ outlet: null, matches: [], isDataRoute: false }}>
      <BackgroundRoutes routes={routes} basePath={basePath} location={location} />
    </UNSAFE_RouteContext.Provider>
  )
}

function BackgroundRoutes({
  routes,
  basePath,
  location,
}: {
  routes: RouteObject[]
  basePath: string
  location: BackgroundLocation
}) {
  return useRoutes([{ path: basePath, children: routes }], location)
}
