/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect, useMemo, useState, type FormEvent } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"
import type { UseQueryResult } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { Meter } from "@/components/ui/primitives"
import { Stepper, type StepperStep } from "@/components/ui/stepper"
import { cn } from "@/lib/utils"
import { Input } from "@/components/ui/input"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import { Select } from "@/components/ui/select"
import { PanelSkeleton } from "@/components/ui/loading-shapes"
import {
  teacherLoadFailureMessage,
  teacherMutationFailureMessage,
} from "@/lib/teacherOutcome"
import type { Grade } from "@/lib/types"
import {
  useCreateQuizAssignment,
  useDeleteQuizAssignment,
  useGenerateQuizQuestions,
  usePatchQuizDraft,
  useQuizAssignments,
  useQuizDetail,
  useQuizPoolCount,
  useRemoveQuizQuestion,
  useTeacherClasses,
} from "@/lib/hooks/useTeacherApi"
import type {
  ClassList,
  GenerateQuizQuestionsResponse,
  QuizPoolCount,
  QuizQuestion,
  QuizSummary,
  UpdateQuizDraftRequest,
} from "@/lib/teacherTypes"
import { statusLabel, statusTone } from "./Quizzes"

/*
 * Quiz builder (T-09) — the stepped flow at `/teacher/quizzes/:quizId`.
 * `GET /teacher/quizzes/{quizId}` (`useQuizDetail()`) is the single fetch
 * every step below reads from; each step's own mutation
 * (`usePatchQuizDraft`/`useGenerateQuizQuestions`/`useRemoveQuizQuestion`/
 * `useCreateQuizAssignment`/`useDeleteQuizAssignment`) already invalidates
 * it, so nothing here re-fetches by hand.
 *
 * **The step map is fixed by D3.15 — 1 basics, 2 content, 3 difficulty,
 * 4 pool, 5 preview/edit, 6 assign — and does not match the UI spec's literal
 * step-1 wording ("title, subject, class, due date, time limit").**
 * `class`/`due date`/`closes at` are collected at step 6 instead, because
 * they are `quiz_assignments` columns, not `quizzes` columns
 * (`docs/quiz-model.md` §1.6) — see D3.15 for the full reasoning. Step 1
 * only collects title + optional time limit; `subjectCode` is fixed at
 * creation (`CreateQuizRequest`, entered on `Quizzes.tsx`'s "New quiz" form)
 * and has no corresponding `UpdateQuizDraftRequest` field, so it renders
 * read-only here, not as an editable input the PATCH would silently drop.
 *
 * **The active step lives in `?step=n`** (`useSearchParams`), hydrated from
 * `quiz.builderStep` on first load via the effect below, mirroring P3.8
 * chunk b's `Review.tsx` filter-in-the-URL pattern. **Every step
 * navigation — tab click, Back, or a step's own "Save & continue" — goes
 * through one `goToStep(next, extra?)`**: it updates the URL immediately
 * (so the step switch never waits on a network round trip) and, only for a
 * draft quiz, fires one `PATCH` carrying `builderStep: next` plus whatever
 * field values that step is saving, in a single request — that is what
 * makes "draft saving throughout" (a named T-09 state) real: leaving
 * mid-step and coming back resumes exactly where the teacher left off, not
 * just at step 1. A failed patch surfaces as an inline error banner under
 * the stepper without rolling the visible step back — the teacher's local
 * form state for whatever step they're on is unaffected either way, so the
 * only thing at risk of being stale is the *resume point*, not their work.
 *
 * **A non-draft quiz (`status !== "draft"`) is read-only end to end**: every
 * `PATCH`/`questions/generate`/`questions/{ref}` call 422s once the quiz has
 * left `draft` (`lemely/db/quiz_repo.py`'s own precondition checks), so
 * steps 1-5 render their stored values with every input disabled and no
 * save controls at all — never an enabled control wired to a call that can
 * only fail. Step 6 is the one exception: `create_assignment` and
 * `delete_assignment` are governed by their own, independent checks (quiz
 * lifecycle state and submission state respectively — see
 * `lemely/db/quiz_repo.py`), so assigning to a further class stays offered
 * whenever the backend would actually accept it (`status` `draft` or
 * `assigned`, at least one included question), and removing an assignment
 * stays offered regardless of quiz status (only a started submission
 * refuses it). This is a narrower reading than "opens read-only" taken
 * literally everywhere — see the phase report for the judgment call and
 * why T-09's builder still doesn't expose quiz-level close/archive
 * (`useSetQuizStatus` is implemented and exported but unused here; that
 * belongs to a results screen this chunk doesn't build).
 *
 * Honesty notes carried from the backend, not to be "simplified" away:
 * `question_bank` ships empty (D3.7), so a first teacher's `past_paper`
 * pool-count is genuinely 0 for every subject — the expected first-run
 * state, not a bug. `QuizPoolCountDTO.message`/`shortfall` and
 * `GenerateQuizQuestionsResponseDTO.shortfall` are rendered verbatim, never
 * rounded, padded, or replaced with a plausible-looking number.
 *
 * **P4.5 closes this screen's contrast workaround, because the thing it was
 * working around is fixed.** This file used to avoid `--t3` entirely and use
 * `--t2` for every muted label, because axe measured the build-era `--t3` at
 * **4.36:1** against the default surface — below the 4.5:1 AA floor — at the
 * 10-13px sizes these labels use. The note recorded that fixing the shared
 * token was out of that chunk's scope. Phase 2 fixed the shared token: the
 * Study Notebook's `--ink-faint` is set at L 0.529 *specifically* so it clears
 * AA against the darkest surface it ever sits on, measuring 4.94:1 on
 * `--paper`, 5.17:1 on `--paper-raised` and 4.60:1 on `--paper-sunk`, and
 * `tests/test_design_tokens.py` pins all three. DESIGN.md §3.2 also removes
 * the lighter fifth step that made this defect reachable in the first place.
 * So the divergence is retired here and on `Quizzes.tsx`: muted labels use
 * `--ink-faint` like every other screen in the portal, and they are AA by
 * construction rather than by avoidance.
 */

