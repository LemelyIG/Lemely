/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Link } from "react-router-dom"
import { useAuth } from "@/lib/auth/AuthContext"
import { portalPathForRole, loginPathForRole } from "@/lib/auth/RequireAuth"
import { peekExpiredRole } from "@/lib/auth/storage"
import { Button, buttonVariants } from "@/components/ui/button"
import { SkipLink, MAIN_CONTENT_ID } from "@/components/ui/skip-link"
import { Doodle } from "@/components/ui/doodle"
import { Mark } from "@/components/ui/mark"
import { cn } from "@/lib/utils"
import { withNext } from "@/lib/nextPath"
import {
  ACTION_LABEL,
  FULL_PAGE_STATE_COPY,
  type FullPageStateAction,
  type FullPageStateVariant,
} from "./fullPageStateCopy"

/*
 * The nine full-page states, in the one frame `NotFound.tsx` established
 * (PR 2 part A1). `NotFound`/`PortalNotFound` are now built on this; every
 * other full-page state (offline, a stale build, a dropped session, a role
 * mismatch, the marking service down, a rate limit, a stalled slow load) gets
 * the same frame and the same action grammar instead of nine one-off screens.
 *
 * **Two frames, one reason** (carried over from `NotFound.tsx`'s original
 * note, which explains it fully): a portal layout already renders a
 * `<SkipLink>` and a `<main id={MAIN_CONTENT_ID}>`, so a state reached
 * *inside* a portal (offline, a role mismatch on a nested route) must not
 * render a second copy of either — two `<main>` landmarks and a duplicate id
 * would leave a skip link jumping to whichever the browser found first. A
 * state reached *before* or *outside* any portal (signed out, a crashed
 * top-level route, a stale build caught before hydration finishes) needs the
 * standalone frame to exist at all.
 *
 * **Copy lives in `fullPageStateCopy.ts`, not here.** This file only turns
 * that table's four action kinds into real controls: `home` and `sign-in` are
 * session-aware (`useAuth()` + `portalPathForRole`, exactly as the pre-split
 * `NotFoundBody` resolved them); `reload` and `retry` are fixed. No
 * `role="alert"` on the frame — the heading already carries the meaning, and
 * wrapping the whole panel in an assertive live region would announce the
 * kicker and body as one indistinguishable block on top of whatever the
 * caller already announced getting here.
 *
 * **`sign-in` resolves through `loginPathForRole`, not a bare `/login`**
 * (SHOULD-FIX 3, PR 2 adversarial review). A parent whose session expired
 * used to land on the email+password form here regardless — no field on it
 * is one they can fill in, since parents authenticate by phone OTP at
 * `/login/parent`. With a live session, the role to resolve is
 * `session.role`; the one variant this action fires from with `session ===
 * null` is `session-ended`, where `SessionEnded` passes `expiredRole` down
 * from `takeSessionExpired()` — the role of the session that just died,
 * recorded by `markSessionExpired` at the moment it did.
 *
 * The three variant "extras" (offline's waiting line, service-trouble's
 * health row, too-many-requests' countdown) are the one place this component
 * is not pure presentation: it reads `health`/`retryAfterSeconds` and formats
 * them, but never starts a timer or polls anything itself — the caller owns
 * that and re-renders with a fresh prop, so this stays a plain function of its
 * props like every other view in the kit.
 */

export interface FullPageStateProps {
  variant: FullPageStateVariant
  /** `standalone`: full frame, own `<SkipLink>`/`<main>`, for a route reached
   * outside any portal. `portal`: frameless, for a portal's own catch-all or
   * error boundary, which already renders both. */
  frame: "standalone" | "portal"
  /** Wires the `retry` action, when the variant's copy uses one. Omitting it
   * omits the retry control entirely rather than rendering a dead button. */
  onRetry?: () => void
  /** Countdown for `too-many-requests`' "Try again in m:ss" line and for
   * disabling the retry control while it is still counting down. The caller
   * re-renders with a lower value each second; this component runs no timer
   * of its own. */
  retryAfterSeconds?: number
  /** `service-trouble`'s status row. Omitted entirely when not given, rather
   * than rendered in an "unknown, not checked yet" default state nobody
   * asked for. */
  health?: { status: "unknown" | "responding" | "not-responding"; checkedSecondsAgo: number | null }
  /** Where `sign-in` should return to after a successful login. */
  returnTo?: string
  /**
   * The role of the session that just expired, when this state was reached
   * because of one and `useAuth()`'s own `session` is already `null` — the
   * `session-ended` variant's only caller, `SessionEnded`, is the one place
   * that has this (from `takeSessionExpired()`) and passes it down. Ignored
   * by every other variant, and by `session-ended` itself whenever a live
   * `session` is present to resolve `sign-in` from instead.
   */
  expiredRole?: string
}

