import { cva, type VariantProps } from "class-variance-authority"
import type { ButtonHTMLAttributes, HTMLAttributes } from "react"
import { CaretRight } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"

/*
 * C-5 · Weakness chip — a topic tag ("Circle theorems") carrying a severity
 * weight, tappable to drill into evidence (S-19 Weakness detail). Appears in
 * three shapes: `list` (full-width row, e.g. S-18), `grid` (tile, e.g. S-08
 * weakness list), `inline` (compact pill inside prose/summaries, e.g. S-06's
 * "top weaknesses" strip).
 *
 * Severity is never color-only: each tier renders a distinct bar COUNT
 * (1/2/3, like a signal-strength glyph) plus an aria-label, so the ladder
 * survives greyscale/colorblind rendering (MISSION: no meaning by color
 * alone). Tones reuse the shared warn/err tokens — index.css has no
 * dedicated "severity" scale — and `minor` deliberately stays neutral (t3)
 * rather than amber/red, so a small weakness doesn't read as an alarm.
 */

const severityConfig = {
  minor: { bars: 1, textTone: "text-t3", barTone: "bg-t3", label: "Minor" },
  moderate: {
    bars: 2,
    textTone: "text-warn",
    barTone: "bg-warn",
    label: "Moderate",
  },
  significant: {
    bars: 3,
    textTone: "text-err",
    barTone: "bg-err",
    label: "Significant",
  },
} as const

export type WeaknessSeverity = keyof typeof severityConfig

const barHeights = ["h-1", "h-2", "h-3"] as const

function SeverityBars({ severity }: { severity: WeaknessSeverity }) {
  const cfg = severityConfig[severity]
  return (
    <span
      className="inline-flex items-end gap-0.5"
      role="img"
      aria-label={`${cfg.label} severity`}
    >
      {barHeights.map((h, i) => (
        <span
          key={h}
          className={cn(
            "w-1 rounded-full",
            h,
            i < cfg.bars ? cfg.barTone : "bg-border",
          )}
        />
      ))}
    </span>
  )
}

const weaknessChipVariants = cva(
  "inline-flex text-left transition-colors border border-border bg-surface",
  {
    variants: {
      variant: {
        list: "w-full items-center justify-between gap-3 rounded-md px-3.5 py-3",
        grid: "w-full flex-col items-start gap-2.5 rounded-md px-3.5 py-3.5",
        inline: "items-center gap-1.5 rounded-full bg-surface-2 border-transparent px-2.5 py-1",
      },
    },
    defaultVariants: { variant: "list" },
  },
)

export interface WeaknessChipProps
  extends Omit<HTMLAttributes<HTMLDivElement>, "onClick">,
    VariantProps<typeof weaknessChipVariants> {
  /** Topic label, e.g. "Circle theorems". */
  topic: string
  severity: WeaknessSeverity
  /** Optional evidence line, e.g. "cost 14 marks · 3 papers". Not shown in `inline`. */
  meta?: string
  onClick?: () => void
  className?: string
}

export function WeaknessChip({
  topic,
  severity,
  meta,
  variant = "list",
  onClick,
  className,
  ...rest
}: WeaknessChipProps) {
  const interactive = Boolean(onClick)
  const commonClassName = cn(
    weaknessChipVariants({ variant }),
    interactive && "cursor-pointer hover:bg-surface-2 active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
    variant === "inline" && interactive && "hover:bg-surface",
    className,
  )

  const content =
    variant === "inline" ? (
      <>
        <SeverityBars severity={severity} />
        <span className="text-xs font-medium text-t1">{topic}</span>
      </>
    ) : variant === "grid" ? (
      <>
        <div className="flex w-full items-center justify-between">
          <SeverityBars severity={severity} />
          {interactive ? <CaretRight size={12} className="text-t3" /> : null}
        </div>
        <div className="text-body-md font-medium text-t1">{topic}</div>
        {meta ? <div className="text-metadata text-t3">{meta}</div> : null}
      </>
    ) : (
      <>
        <div className="flex min-w-0 items-center gap-3">
          <SeverityBars severity={severity} />
          <div className="min-w-0">
            <div className="truncate text-body-md font-medium text-t1">{topic}</div>
            {meta ? <div className="mt-0.5 text-metadata text-t3">{meta}</div> : null}
          </div>
        </div>
        {interactive ? (
          <CaretRight size={14} className="flex-none text-t3" />
        ) : null}
      </>
    )

  if (interactive) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={commonClassName}
        {...(rest as ButtonHTMLAttributes<HTMLButtonElement>)}
      >
        {content}
      </button>
    )
  }

  return (
    <div className={commonClassName} {...rest}>
      {content}
    </div>
  )
}
