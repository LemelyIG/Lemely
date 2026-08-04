import { useState, type FormEvent } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { usePostOnboarding } from "@/lib/hooks/useStudentApi"
import type { OnboardSliderInput } from "@/lib/studentTypes"

/*
 * Onboarding (isOnboard). This phase is scoped to exactly 3 CAIE subjects
 * (BUILD/MISSION.md §1): Mathematics 0580, Additional Mathematics 0606,
 * Physics 0625 — the confidence sliders below are fixed to that set, each a
 * real interactive range input bound to local state (the mock's static
 * positioned divs are gone). Submits `OnboardingRequest` to
 * usePostOnboarding() and navigates to Overview on success. There is no
 * multi-step wizard backend yet — this is the single confidence-collection
 * step, not the full onboarding flow (the mock's 5-segment progress bar and
 * "Step 3 of 5" copy implied a wizard that doesn't exist, so both are
 * dropped). The mock's "last exam week" chip multi-select has no backing
 * field on `OnboardingRequest` and is dropped rather than submitted as
 * fabricated data.
 */
const SUBJECTS: { label: string; code: string }[] = [
  { label: "Mathematics", code: "0580" },
  { label: "Additional Mathematics", code: "0606" },
  { label: "Physics", code: "0625" },
]

export function Onboarding() {
  const navigate = useNavigate()
  const onboard = usePostOnboarding()
  const [sliders, setSliders] = useState<OnboardSliderInput[]>(
    SUBJECTS.map((s) => ({ label: s.label, code: s.code, pct: 50 })),
  )
  const [gradeLevel, setGradeLevel] = useState("")
  const [school, setSchool] = useState("")
  const [weeklyHoursInput, setWeeklyHoursInput] = useState("")

  function setPct(index: number, pct: number) {
    setSliders((prev) =>
      prev.map((s, i) => (i === index ? { ...s, pct } : s)),
    )
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const weeklyHours = Number(weeklyHoursInput)
    if (!weeklyHours) return
    onboard.mutate(
      {
        gradeLevel: gradeLevel.trim() ? gradeLevel.trim() : undefined,
        school: school.trim() ? school.trim() : undefined,
        weeklyHours,
        sliders,
      },
      { onSuccess: () => navigate("/student") },
    )
  }

  return (
    <div className="lm-screen max-w-[760px] mx-auto flex flex-col gap-6">
      <div>
        <div className="font-serif text-[36px] leading-[1.15]">
          How does each subject actually feel right now?
        </div>
        <div className="text-[14px] text-t2 mt-[9px] text-pretty">
          Be honest rather than optimistic - the plan is built from this.
        </div>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-6">
        <Card className="p-6 flex flex-col gap-[22px]">
          {sliders.map((s, i) => (
            <div key={s.code}>
              <div className="flex items-baseline gap-2.5 mb-[11px]">
                <div className="text-[13.5px] font-medium">{s.label}</div>
                <div className="font-mono text-[11.5px] text-t2">{s.code}</div>
                <div className="flex-1" />
                <div className="text-[12.5px] text-accent">{s.pct}%</div>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                value={s.pct}
                onChange={(event) => setPct(i, Number(event.target.value))}
                className="w-full h-5 accent-ink"
                aria-label={`${s.label} confidence`}
              />
              <div className="flex justify-between text-[11px] text-t3 mt-[5px]">
                <span>lost</span>
                <span>confident</span>
              </div>
            </div>
          ))}
        </Card>

        <Card className="p-6 flex flex-col gap-4">
          <label className="flex flex-col gap-1.5 text-[13px]">
            Grade level
            <input
              type="text"
              value={gradeLevel}
              onChange={(event) => setGradeLevel(event.target.value)}
              placeholder="e.g. Year 11"
              className="rounded-[8px] border border-border px-3 py-2 text-[14px]"
            />
          </label>
          <label className="flex flex-col gap-1.5 text-[13px]">
            Hours you can study each week
            <input
              type="number"
              min={1}
              max={60}
              required
              value={weeklyHoursInput}
              onChange={(event) => setWeeklyHoursInput(event.target.value)}
              className="rounded-[8px] border border-border px-3 py-2 text-[14px] w-[140px]"
            />
          </label>
          <label className="flex flex-col gap-1.5 text-[13px]">
            School (optional)
            <input
              type="text"
              value={school}
              onChange={(event) => setSchool(event.target.value)}
              className="rounded-[8px] border border-border px-3 py-2 text-[14px]"
            />
          </label>
        </Card>

        {onboard.isError ? (
          <div className="text-[12.5px] text-accent">
            Couldn't save your profile: {onboard.error.message}
          </div>
        ) : null}

        <div className="flex gap-3 items-center">
          <Button
            type="submit"
            variant="accent"
            size="lg"
            disabled={onboard.isPending}
          >
            {onboard.isPending ? "Saving…" : "Continue"}
          </Button>
        </div>
      </form>
    </div>
  )
}
