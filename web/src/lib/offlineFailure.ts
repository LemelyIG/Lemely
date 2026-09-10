import { ApiError } from "@/lib/api"

/*
 * A4 · Which query failures are "offline" rather than "broken".
 *
 * `request()` in `lib/api.ts` wraps a `fetch` rejection as `ApiError(0, ...)`
 * — status 0 is this codebase's spelling of "the request never completed"
 * (see `describeQueryFailure`'s own header). A bare `TypeError` is what a
 * `fetch` call throws directly, before `request()` gets a chance to wrap it,
 * when the network is unreachable. Both mean the same thing to a reader: not
 * that Lemely is broken, but that they are not connected to it — a fact
 * `QueryState`'s error branch renders as `OfflineState` rather than
 * `ErrorState` for.
 */
export function isOfflineFailure(error: unknown): boolean {
  return (error instanceof ApiError && error.status === 0) || error instanceof TypeError
}
