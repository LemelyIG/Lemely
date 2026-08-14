/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Card, CardBody } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Eyebrow, Meter } from "@/components/ui/primitives"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { ErrorState } from "@/components/ui/state-views"
import { CardGridSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { adminLoadFailureMessage } from "@/lib/adminOutcome"
import { usePipelineHealth } from "@/lib/hooks/useAdminApi"
import type { PipelineHealth as PipelineHealthData } from "@/lib/adminTypes"

/**
 * X-03 · Pipeline and corpus health.
 *
 * Reads `GET /api/admin/pipeline`. Four panels, and the fourth is the reason
 * this screen is worth reading at all.
 *
 * ── Boundary reliance is the panel that matters ────────────────────────────
 *
 * X-03 asks for "grade boundary coverage with gaps highlighted (this drives
 * whether predictions are real or estimated)". Two readings were available and
 * this screen shows the stronger one: not how much of the corpus *could*
 * resolve exactly, but how much actually *did*. `boundarySourceCounts` is the
 * observed distribution across every recorded past-paper attempt, so a rising
 * `global_default` share is visible evidence that predictions are drifting
 * towards guesswork, months before anyone would notice it in a grade.
 *
 * The key-count figures sit beside it as the prospective half, clearly labelled
 * as a different thing.
 *
 * ── The panel that is deliberately prose ───────────────────────────────────
 *
 * X-03 also asks for "marking accuracy metrics against the golden fixture
 * set". Nothing at runtime carries them: they are produced by the accuracy
 * harness into `reports/`, on demand. A number read off a file that this screen
 * could not date would be worse than no number, because an administrator would
 * quote it. So the API sends a sentence saying where the figures live, and this
 * screen prints it.
 */
export function PipelineHealth() {
  const { data, isPending, isError, error } = usePipelineHealth()

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1.5">
        <Eyebrow>Platform admin</Eyebrow>
        <h1 className="text-display-lg text-ink">Pipeline and corpus</h1>
        <p className="max-w-prose text-body-md text-ink-muted">
          What the marking pipeline has to work with, and what it has been falling back on.
        </p>
      </header>

      {isPending ? (
        <>
          <PageHeaderSkeleton />
          <CardGridSkeleton count={3} />
        </>
      ) : isError ? (
        <ErrorState
          heading="We couldn't read the pipeline's figures"
          body={adminLoadFailureMessage(error)}
          action={{ label: "Try again", onClick: () => window.location.reload() }}
        />
      ) : (
        <>
          <BoundaryPanel health={data} />
          <CorpusPanel health={data} />
          <IngestionPanel health={data} />
          <AccuracyPanel note={data.markingAccuracyNote} />
        </>
      )}
    </div>
  )
}

/** The three boundary sources, and what each one means for a prediction. */
const BOUNDARY_LABELS: Record<string, { title: string; meaning: string }> = {
  exact: {
    title: "Published boundaries",
    meaning: "The real boundaries for that exact paper and session were found.",
  },
  subject_default: {
    title: "Subject fallback",
    meaning: "No boundaries for that paper, so the subject's typical ones were used.",
  },
  global_default: {
    title: "Global fallback",
    meaning: "Nothing subject-specific either, so a platform-wide guess was used.",
  },
  unrecorded: {
    title: "No source recorded",
    meaning: "The attempt predates boundary tracking, or the prediction did not run.",
  },
}

