/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ReactNode } from "react"
import { ErrorState } from "@/components/ui/state-views"
import { describeQueryFailure } from "@/lib/queryFailure"

/*
 * Loading/error primitives PR, part A · `<QueryState>`: a react-query result
 * in, the pending/error/empty/success render out.
 *
 * ── The drift this closes ───────────────────────────────────────────────────
 *
 * `Overview.tsx` (the reference conversion in this same PR) shows the shape
 * every data-loading screen in the product hand-writes today: an `isPending`
 * branch with a skeleton matching the loaded layout, an `isError` branch with
 * an `ErrorState` and a `refetch`-backed retry, sometimes an empty-data branch
 * ahead of the real render. Nothing wrong with any one of those three branches
 * — the problem is there are, or will be, roughly twenty-five of them, each
 * written by hand, each one small enough to differ from its neighbours without
 * anyone noticing at review time. `studentOutcome.ts`'s own header records
 * what that drift costs in this exact codebase: two whole screens shipped
 * rendering a machine's raw error message because the pattern that would have
 * caught it did not exist yet when they were written, and nothing connected
 * "a new failure-copy module exists" to "screens built before it should be
 * revisited." A shared wrapper does not fix a screen that skips it, but it
 * does mean there is one pattern to skip rather than twenty-five hand-rolled
 * ones to individually get wrong, and a follow-up PR's gate test can require
 * every data-loading screen to use it or be named on an allowlist.
 *
 * ── Why this takes a query, not a fetch function ────────────────────────────
 *
 * `query` is typed structurally rather than as `UseQueryResult<T>` from
 * `@tanstack/react-query`, so a real query result satisfies it with no cast
 * needed, but so does a hand-built object — which is exactly what the kit
 * preview page and this module's own tests need for the error/empty/success
 * cells and cases a live query cannot deterministically reach on demand.
 *
 * ── Why skeleton, error and empty are all caller-supplied ───────────────────
 *
 * DESIGN.md §12 is explicit — "skeletons, not spinners; loading states match
 * the layout they replace" — and a shared component cannot know a screen's
 * layout. Every attempt to guess it (a generic centred spinner, a fixed-height
 * grey box) is the CLS bug the mission's own skeleton primitives exist to
 * prevent, so `QueryState` never invents one: `skeleton` is the caller's own
 * composition from `loading-shapes.tsx`, the same shapes it would have reached
 * for by hand. `empty` is the same argument for content — a caller's
 * `GettingStarted` panel and another's plain `<EmptyState>` are not
 * interchangeable, so nothing here picks one for them.
 *
 * ── `srHeading` ──────────────────────────────────────────────────────────────
 *
 * `Overview.tsx` renders `<h1 className="sr-only">Overview</h1>` above both
 * its pending and its error branch, so a screen reader arriving mid-load or
 * mid-failure still lands on a heading that names the page rather than on
 * unlabelled content — the loaded render supplies its own visible `<h1>`
 * instead, which is why this is not simply "always render a heading". Optional
 * because not every `QueryState` call site is a whole route (a panel inside a
 * larger screen has no landmark of its own to announce).
 */

/**
 * The subset of `UseQueryResult<T>` this component actually reads.
 *
 * A real `UseQueryResult<T, E>` satisfies this without a cast (`refetch`
 * returns a `Promise`, which is assignable to `unknown`). Kept narrow rather
 * than importing the react-query type directly so a hand-built object — the
 * kit preview page's four `QueryState` cells, and this component's own future
 * tests — can satisfy it too, with no query client in sight.
 */
export interface QueryStateQuery<T> {
  status: "pending" | "error" | "success"
  data: T | undefined
  error: unknown
  refetch: () => unknown
}

/** What to show for `status === "error"`. `body` defaults to
 * `describeQueryFailure(query.error)` when omitted, which is this PR's shared,
 * portal-agnostic failure sentence — a call site with its own outcome module
 * (`studentLoadFailureMessage` and its six siblings) passes `body` to use it
 * instead. */
export interface QueryStateErrorProps {
  heading: string
  body?: string | ((error: unknown) => string)
  retryLabel?: string
  marginalia?: string
}

export interface QueryStateProps<T> {
  query: QueryStateQuery<T>
  /** Rendered while `query.status === "pending"`. Compose it from
   * `loading-shapes.tsx` to match the layout `children` renders once data
   * arrives — see the module header on why this is never invented here. */
  skeleton: ReactNode
  error: QueryStateErrorProps
  /** Whether the loaded `data` counts as empty. Only consulted once
   * `query.status === "success"` and `data` is defined. */
  isEmpty?: (data: T) => boolean
  /** Rendered when `isEmpty` returns true. If `isEmpty` says empty but no
   * `empty` was supplied, falls through to `children` — a call site that has
   * not decided on an empty treatment yet still renders something rather than
   * nothing. */
  empty?: ReactNode
  /** Above the skeleton and error render, for a screen that needs a landmark
   * in every state (see the module header). Rendered nowhere once `children`
   * takes over — the loaded render supplies its own heading. */
  srHeading?: string
  children: (data: T) => ReactNode
}

export function QueryState<T>({
  query,
  skeleton,
  error,
  isEmpty,
  empty,
  srHeading,
  children,
}: QueryStateProps<T>) {
  const heading = srHeading ? <h1 className="sr-only">{srHeading}</h1> : null

  if (query.status === "pending") {
    return (
      <>
        {heading}
        {skeleton}
      </>
    )
  }

  if (query.status === "error") {
    const body =
      typeof error.body === "function"
        ? error.body(query.error)
        : (error.body ?? describeQueryFailure(query.error))
    return (
      <>
        {heading}
        <ErrorState
          heading={error.heading}
          body={body}
          marginalia={error.marginalia}
          action={{ label: error.retryLabel ?? "Try again", onClick: () => query.refetch() }}
        />
      </>
    )
  }

  // `query.status === "success"` from here: `data` is defined by react-query's
  // own contract once status is success, but `QueryStateQuery` types it as
  // `T | undefined` to stay structural rather than re-declaring react-query's
  // discriminated union, so the narrowing below is explicit rather than free.
  const data = query.data as T

  if (isEmpty?.(data)) {
    return empty ?? children(data)
  }

  return children(data)
}
