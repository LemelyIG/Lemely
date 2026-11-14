import { lazy, Suspense } from "react"
import type { RouteObject } from "react-router-dom"
import { RouteSkeleton } from "@/components/ui/route-skeleton"
import type { PageMeta } from "@/lib/meta/documentMeta"

const DriftStackedDialogs = lazy(() => import("@/lib/nav/DriftStackedDialogs"))

/** The stacked-dialog harness page; `routes.tsx` adds it only in a drift build. */
export const driftStackedDialogsRoute: RouteObject = {
  path: "/__drift/stacked-dialogs",
  handle: { title: "Stacked dialogs", description: "Behaviour harness page.", skeleton: "standalone" } satisfies PageMeta,
  element: (
    <Suspense fallback={<RouteSkeleton />}>
      <DriftStackedDialogs />
    </Suspense>
  ),
}
