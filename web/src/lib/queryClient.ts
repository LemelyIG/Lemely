import { QueryClient } from "@tanstack/react-query"
import { actingQueryHash, looksLikeTeamPermissionDenied } from "./actingTeacher"

/*
 * Shared react-query client. `retry: 1` avoids hammering the backend (and the
 * Gemini-backed endpoints) on transient failures without masking real errors
 * behind an unbounded retry loop; `refetchOnWindowFocus: false` keeps portal
 * tab-switching from firing surprise network calls.
 *
 * `queryKeyHashFn` partitions the cache by who the caller is acting for (an assistant working
 * as their lead teacher). It is the default hash while nobody is being acted for. See
 * `lib/actingTeacher.ts`.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // One retry for any failure, except an assistant's refusal: "your role (or this lead) does
      // not allow that" will not change on a second ask, and asking again is what a loop looks like.
      retry: (failureCount, error) => failureCount < 1 && !looksLikeTeamPermissionDenied(error),
      refetchOnWindowFocus: false,
      queryKeyHashFn: actingQueryHash,
    },
  },
})
