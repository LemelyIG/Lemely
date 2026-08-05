import { useLocation, useNavigate, useParams } from "react-router-dom"
import { Check, Minus, Warning } from "@phosphor-icons/react"
import { Card } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { Eyebrow } from "@/components/ui/primitives"
import { PaperIdentity } from "@/components/ui/paper-identity"
import { MarkDisplay } from "@/components/ui/mark-display"
import { GradeBadge } from "@/components/ui/grade-badge"
import { BoundaryBar, type GradeBoundary } from "@/components/ui/boundary-bar"
import {
  ConfidenceIndicatorSummary,
  type ConfidenceTier,
} from "@/components/ui/confidence-indicator"
import { QuestionRow, type MarkState } from "@/components/ui/question-row"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { ApiError } from "@/lib/api"
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

/**
 * `reviewReason` is the backend's explicit "a human needs to look at this"
 * signal, so it always wins. Below that, `confidence` (0-1) is bucketed
 * against the product's stated 0.70 escalation floor (see `data.ts`'s
 * `proof` stat "confidence floor before a human is asked") with an
 * additional, softer 0.85 band for "uncertain but not review-worthy" — that
 * second threshold isn't backend-supplied, it's a frontend judgement call
 * made for this retrofit (see the P2.5.3 report).
 */
function confidenceTier(q: QuestionResult): ConfidenceTier {
  if (q.reviewReason) return "needs-review"
  if (typeof q.confidence === "number" && q.confidence < 0.85) return "uncertain"
  return "confident"
}

function confidenceSummary(questions: QuestionResult[]) {
  return questions.reduce(
    (acc, q) => {
      const tier = confidenceTier(q)
      if (tier === "confident") acc.confident += 1
      else if (tier === "uncertain") acc.uncertain += 1
      else acc.needsReview += 1
      return acc
    },
    { confident: 0, uncertain: 0, needsReview: 0 },
  )
}

function IntegrityMark({ row }: { row: IntegrityRow }) {
  const Icon = row.mark === "check" ? Check : row.mark === "bang" ? Warning : Minus
  return (
    <div
      className={`w-4 h-4 flex-none mt-px rounded-full border-[1.5px] flex items-center justify-center ${
        row.color === "ok"
          ? "border-ok text-ok"
          : row.color === "warn"
            ? "border-warn text-warn"
            : "border-t2 text-t2"
      }`}
    >
      <Icon size={9} weight="bold" />
    </div>
  )
}

function ResultHeader({ res }: { res: Result }) {
  return (
    <Card className="rounded-xl overflow-hidden">
      <div className="lm-cols grid grid-cols-[1fr_300px] max-[1180px]:grid-cols-1">
        <div className="px-7 py-[26px]">
          <div className="flex items-center gap-[9px] flex-wrap">
            <PaperIdentity code={res.code} session={res.session} paperLabel={res.paper} />
            {res.markerLabel ? <Chip tone="neutral">{res.markerLabel}</Chip> : null}
          </div>
          {res.headline ? (
            <h1 className="text-display-md text-t1 mt-2.5">
              {res.headline}
            </h1>
          ) : (
            <h1 className="sr-only">
              Paper result — {res.code} {res.paper}
            </h1>
          )}
          {res.summary ? (
            <div className="text-body-md text-t2 mt-[9px] max-w-[56ch] text-pretty">
              {res.summary}
            </div>
          ) : null}

          <div className="flex items-end gap-6 mt-6 flex-wrap">
            <MarkDisplay awarded={res.awarded} available={res.max} size="hero" />
            <GradeBadge grade={res.grade} size="hero" basis="predicted" />
          </div>

          <div className="mt-[30px] border-t border-border pt-container-mobile">
            <div className="flex items-baseline gap-2.5 mb-3 flex-wrap">
              <Eyebrow>Against the {res.boundaryYear} boundaries</Eyebrow>
              <div className="flex-1" />
              {res.railFoot ? (
                <div className="font-mono text-xs text-t2">{res.railFoot}</div>
              ) : null}
            </div>
            <BoundaryBar score={res.awarded} maxScore={res.max} boundaries={NO_BOUNDARIES} />
            {res.railNote ? (
              <div className="text-body-md text-t2 leading-[1.5] mt-2 text-pretty">
                {res.railNote}
              </div>
            ) : null}
          </div>
        </div>

        <div className="border-l border-border bg-surface-2 px-container-mobile py-6 flex flex-col gap-4">
          <div className="text-sm font-semibold">
            Integrity &amp; provenance
          </div>
          {res.integrity.length === 0 ? (
            <div className="text-xs text-t2 leading-[1.4]">
              No integrity checks recorded for this paper.
            </div>
          ) : (
            res.integrity.map((i) => (
              <div key={i.label} className="flex gap-2.5 items-start">
                <IntegrityMark row={i} />
                <div>
                  <div className="text-xs leading-[1.3]">{i.label}</div>
                  <div className="text-xs text-t2 mt-0.5 leading-[1.35]">
                    {i.detail}
                  </div>
                </div>
              </div>
            ))
          )}
          {res.provenance ? (
            <div className="mt-auto font-mono text-[10.5px] text-t3 leading-[1.6] break-all border-t border-border pt-3 whitespace-pre-line">
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
    return <EmptyState {...NO_QUESTION_DETAIL} />
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
          confidence={confidenceTier(q)}
          topic={q.topic}
        >
          <div className="flex flex-col gap-2.5">
            <Chip tone="neutral" className="w-fit">
              {q.markerSource}
            </Chip>
            {q.feedback ? (
              <div className="rounded-md bg-surface-2 px-3.5 py-3 text-body-md text-t2 text-pretty">
                {q.feedback}
              </div>
            ) : null}
            {q.reviewReason ? (
              <div className="text-body-md text-warn leading-[1.4]">
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
    const summary = confidenceSummary(live.questions)
    return (
      <div className="lm-screen flex flex-col gap-container-mobile">
        <ResultHeader res={live} />
        {live.questions.length > 0 ? (
          <ConfidenceIndicatorSummary
            confident={summary.confident}
            uncertain={summary.uncertain}
            needsReview={summary.needsReview}
          />
        ) : null}
        <QuestionList questions={live.questions} />
      </div>
    )
  }

  if (isPending) {
    return (
      <div className="lm-screen flex flex-col gap-6">
        <h1 className="sr-only">Paper result</h1>
        <div role="status" className="text-sm text-t2">
          Loading result…
        </div>
      </div>
    )
  }

  if (isError) {
    if (error instanceof ApiError && error.status === 404) {
      return (
        <div className="lm-screen flex flex-col gap-6">
          <h1 className="sr-only">Paper result</h1>
          <EmptyState
            heading="No paper recorded at this address"
            body={`We don't have a result at ${paperId}.`}
            action={{ label: "Correct a paper", onClick: () => navigate("/student/correct") }}
            secondaryAction={{ label: "Back to overview", onClick: () => navigate("/student") }}
          />
        </div>
      )
    }
    return (
      <div className="lm-screen flex flex-col gap-6">
        <h1 className="sr-only">Paper result</h1>
        <ErrorState
          heading="Couldn't load this result"
          body={error.message}
          action={{ label: "Try again", onClick: () => refetch() }}
        />
      </div>
    )
  }

  return (
    <div className="lm-screen flex flex-col gap-container-mobile">
      <ResultHeader res={data} />
      <EmptyState {...NO_QUESTION_DETAIL} />
    </div>
  )
}
