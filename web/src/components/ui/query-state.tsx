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
 *
 * ── `idle`, and why `pending` alone is not "loading" ────────────────────────
 *
 * react-query's `enabled: false` (18+ hooks across `useStudentApi.ts`,
 * `usePlacementApi.ts`, `usePracticeApi.ts` and `useTeacherApi.ts` use it;
 * `useParentApi.ts`'s child-linking query stays disabled permanently) parks a
 * query at `status: "pending", fetchStatus: "idle"` with no fetch ever
 * scheduled, rather than transitioning it through `"success"` or `"error"`.
 * The first draft of this component treated `"pending"` as one state and
 * always rendered `skeleton`, which is correct for an enabled query mid-fetch
 * and wrong for a disabled one — a skeleton that never resolves is worse than
 * no skeleton at all, since it tells a reader something is coming. `idle`
 * exists for that second case; see its own doc comment for what a caller
 * should put there. `fetchStatus` is optional on `QueryStateQuery` for the
 * same structural reason `data`/`error`/`refetch` already are: a hand-built
 * query object that never sets it just never idles.
 *
 * ── Why a `"success"` status can still reach the error branch ──────────────
 *
 * `request()` in `lib/api.ts` returns `undefined as T` on a 204, so
 * `status === "success"` does not imply `data !== undefined` the way
 * react-query's own discriminated union would suggest — `QueryStateQuery` is
 * a structural type, not that union, and stays that way for the reason given
 * above. The old code cast past this (`query.data as T`) and handed a value
 * the caller's own `T` says cannot be `undefined` straight to `isEmpty` and
 * `children`. This module now checks for it explicitly and renders the error
 * branch instead — see that block's own comment for why error, not skeleton
 * or empty.
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
  /** react-query's own `fetchStatus` — "fetching" while a request is in
   * flight, "paused" while offline, "idle" otherwise. Optional, and
   * deliberately not required: a hand-built object (this file's own tests,
   * the kit preview page) satisfies `QueryStateQuery` without inventing one.
   * A caller whose query can sit at `status: "pending", fetchStatus: "idle"`
   * — any `enabled: false` query, for as long as it stays disabled — should
   * supply both this and `idle`; see that prop's doc for why. */
  fetchStatus?: "fetching" | "paused" | "idle"
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
  /** Rendered instead of `skeleton` when `query.status === "pending"` and
   * `query.fetchStatus === "idle"` — a query sitting at `enabled: false`,
   * which react-query leaves pending forever rather than fetching. Without
   * this, a converted screen behind a conditional `enabled:` shows a
   * skeleton that never resolves, because no fetch is coming to resolve it.
   * Falls back to `skeleton` when omitted, so a query that is always enabled
   * (most of them) needs nothing extra. A call site with a conditionally
   * enabled query should supply this — an empty state or a prompt naming
   * what turns the query on, not the loading shape for data that is not
   * being asked for. */
  idle?: ReactNode
  /** Whether the loaded `data` counts as empty. Only consulted once
   * `query.status === "success"` and `data` is defined — a success with
   * `data === undefined` (a 204; see `lib/api.ts`) is handled before this
   * runs, as an error rather than empty, since the module's error branch
   * doc explains why. */
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
  idle,
  error,
  isEmpty,
  empty,
  srHeading,
  children,
}: QueryStateProps<T>) {
  const heading = srHeading ? <h1 className="sr-only">{srHeading}</h1> : null

  if (query.status === "pending") {
    // `enabled: false` (18+ hooks across the API modules use it, and
    // `useParentApi.ts`'s child-linking query stays disabled permanently)
    // leaves react-query sitting at `status: "pending", fetchStatus: "idle"`
    // forever — no fetch is in flight, so nothing will ever move this query
    // off `pending` on its own. Rendering `skeleton` there is a promise this
    // component cannot keep: a skeleton says "this resolves shortly", and
    // this one would not resolve at all. `idle` is what the caller shows
    // instead; falling back to `skeleton` keeps every always-enabled query
    // (most of them) working with no extra prop.
    if (query.fetchStatus === "idle") {
      return (
        <>
          {heading}
          {idle ?? skeleton}
        </>
      )
    }
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

  if (query.data === undefined) {
    // `query.status === "success"` with `data === undefined` is
    // representable, not theoretical: `request()` in `lib/api.ts` returns
    // `undefined as T` on a 204. Handing that straight to `isEmpty`/
    // `children` as `T` would be the same false cast this block exists to
    // remove, just moved one line down — and holding on `skeleton` is worse
    // than that, because react-query already resolved successfully, so
    // (unlike the `idle` case above) no further fetch is coming to replace
    // the skeleton with anything. Rendering the error branch is the honest
    // answer: the caller asked for data and got none, which is a failure to
    // show something even though nothing in `query.error` says so — a
    // reader who sees a retry button can act on that (a manual refetch may
    // turn up whatever a 204 stood in for) where a reader staring at a
    // skeleton that will never resolve cannot. `error.body` is deliberately
    // not consulted here: it exists to interpret `query.error`, and there is
    // no `query.error` to interpret — `describeQueryFailure(undefined)` is
    // this module's own generic sentence, not a stand-in for the caller's.
    return (
      <>
        {heading}
        <ErrorState
          heading={error.heading}
          body={describeQueryFailure(undefined)}
          marginalia={error.marginalia}
          action={{ label: error.retryLabel ?? "Try again", onClick: () => query.refetch() }}
        />
      </>
    )
  }

  // `query.status === "success"` and `query.data !== undefined` from here,
  // so `data` narrows to `T` from the check above with no cast — see the
  // block above for why `data` can be `undefined` on a `"success"` status in
  // the first place.
  const data: T = query.data

  if (isEmpty?.(data)) {
    return empty ?? children(data)
  }

  return children(data)
}
