/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { ReactNode } from "react"
import { useLocation, useNavigate, useParams } from "react-router-dom"
import { Check, Minus, Warning } from "@phosphor-icons/react"
import { Card } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { PaperIdentity } from "@/components/ui/paper-identity"
import { MarkDisplay } from "@/components/ui/mark-display"
import { GradeBadge } from "@/components/ui/grade-badge"
import { BoundaryBar, type GradeBoundary } from "@/components/ui/boundary-bar"
import { ConfidenceIndicatorSummary } from "@/components/ui/confidence-indicator"
import { QuestionRow, type MarkState } from "@/components/ui/question-row"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { ListSkeleton, PanelSkeleton } from "@/components/ui/loading-shapes"
import { ApiError } from "@/lib/api"
import { confidenceSummaryOf, confidenceTierFor } from "@/lib/markingConfidence"
import { useResult } from "@/lib/hooks/useStudentApi"
import type { IntegrityRow, QuestionResult, Result } from "@/lib/studentTypes"

/*
 * Paper Result (isResult) - the flagship screen. Renders one result, from
 * either of two sources:
 *   - live: `location.state`, set by `CorrectPaper`'s navigate() right after a
 *     `/student/correct` run completes - carries a real `questions` array, so
 *     the flat per-question list renders.
 *   - history: `GET /student/result/{paperId}` (useResult) when there's no
 *     live state (browsing from `Subject`'s paper-history table) - no
 *     per-question detail is stored for history records, so an honest note
 *     replaces the list instead of an empty or fabricated one.
 * The shared header (marks/percentage/grade, boundary bar, integrity +
 * provenance sidebar) renders from whichever source is active.
 *
 * ── P4.2 (redesign Phase 4, surface 2 of 10) ──────────────────────────────
 *
 * Migrated to the Study Notebook system. Three changes are not styling:
 *
 *   1. **The confidence threshold disagreed with the backend.** Bucketing
 *      moved to `lib/markingConfidence.ts`, which uses the real 0.90 review
 *      floor instead of the 0.85 this screen had invented, and is pinned
 *      against the Python constant by a test. See that file: at 0.85 a mark
 *      scoring 0.87 read "confident" to the student and "not confident" to
 *      their teacher, on the same paper.
 *   2. **Loading was one line of text where a full result arrives.** Replaced
 *      with skeletons shaped like the header and the question list, so the
 *      page does not jump several hundred pixels when the data lands
 *      (DESIGN.md §12, CLS < 0.1).
 *   3. **The four terminal states were four hand-built page shells.** They
 *      share one now, so a heading, a container width or a gap can no longer
 *      be right in three of them and wrong in the fourth.
 *
 * **Not done here: the celebration register.** DESIGN.md §9.3 names "the
 * marked-paper result reveal" as one of the five moments that earn expressive
 * motion, and this is that screen. Phase 5 owns the motion sweep product-wide,
 * and building a count-up here first would set the register from one surface
 * before the spec for it exists in code.
 */

type LiveResult = Result & { questions: QuestionResult[] }

function isLiveResult(state: unknown): state is LiveResult {
  return !!state && typeof state === "object" && "questions" in state
}

/**
 * `ResultDTO` only ships a precomputed rail position (`railLeft`/`railFoot`),
 * not real per-grade mark thresholds — the old `BoundaryRail` faked a bar out
 * of fixed, paper-independent tick percentages (U=6%, E=24%, ... regardless
 * of the actual paper). `BoundaryBar` (C-3) refuses to do that: given no
 * `boundaries`, it shows an honest "not available" message instead. This
 * stays empty until `ResultDTO` exposes real `{grade, minMark}` boundaries —
 * a genuine backend/DTO gap, flagged in the P2.5.3 report, not something to
 * fabricate here.
 */
const NO_BOUNDARIES: GradeBoundary[] = []

const NO_QUESTION_DETAIL = {
  heading: "No per-question detail for this paper",
  body: "Per-question detail is only available right after correcting a paper.",
}

/** correct = full marks, wrong = zero, partial = anything between. */
function markState(q: QuestionResult): MarkState {
  if (q.maxMarks <= 0) return q.awardedMarks > 0 ? "correct" : "wrong"
  if (q.awardedMarks >= q.maxMarks) return "correct"
  if (q.awardedMarks <= 0) return "wrong"
  return "partial"
}

