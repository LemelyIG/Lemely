/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V4 */
import { Fire } from "@phosphor-icons/react"
import type { XpProfile } from "@/lib/xpTypes"
import { cn } from "@/lib/utils"
import { FOCUS, ROW_PRESS } from "../gradeClass"
import { streakLine, streakStrip } from "./meModel"

export function StreakStrip({ xp, onOpen, className }: { xp: XpProfile; onOpen: (trigger: HTMLElement) => void; className?: string }) {
  const strip = streakStrip(xp)
  const line = streakLine(xp)
  const active = strip.filter((d) => d.on).length
  const today = strip[strip.length - 1]?.on ?? false
  /* The strip is colour only, so its text alternative says the same thing in words. */
  const summary = `Earned XP on ${active} of the last ${strip.length} days${today ? ", including today" : ""}`
  return (
    <button
      type="button"
      onClick={(e) => onOpen(e.currentTarget)}
      aria-label={`${line.main}${line.best ? `, ${line.best}` : ""}. ${summary}. Open your progress`}
      className={cn("grid gap-2 text-start text-on-surface", ROW_PRESS, FOCUS, className)}
    >
      <span aria-hidden="true" className="grid grid-cols-[repeat(14,1fr)] gap-1">
        {strip.map((d) => (
          <i
            key={d.day}
            className={cn(
              "h-[22px] rounded-[6px]",
              d.on ? (d.now ? "bg-tertiary" : "bg-tertiary/60") : "bg-surface-container-highest",
              d.now && "ring-2 ring-on-tertiary-container/60",
            )}
          />
        ))}
      </span>
      <span className="flex items-center gap-2 text-[13px] text-on-surface-variant">
        <b className="inline-flex items-center gap-[5px] text-[15px] font-bold text-on-tertiary-container">
          <Fire size={14} weight="fill" aria-hidden="true" />
          {line.main}
        </b>
        {line.best}
      </span>
    </button>
  )
}
