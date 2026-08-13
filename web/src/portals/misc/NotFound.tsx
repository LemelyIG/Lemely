/* Hallmark · pre-emit critique: P5 H4 E4 S5 R4 V4 */
import { Link, useRouteError, isRouteErrorResponse } from "react-router-dom"
import { useAuth } from "@/lib/auth/AuthContext"
import { portalPathForRole } from "@/lib/auth/RequireAuth"
import { Button, buttonVariants } from "@/components/ui/button"
import { SkipLink, MAIN_CONTENT_ID } from "@/components/ui/skip-link"

/*
 * P3.1 (DECISION D1.4) · the 404 and the router-level error screen.
 *
 * Before this, an unmatched path rendered react-router's built-in default —
 * an unstyled black-on-white "Unexpected Application Error!" with a stack
 * trace, outside every portal layout, with no route back to anything. The
 * Phase 1 audit recorded it as a strategic omission; what it actually is is
 * the only screen in the product a mistyped link reliably reaches.
 *
 * One component serves both cases because the reader's situation is the same
 * in both: they asked for something and did not get it, and they need a way
 * onward. What differs is only what we can honestly say about why, and
 * `useRouteError` tells us that — a 404 gets the "this page does not exist"
 * reading, anything else gets "something went wrong at our end", because
 * blaming the reader's URL for our thrown exception is a lie.
 *
 * "Somewhere onward" is role-aware. A signed-in student sent to `/` would be
 * bounced through `Root` to `/student` anyway, so the button says where it is
 * actually going. A signed-out reader is offered sign-in, not a portal they
 * cannot enter.
 *
 * Copy per §3.2 item 10: sentence case, active voice, no exclamation mark, no
 * em-dash, no invented reassurance about what we are doing to fix it.
 */

export function NotFound() {
  const error = useRouteError()
  const { session } = useAuth()

  // `isRouteErrorResponse` distinguishes a thrown Response (a real 404 from
  // the router) from an Error thrown during render. An unmatched path arrives
  // here as the former with status 404; `errorElement` catching a component
  // crash arrives as the latter. Rendered outside a router error context
  // (the explicit `path: "*"` route), `useRouteError` returns undefined and
  // the 404 reading is correct.
  const isNotFound =
    error === undefined || error === null || (isRouteErrorResponse(error) && error.status === 404)

  const home = session ? portalPathForRole(session.role) : "/login"
  const homeLabel = session ? "Go to your dashboard" : "Go to sign in"

  return (
    <div className="flex min-h-screen flex-col bg-paper">
      <SkipLink />
      <main
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center gap-6 px-6 py-16 text-center focus:outline-none"
      >
        {/* The notebook register, used where it belongs: a hand-drawn margin
            mark on the one screen in the product whose entire job is "this is
            not the page you wanted". Decoration only, `aria-hidden` — the
            heading below carries the whole meaning on its own (§4: marginalia
            decorates, never carries meaning alone). */}
        <svg
          viewBox="0 0 120 72"
          className="h-16 w-28 text-rule"
          aria-hidden="true"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        >
          <path d="M6 14h108M6 30h74M6 46h96M6 62h58" />
          <path
            d="M78 8c-14 10-30 34-38 52"
            className="text-accent"
            stroke="currentColor"
            strokeWidth="2"
          />
          <path
            d="M40 8c12 14 26 38 34 52"
            className="text-accent"
            stroke="currentColor"
            strokeWidth="2"
          />
        </svg>

        <div className="flex flex-col gap-2">
          <p className="font-mono text-metadata text-ink-faint">
            {isNotFound ? "404" : "Error"}
          </p>
          <h1 className="text-display-md text-ink">
            {isNotFound ? "We couldn't find that page" : "Something went wrong at our end"}
          </h1>
          <p className="text-body-md text-ink-muted">
            {isNotFound
              ? "The link may be out of date, or the address may have a typo in it. Nothing has been lost."
              : "This page failed to load. Your work is not affected, and trying again often resolves it."}
          </p>
        </div>

        <div className="flex flex-wrap items-center justify-center gap-2">
          <Link to={home} className={buttonVariants({ variant: "primary", size: "md" })}>
            {homeLabel}
          </Link>
          {!isNotFound ? (
            <Button variant="secondary" size="md" onClick={() => window.location.reload()}>
              Reload the page
            </Button>
          ) : null}
        </div>
      </main>
    </div>
  )
}
