import { createBrowserRouter } from "react-router-dom"
import { appRoutes } from "@/routes"
import { applyDocumentMeta } from "@/lib/meta/documentMeta"

/*
 * The router instance, and nothing else.
 *
 * Everything that decides *what* is mounted lives in `routes.tsx`; this file
 * is the one line that turns it into a browser router. The split is P4.9's:
 * `createBrowserRouter` reaches for `document` at import time, so keeping the
 * table in the same module made the product's routing untestable outside a DOM
 * environment. See the note at the top of `routes.tsx`.
 */
export const router = createBrowserRouter(appRoutes)

/*
 * P6.5 · the document title, driven from the route table.
 *
 * A subscription rather than a component. The alternative is a `<DocumentMeta>`
 * calling `useMatches()`, which has to live *inside* the router — and there is
 * no shared layout route to hang it on, so it would mean wrapping all eleven
 * top-level routes in a new parent purely to host it. That parent would also
 * change where `errorElement` bubbles to, which `routes.tsx` sets deliberately
 * per route and explains at length. Restructuring the route tree to set a title
 * is a large change to make for a small reason.
 *
 * `router.subscribe` gives the same match chain with none of that. It is also
 * the honest shape for what this is: a side effect on `document`, not a piece
 * of rendered UI.
 *
 * The explicit first call matters — `subscribe` fires on state *changes*, so a
 * reader who loads a deep link directly and never navigates would otherwise
 * keep `index.html`'s default title on a page that has its own.
 */
/*
 * `router.state.matches` is `DataRouteMatch[]`, where the handle lives at
 * `match.route.handle`. The `useMatches()` hook returns `UIMatch[]`, which
 * hoists it to `match.handle`. They look interchangeable and are not, and the
 * difference is silent at runtime: reading `.handle` off a DataRouteMatch
 * yields `undefined` for every route, so every page would have fallen back to
 * the default title and the feature would have shipped doing nothing.
 *
 * `tsc` caught it, which is worth recording: this is the one defect in P6.5
 * that a type checker could see, and the rest of the phase is a catalogue of
 * things it could not.
 */
const applyFrom = (matches: readonly { route: { handle?: unknown } }[]) =>
  applyDocumentMeta(matches.map((match) => ({ handle: match.route.handle })))

applyFrom(router.state.matches)
router.subscribe((state) => {
  applyFrom(state.matches)
})
