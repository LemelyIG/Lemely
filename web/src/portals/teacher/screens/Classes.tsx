import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { StatCard } from "../components/StatCard"
import { Avatar } from "../components/Avatar"
import {
  classStats,
  mastery,
  distribution,
  bubble,
  students,
  type DistributionTone,
} from "../data"

const DIST_FILL: Record<DistributionTone, string> = {
  ok: "bg-ok",
  accent: "bg-accent",
  b: "bg-[oklch(0.82_0.09_68)]",
  err: "bg-[oklch(0.82_0.07_22)]",
  muted: "bg-[oklch(0.86_0.008_78)]",
}

export function Classes() {
  const navigate = useNavigate()

  return (
    <div className="lm-screen flex flex-col gap-5">
      <div className="flex items-end gap-[18px] pb-[18px] border-b border-border flex-wrap gap-y-2.5">
        <div>
          <div className="font-mono text-[11px] tracking-[0.11em] uppercase text-t3">
            Class · Y11 Physics · 24 students
          </div>
          <div className="font-serif text-[34px] leading-[1.1] mt-1.5">
            How is the class doing?
          </div>
        </div>
        <div className="flex-1" />
        <Button variant="secondary" className="px-4">Topic</Button>
        <Button variant="secondary" className="px-4">
          May/June 2020 · Paper 3 ›
        </Button>
        <Button variant="ink" onClick={() => navigate("/teacher/grading")}>
          Upload scans
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {classStats.map((s) => (
          <StatCard key={s.k} stat={s} />
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1.35fr_1fr] gap-5 items-start">
        {/* Mastery */}
        <div className="bg-surface border border-border rounded-[14px] p-[22px]">
          <div className="flex items-baseline gap-3 flex-wrap gap-y-2">
            <div>
              <div className="font-serif text-[23px]">
                Topic mastery vs. nationwide
              </div>
              <div className="font-mono text-[10.5px] tracking-[0.09em] uppercase text-t3 mt-[5px]">
                IGCSE Physics · 16,400 schools
              </div>
            </div>
            <div className="flex-1" />
            <div className="flex gap-[14px] text-[11.5px] text-t2">
              <span className="flex items-center gap-1.5">
                <span className="w-[7px] h-[7px] rounded-full bg-accent" />
                Your class
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-[7px] h-[7px] rounded-full bg-t3" />
                Nationwide
              </span>
            </div>
          </div>

          <div className="flex flex-col gap-3 mt-[22px]">
            {mastery.map((m) => (
              <div
                key={m.topic}
                className="grid grid-cols-[118px_1fr_92px] gap-[14px] items-center"
              >
                <div
                  className={cn(
                    "text-[13px]",
                    m.below ? "text-[oklch(0.48_0.10_22)]" : "text-t1",
                  )}
                >
                  {m.topic}
                </div>
                <div className="relative h-3 rounded-md bg-[oklch(0.94_0.012_78)]">
                  <div
                    className={cn(
                      "absolute left-0 top-0 bottom-0 rounded-md",
                      m.below ? "bg-[oklch(0.68_0.11_22)]" : "bg-accent",
                    )}
                    style={{ width: `${m.val}%` }}
                  />
                  <div
                    className="absolute -top-[3px] -bottom-[3px] w-0.5 bg-t1"
                    style={{ left: `${m.nat}%` }}
                  />
                </div>
                <div className="font-mono text-[12.5px]">
                  <span className="font-medium">{m.val}</span>{" "}
                  <span className="text-t3">vs {m.nat}</span>
                </div>
              </div>
            ))}
          </div>

          <div className="flex items-center gap-4 bg-err-bg rounded-[12px] px-[18px] py-4 mt-[22px] flex-wrap gap-y-3">
            <div className="flex-1 min-w-[240px]">
              <div className="text-[13.5px] font-medium text-[oklch(0.36_0.10_22)]">
                Thermal physics is 15 points below the national average
              </div>
              <div className="font-serif italic text-[14px] text-[oklch(0.42_0.07_22)] mt-[5px] text-pretty">
                14 of 24 students lost marks on specific heat capacity. Likely
                worth a re-teach.
              </div>
            </div>
            <Button variant="ink" size="sm" className="text-[12.5px] whitespace-nowrap">
              Lesson plan
            </Button>
          </div>
        </div>

        {/* Predicted grades */}
        <div className="bg-surface border border-border rounded-[14px] p-[22px]">
          <div className="font-serif text-[23px]">Predicted grades</div>
          <div className="font-mono text-[10.5px] tracking-[0.09em] uppercase text-t3 mt-[5px]">
            From this paper · official CAIE boundaries
          </div>

          <div className="flex items-end gap-2 h-[150px] mt-[26px]">
            {distribution.map((d) => (
              <div
                key={d.g}
                className="flex-1 flex flex-col justify-end items-center gap-2 h-full"
              >
                <div className="font-mono text-[12.5px]">{d.n}</div>
                <div
                  className={cn("w-full rounded-t-[5px]", DIST_FILL[d.tone])}
                  style={{ height: `${d.h}%` }}
                />
                <div className="font-serif text-[17px] text-t2">{d.g}</div>
              </div>
            ))}
          </div>

          <div className="border border-border rounded-[11px] px-4 py-[15px] mt-[22px] bg-[oklch(0.98_0.008_78)]">
            <div className="font-mono text-[10.5px] tracking-[0.09em] uppercase text-t3">
              Bubble students
            </div>
            <div className="flex flex-wrap gap-[14px] mt-[11px]">
              {bubble.map((b) => (
                <div
                  key={b.name}
                  className="flex items-center gap-[7px] text-[12.5px]"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-accent" />
                  {b.name} <span className="text-t3">→</span>{" "}
                  <span className="font-serif text-[15px]">{b.to}</span>
                </div>
              ))}
            </div>
            <div className="text-[12px] text-t2 mt-3 leading-[1.45] text-pretty">
              Three students are within four marks of the next grade. All three
              lost those marks in the same two topics.
            </div>
          </div>
        </div>
      </div>

      {/* Students table */}
      <div className="bg-surface border border-border rounded-[14px] overflow-hidden">
        <div className="flex items-end gap-3 px-[22px] pt-5 pb-4 flex-wrap gap-y-2.5">
          <div>
            <div className="font-serif text-[23px]">Students</div>
            <div className="font-mono text-[10.5px] tracking-[0.09em] uppercase text-t3 mt-[5px]">
              Sorted by predicted mark
            </div>
          </div>
          <div className="flex-1" />
          <Button variant="secondary" size="sm">
            + Generate group quiz
          </Button>
        </div>
        <div className="grid grid-cols-[1.6fr_80px_80px_70px_1fr_40px] gap-[14px] px-[22px] py-[9px] bg-[oklch(0.965_0.012_78)] border-y border-border font-mono text-[10px] tracking-[0.09em] uppercase text-t3">
          <div>Student</div>
          <div>Grade</div>
          <div>Mark</div>
          <div>Δ</div>
          <div>Weakest topic</div>
          <div />
        </div>
        {students.map((s) => (
          <div
            key={s.name}
            className="grid grid-cols-[1.6fr_80px_80px_70px_1fr_40px] gap-[14px] items-center px-[22px] py-[13px] border-b border-border"
          >
            <div className="flex items-center gap-[11px]">
              <Avatar
                initials={s.initials}
                tone="neutral"
                className="w-7 h-7 text-[10.5px]"
              />
              <span className="text-[13.5px]">{s.name}</span>
            </div>
            <div
              className={cn(
                "font-serif text-[19px]",
                s.gradeAtRisk ? "text-err" : "text-t1",
              )}
            >
              {s.grade}
            </div>
            <div className="font-mono text-[13px]">{s.mark}</div>
            <div
              className={cn(
                "font-mono text-[12.5px]",
                s.deltaDown ? "text-err" : "text-ok",
              )}
            >
              {s.delta}
            </div>
            <div className="text-[12.5px] text-t2">{s.weak}</div>
            <div className="text-right text-t3">›</div>
          </div>
        ))}
      </div>
    </div>
  )
}
