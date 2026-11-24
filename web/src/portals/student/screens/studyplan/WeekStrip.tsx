/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { cn } from "@/lib/utils"
import { TickGlyph } from "./icons"
import type { DayCell } from "./planModel"

function dayLabel(d: DayCell): string {
  const state = d.allDone ? "all done" : d.count === 0 ? "nothing planned" : `${d.count} ${d.count === 1 ? "session" : "sessions"}`
  return `${d.label}: ${state}${d.hasMissed ? ", missed" : ""}`
}

function circleTone(d: DayCell): string {
  if (d.isToday) return "bg-surface-container-lowest text-primary"
  if (d.allDone) return "bg-success-container text-success-text"
  if (d.hasMissed) return "bg-error-container text-on-error-container"
  if (d.count === 0) return "text-on-surface-variant shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)]"
  return "bg-surface-container-high text-on-surface"
}

/*
 * Mon–Sun (`.wk8`). Each day is a button that scrolls to that day; the name says
 * its state in words, so colour never carries it alone. Today is the one solid
 * navy cell; an empty day is a quiet hairline ring rather than a "0".
 */
export function WeekStrip({ days, onDay }: { days: DayCell[]; onDay: (date: string) => void }) {
  return (
    <ol aria-label="This week by day" className="grid grid-cols-7 gap-1.5">
      {days.map((d) => (
        <li key={d.date} className="min-w-0">
          <button
            type="button"
            onClick={() => onDay(d.date)}
            aria-current={d.isToday ? "date" : undefined}
            aria-label={dayLabel(d)}
            className={cn(
              "grid min-h-14 w-full justify-items-center gap-1 rounded-[14px] py-2 font-sans text-xs font-semibold",
              "transition-colors duration-150 ease-out motion-reduce:transition-none",
              "focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary",
              d.isToday ? "bg-primary text-on-primary" : "text-on-surface-variant hover:bg-surface-container-high",
            )}
          >
            <span aria-hidden>{d.letter}</span>
            <i aria-hidden className={cn("grid size-[26px] place-items-center rounded-full font-mono text-[13px] font-bold not-italic", circleTone(d))}>
              {d.allDone ? <TickGlyph size={14} /> : d.count > 0 ? d.count : null}
            </i>
          </button>
        </li>
      ))}
    </ol>
  )
}