function BoundaryPanel({ health }: { health: PipelineHealthData }) {
  const entries = Object.entries(health.boundarySourceCounts)
  const total = entries.reduce((sum, [, count]) => sum + count, 0)
  const estimated = total - (health.boundarySourceCounts.exact ?? 0)

  return (
    <Card>
      <CardBody className="flex flex-col gap-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <Eyebrow>Are predictions real or estimated?</Eyebrow>
          {/* Shown only when most predictions are running on a fallback, and
              labelled — never a bare colour. `warn` is the alert register here;
              the accent belongs to links and the brand, and using it for both
              is what the inspection round caught. */}
          {total > 0 && estimated > total / 2 ? (
            <Badge tone="warn">Most predictions used a fallback</Badge>
          ) : null}
        </div>

        {total === 0 ? (
          <p className="text-body-sm text-ink-muted">
            No past papers have been marked yet, so no prediction has needed a boundary.
          </p>
        ) : (
          <>
            <p className="max-w-prose text-body-sm text-ink-muted">
              Measured across every past-paper attempt on record, not across the corpus. This is
              what predictions actually ran on.
            </p>
            <ul className="flex flex-col gap-3">
              {entries
                .sort((a, b) => b[1] - a[1])
                .map(([source, count]) => {
                  const label = BOUNDARY_LABELS[source] ?? {
                    title: source.replace(/_/g, " "),
                    meaning: "",
                  }
                  const pct = (count / total) * 100
                  return (
                    <li key={source} className="flex flex-col gap-1.5">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="text-body-sm text-ink">{label.title}</span>
                        <span className="text-body-sm tabular-nums text-ink-muted">
                          {count} of {total} ({Math.round(pct)}%)
                        </span>
                      </div>
                      <Meter
                        value={pct}
                        label={`${label.title}: ${count} of ${total} attempts`}
                        // `warn`, not `accent`: the badge above this list is already the
                        // warn register, and painting the same condition in two
                        // different alert colours made one card carry two alarms.
                        fillClassName={source === "exact" ? "bg-ink-faint" : "bg-warn"}
                      />
                      {label.meaning ? (
                        <span className="text-body-sm text-ink-faint">{label.meaning}</span>
                      ) : null}
                    </li>
                  )
                })}
            </ul>
          </>
        )}

        <p className="max-w-prose text-body-sm text-ink-faint">
          Separately, the boundary store carries{" "}
          <span className="tabular-nums">{health.exactBoundaryKeys}</span> published paper variants
          and <span className="tabular-nums">{health.subjectDefaultBoundaryKeys}</span> subject
          fallbacks. That is what could resolve exactly; the figures above are what did.
        </p>
      </CardBody>
    </Card>
  )
}

function CorpusPanel({ health }: { health: PipelineHealthData }) {
  return (
    <section className="flex flex-col gap-3" aria-label="Mark scheme corpus">
      <h2 className="text-display-sm text-ink">Mark scheme corpus</h2>
      {health.subjects.length === 0 ? (
        <Card>
          <CardBody>
            <p className="text-body-sm text-ink-muted">
              No papers are registered yet, so there is no coverage to report.
            </p>
          </CardBody>
        </Card>
      ) : (
        <Table>
          <THead>
            <tr>
              <TH>Subject</TH>
              <TH numeric>Papers</TH>
              <TH numeric>With a scheme</TH>
              {/* The gap, given its own column rather than left to be worked
                  out. A reader scanning for trouble should not have to
                  subtract. */}
              <TH numeric>Missing</TH>
            </tr>
          </THead>
          <TBody>
            {health.subjects.map((subject) => (
              <TR key={subject.subjectCode}>
                <TD>{subject.subjectCode}</TD>
                <TD numeric>{subject.papers}</TD>
                <TD numeric>{subject.papersWithScheme}</TD>
                <TD numeric>
                  <span className={subject.papersWithoutScheme > 0 ? "text-accent-ink" : undefined}>
                    {subject.papersWithoutScheme}
                  </span>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      <p className="max-w-prose text-body-sm text-ink-muted">
        A paper with no parsed mark scheme cannot be marked at all. These counts are papers
        registered in the database, not files on disk.
      </p>
    </section>
  )
}

function IngestionPanel({ health }: { health: PipelineHealthData }) {
  const failed = health.uploadsByStatus.failed ?? 0

  return (
    <Card>
      <CardBody className="flex flex-col gap-3">
        <Eyebrow>Uploads</Eyebrow>
        <dl className="grid gap-3 sm:grid-cols-4">
          {Object.entries(health.uploadsByStatus).map(([status, count]) => (
            <div key={status} className="flex flex-col gap-1">
              <dt className="text-body-sm text-ink-muted capitalize">{status}</dt>
              <dd
                className={
                  status === "failed" && count > 0
                    ? "text-data-md tabular-nums text-accent-ink"
                    : "text-data-md tabular-nums text-ink"
                }
              >
                {count}
              </dd>
            </div>
          ))}
        </dl>
        {failed > 0 ? (
          <div className="flex flex-col gap-1.5 border-t border-rule pt-3">
            <p className="text-body-sm text-ink">
              The most recent failures, newest first. These ids are what to look up in the logs.
            </p>
            <ul className="flex flex-col gap-1">
              {health.recentFailedUploadIds.map((id) => (
                <li key={id} className="text-data-sm text-ink-muted">
                  {id}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-body-sm text-ink-muted">Nothing has failed.</p>
        )}
      </CardBody>
    </Card>
  )
}

function AccuracyPanel({ note }: { note: string }) {
  return (
    <Card>
      <CardBody className="flex flex-col gap-2">
        <Eyebrow>Marking accuracy</Eyebrow>
        <p className="max-w-prose text-body-sm text-ink-muted">{note}</p>
      </CardBody>
    </Card>
  )
}
