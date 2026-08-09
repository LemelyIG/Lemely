import { Check, Info } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"
import {
  GRADE_ORDER,
  QUALIFICATION_LEVELS,
  SESSION_MONTHS,
  SUPPORTED_SUBJECTS,
  type SubjectDraft,
} from "./onboardingData"

/*
 * S-01 · Onboarding step 1: subjects. Qualification level selector, then a
 * card per supported subject (multi-select) that expands in place to
 * capture papers + target grade + target session once selected — exactly
 * the UI spec's "Interactions" line ("Multi-select; each selected subject
 * expands to capture papers and target grade").
 */

export interface SubjectsStepProps {
  qualificationLevel: string | null
  onQualificationLevel: (value: string) => void
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
  qualificationLevel,
  onQualificationLevel,
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
        <h1 className="font-serif text-display-lg leading-display m-0">
          What are you studying?
        </h1>
        <p className="text-body-md text-t2 text-pretty">
          Pick a qualification and every subject you're sitting — we'll build the
          rest of onboarding and your study plan around this.
        </p>
      </div>

      <Card className="p-5 flex flex-col gap-3">
        <div className="text-dense-sm font-medium text-t1">Qualification level</div>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Qualification level">
          {QUALIFICATION_LEVELS.map((level) => {
            const active = qualificationLevel === level.value
            return (
              <Button
                key={level.value}
                type="button"
                variant={active ? "accent" : "secondary"}
                size="sm"
                // `Button size="sm"` computes to ~31px tall (12.5px text +
                // `py-2`), under QUALITY-BAR.md:40's 44px floor. Raised at the
                // call site rather than in the variant, because `sm` is used on
                // dense teacher surfaces where 44px would break the layout —
                // changing the shared variant is a cross-portal decision, not a
                // P4.8 one.
                className="min-h-[44px]"
                aria-pressed={active}
                onClick={() => onQualificationLevel(level.value)}
              >
                {level.label}
              </Button>
            )
          })}
        </div>
      </Card>

      <div className="flex flex-col gap-4">
        {SUPPORTED_SUBJECTS.map((subject) => {
          const draft = drafts[subject.code]
          const selected = Boolean(draft)
          return (
            <Card key={subject.code} className={cn("overflow-hidden", selected && "border-accent")}>
              <button
                type="button"
                aria-pressed={selected}
                onClick={() => onToggleSubject(subject.code)}
                className="flex w-full items-center gap-3 p-5 text-left cursor-pointer hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent min-h-[44px]"
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "flex h-6 w-6 flex-none items-center justify-center rounded border",
                    selected ? "bg-accent border-accent text-accent-on" : "border-border bg-surface",
                  )}
                >
                  {selected ? <Check weight="bold" className="h-3.5 w-3.5" /> : null}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-body-lg font-medium text-t1">{subject.name}</span>
                  <span className="block font-mono text-2xs text-t3">{subject.code}</span>
                </span>
              </button>

              {selected && draft ? (
                <div className="flex flex-col gap-5 border-t border-border p-5">
                  <div className="flex flex-col gap-2">
                    <div className="text-dense-sm font-medium text-t1">Papers you'll sit</div>
                    <div className="flex flex-wrap gap-x-5 gap-y-2.5">
                      {subject.papers.map((paper) => (
                        <Checkbox
                          key={paper.number}
                          label={`Paper ${paper.number} — ${paper.name}`}
                          checked={draft.papers.has(paper.number)}
                          onChange={() => onTogglePaper(subject.code, paper.number)}
                        />
                      ))}
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-4">
                    <label className="flex flex-col gap-1.5 text-dense-sm text-t2">
                      Target grade
                      <select
                        value={draft.targetGrade ?? ""}
                        onChange={(event) =>
                          onTargetGrade(subject.code, event.target.value || null)
                        }
                        className="rounded-lg border border-border bg-surface px-3 py-2 text-dense text-t1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent min-h-[44px]"
                      >
                        <option value="">Not decided yet</option>
                        {GRADE_ORDER.map((grade) => (
                          <option key={grade} value={grade}>
                            {grade}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="flex flex-col gap-1.5 text-dense-sm text-t2">
                      Target session
                      <select
                        value={draft.sessionMonth ?? ""}
                        onChange={(event) =>
                          onSessionMonth(subject.code, event.target.value || null)
                        }
                        className="rounded-lg border border-border bg-surface px-3 py-2 text-dense text-t1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent min-h-[44px]"
                      >
                        <option value="">Not decided yet</option>
                        {SESSION_MONTHS.map((month) => (
                          <option key={month.value} value={month.value}>
                            {month.label}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="flex flex-col gap-1.5 text-dense-sm text-t2">
                      Year
                      <input
                        type="number"
                        inputMode="numeric"
                        placeholder="e.g. 2027"
                        value={draft.sessionYear ?? ""}
                        onChange={(event) =>
                          onSessionYear(
                            subject.code,
                            event.target.value ? Number(event.target.value) : null,
                          )
                        }
                        className="w-[110px] rounded-lg border border-border bg-surface px-3 py-2 text-dense text-t1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent min-h-[44px]"
                      />
                    </label>
                  </div>
                </div>
              ) : null}
            </Card>
          )
        })}
      </div>

      <div className="flex items-start gap-2.5 rounded-lg bg-surface-2 px-4 py-3">
        <Info size={16} className="mt-0.5 flex-none text-t3" aria-hidden="true" />
        <p className="text-dense-sm text-t2 text-pretty">
          More subjects are coming — Mathematics 0580, Additional Mathematics 0606 and
          Physics 0625 are the ones we can mark and build study plans for today.
        </p>
      </div>

      {error ? <p className="text-dense-sm text-err">{error}</p> : null}

      <div className="flex items-center gap-3">
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
          <span className="text-dense-sm text-t3">Select at least one subject to continue</span>
        ) : null}
      </div>
    </div>
  )
}
