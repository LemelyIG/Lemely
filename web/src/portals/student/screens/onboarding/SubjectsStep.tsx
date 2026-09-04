/* Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4 */
import { Check, Info } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import type { CatalogueSubject, LabelledValue } from "@/lib/referenceTypes"
import { cn } from "@/lib/utils"
import type { SubjectDraft } from "./onboardingData"

/*
 * S-01 · Onboarding step 1: subjects. A card per fetched catalogue subject
 * (multi-select) that expands in place to capture papers + target grade +
 * target session once selected — exactly the UI spec's "Interactions" line
 * ("Multi-select; each selected subject expands to capture papers and
 * target grade"). Qualification level is no longer asked here (D10): the
 * subject carries its own (0580/0606/0625 are all IGCSE syllabuses).
 *
 * ── P4.10, the Study Notebook pass ────────────────────────────────────────
 *
 * **Three form controls were hand-rolled next to a kit that has them.** Two
 * `<select>` elements and a number `<input>` carried their own border, padding
 * and focus ring, so on the first screen a new student fills in, the field
 * shapes did not match any other field in the product and had none of the kit's
 * eight states: no error, no loading, no disabled treatment, and a label that
 * was a bare text node rather than a `<label for>`. They are `Select` and
 * `Input` now, which is also what puts §9.4's state set behind them.
 *
 * **Focus was drawn in the accent colour, four times.** DESIGN.md §3.9 makes
 * the focus ring deliberately blue so it cannot be confused with the accent's
 * own hover and selected states — and this screen's selected subject card is
 * accent-bordered, so a keyboard user tabbing across subjects saw "focused" and
 * "selected" rendered identically. Same defect the teacher and student sidebars
 * were fixed for in P4.5/P4.1; it was still live in the flow that runs before
 * either of them.
 *
 * **The display heading set its own font-family.** `font-serif text-display-lg`
 * declares the face twice: the `display-lg` rung already names it, and
 * `font-serif` is a build-era compat alias. Two `font-family` declarations on
 * one element resolve by stylesheet order rather than by intent, which is
 * D4.2's `MarkDisplay` finding.
 */

export interface SubjectsStepProps {
  subjects: CatalogueSubject[]
  sessionMonths: LabelledValue[]
  targetGrades: (code: string) => string[]
  loading: boolean
  loadError: boolean
  onRetry: () => void
  drafts: Record<string, SubjectDraft>
  onToggleSubject: (code: string) => void
  onTogglePaper: (code: string, paper: number) => void
  onTargetGrade: (code: string, grade: string | null) => void
  onSessionMonth: (code: string, month: string | null) => void
  onSessionYear: (code: string, year: number | null) => void
  onContinue: () => void
  saving: boolean
  error: string | null
}

