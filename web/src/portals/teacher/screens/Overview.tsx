import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { StatCard } from "../components/StatCard"
import { Avatar } from "../components/Avatar"
import { overviewStats, atRisk, retention } from "../data"

const TAG_TONE = {
  err: "bg-err-bg text-[oklch(0.40_0.10_22)]",
  warn: "bg-accent-subtle text-[oklch(0.42_0.10_68)]",
  neutral: "bg-[oklch(0.93_0.008_78)] text-t2",
} as const

const DELTA_TONE = {
  err: "text-err",
  warn: "text-[oklch(0.52_0.11_68)]",
  t2: "text-t2",
} as const

export function Overview() {
  const navigate = useNavigate()

  return (
    <div className="lm-screen flex flex-col gap-6">
      <div className="flex items-end gap-5 flex-wrap gap-y-2.5">
        <div>
          <div className="font-mono text-[11px] tracking-[0.11em] uppercase text-t3">
            Helwan Science Centre · Sunday 27 July
          </div>
          <div className="font-serif text-[40px] leading-[1.08] mt-2">
            Good morning, Mr Sabry.
          </div>
          <div className="text-[14.5px] text-t2 mt-2 max-w-[62ch] text-pretty">
            Twenty-eight papers were graded overnight. Twelve answers want your
            eyes, three students want your attention, and one topic wants
            re-teaching to the whole of 11-B.
          </div>
        </div>
        <div className="flex-1" />
        <Button variant="ink" size="lg" onClick={() => navigate("/teacher/review")}>
          Open review queue →
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {overviewStats.map((s) => (
          <StatCard key={s.k} stat={s} />
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_1.2fr] gap-5 items-start">
        {/* Needs you */}
        <div className="bg-surface border border-border rounded-[14px] overflow-hidden">
          <div className="px-5 pt-[18px] pb-[13px]">
            <div className="font-serif text-[22px]">Needs you</div>
            <div className="font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3 mt-[5px]">
              Flagged by trajectory, not by one bad day
            </div>
          </div>
          {atRisk.map((r) => (
            <div
              key={r.name}
              className="border-t border-border px-5 py-[15px] flex gap-[13px] items-start"
            >
              <Avatar
                initials={r.initials}
                tone={r.avatarTone}
                className="w-8 h-8 text-[11.5px]"
              />
              <div className="flex-1">
                <div className="flex items-center gap-[9px]">
                  <div className="text-[13.5px] font-medium">{r.name}</div>
                  <div
                    className={cn(
                      "text-[10.5px] rounded-full px-[9px] py-0.5",
                      TAG_TONE[r.tagTone],
                    )}
                  >
                    {r.tag}
                  </div>
                  <div className="flex-1" />
                  <div
                    className={cn(
                      "font-mono text-[12px]",
                      DELTA_TONE[r.deltaTone],
                    )}
                  >
                    {r.delta}
                  </div>
                </div>
                <div className="text-[12.5px] text-t2 mt-[5px] leading-[1.45] text-pretty">
                  {r.note}
                </div>
                <div className="flex gap-2 mt-[11px]">
                  <Button variant="secondary" size="sm" className="text-[11.5px] px-[11px] py-[6px]">
                    {r.action}
                  </Button>
                  <Button variant="secondary" size="sm" className="text-[11.5px] px-[11px] py-[6px] text-t2">
                    Message parents
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Retention + hours saved */}
        <div className="flex flex-col gap-5">
          <div className="bg-surface border border-border rounded-[14px] p-5">
            <div className="flex items-baseline gap-2.5 flex-wrap">
              <div className="font-serif text-[22px]">Lesson retention</div>
              <div className="font-mono text-[11px] text-t3">
                MOMENTS &amp; EQUILIBRIUM · 22 MIN · 21 VIEWERS
              </div>
            </div>
            <div className="text-[12.5px] text-t2 my-2.5 mb-[18px] text-pretty">
              Two replay spikes, both on the worked example where the
              substitution step is skipped. Worth re-recording those ninety
              seconds.
            </div>
            <div className="flex items-end gap-0.5 h-20">
              {retention.map((r, i) => (
                <div
                  key={i}
                  className={cn(
                    "flex-1 rounded-t-sm",
                    r.spike ? "bg-accent" : "bg-[oklch(0.88_0.04_68)]",
                  )}
                  style={{ height: `${r.h}%` }}
                />
              ))}
            </div>
            <div className="flex justify-between text-[10.5px] text-t3 font-mono mt-[7px]">
              <span>00:00</span>
              <span>08:40</span>
              <span>14:10</span>
              <span>22:00</span>
            </div>
          </div>

          <div className="bg-ink text-[oklch(0.95_0.008_78)] rounded-[14px] p-[22px] flex gap-[22px] items-center">
            <div className="flex-1">
              <div className="font-serif text-[22px]">
                This week you would have spent 9 hours marking
              </div>
              <div className="text-[13px] opacity-70 mt-2 leading-[1.5] text-pretty">
                You spent 34 minutes, all of it on the twelve answers Lemely
                refused to guess at.
              </div>
            </div>
            <div className="text-right">
              <div className="font-serif text-[46px] leading-none text-accent">
                38h
              </div>
              <div className="font-mono text-[10.5px] opacity-60 tracking-[0.08em]">
                SAVED THIS MONTH
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
