import type { ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Meter } from "@/components/ui/primitives"
import { Slider } from "@/components/ui/slider"
import {
  CONFIDENCE_MAX,
  CONFIDENCE_MIN,
  SUPPORTED_SUBJECTS,
  WEEKLY_HOURS_MAX,
  WEEKLY_HOURS_MIN,
  type QuestionnaireAnswers,
  type QuestionnaireStepDef,
} from "./onboardingData"

/*
 * S-02 · Onboarding step 2: questionnaire. One question per view (the UI
 * spec's explicit design note: "one question per view on mobile, with big
 * touch targets" — applied at every breakpoint here, both because it keeps
 * the flow honest about pace and because it's the simplest thing that is
 * unambiguously still correct on mobile without a second, untested desktop
 * layout branch), a visible progress meter, and a "Skip for now" action on
 * every question — none of these fields are essential (D4.5).
 */

/** A slider question that has never been touched must not render as an
 * answer the student gave (D4.5) — the numeric readout stays "Not set" and
 * the thumb sits at `min` until the first interaction, at which point the
 * real value starts flowing to `onChange`. */
function SkippableSlider({
  value,
  onChange,
  min,
  max,
  ariaLabel,
  formatValue,
  unsetLabel,
}: {
  value: number | undefined
  onChange: (value: number) => void
  min: number
  max: number
  ariaLabel: string
  formatValue: (value: number) => string
  unsetLabel: string
}) {
  const touched = value !== undefined
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <span className="text-dense-sm text-t2">{ariaLabel}</span>
        <span className={touched ? "text-body-md font-medium text-accent" : "text-dense-sm text-t3"}>
          {touched ? formatValue(value) : unsetLabel}
        </span>
      </div>
      <Slider
        value={value ?? min}
        onValueChange={onChange}
        min={min}
        max={max}
        aria-label={ariaLabel}
      />
    </div>
  )
}

/*
 * P3.3. The question heading doubles as the accessible name for whatever
 * control the step renders inside it.
 *
 * The two free-text steps ("Which school are you at?", "What year or grade
 * level are you in?") had a `placeholder` and nothing else — no `<label>`, no
 * `aria-label`. A placeholder is not a label: it is announced inconsistently
 * across screen readers, and it disappears the moment the student starts
 * typing, so it fails the reader who most needs it. The mission bans exactly
 * this ("visible labels, never placeholder-only").
 *
 * A separate visible `<label>` would be the obvious fix and is the wrong one
 * here: the question already IS the visible label, in 32px serif, and adding a
 * second smaller copy of it above the field would be the same words twice.
 * Pointing the control at the heading with `aria-labelledby` gives the field a
 * real name taken from text that is already on screen, with no visual change.
 *
 * A module constant rather than `useId` because the id has to be referenced
 * from the sibling branches below, and exactly one `QuestionShell` is ever
 * mounted at a time (`steps[stepIndex]`), so it cannot collide with itself.
 */
export const QUESTION_HEADING_ID = "onboarding-question-heading"

function QuestionShell({ question, children }: { question: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-5">
      {/* The question IS the page title on this step, and exactly one
       * `QuestionShell` renders at a time (`steps[stepIndex]` above), so this
       * is the screen's single h1 — not a decorative div wearing display
       * type. QUALITY-BAR.md: "one h1 per page, heading order unbroken". */}
      <h1
        id={QUESTION_HEADING_ID}
        className="font-serif text-display-md leading-display text-t1 m-0"
      >
        {question}
      </h1>
      {children}
    </div>
  )
}

export interface QuestionnaireStepProps {
  steps: QuestionnaireStepDef[]
  stepIndex: number
  onBack: () => void
  onSkip: () => void
  onContinue: () => void
  onFinish: () => void
  answers: QuestionnaireAnswers
  onSchoolName: (value: string) => void
  onExternalLessons: (value: boolean) => void
  onWeeklyHours: (value: number) => void
  onGradeLevel: (value: string) => void
  confidenceBySubject: Record<string, Partial<Record<string, number>>>
  onConfidence: (subjectCode: string, topic: string, rating: number) => void
  saving: boolean
  error: string | null
}

