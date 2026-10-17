import type { QuizDetail } from "@/lib/teacherTypes"

/*
 * Task 8 (C3c) · QuizBuilder's "So far" rail (`teacher-tools-quizbuilder-structure-divergence`)
 * and quiz-length slider (`teacher-tools-quiz-length-slider-vs-input`).
 *
 * `POOL_SOURCE_OPTIONS` lives here, not in `QuizBuilder.tsx`, so the rail's
 * "Pool" label can render the same human label `StepPool`'s radio group
 * shows ("Past papers", not the raw `past_paper` wire value) without a
 * circular import or a second, drifting copy of the three options.
 */

export const POOL_SOURCE_OPTIONS: { value: string; label: string; detail: string }[] = [
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

function poolSourceLabel(value: string): string {
  return POOL_SOURCE_OPTIONS.find((opt) => opt.value === value)?.label ?? value
}

/**
 * The builder's five trackable settings, in this fixed declaration order —
 * not step order (`Questions`/`Pool`, step 4, come before `Difficulty`, step
 * 3, on purpose; the order is what the rail always renders, not a re-sort by
 * when each was set). Each is anchored to the step that actually sets it:
 * `Title`/`Subject` at step 1 (Basics — `Subject` reads as read-only there,
 * fixed at quiz creation), `Difficulty` at step 3, `Questions`/`Pool` at
 * step 4 (Question pool). A setting appears only once the builder is
 * *strictly past* the step that sets it (matching the step the caller is
 * currently on shows the field still being decided, not yet "so far") *and*
 * the underlying field actually carries a value — `settingsSoFar` never
 * renders a placeholder for an unset field.
 */
export function settingsSoFar(
  quiz: QuizDetail,
  currentStep: number,
): { label: string; value: string }[] {
  const q = quiz.quiz
  const out: { label: string; value: string }[] = []

  if (currentStep > 1) {
    if (q.title) out.push({ label: "Title", value: q.title })
    if (q.subjectCode) out.push({ label: "Subject", value: q.subjectCode })
  }
  if (currentStep > 4 && q.requestedCount != null && q.requestedCount > 0) {
    out.push({
      label: "Questions",
      value: `${q.requestedCount} question${q.requestedCount === 1 ? "" : "s"}`,
    })
  }
  if (currentStep > 3 && q.targetGrade) {
    out.push({ label: "Difficulty", value: q.targetGrade })
  }
  if (currentStep > 4 && q.poolSource) {
    out.push({ label: "Pool", value: poolSourceLabel(q.poolSource) })
  }

  return out
}

/** Minutes budgeted per question in the quiz-length slider's "~N min" caption. */
export const QUIZ_MINUTES_PER_QUESTION = 2.5

/** Rounded up — a quiz never advertises less time than it could plausibly take. */
export function estimateQuizMinutes(count: number): number {
  return Math.ceil(count * QUIZ_MINUTES_PER_QUESTION)
}

/**
 * The slider's max: the real pool count once known, else a conservative 50 —
 * never unbounded (a teacher could otherwise drag past what the pool could
 * ever serve) and never below 1 (a `min=1,max=0` range input has no valid
 * value). `poolCount` is `null` before a question source is chosen or while
 * `useQuizPoolCount` is still loading — `StepPool` passes the same "not yet
 * known" case that already gates its `PoolCountPanel`.
 */
export function quizLengthUpperBound(poolCount: number | null): number {
  const base = poolCount ?? 50
  return Math.min(50, Math.max(1, base))
}