const STEPS: StepperStep[] = [
  { id: 1, label: "Basics" },
  { id: 2, label: "Content" },
  { id: 3, label: "Difficulty" },
  { id: 4, label: "Question pool" },
  { id: 5, label: "Preview & edit" },
  { id: 6, label: "Assign" },
]

const GRADES: Grade[] = ["A*", "A", "B", "C", "D", "E", "U"]

const BAND_ORDER = ["foundation", "standard", "challenge"] as const

/** A stand-in count used only to preview the difficulty mix at step 3,
 * before step 4 has ever set a real `requestedCount` — `allocate_difficulty`
 * returns an all-zero mix for `count <= 0`, which would otherwise look like
 * a shortfall rather than "you haven't chosen a count yet". */
const STEP3_PREVIEW_COUNT = 12

const DEFAULT_REQUESTED_COUNT = 10

const POOL_SOURCE_OPTIONS: { value: string; label: string; detail: string }[] = [
  {
    value: "past_paper",
    label: "Past papers",
    detail: "Real CAIE exam questions, indexed by topic and mark allocation.",
  },
  {
    value: "generated",
    label: "AI-generated",
    detail: "New questions written to match CAIE style for this subject.",
  },
  {
    value: "teacher_upload",
    label: "My uploads",
    detail: "Questions taken from papers you've uploaded and had parsed yourself.",
  },
]

/** Turns a `QuizPoolCountDTO.shortfall` into the concrete "which constraint
 * to loosen" options the brief asks for — never just the raw deficit
 * numbers with no next step. */
function shortfallSuggestions(data: QuizPoolCount, quiz: QuizSummary): string[] {
  if (!data.shortfall) return []
  const out: string[] = [`Ask for fewer questions (currently ${data.requested})`]
  if (quiz.includedTopics.length > 0) out.push("Remove or loosen a topic filter in step 2")
  if (quiz.targetGrade) out.push("Try a different target grade in step 3, since bands are mixed differently per grade")
  out.push("Try a different question source")
  return out
}

