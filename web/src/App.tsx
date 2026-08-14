import { createBrowserRouter } from "react-router-dom"
import { appRoutes } from "@/routes"

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
