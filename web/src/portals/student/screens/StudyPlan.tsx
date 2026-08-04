import { useState, type FormEvent } from "react"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { useStudyPlan, usePostStudyPlan } from "@/lib/hooks/useStudentApi"

/*
 * Study plan (isPlan) - "Your week". Wired to `GET /student/plan` via
 * useStudyPlan(). `StudyPlanDTO.sessions` is a flat list with no day/
 * time-slot, so the mock's 7-day timetable grid is replaced with a session
 * list. "Adjust hours" posts a new `weeklyHours` via usePostStudyPlan()
 * (`{weeklyHours, narrate: true}`) and the returned narrative renders above
 * the session list once present.
 */
export function StudyPlan() {
  const { data, isPending, isError, error } = useStudyPlan()
  const postPlan = usePostStudyPlan()
  const [adjusting, setAdjusting] = useState(false)
  const [hoursInput, setHoursInput] = useState("")

  if (isPending) {
    return (
      <div className="lm-screen flex flex-col gap-[22px]">
        <div className="text-[13.5px] text-t2">Loading your plan…</div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="lm-screen flex flex-col gap-[22px]">
        <div className="text-[13.5px] text-accent">
          Couldn't load your study plan: {error.message}
        </div>
      </div>
    )
  }

  const plan = postPlan.data ?? data

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const weeklyHours = Number(hoursInput)
    if (!weeklyHours) return
    postPlan.mutate(
      { weeklyHours, narrate: true },
      { onSuccess: () => setAdjusting(false) },
    )
  }

  return (
    <div className="lm-screen flex flex-col gap-[22px]">
      <div className="flex items-end gap-5 flex-wrap">
        <div>
          <div className="font-serif text-[36px] leading-[1.1]">Your week</div>
          <div className="text-[14px] text-t2 mt-[7px] font-mono">
            {plan.weeklyHours} hours a week
          </div>
        </div>
        <div className="flex-1" />
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setAdjusting((v) => !v)}
        >
          Adjust hours
        </Button>
      </div>

      {adjusting ? (
        <Card className="p-5">
          <form onSubmit={handleSubmit} className="flex items-end gap-3 flex-wrap">
            <label className="flex flex-col gap-1.5 text-[13px]">
              Weekly hours
              <input
                type="number"
                min={1}
                max={40}
                required
                value={hoursInput}
                onChange={(event) => setHoursInput(event.target.value)}
                className="rounded-[8px] border border-border px-3 py-2 text-[14px] w-[120px]"
              />
            </label>
            <Button
              type="submit"
              variant="accent"
              size="sm"
              disabled={postPlan.isPending}
            >
              {postPlan.isPending ? "Rebuilding…" : "Rebuild plan"}
            </Button>
          </form>
          {postPlan.isError ? (
            <div className="text-[12.5px] text-accent mt-2.5">
              Couldn't rebuild your plan: {postPlan.error.message}
            </div>
          ) : null}
        </Card>
      ) : null}

      {plan.narrative ? (
        <Card className="p-5">
          <div className="text-[15px] font-semibold mb-1.5">Why this week</div>
          <div className="text-[13px] text-t2 leading-[1.5] text-pretty">
            {plan.narrative}
          </div>
        </Card>
      ) : null}

      <Card className="overflow-hidden">
        <div className="px-5 pt-[18px] pb-3 text-[15px] font-semibold">
          Sessions
        </div>
        {plan.sessions.length === 0 ? (
          <div className="px-5 pb-5 text-[13px] text-t2">
            No sessions scheduled yet.
          </div>
        ) : (
          plan.sessions.map((s, i) => (
            <div
              key={`${s.subjectCode}-${s.topic}-${i}`}
              className="grid grid-cols-[80px_1fr_70px] gap-3 items-center border-t border-border px-5 py-3"
            >
              <span className="font-mono text-[12px] text-t2">
                {s.subjectCode}
              </span>
              <span className="flex flex-col gap-[3px]">
                <span className="text-[13.5px] font-medium">{s.topic}</span>
                <span className="text-[11.5px] text-t2">{s.focus}</span>
              </span>
              <span className="font-mono text-[12.5px] text-right">
                {s.hours}h
              </span>
            </div>
          ))
        )}
      </Card>
    </div>
  )
}
