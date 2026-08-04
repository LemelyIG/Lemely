import { useNavigate } from "react-router-dom"
import { Card } from "@/components/ui/card"
import { useOverview } from "@/lib/hooks/useStudentApi"
import { Bar } from "../components/viz"

/*
 * Overview (isOverview). Wired to `GET /student/overview` via `useOverview()`.
 * Greeting, subjects ledger, momentum sparkline + weakest threads. The mock's
 * "what to study next" / "this week" agenda / IG-calculator cards and the
 * hardcoded "Papers marked"/"Hours saved" stats + greeting body copy had no
 * backing DTO field and were removed rather than left as stale fabricated
 * content (see D1.6 finding M2).
 */
export function Overview() {
  const navigate = useNavigate()
  const { data, isPending, isError, error } = useOverview()

  if (isPending) {
    return (
      <div className="lm-screen flex flex-col gap-[26px]">
        <div className="text-[13.5px] text-t2">Loading overview…</div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="lm-screen flex flex-col gap-[26px]">
        <div className="text-[13.5px] text-accent">
          Couldn't load your overview: {error.message}
        </div>
      </div>
    )
  }

  const { studentName, forecast, subjects, weakGlobal, momentum } = data

  // `studentName` is the authenticated user's id, not a display name (no
  // user-profile name store exists yet) — fall back to a plain greeting
  // rather than showing a raw id/UUID.
  const greetingName = studentName || "there"

  return (
    <div className="lm-screen flex flex-col gap-[26px]">
      <div className="font-serif text-[38px] leading-[1.1]">
        Good afternoon, {greetingName}.
      </div>

      <Card className="overflow-hidden">
        <div className="flex items-baseline gap-3 px-5 pt-[18px] pb-[14px]">
          <div className="text-[15px] font-semibold">Subjects this session</div>
          <div className="flex-1" />
          <div className="text-[11.5px] text-t2">
            Forecast <span className="font-mono text-t1">{forecast}</span>
          </div>
        </div>
        {subjects.map((s) => (
          <button
            key={s.code}
            onClick={() => navigate(`/student/subject/${s.code}`)}
            className="grid grid-cols-[64px_1fr_132px_86px_54px] items-center gap-[14px] w-full text-left border-0 border-t border-border bg-transparent cursor-pointer px-5 py-[14px] transition-colors hover:bg-surface-2"
          >
            <span className="font-mono text-[12px] text-t2">{s.code}</span>
            <span className="flex flex-col gap-[3px]">
              <span className="text-[14px] font-medium">{s.name}</span>
              <span className="text-[11.5px] text-t2">{s.detail}</span>
            </span>
            <span className="flex flex-col gap-[5px]">
              <Bar width={s.pct} color={s.barColor} />
              <span className="text-[11px] text-t2 font-mono">
                {s.pct}% - {s.papers} papers
              </span>
            </span>
            <span
              className={`text-[11.5px] font-mono ${s.trendUp ? "text-ok" : "text-accent"}`}
            >
              {s.trend}
            </span>
            <span className="font-serif text-[27px] text-right leading-none">
              {s.grade}
            </span>
          </button>
        ))}
      </Card>

      <div className="lm-cols grid grid-cols-2 gap-5 max-[1180px]:grid-cols-1">
        <Card className="px-5 py-[18px]">
          <div className="text-[15px] font-semibold">Momentum</div>
          <div className="text-[12px] text-t2 mb-4">
            Percentage per corrected paper, all subjects
          </div>
          <svg
            viewBox="0 0 300 88"
            className="w-full h-[88px] overflow-visible"
            aria-hidden="true"
          >
            <path d={momentum.area} fill="var(--accent-subtle)" />
            <path
              d={momentum.path}
              fill="none"
              stroke="var(--accent)"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            <circle
              cx={momentum.lastX}
              cy={momentum.lastY}
              r={3.6}
              fill="var(--accent)"
            />
          </svg>
          <div className="flex justify-between text-[11px] text-t3 font-mono mt-1.5">
            {momentum.labels.map((l) => (
              <span key={l}>{l}</span>
            ))}
          </div>
        </Card>

        <Card className="px-5 py-[18px]">
          <div className="text-[15px] font-semibold">Weakest threads</div>
          <div className="text-[12px] text-t2 mb-4">
            Accuracy by topic, all subjects
          </div>
          <div className="flex flex-col gap-[13px]">
            {weakGlobal.map((w) => (
              <div key={w.topic} className="flex flex-col gap-[5px]">
                <div className="flex justify-between text-[12.5px]">
                  <span>{w.topic}</span>
                  <span className="font-mono text-t2">{w.acc}</span>
                </div>
                <Bar width={w.width} color={w.color} />
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