function IntegrityMark({ row }: { row: IntegrityRow }) {
  const Icon = row.mark === "check" ? Check : row.mark === "bang" ? Warning : Minus
  return (
    <div
      // DESIGN.md "Borders: 1px solid borders in the `border` color provide
      // the primary containment strategy" — snapped to the canonical 1px
      // (rule) instead of the undocumented border-[1.5px].
      className={`w-4 h-4 flex-none mt-px rounded-full border flex items-center justify-center ${
        row.color === "ok"
          ? "border-ok text-ok"
          : row.color === "warn"
            ? "border-warn text-warn"
            : "border-ink-muted text-ink-muted"
      }`}
    >
      <Icon size={9} weight="bold" />
    </div>
  )
}

/**
 * One page shell for every state this screen can be in.
 *
 * The four terminal states each carried their own copy of the wrapper, and
 * they had already drifted: the loaded states used `gap-container-mobile`
 * (22px, a build-era rung) while the loading and error states used `gap-6`.
 * A container that differs by state is a container nobody chose.
 */
function ResultScreen({
  children,
  srHeading,
}: {
  children: ReactNode
  srHeading?: string
}) {
  return (
    <div className="lm-screen flex flex-col gap-6">
      {srHeading ? <h1 className="sr-only">{srHeading}</h1> : null}
      {children}
    </div>
  )
}

function ResultHeader({ res }: { res: Result }) {
  return (
    <Card className="overflow-hidden">
      <div className="grid grid-result-cols max-tablet:grid-cols-1">
        <div className="px-7 py-6">
          <div className="flex flex-wrap items-center gap-2.5">
            <PaperIdentity code={res.code} session={res.session} paperLabel={res.paper} />
            {res.markerLabel ? <Chip tone="neutral">{res.markerLabel}</Chip> : null}
          </div>
          {res.headline ? (
            <h1 className="mt-2.5 text-display-md text-ink">{res.headline}</h1>
          ) : (
            <h1 className="sr-only">
              Paper result: {res.code} {res.paper}
            </h1>
          )}
          {/* max-w-[56ch] kept: a reading-measure width (character-count
           * based, not a pixel spacing value) — same reasoning as
           * CorrectPaper's max-w ch value. */}
          {res.summary ? (
            <p className="mt-2 max-w-[56ch] text-pretty text-body-md text-ink-muted">
              {res.summary}
            </p>
          ) : null}

          <div className="mt-6 flex flex-wrap items-end gap-6">
            <MarkDisplay awarded={res.awarded} available={res.max} size="hero" />
            <GradeBadge grade={res.grade} size="hero" basis="predicted" />
          </div>

          {/*
           * P4.2, two removals here, both of something that was said twice.
           *
           * This section rendered its own "Against the 2024 boundaries"
           * eyebrow immediately above `BoundaryBar`'s built-in "Grade
           * boundaries" one, so the flagship screen carried two stacked
           * kickers and an indented empty widget beneath them. The year is the
           * only thing the outer one added, and `BoundaryBar` now takes it as
           * a label.
           *
           * `railFoot` is the DTO's own "63/80" foot string, and it was
           * rendered on the same card as `MarkDisplay`, which is already
           * showing 63 / 80 at 32px a few lines above. Same judgement as
           * D4.1's "Forecast" removal: the field stays on the DTO, this
           * presentation of it goes.
           */}
          <div className="mt-8 border-t border-rule pt-6">
            <BoundaryBar
              score={res.awarded}
              maxScore={res.max}
              boundaries={NO_BOUNDARIES}
              label={`Against the ${res.boundaryYear} boundaries`}
              className="p-0"
            />
            {res.railNote ? (
              <p className="mt-2 text-pretty text-body-md text-ink-muted">{res.railNote}</p>
            ) : null}
          </div>
        </div>

        {/* `border-s`, not `border-l`: this is the divider between the result
            and its sidebar, and under `dir="rtl"` the sidebar moves to the
            other edge with it (P3.4). */}
        <div className="flex flex-col gap-4 border-s border-rule bg-paper-sunk px-6 py-6">
          <h2 className="text-label text-ink">Integrity and provenance</h2>
          {res.integrity.length === 0 ? (
            <p className="text-body-sm text-ink-muted">
              No integrity checks recorded for this paper.
            </p>
          ) : (
            res.integrity.map((i) => (
              <div key={i.label} className="flex items-start gap-2.5">
                <IntegrityMark row={i} />
                <div>
                  <div className="text-body-sm text-ink">{i.label}</div>
                  <div className="mt-0.5 text-body-sm text-ink-muted">{i.detail}</div>
                </div>
              </div>
            ))
          )}
          {/* `mt-4`, not `mt-auto`. This sidebar is a short column in a grid
              stretched to its much taller sibling, so pinning the provenance
              to the bottom opened roughly 600px of empty space in the middle
              of the flagship card. Exactly the finding D4.1 recorded against
              the momentum panel: a component pinned to the extremes of a box
              it did not ask to be that tall. */}
          {res.provenance ? (
            <div className="mt-4 whitespace-pre-line break-all border-t border-rule pt-3 text-data-sm leading-relaxed text-ink-faint">
              {res.provenance}
            </div>
          ) : null}
        </div>
      </div>
    </Card>
  )
}

