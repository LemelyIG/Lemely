/* Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4 */
import type { ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Meter } from "@/components/ui/primitives"
import { Slider } from "@/components/ui/slider"
import { confidenceTopicsFor, subjectFor } from "@/lib/reference"
import type { ReferenceData } from "@/lib/referenceTypes"
import { usePlacementAvailability } from "@/lib/hooks/usePlacementApi"
import { useSubjectName } from "@/lib/hooks/useReferenceApi"
import { QueryState } from "@/components/ui/query-state"
import { unavailableMessage } from "../placement/placementData"
import {
  CONFIDENCE_MAX,
  CONFIDENCE_MIN,
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
 * layout branch), a visible progress meter, and a way past every question —
 * none of these fields are essential (D4.5).
 *
 * ── P4.10, and the button that erased the answer it offered to defer ───────
 *
 * **"Skip for now" appeared only once you had answered, and it deleted your
 * answer.** The condition was `!isLast && answered`, so a student who left a
 * question blank never saw it, and a student who filled one in was offered a
 * button whose label promises deferral and whose handler set the field back to
 * `undefined` before advancing. The two readings of "skip" — *I will come back
 * to this* and *throw away what I just typed* — are not the same act, and the
 * screen used the gentler word for the destructive one.
 *
 * The capability is worth keeping: answers seed from an existing profile
 * (`Onboarding.tsx`), so a student resuming onboarding may genuinely want to
 * unset a previous answer, and the Yes/No and slider questions offer no other
 * way to do it. So it stays, split into the two things it was doing at once:
 *
 *   - **Clear my answer** unsets the field and stays on the question, so the
 *     student sees it cleared rather than being moved on from a state they
 *     cannot check. It appears only when there is an answer to clear.
 *   - **Skip** is the primary action when a question is unanswered, which is
 *     what it already said. It still clears before advancing, because a seeded
 *     value can be `null` rather than `undefined` and only an explicit unset
 *     keeps it out of the PATCH body (D4.5).
 *
 * **Focus was drawn in the accent colour** on both free-text questions, which
 * DESIGN.md §3.9 reserves against precisely so focus stays distinguishable from
 * accent-coloured selection. Same fix as `SubjectsStep`.
 *
 * **A set slider value was rendered in the accent.** On this palette the accent
 * is the alert register (recorded on surfaces 5 and 6), so "8 hours/week" and a
 * confidence of 4 out of 5 — both of them good news, or at worst neutral — were
 * shown to a new student in the colour the product uses for problems.
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
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-body-sm text-ink-muted">{ariaLabel}</span>
        {/* The data face, and never the accent: a set value here is neutral or
            good news, and accent is this palette's alert register. Weight and
            the mono face carry "this is your answer" instead. */}
        <span
          className={touched ? "text-data-sm font-medium text-ink" : "text-body-sm text-ink-faint"}
        >
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
 * here: the question already IS the visible label, in display type, and adding
 * a second smaller copy of it above the field would be the same words twice.
 * Pointing the control at the heading with `aria-labelledby` gives the field a
 * real name taken from text that is already on screen, with no visual change.
 *
 * This is also why the kit's `Input` is deliberately not used on these two
 * steps, and the only place in the product where a bare `<input>` is the right
 * answer: `Input` requires a `label` by construction (§12 bans
 * placeholder-as-label), so using it here would render the question twice. The
 * field carries the kit's own border ladder and focus treatment by hand
 * instead, and has no error or loading state because this step validates
 * nothing.
 *
 * A module constant rather than `useId` because the id has to be referenced
 * from the sibling branches below, and exactly one `QuestionShell` is ever
 * mounted at a time (`steps[stepIndex]`), so it cannot collide with itself.
 */
export const QUESTION_HEADING_ID = "onboarding-question-heading"

/** The shared class list for the two free-text questions. See `QuestionShell`. */
const FREE_TEXT_FIELD =
  "min-h-11 rounded-lg border border-rule bg-paper-raised px-4 py-3 text-body-lg text-ink transition-colors hover:border-rule-strong focus-visible:border-rule-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"

function QuestionShell({ question, children }: { question: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-5">
      {/* The question IS the page title on this step, and exactly one
       * `QuestionShell` renders at a time (`steps[stepIndex]` above), so this
       * is the screen's single h1 — not a decorative div wearing display
       * type. QUALITY-BAR.md: "one h1 per page, heading order unbroken".
       *
       * `display-md` alone, not `font-serif text-display-md`: the rung already
       * names the display face, and pairing it with `font-serif` set
       * `font-family` twice on one element (D4.2). */}
      <h1 id={QUESTION_HEADING_ID} className="text-display-md text-ink">
        {question}
      </h1>
      {children}
    </div>
  )
}

/**
 * One row of the `placementChoice` question — its own component, not a
 * `.map()` callback, because it calls `usePlacementAvailability` and
 * `useSubjectName`, and a hook may never run inside `.map()`, a callback, a
 * condition, or after an early return (Hooks rule; every row renders
 * unconditionally, so every row's hooks run unconditionally too).
 *
 * A subject whose availability reports `available: false` renders its real
 * reason (`unavailableMessage`, the same copy S-03 shows) and is not
 * selectable — the student sees *why* rather than picking a dead end and
 * hitting a wall on the next screen.
 */
