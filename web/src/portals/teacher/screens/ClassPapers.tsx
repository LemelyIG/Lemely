/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useState } from "react"
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/table"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import { EmptyState } from "@/components/ui/state-views"
import { QueryState } from "@/components/ui/query-state"
import { PanelSkeleton } from "@/components/ui/loading-shapes"
import { relativeTime } from "@/lib/utils"
import { classPaperLabel, unshareConsequence } from "@/lib/teacherPaperDeletion"
import { classPaperActionFailureMessage, teacherLoadFailureMessage } from "@/lib/teacherOutcome"
import {
  useClassPapers,
  useReshareClassPaper,
  useUnshareClassPaper,
} from "@/lib/hooks/useTeacherApi"
import type { ClassPaperRow } from "@/lib/teacherTypes"
import { useClassDetailContext } from "./ClassDetail"

/*
 * Class papers (controller addition, Task 13's review: an unshare with no
 * matching visibility). Every rostered student's paper in this class,
 * `GET /classes/{classId}/papers`, with an Unshare control per shared paper
 * and a Reshare control on an already-unshared one — and, load-bearing, the
 * **unshared state itself stays visible** (D9's own review finding): a
 * student who leaves and re-joins this class can have an exclusion silently
 * re-applied, and without a row here a teacher has no way to notice their
 * paper vanished from this class's averages and review queue.
 *
 * Unshare is confirmed (`unshareConsequence` names the paper, scopes the
 * effect to this class, and says the student's own copy is untouched —
 * D9's "must not imply the student loses anything"); reshare is not, the
 * same asymmetry `RecentlyDeleted.tsx` draws between delete and restore —
 * reshare is cheap to undo (unshare again) and idempotent either way.
 */

function UnshareControl({ classId, row }: { classId: string; row: ClassPaperRow }) {
  const unshare = useUnshareClassPaper()
  const reshare = useReshareClassPaper()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (row.unshared) {
    return (
      <div className="flex flex-col items-end gap-1">
        <Button
          variant="secondary"
          size="sm"
          loading={reshare.isPending}
          onClick={() => {
            setError(null)
            reshare.mutate(
              { classId, attemptId: row.attemptId },
              { onError: (err) => setError(classPaperActionFailureMessage(err)) },
            )
          }}
        >
          Reshare
        </Button>
        {error ? (
          <p role="alert" className="text-body-sm text-err">
            {error}
          </p>
        ) : null}
      </div>
    )
  }

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          setError(null)
          setOpen(true)
        }}
      >
        Unshare
      </Button>
      <ConfirmModal
        open={open}
        title="Unshare this paper from the class?"
        consequence={unshareConsequence(classPaperLabel(row))}
        confirmLabel="Unshare"
        pendingLabel="Unsharing…"
        pending={unshare.isPending}
        error={error}
        onConfirm={() => {
          unshare.mutate(
            { classId, attemptId: row.attemptId },
            {
              onSuccess: () => setOpen(false),
              onError: (err) => setError(classPaperActionFailureMessage(err)),
            },
          )
        }}
        onCancel={() => {
          setOpen(false)
          setError(null)
        }}
      />
    </>
  )
}

export function ClassPapers() {
  const { classId } = useClassDetailContext()
  const query = useClassPapers(classId)

  return (
    <QueryState
      query={query}
      srHeading="Class papers"
      skeleton={<PanelSkeleton />}
      error={{
        heading: "Couldn't load this class's papers",
        body: teacherLoadFailureMessage,
      }}
    >
      {(data) =>
        data.papers.length === 0 ? (
          <EmptyState
            heading="No papers yet"
            body="Once a rostered student has a marked paper, it appears here."
          />
        ) : (
          <Table density="operate" tabIndex={0} role="region" aria-label="Class papers, scrollable">
            <caption className="sr-only">
              Every rostered student's papers, with unshared state visible
            </caption>
            <THead>
              <TR>
                <TH>Student</TH>
                <TH>Paper</TH>
                <TH>Recorded</TH>
                <TH>
                  <span className="sr-only">Visibility</span>
                </TH>
                <TH>
                  <span className="sr-only">Actions</span>
                </TH>
              </TR>
            </THead>
            <TBody>
              {data.papers.map((row) => (
                <TR key={row.attemptId}>
                  <TD className="text-data-sm">{row.studentName}</TD>
                  <TD className="whitespace-nowrap text-data-sm">{classPaperLabel(row)}</TD>
                  <TD className="whitespace-nowrap text-ink-muted">
                    {relativeTime(row.recordedAt)}
                  </TD>
                  <TD>
                    {row.unshared ? (
                      <Chip tone="neutral">Unshared from this class</Chip>
                    ) : (
                      <Chip tone="ok">Shared</Chip>
                    )}
                  </TD>
                  <TD className="whitespace-nowrap text-end">
                    <UnshareControl classId={classId} row={row} />
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )
      }
    </QueryState>
  )
}