/**
 * S-16's full question list (C-6 `QuestionRow` per row), expandable in place
 * for the marker-source/feedback/review-reason detail S-17 calls for — the
 * app has no separate question-detail route, so the expand affordance is
 * where that content actually lives.
 *
 * Deliberately drops the old per-question "Plagiarism flagged" / "AI-detection
 * flagged" pills that used to render here: QUALITY-BAR.md is explicit that
 * integrity flags are teacher-only and must never read as an accusation on a
 * student-facing screen. `plagiarismFlagged`/`aiDetectionFlagged` stay on the
 * DTO (no data-flow change) but are no longer rendered to the student. Noted
 * in the P2.5.3 report as a deliberate deviation.
 */
function QuestionList({ questions }: { questions: QuestionResult[] }) {
  if (questions.length === 0) {
    // Inside a Card, like the populated list it stands in for. Bare, it
    // floated in the middle of the page with nothing to say which region was
    // empty — and this is the *history* view's normal state, not an edge case.
    return (
      <Card>
        <EmptyState {...NO_QUESTION_DETAIL} marginalia="Not kept for this one" />
      </Card>
    )
  }
  return (
    <Card className="px-3">
      {questions.map((q) => (
        <QuestionRow
          key={q.questionId}
          number={q.questionId}
          awarded={q.awardedMarks}
          available={q.maxMarks}
          state={markState(q)}
          confidence={confidenceTierFor(q)}
          topic={q.topic}
        >
          <div className="flex flex-col gap-2.5">
            <Chip tone="neutral" className="w-fit">
              {q.markerSource}
            </Chip>
            {q.feedback ? (
              <div className="rounded-md bg-paper-sunk px-3.5 py-3 text-pretty text-body-md text-ink-muted">
                {q.feedback}
              </div>
            ) : null}
            {q.reviewReason ? (
              <div className="text-body-md leading-snug text-warn">
                Needs review: {q.reviewReason}
              </div>
            ) : null}
          </div>
        </QuestionRow>
      ))}
    </Card>
  )
}

export function PaperResult() {
  const { paperId } = useParams<{ paperId: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const live = isLiveResult(location.state) ? location.state : null

  const { data, isPending, isError, error, refetch } = useResult(live ? "" : (paperId ?? ""))

  if (live) {
    const summary = confidenceSummaryOf(live.questions)
    return (
      <ResultScreen>
        <ResultHeader res={live} />
        {live.questions.length > 0 ? (
          <ConfidenceIndicatorSummary
            confident={summary.confident}
            uncertain={summary.uncertain}
            needsReview={summary.needsReview}
          />
        ) : null}
        <QuestionList questions={live.questions} />
      </ResultScreen>
    )
  }

  /*
   * P4.2: this was a single line reading "Loading result…" where a full paper
   * result arrives — a header card with a hero mark, a grade badge, a boundary
   * bar and a sidebar, then a question list. One text row standing in for all
   * of that is the layout shift DESIGN.md §12 names, and it is at its worst
   * here: this screen is what a student lands on straight after watching the
   * marking finish, so the jump happens at the exact moment they are looking
   * for their score.
   */
  if (isPending) {
    return (
      <ResultScreen srHeading="Paper result">
        <PanelSkeleton bodyClassName="h-40" />
        <ListSkeleton rows={5} />
      </ResultScreen>
    )
  }

  if (isError) {
    if (error instanceof ApiError && error.status === 404) {
      return (
        <ResultScreen srHeading="Paper result">
          <EmptyState
            heading="No paper recorded at this address"
            body="We don't have a result stored under this link. It may have been removed, or the address may be wrong."
            marginalia="Nothing filed here"
            action={{ label: "Correct a paper", onClick: () => navigate("/student/correct") }}
            secondaryAction={{ label: "Back to overview", onClick: () => navigate("/student") }}
          />
        </ResultScreen>
      )
    }
    return (
      <ResultScreen srHeading="Paper result">
        <ErrorState
          heading="We couldn't load this result"
          body={error.message}
          action={{ label: "Try again", onClick: () => refetch() }}
          secondaryAction={{ label: "Back to overview", onClick: () => navigate("/student") }}
        />
      </ResultScreen>
    )
  }

  return (
    <ResultScreen>
      <ResultHeader res={data} />
      <QuestionList questions={[]} />
    </ResultScreen>
  )
}