function PlacementChoiceRow({
  subjectCode,
  selected,
  onSelect,
}: {
  subjectCode: string
  selected: boolean
  onSelect: () => void
}) {
  const subjectName = useSubjectName(subjectCode)
  const query = usePlacementAvailability(subjectCode)

  return (
    <QueryState
      query={query}
      skeleton={
        <div className="flex flex-col gap-1 rounded-lg border border-rule p-4">
          <span className="text-body-md font-medium text-ink">{subjectName}</span>
          <span className="text-body-sm text-ink-faint">Checking availability…</span>
        </div>
      }
      // Inline (`compact`), not the full centred panel: this is one row among
      // several placement-choice candidates, not a page-sized failure — same
      // reasoning as the practice generator's preview line.
      error={{
        heading: `Couldn't check ${subjectName}'s availability`,
        compact: true,
      }}
    >
      {(data) => {
        if (!data.available) {
          const message = unavailableMessage(data.reason)
          return (
            <div
              className="flex flex-col gap-1 rounded-lg border border-rule bg-paper-sunk p-4 opacity-70"
              aria-disabled="true"
            >
              <span className="text-body-md font-medium text-ink">{subjectName}</span>
              <span className="text-body-sm text-ink-muted">{message.heading}</span>
            </div>
          )
        }

        return (
          <button
            type="button"
            aria-pressed={selected}
            onClick={onSelect}
            className={`flex flex-col gap-1 rounded-lg border p-4 text-start transition-colors ${
              selected
                ? "border-accent bg-paper-raised"
                : "border-rule bg-paper-raised hover:border-rule-strong"
            }`}
          >
            <span className="text-body-md font-medium text-ink">{subjectName}</span>
            <span className="text-body-sm text-ink-muted">
              {data.questionCount} question{data.questionCount === 1 ? "" : "s"} · about{" "}
              {Math.round(data.estimatedMinutes)} minute
              {Math.round(data.estimatedMinutes) === 1 ? "" : "s"}
            </span>
          </button>
        )
      }}
    </QueryState>
  )
}

export interface QuestionnaireStepProps {
  reference: ReferenceData | undefined
  steps: QuestionnaireStepDef[]
  stepIndex: number
  onBack: () => void
  /** Unset this question's answer and advance. The primary action when a
   * question is unanswered. */
  onSkip: () => void
  /** Unset this question's answer and stay put. See the module note. */
  onClear: () => void
  onContinue: () => void
  onFinish: () => void
  answers: QuestionnaireAnswers
  onSchoolName: (value: string) => void
  onExternalLessons: (value: boolean) => void
  onWeeklyHours: (value: number) => void
  onGradeLevel: (value: string) => void
  confidenceBySubject: Record<string, Partial<Record<string, number>>>
  onConfidence: (subjectCode: string, topic: string, rating: number) => void
  /** The chosen subject code for `kind === "placementChoice"`, or
   * `undefined` when unanswered — same skip semantics as every other step. */
  placementChoice?: string
  onPlacementChoice: (subjectCode: string) => void
  saving: boolean
  error: string | null
}

export function QuestionnaireStep({
  reference,
  steps,
  stepIndex,
  onBack,
  onSkip,
  onClear,
  onContinue,
  onFinish,
  answers,
  onSchoolName,
  onExternalLessons,
  onWeeklyHours,
  onGradeLevel,
  confidenceBySubject,
  onConfidence,
  placementChoice,
  onPlacementChoice,
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
          className={FREE_TEXT_FIELD}
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
          className={FREE_TEXT_FIELD}
        />
      </QuestionShell>
    )
  } else if (step.kind === "confidence") {
    const subject = subjectFor(reference, step.subjectCode ?? "")
    const topics = confidenceTopicsFor(subject)
    const ratings = (step.subjectCode ? confidenceBySubject[step.subjectCode] : undefined) ?? {}
    answered = Object.values(ratings).some((v) => v !== undefined)
    body = (
      <QuestionShell
        question={`How confident do you feel in ${subject?.name ?? "this subject"} right now?`}
      >
        <Card className="flex flex-col gap-5 p-5">
          {topics.map((topic) => (
            <SkippableSlider
              key={topic}
              value={ratings[topic]}
              onChange={(rating) =>
                step.subjectCode && onConfidence(step.subjectCode, topic, rating)
              }
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
  } else {
    // "placementChoice" — one row per subject the student enrolled in
    // (S-01's selection order, read off the confidence steps that precede
    // this one). Every row is its own component so its per-subject
    // availability hook runs unconditionally (see `PlacementChoiceRow`).
    const enrolledCodes = steps
      .filter((s) => s.kind === "confidence" && s.subjectCode)
      .map((s) => s.subjectCode as string)
    answered = placementChoice !== undefined
    body = (
      <QuestionShell question="Which subject would you like to be placed in first?">
        <div className="flex flex-col gap-3">
          {enrolledCodes.map((code) => (
            <PlacementChoiceRow
              key={code}
              subjectCode={code}
              selected={placementChoice === code}
              onSelect={() => onPlacementChoice(code)}
            />
          ))}
        </div>
      </QuestionShell>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1.5">
        <Meter value={progressPct} label={`Question ${stepIndex + 1} of ${total}`} />
        <span className="text-data-sm text-ink-faint">
          Question {stepIndex + 1} of {total}
        </span>
      </div>

      {body}

      {/* Above the buttons, which is where §12 puts a form-level error. */}
      {error ? (
        <p role="alert" className="text-body-sm text-err">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="ghost"
          size="lg"
          onClick={onBack}
          disabled={stepIndex === 0 || saving}
        >
          Back
        </Button>
        <div className="flex-1" />
        {/* Only when there is an answer to clear, and it says so. It does not
            advance: being moved on from a question whose state you cannot see
            is what made the old "Skip for now" misleading. */}
        {answered ? (
          <Button type="button" variant="ghost" size="lg" onClick={onClear} disabled={saving}>
            Clear my answer
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
