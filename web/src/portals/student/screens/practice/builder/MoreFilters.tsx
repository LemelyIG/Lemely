/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
/* L4 · "Difficulty and source" fold (the mock's `details.more`). Native details: keyboard and reduced motion for free. */
import { PRACTICE_SOURCES } from "@/lib/practiceSources"
import { ChevronIcon } from "../practiceIcons"
import { radioKeyDown } from "./radioKeys"
import { SUBJECT_CHIP_CLASS } from "./SubjectChoice"

export function MoreFilters({
  bands,
  availableBands,
  source,
  onToggleBand,
  onSource,
}: {
  bands: readonly string[]
  availableBands: readonly string[]
  source: string | null
  onToggleBand: (band: string) => void
  onSource: (source: string | null) => void
}) {
  // Roving tabindex: the checked source is the one Tab stop; arrows move within the group.
  const stop = PRACTICE_SOURCES.some((o) => o.value === source) ? source : PRACTICE_SOURCES[0]?.value
  return (
    <details className="group">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-1.5 text-[14px] font-semibold text-primary focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary [&::-webkit-details-marker]:hidden">
        Difficulty and source
        {/* A turned icon, not a physical border corner: it points down (up when open) in either reading direction. */}
        <ChevronIcon size={16} className="rotate-90 transition-transform duration-150 motion-reduce:transition-none group-open:-rotate-90" />
      </summary>
      <div className="grid gap-3 pt-1">
        {availableBands.length > 0 ? (
          <div className="grid gap-1.5">
            <h3 className="text-[12.5px] font-semibold text-on-surface-variant">Difficulty</h3>
            <div className="flex flex-wrap gap-1.5">
              {availableBands.map((band) => (
                <button
                  key={band}
                  type="button"
                  aria-pressed={bands.includes(band)}
                  className={`${SUBJECT_CHIP_CLASS} aria-pressed:bg-primary aria-pressed:text-on-primary aria-pressed:shadow-none`}
                  onClick={() => onToggleBand(band)}
                >
                  {band[0].toUpperCase() + band.slice(1)}
                </button>
              ))}
            </div>
            <p className="text-[12.5px] text-on-surface-variant">None picked means any difficulty.</p>
          </div>
        ) : null}
        <div className="grid gap-1.5">
          <h3 className="text-[12.5px] font-semibold text-on-surface-variant">Source</h3>
          <div
            role="radiogroup"
            aria-label="Question source"
            onKeyDown={(e) => radioKeyDown(e, (i) => onSource(PRACTICE_SOURCES[i].value))}
            className="flex flex-wrap gap-1.5"
          >
            {PRACTICE_SOURCES.map((opt) => (
              <button
                key={opt.value ?? "all"}
                type="button"
                role="radio"
                aria-checked={source === opt.value}
                tabIndex={opt.value === stop ? 0 : -1}
                className={SUBJECT_CHIP_CLASS}
                onClick={() => onSource(opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </details>
  )
}
