/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
import { Button } from "@/components/ui/button"
import { refreshFailed } from "@/lib/adminOpsModel"

/*
 * The note for a query that refreshes in the background (the problem queue and health every
 * minute, a list after every write). React Query v5 flips `status` to "error" when a refresh
 * fails even though `data` is still there, and `QueryState` would swap the whole screen for the
 * error panel. Screens therefore give `QueryState` the first load only (`data === undefined`);
 * once data exists it stays on screen and this note says the last refresh failed, so a
 * transient failure neither hides the figures nor passes them off as fresh.
 *
 * A failed "Load more" (`isFetchNextPageError`) is the list's own business, not a failed refresh.
 */

interface Refreshing {
  status: "pending" | "error" | "success"
  data: unknown
  isFetchNextPageError?: boolean
  refetch: () => unknown
}

export function RefreshNote({ query }: { query: Refreshing }) {
  if (!refreshFailed(query)) return null
  return (
    <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-surface-container-low px-3 py-2 text-body-sm text-on-surface">
      <span>Last refresh failed. This is the last data that loaded.</span>
      <Button size="sm" variant="ghost" onClick={() => void query.refetch()}>
        Try again
      </Button>
    </div>
  )
}
