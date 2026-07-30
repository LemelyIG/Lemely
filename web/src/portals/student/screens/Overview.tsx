import { useNavigate } from "react-router-dom"
import { Card } from "@/components/ui/card"
import {
  agenda,
  firstName,
  igCalculator,
  momentum,
  nextUp,
  overviewForecast,
  subjects,
  weakGlobal,
} from "../data"
import { Bar } from "../components/viz"

/*
 * Overview (isOverview). Greeting + two stat cards, then a subjects ledger,
 * a "what to study next" + weekly agenda column, and a momentum sparkline /
 * weakest threads / IG calculator triptych.
 */
export function Overview() {
  const navigate = useNavigate()
  return (
    <div className="lm-screen flex flex-col gap-[26px]">
      <div className="flex items-end gap-5 flex-wrap">
        <div>
          <div className="font-serif text-[38px] leading-[1.1]">
            Good afternoon, {firstName}.
          </div>
          <div className="text-[14.5px] text-t2 mt-[7px] max-w-[58ch] text-pretty">
            You are 14 weeks from the October/November session. Two papers were
            corrected since Friday - thermal physics is still the weakest thread
            across your science subjects.
          </div>
        </div>
        <div className="flex-1" />
        <div className="flex gap-2.5">
          <Card className="px-[18px] py-[13px] rounded-xl min-w-[118px]">
            <div className="text-[11px] tracking-[0.09em] uppercase text-t3">
              Papers marked
            </div>
            <div className="font-serif text-[30px] leading-[1.15]">31</div>
          </Card>
          <Card className="px-[18px] py-[13px] rounded-xl min-w-[118px]">
            <div className="text-[11px] tracking-[0.09em] uppercase text-t3">
              Hours saved
            </div>
            <div className="font-serif text-[30px] leading-[1.15]">19.5</div>
          </Card>
        </div>
      </div>

      <div className="lm-cols grid grid-cols-[1.55fr_1fr] gap-5 items-start max-[1180px]:grid-cols-1">
        <Card className="overflow-hidden">
          <div className="flex items-baseline gap-3 px-5 pt-[18px] pb-[14px]">
            <div className="text-[15px] font-semibold">Subjects this session</div>
            <div className="text-[12px] text-t2">Oct/Nov 2026 - 5 enrolled</div>
            <div className="flex-1" />
            <div className="text-[11.5px] text-t2">
              Forecast{" "}
              <span className="font-mono text-t1">{overviewForecast}</span>
            </div>
          </div>
          {subjects.map((s) => (
            <button
              key={s.code}
              onClick={() => navigate("/student/subject")}
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

        <div className="flex flex-col gap-5">
          <Card className="px-5 py-[18px]">
            <div className="text-[15px] font-semibold mb-1">
              What to study next
            </div>
            <div className="text-[12px] text-t2 mb-[14px]">
              Generated from 31 corrected papers
            </div>
            <div className="flex flex-col gap-[11px]">
              {nextUp.map((n) => (
                <div
                  key={n.badge}
                  className="flex gap-3 items-start p-3 border border-border rounded-[11px] bg-surface-2"
                >
                  <div className="w-[34px] h-[34px] flex-none rounded-[9px] bg-accent-subtle text-accent flex items-center justify-center font-mono text-[11.5px] font-medium">
                    {n.badge}
                  </div>
                  <div className="flex-1 leading-[1.35]">
                    <div className="text-[13.5px] font-medium">{n.title}</div>
                    <div className="text-[12px] text-t2 mt-[3px] text-pretty">
                      {n.body}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card className="px-5 py-[18px]">
            <div className="flex items-baseline gap-2.5 mb-[14px]">
              <div className="text-[15px] font-semibold">This week</div>
              <div className="text-[12px] text-t2">3 sessions - 1 quiz</div>
            </div>
            <div className="flex flex-col">
              {agenda.map((a) => (
                <div
                  key={a.when}
                  className="grid grid-cols-[52px_1fr_auto] gap-3 items-center py-2.5 border-t border-border"
                >
                  <span className="font-mono text-[11.5px] text-t2">
                    {a.when}
                  </span>
                  <span className="text-[13px]">{a.what}</span>
                  <span
                    className={`text-[10.5px] tracking-[0.06em] uppercase border rounded-[20px] px-2 py-0.5 ${
                      a.tone === "accent"
                        ? "text-accent border-accent"
                        : a.tone === "warn"
                          ? "text-warn border-warn"
                          : "text-t2 border-border"
                    }`}
                  >
                    {a.tag}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>

      <div className="lm-cols grid grid-cols-3 gap-5 max-[1180px]:grid-cols-1">
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

        <div className="bg-ink text-bg rounded-lg px-5 py-[18px] flex flex-col">
          <div className="text-[15px] font-semibold">{igCalculator.title}</div>
          <div className="text-[12px] opacity-[0.62] mb-[14px]">
            {igCalculator.target}
          </div>
          <div className="flex items-baseline gap-2.5">
            <div className="font-serif text-[46px] leading-none">
              {igCalculator.projected}
            </div>
            <div className="text-[12px] opacity-70 leading-[1.3]">
              projected
              <br />
              aggregate
            </div>
          </div>
          <div className="h-px bg-[oklch(0.32_0.02_35)] my-4" />
          <div className="text-[12.5px] leading-[1.5] opacity-[0.82] text-pretty">
            {igCalculator.note}
          </div>
          <div className="flex-1" />
          <button className="mt-4 self-start border border-[oklch(0.42_0.02_35)] bg-transparent text-inherit font-sans text-[12.5px] px-[14px] py-2 rounded-lg cursor-pointer transition-colors hover:bg-[oklch(0.26_0.02_35)]">
            Model another route
          </button>
        </div>
      </div>
    </div>
  )
}
