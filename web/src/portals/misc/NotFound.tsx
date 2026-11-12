/* Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4 */
import { useRouteError, isRouteErrorResponse } from "react-router-dom"
import { FullPageState } from "./FullPageState"

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
 * ── PR 2 part A1 · rebuilt on `FullPageState` ───────────────────────────────
 *
 * This file used to own the frame, the doodle SVG and the copy directly. All
 * three moved out: the frame split (standalone vs. portal) and the copy/action
 * grammar are now shared by every full-page state, not just these two, and
 * live in `FullPageState.tsx`/`fullPageStateCopy.ts`. What stays here is only
 * the one thing genuinely specific to this screen — reading `useRouteError`
 * to decide which of the two readings applies — plus this note, since the
 * reasoning below (why two exports, why the split is about landmarks and not
 * styling, why a render error is still full-screen) is still the whole
 * explanation for why `NotFound`/`PortalNotFound` exist as two call sites
 * rather than one.
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
 * So the screen splits in two. `NotFound` renders `FullPageState` in the
 * `standalone` frame for the top-level routes; `PortalNotFound` renders it in
 * the `portal` frame as a catch-all child inside each portal, where the layout
 * already provides the frame.
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

  // `isRouteErrorResponse` distinguishes a thrown Response (a real 404 from
  // the router) from an Error thrown during render. An unmatched path arrives
  // here as the former with status 404; `errorElement` catching a component
  // crash arrives as the latter. Rendered outside a router error context
  // (the explicit `path: "*"` route), `useRouteError` returns undefined and
  // the 404 reading is correct.
  const isNotFound =
    error === undefined || error === null || (isRouteErrorResponse(error) && error.status === 404)

  return <FullPageState variant={isNotFound ? "not-found" : "crash"} frame="standalone" />
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
  return <FullPageState variant="not-found" frame="portal" />
}