export function QuestionnaireStep({
  steps,
  stepIndex,
  onBack,
  onSkip,
  onContinue,
  onFinish,
  answers,
  onSchoolName,
  onExternalLessons,
  onWeeklyHours,
  onGradeLevel,
  confidenceBySubject,
  onConfidence,
  saving,
  error,
}: QuestionnaireStepProps) {
  const total = steps.length
  const step = steps[stepIndex]
  const isLast = stepIndex === total - 1
  const progressPct = total > 0 ? ((stepIndex + 1) / total) * 100 : 100

  if (!step) {
    return null
  }

  let body: ReactNode
  let answered = false

  if (step.kind === "school") {
    answered = answers.schoolName !== undefined && answers.schoolName !== null
    body = (
      <QuestionShell question="Which school are you at?">
        <input
          type="text"
          autoFocus
          value={answers.schoolName ?? ""}
          onChange={(event) => onSchoolName(event.target.value)}
          aria-labelledby={QUESTION_HEADING_ID}
          placeholder="e.g. Greenwood International School"
          className="rounded-lg border border-border bg-surface px-4 py-3 text-body-lg text-t1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent min-h-[44px]"
        />
      </QuestionShell>
    )
  } else if (step.kind === "externalLessons") {
    answered = answers.hasExternalLessons !== undefined && answers.hasExternalLessons !== null
    body = (
      <QuestionShell question="Do you take lessons or tutoring outside school?">
        <div className="flex gap-3" role="group" aria-label="External lessons or tutoring">
          <Button
            type="button"
            size="lg"
            variant={answers.hasExternalLessons === true ? "accent" : "secondary"}
            aria-pressed={answers.hasExternalLessons === true}
            onClick={() => onExternalLessons(true)}
          >
            Yes
          </Button>
          <Button
            type="button"
            size="lg"
            variant={answers.hasExternalLessons === false ? "accent" : "secondary"}
            aria-pressed={answers.hasExternalLessons === false}
            onClick={() => onExternalLessons(false)}
          >
            No
          </Button>
        </div>
      </QuestionShell>
    )
  } else if (step.kind === "weeklyHours") {
    answered = answers.weeklyStudyHours !== undefined && answers.weeklyStudyHours !== null
    body = (
      <QuestionShell question="How many hours can you study each week, outside class?">
        <SkippableSlider
          value={answers.weeklyStudyHours ?? undefined}
          onChange={onWeeklyHours}
          min={WEEKLY_HOURS_MIN}
          max={WEEKLY_HOURS_MAX}
          ariaLabel="Weekly study hours"
          unsetLabel="Not set"
          formatValue={(v) => `${v} ${v === 1 ? "hour" : "hours"}/week`}
        />
      </QuestionShell>
    )
  } else if (step.kind === "gradeLevel") {
    answered = answers.gradeLevel !== undefined && answers.gradeLevel !== null
    body = (
      <QuestionShell question="What year or grade level are you in?">
        <input
          type="text"
          autoFocus
          value={answers.gradeLevel ?? ""}
          onChange={(event) => onGradeLevel(event.target.value)}
          aria-labelledby={QUESTION_HEADING_ID}
          placeholder="e.g. Year 11"
          className="rounded-lg border border-border bg-surface px-4 py-3 text-body-lg text-t1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent min-h-[44px]"
        />
      </QuestionShell>
    )
  } else {
    const subject = SUPPORTED_SUBJECTS.find((s) => s.code === step.subjectCode)
    const ratings = (step.subjectCode ? confidenceBySubject[step.subjectCode] : undefined) ?? {}
    answered = Object.values(ratings).some((v) => v !== undefined)
    body = (
      <QuestionShell
        question={`How confident do you feel in ${subject?.name ?? "this subject"} right now?`}
      >
        <Card className="p-5 flex flex-col gap-5">
          {(subject?.confidenceTopics ?? []).map((topic) => (
            <SkippableSlider
              key={topic}
              value={ratings[topic]}
              onChange={(rating) => step.subjectCode && onConfidence(step.subjectCode, topic, rating)}
              min={CONFIDENCE_MIN}
              max={CONFIDENCE_MAX}
              ariaLabel={topic}
              unsetLabel="Not rated yet"
              formatValue={(v) => `${v} / ${CONFIDENCE_MAX}`}
            />
          ))}
        </Card>
      </QuestionShell>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1.5">
        <Meter
          value={progressPct}
          label={`Question ${stepIndex + 1} of ${total}`}
          className="h-1.5"
        />
        <span className="text-dense-sm text-t3">
          Question {stepIndex + 1} of {total}
        </span>
      </div>

      {body}

      {error ? <p className="text-dense-sm text-err">{error}</p> : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" variant="ghost" size="lg" onClick={onBack} disabled={stepIndex === 0 || saving}>
          Back
        </Button>
        <div className="flex-1" />
        {!isLast && answered ? (
          <Button type="button" variant="ghost" size="lg" onClick={onSkip} disabled={saving}>
            Skip for now
          </Button>
        ) : null}
        <Button
          type="button"
          variant="accent"
          size="lg"
          disabled={saving}
          onClick={isLast ? onFinish : answered ? onContinue : onSkip}
        >
          {saving ? "Saving…" : isLast ? "Finish" : answered ? "Continue" : "Skip"}
        </Button>
      </div>
    </div>
  )
}
