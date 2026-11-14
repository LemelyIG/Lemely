import { matchRoutes, type RouteObject } from "react-router-dom"
import { readPlatform } from "@/lib/platform"
import { PHONE_MEDIA, isNativeFrame } from "@/lib/useNativeFrame"
import type { NavigateMiddleware, NavigateOptions } from "@/lib/nav/navigateMiddleware"

/*
 * Native frame · every drill-down pushes on a phone.
 *
 * About 180 `<Link>`s and a hundred `navigate()` calls exist, but only the shell chrome passed
 * `viewTransition`, so most drill-downs swapped instantly on iOS and Android. Rather than sprinkle
 * the prop everywhere (and forget it on the next screen), this middleware makes "push" the default
 * for a phone running the native frame, and the call sites state exceptions.
 *
 * It runs BEFORE the swipe-back snapshot capture (a later `installNavigateMiddleware` call wraps
 * outside an earlier one), so the capture sees the options as they will actually run.
 */

/** Everything the decision needs, read once per call so the rule is a pure function. */
export interface PushDecisionInput {
  to: unknown
  options: NavigateOptions | undefined
  /** `window.location.pathname` when the call is made. */
  currentPathname: string
  /** `window.history.state?.usr`: the location state of the entry being left. */
  currentState: unknown
  /** Phone width and an iOS or Android platform, read live. */
  nativeFrame: boolean
  /** True when the destination route's `handle.viewTransition` is `false`. */
  destinationOptsOut: (pathname: string) => boolean
}

function hasKey(state: unknown, key: string): boolean {
  return typeof state === "object" && state !== null && Boolean((state as Record<string, unknown>)[key])
}

function trimSlash(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname
}

/**
 * The absolute pathname a `to` points at, `current` when it names none (a `?filter=` or `#hash`
 * only), or null when it is a relative path (resolved against the route, which this layer cannot
 * see). A relative path is treated as a pathname change with no destination to check.
 */
export function targetPathname(to: unknown, current: string): string | null {
  let raw: string | undefined
  if (typeof to === "string") raw = to.split(/[?#]/, 1)[0]
  else if (typeof to === "object" && to !== null) {
    const pathname = (to as { pathname?: unknown }).pathname
    raw = typeof pathname === "string" ? pathname : ""
  } else return null
  if (raw === "") return current
  if (raw.startsWith("/")) return trimSlash(raw)
  return null
}

/** Should this navigation push with a view transition when the caller said nothing? */
export function shouldDefaultToPush(input: PushDecisionInput): boolean {
  const { to, options, currentPathname, currentState, nativeFrame, destinationOptsOut } = input
  if (!nativeFrame) return false
  // An explicit choice, either way, is never overridden.
  if (options?.viewTransition !== undefined) return false
  if (typeof to === "number") return false
  if (options?.replace) return false
  // A navigation made from inside an open dialog or sheet dismisses it: native iOS closes the
  // sheet and shows the destination, with no push behind it.
  if (hasKey(currentState, "lemelyDialog") || hasKey(options?.state, "lemelyDialog")) return false
  // A route-backed overlay opens as a dialog over the page, it is not a drill-down.
  if (hasKey(options?.state, "backgroundLocation")) return false
  const target = targetPathname(to, currentPathname)
  if (target !== null && trimSlash(target) === trimSlash(currentPathname)) return false
  if (target !== null && destinationOptsOut(target)) return false
  return true
}

/** True when the route that renders `pathname` carries `handle.viewTransition: false`. */
export function routeOptsOutOfTransitions(routes: RouteObject[], pathname: string): boolean {
  const matches = matchRoutes(routes, pathname)
  if (!matches) return false
  const handle = matches[matches.length - 1].route.handle as { viewTransition?: unknown } | undefined
  return handle?.viewTransition === false
}

/** The middleware, bound to the router whose route table decides the per-route opt-out. */
export function createNativePushDefault(router: { routes: RouteObject[] }): NavigateMiddleware {
  return (to, options, next) => {
    let push = false
    try {
      push = shouldDefaultToPush({
        to,
        options,
        currentPathname: window.location.pathname,
        currentState: window.history.state?.usr,
        nativeFrame: isNativeFrame(readPlatform(), window.matchMedia(PHONE_MEDIA).matches),
        destinationOptsOut: (pathname) => routeOptsOutOfTransitions(router.routes, pathname),
      })
    } catch (error) {
      // A navigation must never fail because the default could not be worked out.
      if (import.meta.env.DEV) console.error("nativePushDefault", error)
    }
    return next(to, push ? { ...options, viewTransition: true } : options)
  }
}
