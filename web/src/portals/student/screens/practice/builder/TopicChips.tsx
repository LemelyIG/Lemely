/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
/* L4 · topic chips (the mock's `tmap`). Full topic text plus its count; a topic with marks lost reads weak. */
import type { TopicGroup } from "../practiceData"
import { cn } from "@/lib/utils"

export function TopicChips({
  groups,
  selected,
  onToggle,
}: {
  groups: readonly TopicGroup[]
  selected: readonly string[]
  onToggle: (topic: string) => void
}) {
  if (groups.length === 0) return null
  const showHeadings = groups.length > 1
  return (
    <div role="group" aria-label="Topics" className="grid gap-3">
      {groups.map((g) => (
        <div key={g.syllabusGroup} className="grid gap-1.5">
          {showHeadings ? <h3 className="text-[12.5px] font-semibold text-on-surface-variant">{g.syllabusGroup}</h3> : null}
          <div className="flex flex-wrap gap-1.5">
            {g.topics.map((t) => {
              const on = selected.includes(t.topic)
              return (
                <button
                  key={t.topic}
                  type="button"
                  aria-pressed={on}
                  onClick={() => onToggle(t.topic)}
                  className={cn(
                    "relative inline-flex min-h-11 items-center gap-2 rounded-[12px] px-3 text-[13.5px] font-semibold transition-[translate] duration-200 ease-out hover:-translate-y-0.5 motion-reduce:transition-none motion-reduce:hover:translate-y-0",
                    "focus-visible:!rounded-[12px] focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary",
                    t.marksLost > 0
                      ? "bg-error-container text-on-error-container"
                      : "bg-surface-container-low text-on-surface shadow-[inset_0_0_0_1px_var(--color-outline-variant)]",
                    on && t.marksLost > 0 && "shadow-[inset_0_0_0_2px_var(--color-on-error-container)]",
                    on && t.marksLost <= 0 && "bg-primary-container text-primary shadow-[inset_0_0_0_2px_var(--color-primary)]",
                  )}
                >
                  <span>{t.topic}</span>
                  <b className="font-mono text-[12px] font-bold">{t.availableCount}</b>
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
