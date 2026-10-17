import { ApiError } from "@/lib/api"

/*
 * A4 · Which query failures are "offline" rather than "broken".
 *
 * `request()` in `lib/api.ts` wraps every `fetch` rejection — dropped
 * connection included — as `ApiError(0, ...)` before it ever reaches a
 * query's `error` field (see that module's own header: status 0 is this
 * codebase's spelling of "the request never completed"). That is the only
 * shape a network failure takes by the time it gets here, which is why a
 * bare `TypeError` is deliberately not treated as offline: nothing in this
 * client's request path lets a dropped connection reach `query.error` as one,
 * so classifying it as offline would instead mislabel a genuine application
 * bug (a `.map` on `undefined`, say) as "you're offline" the moment it
 * happened to surface through a query's error field — a worse outcome than
 * the honest, generic failure `ErrorState` already gives it.
 */
export function isOfflineFailure(error: unknown): boolean {
  return error instanceof ApiError && error.status === 0
}
