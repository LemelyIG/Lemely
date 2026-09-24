/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useState } from "react"
import { ArrowCounterClockwise, Trash } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { Eyebrow } from "@/components/ui/primitives"
import { EmptyState } from "@/components/ui/state-views"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { deleteCountdown } from "@/lib/paperDeletion"
import { studentSaveFailureMessage } from "@/lib/studentOutcome"
import { useDeletedPapers, useRestorePaper } from "@/lib/hooks/usePaperDeletionApi"
import type { DeletedPaper } from "@/lib/studentTypes"

/*
 * Recently deleted (spec 2026-09-22, Task 14). A student's own withdrawn
 * papers, one row per upload (R7) — deleting a paper takes every marking run
 * of that scan with it, so the list never shows the same scan twice.
 *
 * Follows `Parents.tsx`'s shape for a small owned-records screen: a
 * `QueryState`-wrapped list of cards, each with its own inline failure
 * rather than one screen-wide error banner, since a restore that fails
 * should not blank out every other row still waiting to be restored.
 *
 * Restore is a single action with no confirmation — the same judgement
 * `Friends.tsx` records for decline/cancel/unfriend: the only way to get here
 * wrongly is a stray tap, it is cheap to undo (delete again), and a modal
 * would cost more attention than the mistake it prevents. Delete, by
 * contrast, is confirmed on `PaperResult` — the two actions are not
 * symmetric in cost, so they are not symmetric in ceremony.
 */

/**
 * `days` is computed once, by the caller (Task 14 review, Minor 2), and
 * passed in rather than re-derived here — `DeletedPaperRow` was calling
 * `deleteCountdown` a second time for its own `gone` flag, both reads of
 * the same clock a render apart. Not a correctness bug (`now` is a stable
 * per-render string, not `Date.now()` read twice), but two call sites doing
 * the same arithmetic over the same inputs is exactly the drift risk this
 * whole feature's pure-helper split exists to avoid.
 */
function countdownLabel(days: number): string {
  if (days <= 0) return "Restore window closed"
  if (days === 1) return "1 day left to restore"
  return `${days} days left to restore`
}

function DeletedPaperRow({
  paper,
  now,
}: {
  paper: DeletedPaper
  now: string
}) {
  const restorePaper = useRestorePaper()
  const [error, setError] = useState<string | null>(null)
  const daysLeft = deleteCountdown(paper.restoreDeadline, now)
  const gone = daysLeft <= 0

  async function handleRestore() {
    setError(null)
    try {
      await restorePaper.mutateAsync({ attemptId: paper.attemptId })
    } catch (err) {
      setError(studentSaveFailureMessage(err))
    }
  }

  return (
    <Card className="flex flex-col gap-3 px-4 py-3.5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone="neutral">{paper.subjectCode}</Chip>
            <span className="truncate text-body-md text-ink">{paper.paperLabel}</span>
          </div>
          <span className="text-data-sm text-ink-muted">{countdownLabel(daysLeft)}</span>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void handleRestore()}
          loading={restorePaper.isPending}
          disabled={gone}
        >
          <ArrowCounterClockwise size={16} weight="bold" />
          Restore
        </Button>
      </div>
      {error ? (
        <p role="alert" className="text-body-sm text-err">
          {error}
        </p>
      ) : null}
    </Card>
  )
}

export function RecentlyDeleted() {
  const query = useDeletedPapers()
  const now = new Date().toISOString()

  return (
    <div className="flex flex-col gap-6">
      <QueryState
        query={query}
        srHeading="Recently deleted"
        skeleton={<ListSkeleton rows={3} />}
        error={{
          heading: "We couldn't load your recently deleted papers",
          body: "This is a connection problem, not an empty list.",
        }}
      >
        {(data) => (
          <>
            <header className="flex flex-col gap-1">
              <Eyebrow>Recently deleted</Eyebrow>
              <h1 className="text-display-md text-ink">Recently deleted</h1>
              <p className="max-w-[56ch] text-pretty text-body-md text-ink-muted">
                A deleted paper stays here for {data.retentionDays} days, in case you want it back.
              </p>
            </header>
            {data.papers.length === 0 ? (
              <Card>
                <EmptyState
                  icon={<Trash size={20} weight="bold" aria-hidden="true" />}
                  heading="Nothing deleted right now"
                  body="Papers you delete from their result page show up here until the restore window closes."
                  marginalia="All clear"
                />
              </Card>
            ) : (
              <div className="flex flex-col gap-2.5">
                {data.papers.map((paper) => (
                  <DeletedPaperRow key={paper.attemptId} paper={paper} now={now} />
                ))}
              </div>
            )}
          </>
        )}
      </QueryState>
    </div>
  )
}
