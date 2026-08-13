import { useState } from "react"
import { CheckCircle, Flag, Info, WarningCircle, type Icon } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"

/*
 * C-4 Confidence indicator — the most novel component in the product
 * (LEMELY_UI_SPEC 1.6 / 2). Three tiers, each carrying color AND a distinct
 * icon shape so the ladder survives greyscale: confident is quiet (small,
 * unfilled, no chrome), needs-review is loud (filled, bordered, labeled) —
 * "quiet when confident, impossible to miss when it's low."
 *
 * Two variants:
 *   - ConfidenceIndicator: per-question compact chip, click-to-expand plain-
 *     language explanation (a real disclosure, not a hover-only tooltip, so
 *     it works on the touch-first student surface).
 *   - ConfidenceIndicatorSummary: per-paper aggregate — "We're confident
 *     about 19 of 21 questions. Two are waiting for your teacher to check."
 */

export type ConfidenceTier = "confident" | "uncertain" | "needs-review"

interface TierMeta {
  label: string
  icon: Icon
  explanation: string
}

const tierMeta: Record<ConfidenceTier, TierMeta> = {
  confident: {
    label: "Confident",
    icon: CheckCircle,
    explanation: "We're confident about this mark.",
  },
  uncertain: {
    label: "Uncertain",
    icon: WarningCircle,
    explanation:
      "We're not fully certain about this one. It's a close call, and your teacher may take a look.",
  },
  "needs-review": {
    label: "Needs review",
    icon: Flag,
    explanation:
      "We're not certain about this one. Your teacher will check it before it counts.",
  },
}

const tierClasses: Record<ConfidenceTier, string> = {
  confident: "text-confidence-high hover:bg-confidence-high-bg",
  uncertain: "text-confidence-medium bg-confidence-medium-bg border-confidence-medium",
  "needs-review": "text-confidence-low bg-confidence-low-bg border-confidence-low font-medium",
}

export interface ConfidenceIndicatorProps {
  tier: ConfidenceTier
  className?: string
}

/** Per-question compact confidence chip with a tap-to-expand explanation. */
export function ConfidenceIndicator({ tier, className }: ConfidenceIndicatorProps) {
  const [open, setOpen] = useState(false)
  const meta = tierMeta[tier]
  const Icon = meta.icon
  const loud = tier !== "confident"

  return (
    <span className={cn("relative inline-flex", className)}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={`Confidence: ${meta.label}. ${meta.explanation}`}
        className={cn(
          "inline-flex items-center gap-1 rounded-full border border-transparent cursor-pointer transition-colors",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
          loud ? "px-2 py-1" : "p-0.5",
          tierClasses[tier],
        )}
      >
        <Icon weight={loud ? "fill" : "regular"} className="w-4 h-4" aria-hidden />
        {loud && <span className="text-label-sm">{meta.label}</span>}
      </button>
      {open && (
        <div
          role="tooltip"
          className="absolute z-10 top-full mt-1.5 left-0 w-56 rounded-md border border-border bg-surface p-2.5 text-body-md text-t2 shadow-sm"
        >
          {meta.explanation}
        </div>
      )}
    </span>
  )
}

export interface ConfidenceIndicatorSummaryProps {
  confident: number
  uncertain: number
  needsReview: number
  className?: string
}

/** Per-paper aggregated confidence summary with a plain-language explainer. */
export function ConfidenceIndicatorSummary({
  confident,
  uncertain,
  needsReview,
  className,
}: ConfidenceIndicatorSummaryProps) {
  const [open, setOpen] = useState(false)
  const total = confident + uncertain + needsReview
  const flagged = uncertain + needsReview
  const allConfident = flagged === 0

  return (
    <div
      className={cn(
        "rounded-lg border p-3.5",
        allConfident ? "border-border bg-surface" : "border-confidence-low bg-confidence-low-bg",
        className,
      )}
    >
      <div className="flex items-start gap-2.5">
        {allConfident ? (
          <CheckCircle weight="regular" className="w-4.5 h-4.5 flex-none mt-0.5 text-confidence-high" aria-hidden />
        ) : (
          <Flag weight="fill" className="w-4.5 h-4.5 flex-none mt-0.5 text-confidence-low" aria-hidden />
        )}
        <p className={cn("text-body-md m-0", allConfident ? "text-t1" : "text-confidence-low font-medium")}>
          We're confident about {confident} of {total} question{total === 1 ? "" : "s"}.
          {flagged > 0 &&
            ` ${flagged} ${flagged === 1 ? "is" : "are"} waiting for your teacher to check.`}
        </p>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-label="What does confidence mean?"
          className="ml-auto flex-none text-t3 hover:text-t2 cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent rounded-full"
        >
          <Info className="w-4 h-4" aria-hidden />
        </button>
      </div>
      {open && (
        <p className="text-sm text-t2 mt-2.5 mb-0 pl-7">
          Confidence tells you how sure we are about each mark. Low-confidence marks are
          checked by your teacher before they count toward your result.
        </p>
      )}
    </div>
  )
}
