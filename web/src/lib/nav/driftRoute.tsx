import { lazy, Suspense } from "react"
import type { RouteObject } from "react-router-dom"
import { RouteSkeleton } from "@/components/ui/route-skeleton"
import type { PageMeta } from "@/lib/meta/documentMeta"

/**
 * The stacked-dialog harness page. Everything, including the `lazy()` import, sits inside the
 * `import.meta.env.VITE_LEMELY_DRIFT === "1"` branch, written inline so Vite folds it before the module graph is built (a constant imported from another module is not folded early enough, and the chunk was still emitted): a plain build drops the dynamic import, so it emits no
 * chunk, the main bundle keeps no reference, and the service worker precaches nothing for it.
 */
export const driftStackedDialogsRoute: RouteObject | null = import.meta.env.VITE_LEMELY_DRIFT === "1"
  ? (() => {
      const DriftStackedDialogs = lazy(() => import("@/lib/nav/DriftStackedDialogs"))
      return {
        path: "/__drift/stacked-dialogs",
        handle: { title: "Stacked dialogs", description: "Behaviour harness page.", skeleton: "standalone" } satisfies PageMeta,
        element: (
          <Suspense fallback={<RouteSkeleton />}>
            <DriftStackedDialogs />
          </Suspense>
        ),
      }
    })()
  : null
