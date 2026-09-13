/* Hallmark · pre-emit critique: P5 H5 E4 S5 R4 V4 */
import { useMatches } from "react-router-dom"
import type { SkeletonShape } from "@/lib/meta/documentMeta"
import { RouteFallback } from "@/components/ui/state-views"
import { CardGridSkeleton, ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"

/*
 * Route-declared skeletons (packet B1, DESIGN.md §12).
 *
 * `RouteFallback` used to be handed the same hardcoded "generic content well"
 * skeleton (or nothing, for `frame="standalone"`) at every one of its ~20
 * call sites, and every one of those call sites also had to remember to pass
 * `frame="standalone"` for a top-level form — a fact `loadingTiers.test.ts`
 * had to pin by scanning `routes.tsx`'s source text, because nothing in the
 * type system stopped a new auth route from being added without it.
 *
 * `RouteSkeleton` takes no props and reads the shape off the route table
 * instead: `skeletonForMatches` walks `useMatches()` from the leaf backward —
 * identical to `pageMetaFromMatches`'s own "deepest wins" walk — and returns
 * the first `handle.skeleton` it finds. A route that declares `"standalone"`
 * gets `RouteFallback`'s bare frame (no tier-2 skeleton, since a top-level
 * form has no chrome to promise); the other three shapes render inside
 * `frame="content"`, with the skeleton matched to what the screen actually
 * opens with.
 */

function skeletonBody(shape: SkeletonShape) {
  switch (shape) {
    case "card-grid":
      return <CardGridSkeleton />
    case "list":
      return <ListSkeleton />
    case "page-header":
      return <PageHeaderSkeleton />
    case "standalone":
      return undefined
  }
}

interface SkeletonHandle {
  skeleton?: SkeletonShape
}

function isSkeletonHandle(handle: unknown): handle is SkeletonHandle {
  return (
    typeof handle === "object" &&
    handle !== null &&
    "skeleton" in handle &&
    typeof (handle as { skeleton: unknown }).skeleton === "string"
  )
}

/**
 * Picks the tier-2 skeleton shape for a route match chain.
 *
 * **Deepest wins**, same rule and same reason as `pageMetaFromMatches`: the
 * leaf is what the reader is actually waiting for, and a layout route's own
 * handle (if it ever gains one) is only the fallback for its index route.
 *
 * An empty chain (nothing matched at all — the router's own default before
 * the first match resolves) is `"standalone"`: there is no portal shell to
 * promise a content skeleton for. A non-empty chain where nothing declares a
 * shape defaults to `"page-header"` — the generic single-record shape,
 * matching the assumption `RouteFallback`'s old hardcoded default already
 * made for every screen inside a portal.
 */
export function skeletonForMatches(matches: readonly { handle?: unknown }[]): SkeletonShape {
  for (let i = matches.length - 1; i >= 0; i--) {
    const handle = matches[i]?.handle
    if (isSkeletonHandle(handle) && handle.skeleton) return handle.skeleton
  }
  return matches.length === 0 ? "standalone" : "page-header"
}

export function RouteSkeleton() {
  const matches = useMatches()
  const shape = skeletonForMatches(matches)
  return (
    <RouteFallback
      frame={shape === "standalone" ? "standalone" : "content"}
      skeleton={skeletonBody(shape)}
    />
  )
}