const HEALTH_DOT: Record<"unknown" | "responding" | "not-responding", string> = {
  responding: "bg-ok",
  "not-responding": "bg-warn",
  unknown: "bg-rule",
}

const HEALTH_LABEL: Record<"unknown" | "responding" | "not-responding", string> = {
  responding: "responding",
  "not-responding": "not responding",
  unknown: "unknown",
}

/** `retryAfterSeconds` as "m:ss". Negative or fractional input is clamped and
 * rounded rather than trusted, since the caller is expected to be counting
 * down live from a server-supplied value. */
function formatCountdown(totalSeconds: number): string {
  const clamped = Math.max(0, Math.round(totalSeconds))
  const minutes = Math.floor(clamped / 60)
  const seconds = clamped % 60
  return `${minutes}:${String(seconds).padStart(2, "0")}`
}

function renderAction(
  action: FullPageStateAction,
  buttonVariant: "primary" | "secondary",
  ctx: {
    home: string
    homeLabel: string
    signIn: string
    returnTo?: string
    onRetry?: () => void
    retryDisabled: boolean
  },
) {
  const linkClass = buttonVariants({ variant: buttonVariant, size: "md" })

  if (action === "home") {
    return (
      <Link key="home" to={ctx.home} className={linkClass}>
        {ctx.homeLabel}
      </Link>
    )
  }
  if (action === "sign-in") {
    // `ctx.signIn` is already `loginPathForRole`'s answer (`/login` or
    // `/login/parent`) — `withNext` only has to append `?next=`, the same
    // allowlisted append every other `?next=` carrier in this app uses
    // (`RequireAuth`, `SessionEnded`), rather than this one control building
    // its own query string by hand as it used to.
    const to = withNext(ctx.signIn, ctx.returnTo ?? null)
    return (
      <Link key="sign-in" to={to} className={linkClass}>
        {ACTION_LABEL["sign-in"]}
      </Link>
    )
  }
  if (action === "reload") {
    return (
      <Button key="reload" variant={buttonVariant} size="md" onClick={() => window.location.reload()}>
        {ACTION_LABEL.reload}
      </Button>
    )
  }
  // action === "retry". Omitted entirely without a handler: a retry button
  // that does nothing is worse than no button, and every caller that wants
  // one has an obvious retry to wire (refetch, reconnect, re-check health).
  if (!ctx.onRetry) return null
  return (
    <Button
      key="retry"
      variant={buttonVariant}
      size="md"
      disabled={ctx.retryDisabled}
      onClick={ctx.onRetry}
    >
      {ACTION_LABEL.retry}
    </Button>
  )
}

/** The frameless inner content, for a caller that supplies its own frame
 * (a modal, a boundary that is neither of the two shapes above). */
