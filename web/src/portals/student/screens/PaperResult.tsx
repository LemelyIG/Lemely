/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { ReactNode } from "react"
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { Check, Minus, ShareNetwork, Warning } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { PaperIdentity } from "@/components/ui/paper-identity"
import { MarkDisplay } from "@/components/ui/mark-display"
import { GradeBadge } from "@/components/ui/grade-badge"
import { BoundaryBar, type GradeBoundary } from "@/components/ui/boundary-bar"
import { ConfidenceIndicatorSummary } from "@/components/ui/confidence-indicator"
import { QuestionRow } from "@/components/ui/question-row"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { ListSkeleton, PanelSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Tabs, TabsList } from "@/components/ui/tabs"
import { useToast } from "@/components/ui/toast"
import { ApiError } from "@/lib/api"
import { confidenceSummaryOf, confidenceTierFor } from "@/lib/markingConfidence"
import { filterQuestions, markState, type QuestionFilter } from "@/lib/questionFilter"
import { shareResult } from "@/lib/share"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"
import { useAttemptQuestions } from "@/lib/hooks/useSelfReviewApi"
import { useResult } from "@/lib/hooks/useStudentApi"
import type { IntegrityRow, QuestionResult, Result } from "@/lib/studentTypes"

/*
 * Paper Result (isResult) - the flagship screen. Renders one result, from
 * either of two sources:
 *   - live: `location.state`, set by `CorrectPaper`'s navigate() right after a
 *     `/student/correct` run completes - carries a real `questions` array, so
 *     the flat per-question list renders.
 *   - history: `GET /student/result/{paperId}` (useResult) when there's no
 *     live state (browsing from `Subject`'s paper-history table), for the
 *     header - plus `GET /student/attempts/{attemptId}/questions`
 *     (useAttemptQuestions) for the per-question rows, when the record
 *     carries an attempt id. A file-store record has none, so an honest
 *     note replaces the list instead of an empty or fabricated one.
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

function ResultHeader({
  res,
  reveal = false,
  paperId,
}: {
  res: Result
  reveal?: boolean
  /**
   * `paperId` is passed only from the history-sourced branch below — the
   * live branch (fresh off `/student/correct`) never carries one, and that
   * absence is exactly how the Share button stays hidden there, per the
   * spec's "when paperId is present and not live".
   */
  paperId?: string
}) {
  const { toast } = useToast()
  return (
    <Card className="overflow-hidden">
      <div className="grid grid-result-cols max-tablet:grid-cols-1">
        <div className="px-7 py-6">
          <div className="flex flex-wrap items-center justify-between gap-2.5">
            <div className="flex flex-wrap items-center gap-2.5">
              <PaperIdentity code={res.code} session={res.session} paperLabel={res.paper} />
              {res.markerLabel ? <Chip tone="neutral">{res.markerLabel}</Chip> : null}
            </div>
            {paperId ? (
              // C4 (Task 11): an interactive action, not paper content — a
              // printed sheet has no click target for it.
              <Button
                variant="secondary"
                size="sm"
                data-print="hide"
                onClick={() =>
                  void shareResult(
                    {
                      url: `${location.origin}/student/result/${paperId}`,
                      title: `${res.code} ${res.paper} result`,
                      text: `${res.awarded}/${res.max}, ${res.grade}`,
                    },
                    { toast: (msg) => toast({ title: msg }) },
                  )
                }
              >
                <ShareNetwork size={16} weight="bold" />
                Share
              </Button>
            ) : null}
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
            <MarkDisplay awarded={res.awarded} available={res.max} size="hero" reveal={reveal} />
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
 * C3a (Task 6): copy for the two ways a *filtered* list can come up empty.
 * Distinct from `NO_QUESTION_DETAIL` above, which is the "this paper has no
 * per-question detail at all" case — these fire only when real questions
 * exist but none of them match the selected tab (a perfect paper filtered to
 * "Lost", say).
 */
const FILTER_EMPTY_COPY: Record<
  Exclude<QuestionFilter, "all">,
  { heading: string; body: string; marginalia: string }
> = {
  lost: {
    heading: "Every question here is correct",
    body: "No marks were dropped on this paper.",
    marginalia: "Nothing lost here",
  },
  flagged: {
    heading: "Nothing needs a second look",
    body: "No question was flagged for review or came back below the confidence floor.",
    marginalia: "Nothing flagged",
  },
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
 *
 * C3a adds the All / Lost / Flagged tabs above the row list, reading
 * `filterQuestions` — the tabs themselves only render when there is a real
 * list to filter (`questions.length > 0`); the "no per-question detail for
 * this paper" state above stays exactly as it was.
 */
function QuestionList({
  questions,
  subjectCode,
  onShare,
  filter,
  onFilterChange,
}: {
  questions: QuestionResult[]
  /** The paper's subject code (`res.code.split("/")[0]`), used to build
   * each row's `practiceHref`. */
  subjectCode: string
  /** Task 6 (B4b): shared by every row's long-press "Share" item — the same
   * action `ResultHeader`'s own Share button offers, just reachable from
   * any question row too. Unlike that button (gated on a real `paperId`),
   * this is wired from both call sites: a live result has no `paperId` yet
   * to build a permalink from, so its share falls back to the current URL
   * rather than losing the affordance entirely. */
  onShare?: () => void
  filter: QuestionFilter
  onFilterChange: (filter: QuestionFilter) => void
}) {
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

  const lostCount = filterQuestions(questions, "lost").length
  const flaggedCount = filterQuestions(questions, "flagged").length
  const visible = filterQuestions(questions, filter)

  return (
    <Card className="px-3">
      <Tabs
        value={filter}
        onValueChange={(next) => onFilterChange(next as QuestionFilter)}
        className="px-0.5 pt-1"
      >
        <TabsList
          label="Filter questions"
          tabs={[
            { value: "all", label: `All (${questions.length})` },
            { value: "lost", label: `Lost (${lostCount})` },
            { value: "flagged", label: `Flagged (${flaggedCount})` },
          ]}
        />
      </Tabs>
      {visible.length === 0 && filter !== "all" ? (
        <EmptyState
          heading={FILTER_EMPTY_COPY[filter].heading}
          body={FILTER_EMPTY_COPY[filter].body}
          marginalia={FILTER_EMPTY_COPY[filter].marginalia}
        />
      ) : (
        visible.map((q) => (
          <QuestionRow
            key={q.questionId}
            number={q.questionId}
            awarded={q.awardedMarks}
            available={q.maxMarks}
            state={markState(q)}
            confidence={confidenceTierFor(q)}
            topic={q.topic}
            practiceHref={
              q.topic
                ? `/student/practice/${subjectCode}?topic=${encodeURIComponent(q.topic)}`
                : undefined
            }
            onShare={onShare}
            register={markState(q) === "wrong" ? "red-pen" : "plain"}
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
        ))
      )}
    </Card>
  )
}

/** `?q=` values that map onto a real `QuestionFilter`; anything else (absent,
 * malformed, stale) reads as the default `"all"`. */
function filterFromParams(searchParams: URLSearchParams): QuestionFilter {
  const raw = searchParams.get("q")
  return raw === "lost" || raw === "flagged" ? raw : "all"
}

/**
 * The history-sourced question list. A separate component so the hook is
 * called unconditionally inside `QueryState`'s render prop. `result.attemptId`
 * is `null` for a file-store record, which leaves the query disabled and the
 * list empty — the same honest state this screen always had for those. A
 * fetched 404 reads the same way (see the comment on that branch below); any
 * other failure renders its own `ErrorState` rather than the honest-empty
 * list, so a broken request is never mistaken for a paper with no detail.
 */
function HistoryQuestions({
  result,
  filter,
  onFilterChange,
  onShare,
}: {
  result: Result
  filter: QuestionFilter
  onFilterChange: (filter: QuestionFilter) => void
  onShare?: () => void
}) {
  const questions = useAttemptQuestions(result.attemptId)
  if (result.attemptId && questions.isPending) {
    return <ListSkeleton rows={5} />
  }
  /*
   * A 404 here is an expected answer, not a failure: the new server-side
   * gate (`routers/student.py`) withholds a paper whose stored mark points
   * predate the group columns, deliberately, rather than serving detail it
   * cannot stand behind. That is the same "there is no per-question detail
   * for this paper" state `QuestionList`'s own empty branch already renders
   * for a file-store record with no `attemptId` at all — so a gated 404
   * falls through to `rows = []` below rather than into the error branch.
   * Anything else (a 500, a dropped connection) is a real failure the
   * honest-empty state must not be confused with, so it gets its own
   * `ErrorState` instead of silently reading as "this paper has none."
   */
  if (questions.isError && !(questions.error instanceof ApiError && questions.error.status === 404)) {
    return (
      <ErrorState
        compact
        heading="We couldn't load your questions"
        body={studentLoadFailureMessage(questions.error)}
        action={{ label: "Try again", onClick: () => void questions.refetch() }}
      />
    )
  }
  const rows = questions.data ?? []
  const summary = confidenceSummaryOf(rows)
  return (
    <>
      {rows.length > 0 ? (
        <ConfidenceIndicatorSummary
          confident={summary.confident}
          uncertain={summary.uncertain}
          needsReview={summary.needsReview}
        />
      ) : null}
      <QuestionList
        questions={rows}
        subjectCode={result.code.split("/")[0]}
        onShare={onShare}
        filter={filter}
        onFilterChange={onFilterChange}
      />
    </>
  )
}

export function PaperResult() {
  const { paperId } = useParams<{ paperId: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const { toast } = useToast()
  const live = isLiveResult(location.state) ? location.state : null

  const query = useResult(live ? "" : (paperId ?? ""))

  // C3a (Task 6): the All/Lost/Flagged filter lives in `?q=`, not local
  // component state, so it survives a round trip through a practice-topic
  // link and back (the router restores search params on a POP navigation;
  // local state does not). `replace: true` keeps a tab switch from stacking
  // a browser-history entry per tap — the URL still carries the current
  // filter whenever the reader lands here from elsewhere.
  const [searchParams, setSearchParams] = useSearchParams()
  const filter = filterFromParams(searchParams)
  function setFilter(next: QuestionFilter) {
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev)
        if (next === "all") params.delete("q")
        else params.set("q", next)
        return params
      },
      { replace: true },
    )
  }

  // Task 6 (B4b): the same share action `ResultHeader`'s own Share button
  // builds, reused for every question row's long-press "Share" item. A
  // live result has no `paperId` yet (fresh off `/student/correct`, not
  // persisted to a `/student/result/:paperId` address) — `location.href`
  // is what that student actually has open, honest even if not a permalink.
  function shareHandler(res: Result, forPaperId?: string): () => void {
    return () =>
      void shareResult(
        {
          url: forPaperId
            ? `${window.location.origin}/student/result/${forPaperId}`
            : window.location.href,
          title: `${res.code} ${res.paper} result`,
          text: `${res.awarded}/${res.max}, ${res.grade}`,
        },
        { toast: (msg) => toast({ title: msg }) },
      )
  }

  if (live) {
    const summary = confidenceSummaryOf(live.questions)
    return (
      <ResultScreen>
        <ResultHeader res={live} reveal />
        {live.questions.length > 0 ? (
          <ConfidenceIndicatorSummary
            confident={summary.confident}
            uncertain={summary.uncertain}
            needsReview={summary.needsReview}
          />
        ) : null}
        <QuestionList
          questions={live.questions}
          subjectCode={live.code.split("/")[0]}
          onShare={shareHandler(live)}
          filter={filter}
          onFilterChange={setFilter}
        />
      </ResultScreen>
    )
  }

  /*
   * The 404 case stays its own branch ahead of `<QueryState>` rather than
   * living in its `error` slot: it renders `EmptyState`, not `ErrorState`,
   * with two actions, and a heading that says what actually
   * happened ("no paper recorded here") rather than the generic "we couldn't
   * load this". `useResult`'s `enabled: !!code` only ever goes false on the
   * `live ? "" : …` branch above, which has already returned by this point —
   * so `query` below is always enabled and never parks at `fetchStatus:
   * "idle"`; no `idle` prop is needed.
   */
  if (query.isError && query.error instanceof ApiError && query.error.status === 404) {
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
    <ResultScreen>
      <QueryState
        query={query}
        srHeading="Paper result"
        /*
         * P4.2: this was a single line reading "Loading result…" where a full
         * paper result arrives — a header card with a hero mark, a grade
         * badge, a boundary bar and a sidebar, then a question list. One text
         * row standing in for all of that is the layout shift DESIGN.md §12
         * names, and it is at its worst here: this screen is what a student
         * lands on straight after watching the marking finish, so the jump
         * happens at the exact moment they are looking for their score.
         */
        skeleton={
          <>
            <PanelSkeleton bodyClassName="h-40" />
            <ListSkeleton rows={5} />
          </>
        }
        error={{
          heading: "We couldn't load this result",
          /* P6.2. This rendered `error.message`, which on a dropped connection
             is the browser's "Failed to fetch" and on a 500 is the status line.
             The 404 above is handled properly and was doing the work of hiding
             that: it is the failure anyone testing this screen reaches for, and
             it never touches this branch.

             Status-first, not detail-first. `routers/student.py`'s read paths
             raise `f"No paper {paper_id}"` — a bare UUID — so there is no
             sentence here worth keeping, which is the exact evidence
             `studentOutcome.ts` was written on. `correctionOutcome.ts` is the
             detail-first one and belongs to the marking stream, not to this
             GET.
 */
          body: studentLoadFailureMessage,
          /* The second button is the same one this branch always had. A
             result that will not load is often a result that will not load
             on the fourth try either, and a student stuck on it needs a way
             back to their overview more than a fourth retry. */
          secondaryAction: { label: "Back to overview", onClick: () => navigate("/student") },
        }}
      >
        {(data) => (
          <>
            <ResultHeader res={data} paperId={paperId} />
            {/*
             * `data.theory` is never the source for this list: it's the
             * wrong shape (`TheoryQuestionDTO`'s pre-bucketed
             * `conf`/`confColor`/`points`/`markOk`, not `QuestionResult`'s
             * raw `confidence`/`awardedMarks`/`reviewReason`) and every
             * `GET /student/result/{paper_id}` response still builds it as
             * `[]` unconditionally (`routers/student.py::student_result`).
             * The real rows come from a second endpoint keyed on the
             * attempt instead: `GET /student/attempts/{attemptId}/questions`
             * (`useAttemptQuestions`, `HistoryQuestions` below). A
             * file-store record has no `attemptId`, which disables that
             * query and leaves `QuestionList`'s own honest "No per-question
             * detail for this paper" empty state — the true state of that
             * one record, not a stand-in for data that could exist.
             */}
            <HistoryQuestions
              result={data}
              filter={filter}
              onFilterChange={setFilter}
              onShare={paperId ? shareHandler(data, paperId) : undefined}
            />
          </>
        )}
      </QueryState>
    </ResultScreen>
  )
}
