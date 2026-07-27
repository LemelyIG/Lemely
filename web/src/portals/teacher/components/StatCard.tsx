import { cn } from "@/lib/utils"
import type { StatCard as StatCardData } from "../data"

const VALUE_TONE = {
  t1: "text-t1",
  accent: "text-accent",
  err: "text-err",
} as const

const FOOT_TONE = {
  t2: "text-t2",
  ok: "text-ok",
  err: "text-err",
} as const

/** The four-up metric card used on Overview, Classes and Mark schemes. */
export function StatCard({ stat }: { stat: StatCardData }) {
  return (
    <div className="bg-surface border border-border rounded-[13px] px-5 py-[18px]">
      <div className="font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3">
        {stat.k}
      </div>
      <div className="flex items-baseline gap-1.5 mt-2">
        <div
          className={cn(
            "font-serif text-[40px] leading-none",
            VALUE_TONE[stat.valueTone ?? "t1"],
          )}
        >
          {stat.v}
        </div>
        {stat.unit ? (
          <div className="text-[13px] text-t2">{stat.unit}</div>
        ) : null}
      </div>
      {stat.foot ? (
        <div
          className={cn(
            "font-mono text-[11.5px] mt-2",
            FOOT_TONE[stat.footTone ?? "t2"],
          )}
        >
          {stat.foot}
        </div>
      ) : null}
    </div>
  )
}
