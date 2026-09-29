/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useState } from "react"
import { ArrowCounterClockwise, Trash } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Eyebrow } from "@/components/ui/primitives"
import { EmptyState } from "@/components/ui/state-views"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { deleteCountdown, teacherPaperCountdownLabel } from "@/lib/teacherPaperDeletion"
import { teacherMutationFailureMessage } from "@/lib/teacherOutcome"
import { useDeletedTeacherPapers, useRestoreTeacherPaper } from "@/lib/hooks/useTeacherApi"
import type { DeletedTeacherPaper } from "@/lib/teacherTypes"

/*
 * Recently deleted, teacher console (Task 17, R2). The uploader's own
 * withdrawn grading-console papers, one row per upload — the full mirror of
 * the student flow (`portals/student/screens/RecentlyDeleted.tsx`), which R2
 * chose over a hidden safety net (D4's objection): a teacher who deletes a
 * paper from the grid can find it again the same way a student can.
 *
 * Same shape as the student screen for the same reasons its own header
 * records: a `QueryState`-wrapped list of cards, each with its own inline
 * failure so one row's failed restore never blanks out the others; restore
 * is a single action with no confirmation (cheap to undo — delete it again —
 * and a modal would cost more attention than a stray tap warrants), while
 * delete itself is confirmed on the grading console grid, not here.
 *
 * `deleteCountdown`/`teacherPaperCountdownLabel` live in
 * `lib/teacherPaperDeletion.ts`, re-exporting the student flow's own
 * retention arithmetic rather than recomputing it — one `RETENTION_DAYS`
 * behind both.
 */

function DeletedPaperRow({ paper, now }: { paper: DeletedTeacherPaper; now: string }) {
  const restorePaper = useRestoreTeacherPaper()
  const [error, setError] = useState<string | null>(null)
  const daysLeft = deleteCountdown(paper.restoreDeadline, now)
  const gone = daysLeft <= 0

  async function handleRestore() {
    setError(null)
    try {
      await restorePaper.mutateAsync({ paperId: paper.paperId })
    } catch (err) {
      setError(teacherMutationFailureMessage(err))
    }
  }

  return (
    <Card className="flex flex-col gap-3 px-4 py-3.5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="truncate text-body-md text-ink">{paper.label}</span>
          <span className="text-data-sm text-ink-muted">
            {teacherPaperCountdownLabel(daysLeft)}
          </span>
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
  const query = useDeletedTeacherPapers()
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
                A paper you delete from the grading console stays here for{" "}
                {data.retentionDays} days, in case you want it back.
              </p>
            </header>
            {data.papers.length === 0 ? (
              <Card>
                <EmptyState
                  icon={<Trash size={20} weight="bold" aria-hidden="true" />}
                  heading="Nothing deleted right now"
                  body="Console papers you delete show up here until the restore window closes."
                  marginalia="All clear"
                />
              </Card>
            ) : (
              <div className="flex flex-col gap-2.5">
                {data.papers.map((paper) => (
                  <DeletedPaperRow key={paper.paperId} paper={paper} now={now} />
                ))}
              </div>
            )}
          </>
        )}
      </QueryState>
    </div>
  )
}
