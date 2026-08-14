/* Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4 */
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
 *
 * ── P4.10 · the 404 inside a portal keeps its portal ───────────────────────
 *
 * This file's own note, and `routes.tsx`'s, both recorded the same known gap:
 * an unmatched path *within* a portal (`/student/nonsense`) fell through to the
 * top-level `path: "*"`, because each portal route enumerates its children and
 * matches none of them. The reader lost the sidebar, the breadcrumb trail and
 * the header on a mistyped URL, and was handed a full-screen dead end in place
 * of the app they were already inside. Both notes deferred it to "once each
 * portal layout is its final shape", which after surface 9 they all are.
 *
 * So the screen splits in two. `NotFoundBody` is everything the reader
 * actually reads; `NotFound` wraps it in a standalone frame for the top-level
 * routes, and `PortalNotFound` is the same body mounted as a catch-all child
 * inside each portal, where the layout already provides the frame.
 *
 * **The split exists because of the landmarks, not the styling.** A portal
 * layout already renders a `<SkipLink>` and a `<main id={MAIN_CONTENT_ID}>`.
 * Dropping the standalone screen inside one would put two `<main>` landmarks
 * and two elements with the same id on the page, so a skip link would jump to
 * whichever the browser found first. Nothing visual would look wrong, which is
 * exactly why it is worth a comment.
 *
 * **Render errors are deliberately still full-screen.** `errorElement` stays on
 * the top-level routes only. A screen that threw may well have thrown from the
 * chrome around it, and re-rendering that chrome to frame the report is how a
 * crash becomes a crash loop. An unmatched path carries no such doubt: nothing
 * failed, the reader simply asked for a page that is not there, and the portal
 * around them is known good.
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

  return (
    <div className="flex min-h-screen flex-col bg-paper">
      <SkipLink />
      <main
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center gap-6 px-6 py-16 text-center focus:outline-none"
      >
        <NotFoundBody isNotFound={isNotFound} session={session} />
      </main>
    </div>
  )
}

/**
 * The same screen, mounted as a portal's catch-all child.
 *
 * No frame, no skip link and no `<main>`: the portal layout around it already
 * renders all three, and a second copy of each is the defect this split exists
 * to avoid (see the module note). The reader keeps the sidebar, the header and
 * the trail, so a mistyped URL inside the app leaves them still inside the app.
 *
 * Always the 404 reading. This is only ever reached by a path the portal's own
 * children did not match, which is a fact about the URL and never an error.
 */
export function PortalNotFound() {
  const { session } = useAuth()
  return (
    <div className="mx-auto flex w-full max-w-md flex-col items-center justify-center gap-6 py-12 text-center">
      <NotFoundBody isNotFound session={session} />
    </div>
  )
}

/** Everything the reader reads, in either frame. */
function NotFoundBody({
  isNotFound,
  session,
}: {
  isNotFound: boolean
  session: { role: string } | null
}) {
  const home = session ? portalPathForRole(session.role) : "/login"
  const homeLabel = session ? "Go to your dashboard" : "Go to sign in"

  return (
    <>
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
          {/* P4.10. This was `font-mono text-metadata`, which is two defects
              at once: `text-metadata` is a build-era compat rung, and its
              Study Notebook replacement `text-data-sm` already names the data
              face, so the pair set `font-family` twice on one element and
              resolved by stylesheet order rather than by intent (D4.2's
              `MarkDisplay` finding). Neither was visible until this file was
              added to `MIGRATED_FILES` — it was written in P3.1, before that
              list existed, and no gate had ever read it. */}
          <p className="text-data-sm text-ink-faint">{isNotFound ? "404" : "Error"}</p>
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
    </>
  )
}