export function SubjectsStep({
  subjects,
  sessionMonths,
  targetGrades,
  loading,
  loadError,
  onRetry,
  drafts,
  onToggleSubject,
  onTogglePaper,
  onTargetGrade,
  onSessionMonth,
  onSessionYear,
  onContinue,
  saving,
  error,
}: SubjectsStepProps) {
  const selectedCount = Object.keys(drafts).length

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-display-lg text-ink">What are you studying?</h1>
        <p className="max-w-[65ch] text-pretty text-body-md text-ink-muted">
          Pick a qualification and every subject you're sitting. We'll build the rest of
          onboarding and your study plan around this.
        </p>
      </div>

      {loadError ? (
        <Card className="flex flex-col items-start gap-3 p-5">
          <p role="alert" className="text-body-md text-ink">
            We couldn't load the subject list. Nothing you've entered has been lost.
          </p>
          <Button type="button" variant="secondary" size="sm" className="min-h-11" onClick={onRetry}>
            Try again
          </Button>
        </Card>
      ) : loading ? (
        // A skeleton rather than a spinner: the shape of what is coming is
        // known (a stack of subject cards), so showing it avoids the layout
        // shift a spinner guarantees.
        <div className="flex flex-col gap-4" aria-busy="true" aria-live="polite">
          <span className="sr-only">Loading subjects</span>
          {[0, 1, 2].map((i) => (
            <Card key={i} className="h-20 animate-pulse bg-paper-sunk" />
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {subjects.map((subject) => {
            const draft = drafts[subject.code]
            const selected = Boolean(draft)
            return (
              <Card
                key={subject.code}
                className={cn("overflow-hidden", selected && "border-accent")}
              >
                <button
                  type="button"
                  aria-pressed={selected}
                  onClick={() => onToggleSubject(subject.code)}
                  className="flex min-h-11 w-full cursor-pointer items-center gap-3 p-5 text-start transition-colors hover:bg-paper-sunk focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                >
                  <span
                    aria-hidden="true"
                    className={cn(
                      "flex h-6 w-6 flex-none items-center justify-center rounded-sm border",
                      selected
                        ? "border-accent bg-accent text-accent-on"
                        : "border-rule bg-paper-raised",
                    )}
                  >
                    {selected ? <Check weight="bold" className="h-3.5 w-3.5" /> : null}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-body-lg font-medium text-ink">{subject.name}</span>
                    {/* The data face: a syllabus code is an identifier, and
                        `data-sm` names the mono face itself rather than pairing
                        `font-mono` with a size rung. */}
                    <span className="block text-data-sm text-ink-faint">{subject.code}</span>
                  </span>
                </button>

                {selected && draft ? (
                  <div className="flex flex-col gap-5 border-t border-rule p-5">
                    <div className="flex flex-col gap-2">
                      <div className="text-body-sm font-medium text-ink">Papers you'll sit</div>
                      <div className="flex flex-wrap gap-x-5 gap-y-2.5">
                        {subject.papers.map((paper) => (
                          <Checkbox
                            key={paper.number}
                            label={`Paper ${paper.number}: ${paper.name}`}
                            checked={draft.papers.has(paper.number)}
                            onChange={() => onTogglePaper(subject.code, paper.number)}
                          />
                        ))}
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-4">
                      <Select
                        label="Target grade"
                        value={draft.targetGrade ?? ""}
                        onChange={(event) => onTargetGrade(subject.code, event.target.value || null)}
                        wrapperClassName="w-44"
                      >
                        <option value="">Not decided yet</option>
                        {targetGrades(subject.code).map((grade) => (
                          <option key={grade} value={grade}>
                            {grade}
                          </option>
                        ))}
                      </Select>

                      <Select
                        label="Target session"
                        value={draft.sessionMonth ?? ""}
                        onChange={(event) => onSessionMonth(subject.code, event.target.value || null)}
                        wrapperClassName="w-44"
                      >
                        <option value="">Not decided yet</option>
                        {sessionMonths.map((month) => (
                          <option key={month.value} value={month.value}>
                            {month.label}
                          </option>
                        ))}
                      </Select>

                      <Input
                        label="Year"
                        type="number"
                        inputMode="numeric"
                        // A genuine format hint, not a label substitute — `Input`
                        // refuses the latter by construction (§12).
                        placeholder="e.g. 2027"
                        value={draft.sessionYear ?? ""}
                        onChange={(event) =>
                          onSessionYear(
                            subject.code,
                            event.target.value ? Number(event.target.value) : null,
                          )
                        }
                        wrapperClassName="w-32"
                      />
                    </div>
                  </div>
                ) : null}
              </Card>
            )
          })}
        </div>
      )}

      <div className="flex items-start gap-2.5 rounded-lg bg-paper-sunk px-4 py-3">
        <Info size={16} className="mt-0.5 flex-none text-ink-faint" aria-hidden="true" />
        <p className="text-pretty text-body-sm text-ink-muted">
          More subjects are coming.{" "}
          {subjects.length > 0
            ? `${subjects.map((s) => s.name).join(", ")} ${subjects.length === 1 ? "is the one" : "are the ones"} we can mark and build study plans for today.`
            : ""}
        </p>
      </div>

      {/* Directly above the button that produced it, which is where §12 puts a
          form-level error — not at the top of the form, and not at the bottom
          under everything else. */}
      {error ? (
        <p role="alert" className="text-body-sm text-err">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="accent"
          size="lg"
          disabled={selectedCount === 0 || saving}
          onClick={onContinue}
        >
          {saving ? "Saving…" : "Continue"}
        </Button>
        {selectedCount === 0 ? (
          <span className="text-body-sm text-ink-faint">
            Select at least one subject to continue
          </span>
        ) : null}
      </div>
    </div>
  )
}