function PoolCountPanel({ data, suggestions }: { data: QuizPoolCount; suggestions: string[] }) {
  const attention = data.message != null || data.shortfall != null
  return (
    <div
      className={cn(
        "border rounded-md p-4 flex flex-col gap-2.5",
        attention ? "border-warn bg-warn-wash" : "border-rule bg-paper-raised",
      )}
    >
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="text-display-sm">{data.matching}</span>
        <span className="text-body-sm text-ink-faint">
          matching question{data.matching === 1 ? "" : "s"} available · {data.requested} requested
        </span>
      </div>
      {data.message ? <p className="text-body-sm text-ink m-0 text-pretty">{data.message}</p> : null}
      {data.shortfall ? (
        <div className="flex flex-col gap-1.5">
          <div className="text-body-sm text-ink">Short by band:</div>
          <ul className="m-0 ps-4 text-body-sm text-ink-faint list-disc">
            {Object.entries(data.shortfall).map(([band, deficit]) => (
              <li key={band}>
                {band}: {deficit} short
              </li>
            ))}
          </ul>
          {suggestions.length > 0 ? (
            <>
              <div className="text-body-sm text-ink mt-1">To fix this, try one of:</div>
              <ul className="m-0 ps-4 text-body-sm text-ink-faint list-disc">
                {suggestions.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      ) : !data.message ? (
        <div className="text-body-sm text-ok">Enough questions available for this quiz.</div>
      ) : null}
      {data.difficultyEstimated ? (
        <div className="text-body-sm text-ink-faint">
          Difficulty for some of these questions is estimated from mark allocation, not measured.
        </div>
      ) : null}
    </div>
  )
}

function QuestionCard({
  question,
  onRemove,
  removing,
  removedLabel,
}: {
  question: QuizQuestion
  onRemove?: () => void
  removing?: boolean
  removedLabel?: boolean
}) {
  return (
    <div className="bg-paper-raised border border-rule rounded-md px-[18px] py-4 flex flex-col gap-2">
      <div className="flex items-center gap-2.5 flex-wrap">
        <span className="text-data-sm text-ink-faint">Q{question.position}</span>
        <Chip tone="neutral">{question.difficulty}</Chip>
        {question.topic ? <Chip tone="accent">{question.topic}</Chip> : null}
        {removedLabel ? <Chip tone="err">Removed</Chip> : null}
        <span className="flex-1" />
        <span className="text-data-sm text-ink-faint">[{question.totalMarks}]</span>
        {onRemove ? (
          <Button size="sm" variant="ghost" className="text-err" disabled={removing} onClick={onRemove}>
            Remove
          </Button>
        ) : null}
      </div>
      {/* The question stem. It used to be `font-serif italic text-base` — the
          D4.1 defect, so it rendered in Tailwind's default Georgia rather than
          in any face this design system names, and it set an exam question in
          italic. §4.2 makes italic body-copy-only and this is body copy a
          teacher reads closely, so it is now plain `body-lg` in the UI face at
          the measure §4.2 gives it. */}
      <div className="text-body-lg text-ink text-pretty">{question.prompt}</div>
      {question.mcqOptions && question.mcqOptions.length > 0 ? (
        <ul className="m-0 ps-4 text-body-md text-ink-faint list-disc">
          {question.mcqOptions.map((opt, i) => (
            <li key={i}>{opt}</li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function StepBasics({
  quiz,
  isDraft,
  onNext,
}: {
  quiz: QuizSummary
  isDraft: boolean
  onNext: (extra: UpdateQuizDraftRequest) => void
}) {
  const [title, setTitle] = useState(quiz.title)
  const [timeLimit, setTimeLimit] = useState(
    quiz.timeLimitMinutes != null ? String(quiz.timeLimitMinutes) : "",
  )

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = title.trim()
    if (!trimmed) return
    onNext({ title: trimmed, timeLimitMinutes: timeLimit.trim() ? Number(timeLimit) : null })
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5 max-w-[520px]">
      <div>
        <div className="text-eyebrow text-ink-faint mb-2">Subject</div>
        <div className="text-data-md text-ink-faint">
          {quiz.subjectCode} <span className="text-ink-faint">(fixed when the quiz was created)</span>
        </div>
      </div>
      <Input
        required
        label="Title"
        disabled={!isDraft}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <Input
        type="number"
        min={1}
        label="Time limit, minutes (optional)"
        disabled={!isDraft}
        value={timeLimit}
        onChange={(e) => setTimeLimit(e.target.value)}
        placeholder="No limit"
        wrapperClassName="w-[220px]"
      />
      {isDraft ? (
        <div>
          <Button type="submit" variant="ink">
            Save & continue →
          </Button>
        </div>
      ) : null}
    </form>
  )
}

function StepContent({
  quiz,
  classes,
  isDraft,
  onNext,
  onBack,
}: {
  quiz: QuizSummary
  classes: { subjectCode: string | null; topWeakness: string | null }[]
  isDraft: boolean
  onNext: (extra: UpdateQuizDraftRequest) => void
  onBack: (extra: UpdateQuizDraftRequest) => void
}) {
  const [topics, setTopics] = useState<string[]>(quiz.includedTopics)
  const [draftTopic, setDraftTopic] = useState("")

  const suggestions = useMemo(() => {
    const found = new Set<string>()
    for (const c of classes) {
      if (c.subjectCode === quiz.subjectCode && c.topWeakness) found.add(c.topWeakness)
    }
    for (const t of topics) found.delete(t)
    return [...found]
  }, [classes, quiz.subjectCode, topics])

  function addTopic(value: string) {
    const trimmed = value.trim()
    if (!trimmed || topics.includes(trimmed)) return
    setTopics((prev) => [...prev, trimmed])
  }

  function removeTopic(value: string) {
    setTopics((prev) => prev.filter((t) => t !== value))
  }

  function handleAddSubmit(e: FormEvent) {
    e.preventDefault()
    addTopic(draftTopic)
    setDraftTopic("")
  }

  return (
    <div className="flex flex-col gap-5 max-w-[620px]">
      <p className="text-body-md text-ink-faint text-pretty m-0">
        Topics narrow the question pool the next two steps draw from. Leave this empty to draw
        from the whole subject.
      </p>
      {isDraft ? (
        <form onSubmit={handleAddSubmit} className="flex items-end gap-2">
          <Input
            label="Add a topic"
            value={draftTopic}
            onChange={(e) => setDraftTopic(e.target.value)}
            placeholder="e.g. Kinetic theory"
            wrapperClassName="flex-1"
          />
          <Button type="submit" variant="secondary">
            Add
          </Button>
        </form>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {topics.length === 0 ? (
          <span className="text-body-sm text-ink-faint">
            No topics added, so every topic in the subject is eligible.
          </span>
        ) : null}
        {topics.map((t) => (
          <Chip key={t} tone="accent" className="gap-1.5">
            {t}
            {isDraft ? (
              <button
                type="button"
                onClick={() => removeTopic(t)}
                aria-label={`Remove topic ${t}`}
                className="cursor-pointer bg-transparent border-0 p-0 text-inherit"
              >
                ×
              </button>
            ) : null}
          </Chip>
        ))}
      </div>
      {isDraft && suggestions.length > 0 ? (
        <div>
          <div className="text-eyebrow text-ink-faint mb-1.5">
            Suggested from your classes' weak topics
          </div>
          <div className="flex flex-wrap gap-1.5">
            {suggestions.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => addTopic(s)}
                className="border border-dashed border-rule rounded-md px-3 py-1 text-body-sm text-ink-faint hover:bg-paper-sunk cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
              >
                + {s}
              </button>
            ))}
          </div>
        </div>
      ) : null}
      <div className="flex items-center gap-2">
        <Button type="button" variant="secondary" onClick={() => onBack({ includedTopics: topics })}>
          ← Back
        </Button>
        {isDraft ? (
          <Button type="button" variant="ink" onClick={() => onNext({ includedTopics: topics })}>
            Save & continue →
          </Button>
        ) : null}
      </div>
    </div>
  )
}

function StepDifficulty({
  quiz,
  isDraft,
  onNext,
  onBack,
}: {
  quiz: QuizSummary
  isDraft: boolean
  onNext: (extra: UpdateQuizDraftRequest) => void
  onBack: (extra: UpdateQuizDraftRequest) => void
}) {
  const [grade, setGrade] = useState<string | null>(quiz.targetGrade)
  const previewCount = quiz.requestedCount && quiz.requestedCount > 0 ? quiz.requestedCount : STEP3_PREVIEW_COUNT

  const poolCountQuery = useQuizPoolCount({
    subjectCode: quiz.subjectCode,
    requestedCount: previewCount,
    targetGrade: grade,
  })

  return (
    <div className="flex flex-col gap-5 max-w-[620px]">
      <p className="text-body-md text-ink-faint text-pretty m-0">
        Lemely mixes question difficulty to suit the grade you're targeting. A quiz aimed at a C
        student made entirely of "standard" questions can't tell who's nearly a B from who's
        slipping to a D, so every target keeps at least two difficulty bands in play.
      </p>
      <div>
        <div className="text-eyebrow text-ink-faint mb-2">
          Target grade
        </div>
        <div
          role="radiogroup"
          aria-label="Target grade"
          className="flex flex-wrap gap-1 bg-paper-sunk p-[5px] rounded-md w-fit"
        >
          {GRADES.map((g) => {
            const on = grade === g
            return (
              <button
                key={g}
                type="button"
                role="radio"
                aria-checked={on}
                disabled={!isDraft}
                onClick={() => setGrade(g)}
                className={cn(
                  // A grade letter is data, so the data face (§4), not the display
                  // serif this reached for by a name that resolved to Georgia.
                  // The focus ring is explicit because §3.9 says it is never
                  // removed on any element, and a bare `<button role="radio">`
                  // had only the browser default.
                  "border cursor-pointer text-data-md w-11 py-2 rounded disabled:cursor-not-allowed",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring",
                  on ? "border-rule bg-paper-raised text-ink" : "border-transparent bg-transparent text-ink-faint",
                )}
              >
                {g}
              </button>
            )
          })}
          <button
            type="button"
            role="radio"
            aria-checked={grade === null}
            disabled={!isDraft}
            onClick={() => setGrade(null)}
            className={cn(
              "border cursor-pointer text-body-sm px-3 py-2 rounded disabled:cursor-not-allowed",
              grade === null ? "border-rule bg-paper-raised text-ink" : "border-transparent text-ink-faint",
            )}
          >
            No target
          </button>
        </div>
      </div>
      <div>
        <div className="text-eyebrow text-ink-faint mb-2">
          Example mix for a {previewCount}-question quiz at this target
        </div>
        {poolCountQuery.isPending ? (
          <div className="text-body-sm text-ink-faint">Loading…</div>
        ) : poolCountQuery.isError ? (
          <div className="text-body-sm text-err">
            Couldn't load the difficulty mix: {teacherLoadFailureMessage(poolCountQuery.error)}
          </div>
        ) : (
          <div className="flex flex-col gap-2.5">
            {BAND_ORDER.map((band) => {
              const value = poolCountQuery.data.byBand[band] ?? 0
              const total = poolCountQuery.data.requested
              return (
                <div key={band} className="flex items-center gap-3">
                  <span className="w-[76px] flex-none text-body-sm text-ink-faint capitalize">{band}</span>
                  <Meter
                    value={total > 0 ? (value / total) * 100 : 0}
                    label={`${band}: ${value} of ${total} questions`}
                    className="flex-1"
                  />
                  <span className="w-8 flex-none text-end text-data-sm text-ink-faint">{value}</span>
                </div>
              )
            })}
            {quiz.requestedCount == null || quiz.requestedCount <= 0 ? (
              <p className="text-body-sm text-ink-faint m-0">
                This is an example. You'll choose the real question count in the next step.
              </p>
            ) : null}
          </div>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Button type="button" variant="secondary" onClick={() => onBack({ targetGrade: grade })}>
          ← Back
        </Button>
        {isDraft ? (
          <Button type="button" variant="ink" onClick={() => onNext({ targetGrade: grade })}>
            Save & continue →
          </Button>
        ) : null}
      </div>
    </div>
  )
}

function StepPool({
  quiz,
  isDraft,
  onNext,
  onBack,
}: {
  quiz: QuizSummary
  isDraft: boolean
  onNext: (extra: UpdateQuizDraftRequest) => void
  onBack: (extra: UpdateQuizDraftRequest) => void
}) {
  const [poolSource, setPoolSource] = useState<string | null>(quiz.poolSource)
  const [requestedCount, setRequestedCount] = useState(quiz.requestedCount ?? DEFAULT_REQUESTED_COUNT)
  const [debouncedCount, setDebouncedCount] = useState(requestedCount)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedCount(requestedCount), 300)
    return () => clearTimeout(timer)
  }, [requestedCount])

  const poolCountQuery = useQuizPoolCount({
    subjectCode: quiz.subjectCode,
    requestedCount: debouncedCount,
    targetGrade: quiz.targetGrade,
    topics: quiz.includedTopics,
    source: poolSource,
  })

  const suggestions = poolCountQuery.data ? shortfallSuggestions(poolCountQuery.data, quiz) : []

  return (
    <div className="flex flex-col gap-5 max-w-[640px]">
      <div>
        <div className="text-eyebrow text-ink-faint mb-2">
          Question source
        </div>
        <div role="radiogroup" aria-label="Question source" className="flex flex-col gap-2.5">
          {POOL_SOURCE_OPTIONS.map((opt) => {
            const on = poolSource === opt.value
            return (
              <button
                key={opt.value}
                type="button"
                role="radio"
                aria-checked={on}
                disabled={!isDraft}
                onClick={() => setPoolSource(opt.value)}
                className={cn(
                  "flex flex-col items-start gap-0.5 text-start border bg-paper-raised rounded-md px-4 py-3 cursor-pointer disabled:cursor-not-allowed",
                  on ? "border-accent" : "border-rule hover:bg-paper-sunk",
                )}
              >
                <span className="text-body-md text-ink">{opt.label}</span>
                <span className="text-body-sm text-ink-faint">{opt.detail}</span>
              </button>
            )
          })}
        </div>
      </div>
      <Input
        type="number"
        min={1}
        label="Number of questions"
        disabled={!isDraft}
        value={requestedCount}
        onChange={(e) => setRequestedCount(Math.max(0, Number(e.target.value) || 0))}
        wrapperClassName="w-[200px]"
      />

      {poolSource == null ? (
        <p className="text-body-sm text-ink-faint m-0">
          Choose a source above to see how many matching questions are available.
        </p>
      ) : poolCountQuery.isPending ? (
        <div className="text-body-sm text-ink-faint">Checking the question pool…</div>
      ) : poolCountQuery.isError ? (
        <div className="text-body-sm text-err">
          Couldn't check the pool: {teacherLoadFailureMessage(poolCountQuery.error)}
        </div>
      ) : (
        <PoolCountPanel data={poolCountQuery.data} suggestions={suggestions} />
      )}

      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="secondary"
          onClick={() => onBack({ poolSource, requestedCount })}
        >
          ← Back
        </Button>
        {isDraft ? (
          <Button
            type="button"
            variant="ink"
            onClick={() => onNext({ poolSource, requestedCount })}
          >
            Save & continue →
          </Button>
        ) : null}
      </div>
    </div>
  )
}

function StepPreview({
  quizId,
  quiz,
  questions,
  isDraft,
  onNext,
  onBack,
}: {
  quizId: string | undefined
  quiz: QuizSummary
  questions: QuizQuestion[]
  isDraft: boolean
  onNext: () => void
  onBack: () => void
}) {
  const generate = useGenerateQuizQuestions(quizId)
  const removeQuestion = useRemoveQuizQuestion(quizId)
  const [lastGenerated, setLastGenerated] = useState<GenerateQuizQuestionsResponse | null>(null)
  const [showRemoved, setShowRemoved] = useState(false)

  const included = questions.filter((q) => q.status === "included").sort((a, b) => a.position - b.position)
  const removed = questions.filter((q) => q.status !== "included")
  const canGenerate = quiz.poolSource != null

  function handleGenerate() {
    generate.mutate(undefined, { onSuccess: (data) => setLastGenerated(data) })
  }

  return (
    <div className="flex flex-col gap-5">
      {isDraft ? (
        <div className="flex items-center gap-3 flex-wrap">
          <Button
            type="button"
            variant="ink"
            disabled={!canGenerate || generate.isPending}
            title={canGenerate ? undefined : "Choose a question source in step 4 first"}
            onClick={handleGenerate}
          >
            {generate.isPending
              ? "Generating…"
              : included.length > 0
                ? "Generate more questions"
                : "Generate questions"}
          </Button>
          <span className="text-body-sm text-ink-faint">
            {quiz.requestedCount != null
              ? `${included.length} of ${quiz.requestedCount} requested`
              : `${included.length} question${included.length === 1 ? "" : "s"} so far`}
          </span>
        </div>
      ) : null}
      {!canGenerate && isDraft ? (
        <p className="text-body-sm text-ink-faint m-0">Choose a question source in step 4 before generating.</p>
      ) : null}
      {generate.isError ? (
        <div role="alert" className="text-body-sm text-err">
          Couldn't generate questions: {teacherMutationFailureMessage(generate.error)}
        </div>
      ) : null}
      {lastGenerated ? (
        <div className="text-body-sm text-ink-faint bg-paper-sunk border border-rule rounded-md px-3.5 py-3">
          Added {lastGenerated.created.length} question{lastGenerated.created.length === 1 ? "" : "s"}.
          {lastGenerated.shortfall ? (
            <ul className="m-0 mt-1.5 ps-4 list-disc">
              {Object.entries(lastGenerated.shortfall).map(([band, deficit]) => (
                <li key={band}>
                  {band}: still {deficit} short. Loosen a filter in an earlier step, or generate
                  again once more questions are indexed.
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {included.length === 0 ? (
        <EmptyState
          heading="No questions yet"
          body="Generate questions from the source chosen in step 4, or come back once more are available."
        />
      ) : (
        <div className="flex flex-col gap-3">
          {included.map((q) => (
            <QuestionCard
              key={q.questionRef}
              question={q}
              removing={removeQuestion.isPending}
              onRemove={isDraft ? () => removeQuestion.mutate(q.questionRef) : undefined}
            />
          ))}
        </div>
      )}
      {removeQuestion.isError ? (
        <div role="alert" className="text-body-sm text-err">
          Couldn't remove that question: {teacherMutationFailureMessage(removeQuestion.error)}
        </div>
      ) : null}

      {removed.length > 0 ? (
        <div>
          <button
            type="button"
            onClick={() => setShowRemoved((v) => !v)}
            className="text-body-sm text-ink-faint hover:text-ink bg-transparent border-0 p-0 cursor-pointer"
          >
            {showRemoved ? "Hide" : "Show"} {removed.length} removed question
            {removed.length === 1 ? "" : "s"} (kept for audit, not part of the quiz)
          </button>
          {showRemoved ? (
            <div className="flex flex-col gap-2 mt-2.5 opacity-70">
              {removed.map((q) => (
                <QuestionCard key={q.questionRef} question={q} removedLabel />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="flex items-center gap-2">
        <Button type="button" variant="secondary" onClick={onBack}>
          ← Back
        </Button>
        <Button type="button" variant="ink" onClick={onNext}>
          {isDraft ? "Save & continue →" : "Continue →"}
        </Button>
      </div>
    </div>
  )
}

function StepAssign({
  quizId,
  quiz,
  classesQuery,
  onBack,
}: {
  quizId: string | undefined
  quiz: QuizSummary
  classesQuery: UseQueryResult<ClassList, Error>
  onBack: () => void
}) {
  const assignmentsQuery = useQuizAssignments(quizId)
  const createAssignment = useCreateQuizAssignment(quizId)
  const deleteAssignment = useDeleteQuizAssignment(quizId)

  const [classId, setClassId] = useState("")
  const [dueAt, setDueAt] = useState("")
  const [closesAt, setClosesAt] = useState("")

  const canAssign =
    (quiz.status === "draft" || quiz.status === "assigned") && quiz.questionCount > 0

  function handleAssign(e: FormEvent) {
    e.preventDefault()
    if (!classId) return
    createAssignment.mutate(
      {
        classId,
        dueAt: dueAt ? new Date(dueAt).toISOString() : undefined,
        closesAt: closesAt ? new Date(closesAt).toISOString() : undefined,
      },
      {
        onSuccess: () => {
          setClassId("")
          setDueAt("")
          setClosesAt("")
        },
      },
    )
  }

  /*
   * `window.confirm` used to stand here. It is an OS dialog whose buttons say
   * "OK" and "Cancel", so the destructive choice was never named; it cannot
   * show the pending or failed state of the mutation behind it; and browsers
   * may suppress it after repeated use, which means a confirmation the
   * product believes it is showing can stop appearing. C-24 `ConfirmModal` is
   * the pattern surface 3 established for exactly this.
   *
   * The consequence line is overridden because this action is genuinely
   * recoverable: unassigning does not delete the quiz, and the same class can
   * be assigned again. Claiming "this cannot be undone" here would be the
   * honesty defect in the other direction.
   */
  const [unassigning, setUnassigning] = useState<{ id: string; className: string } | null>(null)

  return (
    <div className="flex flex-col gap-5 max-w-[640px]">
      {quiz.questionCount === 0 ? (
        <p className="text-body-sm text-warn m-0">
          Add at least one question in step 5 before assigning this quiz.
        </p>
      ) : quiz.status === "closed" || quiz.status === "archived" ? (
        <p className="text-body-sm text-ink-faint m-0">
          This quiz is {statusLabel(quiz.status).toLowerCase()}, so it can no longer be assigned
          to any class.
        </p>
      ) : canAssign ? (
        <form
          onSubmit={handleAssign}
          className="bg-paper-raised border border-rule rounded-lg p-[18px] flex flex-col gap-3"
        >
          {/* The label used to wrap all three branches, so while the classes
              were loading or had failed there was a `<label>` pointing at no
              control at all. The kit's `<Select>` owns its own label, and the
              two non-ready states are now plain lines beside it rather than
              inside it. */}
          {classesQuery.isPending ? (
            <div className="text-body-sm text-ink-faint">Loading your classes…</div>
          ) : classesQuery.isError ? (
            <div className="text-body-sm text-err">
              Couldn't load your classes: {teacherLoadFailureMessage(classesQuery.error)}
            </div>
          ) : (
            <Select
              required
              label="Class"
              value={classId}
              onChange={(e) => setClassId(e.target.value)}
            >
              <option value="" disabled>
                Choose a class…
              </option>
              {classesQuery.data.classes.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </Select>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Input
              type="datetime-local"
              label="Due (optional)"
              value={dueAt}
              onChange={(e) => setDueAt(e.target.value)}
            />
            <Input
              type="datetime-local"
              label="Closes (optional)"
              value={closesAt}
              onChange={(e) => setClosesAt(e.target.value)}
            />
          </div>
          <div>
            <Button type="submit" variant="ink" disabled={createAssignment.isPending || !classId}>
              {createAssignment.isPending ? "Assigning…" : "Assign"}
            </Button>
          </div>
          {createAssignment.isError ? (
            <div role="alert" className="text-body-sm text-err">
              Couldn't assign: {teacherMutationFailureMessage(createAssignment.error)}
            </div>
          ) : null}
        </form>
      ) : null}

      <div>
        <div className="text-eyebrow text-ink-faint mb-2">
          Assigned to
        </div>
        {assignmentsQuery.isPending ? (
          <div className="text-body-sm text-ink-faint">Loading assignments…</div>
        ) : assignmentsQuery.isError ? (
          <div className="text-body-sm text-err">
            Couldn't load assignments: {teacherLoadFailureMessage(assignmentsQuery.error)}
          </div>
        ) : assignmentsQuery.data.assignments.length === 0 ? (
          <div className="text-body-sm text-ink-faint">Not assigned to any class yet.</div>
        ) : (
          <ul className="flex flex-col gap-2 m-0 p-0 list-none">
            {assignmentsQuery.data.assignments.map((a) => (
              <li
                key={a.id}
                className="bg-paper-raised border border-rule rounded-md px-4 py-3 flex items-center gap-3 flex-wrap"
              >
                <Link to={`/teacher/classes/${a.classId}`} className="text-ink hover:underline text-body-lg">
                  {a.className}
                </Link>
                <span className="text-body-sm text-ink-faint">
                  {a.rosterSize} student{a.rosterSize === 1 ? "" : "s"}
                </span>
                {a.dueAt ? (
                  <span className="text-body-sm text-ink-faint">Due {new Date(a.dueAt).toLocaleString()}</span>
                ) : null}
                <span className="flex-1" />
                {/* T-09's exit to T-10. Results are per assignment, so the
                    link carries this assignment's id, not just the quiz's. */}
                <Link
                  to={`/teacher/quizzes/${quizId}/assignments/${a.id}/results`}
                  className="text-body-sm text-ink hover:underline"
                >
                  View results →
                </Link>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-err"
                  disabled={deleteAssignment.isPending}
                  onClick={() => setUnassigning({ id: a.id, className: a.className })}
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
        <ConfirmModal
          open={unassigning !== null}
          title="Remove this quiz from the class?"
          description={
            unassigning ? `${unassigning.className} will no longer see this quiz.` : undefined
          }
          consequence="You can assign it to this class again later. Any submissions already started are not deleted."
          confirmLabel="Remove"
          pendingLabel="Removing…"
          pending={deleteAssignment.isPending}
          error={
            deleteAssignment.isError
              ? teacherMutationFailureMessage(deleteAssignment.error)
              : null
          }
          onCancel={() => setUnassigning(null)}
          onConfirm={() => {
            if (!unassigning) return
            deleteAssignment.mutate(unassigning.id, {
              onSuccess: () => setUnassigning(null),
            })
          }}
        />
      </div>

      <div>
        <Button type="button" variant="secondary" onClick={onBack}>
          ← Back
        </Button>
      </div>
    </div>
  )
}

export function QuizBuilder() {
  const { quizId } = useParams<{ quizId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()

  const quizQuery = useQuizDetail(quizId)
  const patchDraft = usePatchQuizDraft(quizId)
  const classesQuery = useTeacherClasses()

  const quiz = quizQuery.data?.quiz

  // Hydrate `?step=` from the stored `builderStep` on first load only — a
  // teacher who has already navigated (the param is present) keeps control
  // of where they are, this never fights their own back-button use.
  useEffect(() => {
    if (quiz && !searchParams.get("step")) {
      setSearchParams({ step: String(quiz.builderStep) }, { replace: true })
    }
  }, [quiz, searchParams, setSearchParams])

  if (quizQuery.isPending) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Quiz builder</h1>
        {/* The stepper plus a step panel are what arrive, so two panel
            shapes hold that space. §12: the loading state matches the layout
            it replaces. */}
        <PanelSkeleton />
        <PanelSkeleton />
      </div>
    )
  }

  if (quizQuery.isError) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Quiz builder</h1>
        <ErrorState
          heading="Couldn't load this quiz"
          body={teacherLoadFailureMessage(quizQuery.error)}
          action={{ label: "Retry", onClick: () => quizQuery.refetch() }}
          secondaryAction={{ label: "Back to quizzes", onClick: () => history.back() }}
        />
      </div>
    )
  }

  const { quiz: loadedQuiz, questions } = quizQuery.data
  const isDraft = loadedQuiz.status === "draft"
  const stepFromUrl = Number(searchParams.get("step"))
  const step =
    Number.isInteger(stepFromUrl) && stepFromUrl >= 1 && stepFromUrl <= 6
      ? stepFromUrl
      : loadedQuiz.builderStep

  function goToStep(next: number, extra?: UpdateQuizDraftRequest) {
    setSearchParams({ step: String(next) })
    if (isDraft) {
      patchDraft.mutate({ ...extra, builderStep: next })
    }
  }

  const completed = new Set<number>()
  if (loadedQuiz.title.trim()) completed.add(1)
  if (loadedQuiz.includedTopics.length > 0) completed.add(2)
  if (loadedQuiz.targetGrade) completed.add(3)
  if (loadedQuiz.poolSource) completed.add(4)
  if (loadedQuiz.questionCount > 0) completed.add(5)
  if (!isDraft) completed.add(6)

  return (
    <div className="lm-screen flex flex-col gap-6 min-w-0">
      <div className="flex flex-col gap-1">
        <Link to="/teacher/quizzes" className="text-body-sm text-ink-faint hover:text-ink w-fit">
          ← All quizzes
        </Link>
        <div className="flex items-start gap-3 flex-wrap gap-y-2 mt-1">
          <div className="min-w-0">
            <div className="text-eyebrow text-ink-faint">
              {loadedQuiz.subjectCode}
            </div>
            <h1 className="text-display-md mt-1 text-pretty">
              {loadedQuiz.title}
            </h1>
          </div>
          <div className="flex-1" />
          <Chip tone={statusTone(loadedQuiz.status)}>{statusLabel(loadedQuiz.status)}</Chip>
        </div>
      </div>

      {!isDraft ? (
        <div className="text-body-sm text-ink-faint bg-paper-sunk border border-rule rounded-md px-3.5 py-3 text-pretty">
          This quiz is {statusLabel(loadedQuiz.status).toLowerCase()}, so its title, topics,
          difficulty, source and questions can no longer be changed. What follows is read-only,
          showing exactly what was configured and (below) who it's assigned to.
        </div>
      ) : null}

      {/* Navigation itself is never disabled, even for a non-draft quiz —
          "read-only" means every step's own form controls can't be edited
          (each step component gates its inputs on `isDraft` individually),
          not that a teacher can no longer browse what was configured. */}
      <Stepper steps={STEPS} current={step} onSelect={(id) => goToStep(id)} completed={completed} />

      {isDraft && patchDraft.isError ? (
        <div role="alert" className="text-body-sm text-err">
          Couldn't save your progress: {teacherMutationFailureMessage(patchDraft.error)}
        </div>
      ) : null}

      {step === 1 ? (
        <StepBasics quiz={loadedQuiz} isDraft={isDraft} onNext={(extra) => goToStep(2, extra)} />
      ) : null}
      {step === 2 ? (
        <StepContent
          quiz={loadedQuiz}
          classes={classesQuery.data?.classes ?? []}
          isDraft={isDraft}
          onNext={(extra) => goToStep(3, extra)}
          onBack={(extra) => goToStep(1, extra)}
        />
      ) : null}
      {step === 3 ? (
        <StepDifficulty
          quiz={loadedQuiz}
          isDraft={isDraft}
          onNext={(extra) => goToStep(4, extra)}
          onBack={(extra) => goToStep(2, extra)}
        />
      ) : null}
      {step === 4 ? (
        <StepPool
          quiz={loadedQuiz}
          isDraft={isDraft}
          onNext={(extra) => goToStep(5, extra)}
          onBack={(extra) => goToStep(3, extra)}
        />
      ) : null}
      {step === 5 ? (
        <StepPreview
          quizId={quizId}
          quiz={loadedQuiz}
          questions={questions}
          isDraft={isDraft}
          onNext={() => goToStep(6)}
          onBack={() => goToStep(4)}
        />
      ) : null}
      {step === 6 ? (
        <StepAssign quizId={quizId} quiz={loadedQuiz} classesQuery={classesQuery} onBack={() => goToStep(5)} />
      ) : null}
    </div>
  )
}