export function FullPageStateBody({
  variant,
  onRetry,
  retryAfterSeconds,
  health,
  returnTo,
  expiredRole,
}: Omit<FullPageStateProps, "frame">) {
  const copy = FULL_PAGE_STATE_COPY[variant]
  const { session } = useAuth()
  const home = session ? portalPathForRole(session.role) : "/login"
  const homeLabel = session ? "Go to your dashboard" : "Go to sign in"
  // A live session's own role wins when there is one. With none, the role
  // of the session that just expired decides between the email form and the
  // parent's phone sign-in: passed in by `SessionEnded` (which consumed the
  // flag), or read off the still-pending flag for a caller that did not (a
  // route-level 401 reaching `route-error.tsx`, a `RequireAuth` no-access
  // screen rendered mid-expiry). `peekExpiredRole` is a plain read of a
  // module value, never a consume, so it is safe in a render body.
  const signIn = loginPathForRole(session ? session.role : (expiredRole ?? peekExpiredRole()))
  const retryDisabled = typeof retryAfterSeconds === "number" && retryAfterSeconds > 0
  const ctx = { home, homeLabel, signIn, returnTo, onRetry, retryDisabled }

  return (
    <>
      {variant === "slow-load" ? <Mark size={96} animated /> : <Doodle kind={variant} />}

      <div className="flex flex-col gap-2">
        {copy.kicker ? <p className="text-data-sm text-ink-faint">{copy.kicker}</p> : null}
        <h1 className="text-display-md text-ink">{copy.heading}</h1>
        <p className="text-body-md text-ink-muted">{copy.body}</p>
      </div>

      {variant === "offline" ? (
        // Polite, not assertive: connectivity dropping is a fact of the
        // moment, not an event to interrupt over (the same reasoning
        // `state-views.tsx` gives `OfflineState`'s own role).
        <div role="status" className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-warn animate-lm-pulse" aria-hidden="true" />
          <p className="text-data-sm text-ink-muted">Waiting for a connection</p>
        </div>
      ) : null}

      {variant === "service-trouble" && health ? (
        <div className="flex items-center gap-2 rounded-md border border-rule bg-paper-raised px-3 py-2">
          <span className={cn("h-2 w-2 rounded-full", HEALTH_DOT[health.status])} aria-hidden="true" />
          <p className="text-data-sm text-ink-muted">
            Marking service · {HEALTH_LABEL[health.status]} ·{" "}
            {health.checkedSecondsAgo === null
              ? "not checked yet"
              : `checked ${health.checkedSecondsAgo} s ago`}
          </p>
        </div>
      ) : null}

      {variant === "too-many-requests" && retryAfterSeconds !== undefined ? (
        <p className="text-data-md text-ink-muted">Try again in {formatCountdown(retryAfterSeconds)}</p>
      ) : null}

      {copy.primary || copy.secondary || (variant === "crash" && onRetry) ? (
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
          {copy.primary ? renderAction(copy.primary, "primary", ctx) : null}
          {copy.secondary ? renderAction(copy.secondary, "secondary", ctx) : null}
          {/*
           * PR 2 part A2 · `crash`'s copy fixes "home" + "reload" (see
           * `fullPageStateCopy.ts`), which is right for a route the reader
           * merely navigated to. `PortalErrorFallback` reaches this variant
           * from inside an `ErrorBoundary`, though, where `reset()` re-renders
           * the crashed content in place — a real third option a bare page
           * reload cannot offer (it keeps the reader's place in the app
           * instead of a full round trip). Rendered only when a caller
           * actually supplied `onRetry`, so a route-level crash with no
           * `reset` to call keeps exactly the two actions the copy table
           * names.
           */}
          {variant === "crash" && onRetry ? renderAction("retry", "secondary", ctx) : null}
        </div>
      ) : null}
    </>
  )
}

export function FullPageState({
  variant,
  frame,
  onRetry,
  retryAfterSeconds,
  health,
  returnTo,
  expiredRole,
}: FullPageStateProps) {
  const body = (
    <FullPageStateBody
      variant={variant}
      onRetry={onRetry}
      retryAfterSeconds={retryAfterSeconds}
      health={health}
      returnTo={returnTo}
      expiredRole={expiredRole}
    />
  )

  if (frame === "standalone") {
    return (
      <div className="flex min-h-screen flex-col bg-paper">
        <SkipLink />
        <main
          id={MAIN_CONTENT_ID}
          tabIndex={-1}
          className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center gap-6 px-6 py-16 text-center focus:outline-none"
        >
          {body}
        </main>
      </div>
    )
  }

  return (
    <div className="mx-auto flex w-full max-w-md flex-col items-center justify-center gap-6 py-12 text-center">
      {body}
    </div>
  )
}
