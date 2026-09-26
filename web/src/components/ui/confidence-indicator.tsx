import { useState } from "react"
import { CheckCircle, Flag, Info, Minus, WarningCircle, type Icon } from "@phosphor-icons/react"
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
 *     about 19 of 21 questions. 2 are flagged for your teacher."
 *
 * WHAT THIS COMPONENT MUST NOT SAY, and why (product owner's ruling,
 * 2026-09-21). Every tier here previously promised that a low-confidence
 * mark would be "checked by your teacher before it counts". That was false
 * in both halves, and it was told to the STUDENT about their own grade:
 *
 *   - it has already counted. `QuestionResult.effective_marks`
 *     (`lemely/db/models/attempts.py:232`) returns the AI's `awarded_marks`
 *     whenever no teacher override exists, and `lemely/db/review_repo.py`
 *     sums that into the paper total as soon as marking finishes.
 *   - nothing requires a teacher to check it. `needs_teacher_review` is a
 *     ROUTING boolean; it withholds nothing. The review queue's own
 *     bulk-approve "accepts each selected mark exactly as Lemely awarded
 *     it" (`portals/teacher/screens/Review.tsx`), unopened.
 *
 * So this component states CONFIDENCE and nothing about what happens next.
 * A tier may carry no explanation at all — that is deliberate, not an
 * oversight, and `explanation` is optional for exactly that reason. If you
 * are about to add a sentence here about teacher review, check first
 * whether the product actually performs it.
 */

export type ConfidenceTier = "confident" | "uncertain" | "needs-review" | "not-marked"

interface TierMeta {
  label: string
  icon: Icon
  /** Optional: a tier with nothing TRUE to add says nothing. See above. */
  explanation?: string
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
    // No explanation, deliberately. The only thing this tier could add
    // beyond its label is what happens next, and the product does not
    // guarantee anything happens next. See the header.
  },
  // US-039 finding G. Neither a pass nor a warning — no marker (human or AI)
  // formed an opinion here, so this must not borrow the confident tier's
  // "we checked and we're sure" green or the uncertain/needs-review tiers'
  // "look at this" tones. `text-ink-muted` / `bg-paper-sunk` are the same
  // pair `<Chip tone="neutral">` uses, so this reads as the same "quiet,
  // administrative" register as the "not marked" chip already on this
  // screen (`PaperResult.markerSourceLabel`).
  "not-marked": {
    label: "Not marked",
    icon: Minus,
    explanation: "This question was left blank. No marker, human or AI, looked at it.",
  },
}

const tierClasses: Record<ConfidenceTier, string> = {
  confident: "text-confidence-high hover:bg-confidence-high-bg",
  uncertain: "text-confidence-medium bg-confidence-medium-bg border-confidence-medium",
  "needs-review": "text-confidence-low bg-confidence-low-bg border-confidence-low font-medium",
  "not-marked": "text-ink-muted bg-paper-sunk hover:bg-paper-sunk",
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
  // "not-marked" stays quiet alongside "confident" — it is deliberately
  // neither a pass nor a warning (US-039 finding G), so it gets none of the
  // bordered/labelled chrome the two tiers that DO want attention use.
  const loud = tier === "uncertain" || tier === "needs-review"

  // A tier with no explanation has nothing to disclose, so it renders as a
  // plain labelled span rather than a button: an expand affordance that
  // opens an empty tooltip is worse than no affordance. `aria-expanded` and
  // the disclosure are both gated on the same condition, so the accessible
  // name never promises a disclosure that isn't there.
  if (!meta.explanation) {
    return (
      <span
        className={cn("relative inline-flex", className)}
        aria-label={`Confidence: ${meta.label}`}
      >
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded-full border border-transparent",
            loud ? "px-2 py-1" : "p-0.5",
            tierClasses[tier],
          )}
        >
          <Icon weight={loud ? "fill" : "regular"} className="w-4 h-4" aria-hidden />
          {loud && <span className="text-label-sm">{meta.label}</span>}
        </span>
      </span>
    )
  }

  return (
    <span className={cn("relative inline-flex", className)}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={`Confidence: ${meta.label}. ${meta.explanation}`}
        className={cn(
          "inline-flex items-center gap-1 rounded-full border border-transparent cursor-pointer transition-[color,background-color,transform] active:scale-[0.98]",
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
          // P6.3: `z-dropdown`, not the raw `z-10` this carried. 10 is
          // `--z-index-sticky`'s value, i.e. this floating tooltip declared the
          // band that belongs to sticky table headers and portal top bars —
          // the two things most likely to sit over it. Every other floating
          // layer in the kit (`popover.tsx`) is already in the dropdown band;
          // this is the only one that was not, and it is live on `PaperResult`
          // and `PracticeResult` via `QuestionRow`.
          className="absolute z-dropdown top-full mt-1.5 start-0 w-56 rounded-md border border-border bg-surface p-2.5 text-body-md text-t2 shadow-sm"
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
  /**
   * US-039 finding G. Questions no marker scored (a genuine blank) — excluded
   * from the confidence population entirely, per the same rule lane 1 applied
   * to the backend's own confidence populations (`review_queue_rules.py`,
   * `teacher.py`'s pipeline cards): a blank has no confidence, neither high
   * nor low, so it must not inflate or deflate "confident about X of Y".
   * Defaults to 0 so every existing caller keeps behaving exactly as before.
   */
  notMarked?: number
  className?: string
}

/** Per-paper aggregated confidence summary with a plain-language explainer. */
export function ConfidenceIndicatorSummary({
  confident,
  uncertain,
  needsReview,
  notMarked = 0,
  className,
}: ConfidenceIndicatorSummaryProps) {
  const [open, setOpen] = useState(false)
  // `scored` — not `total` — because `notMarked` questions were never scored
  // by any marker and must not appear in either half of "confident about X
  // of Y" (see `notMarked`'s doc above).
  const scored = confident + uncertain + needsReview
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
          {scored > 0 ? (
            <>
              We're confident about {confident} of {scored} question{scored === 1 ? "" : "s"}.
              {flagged > 0 &&
                ` ${flagged} ${flagged === 1 ? "is" : "are"} flagged for your teacher.`}
            </>
          ) : (
            "No questions on this paper were marked."
          )}
          {notMarked > 0 &&
            ` ${notMarked} question${notMarked === 1 ? "" : "s"} left blank and not marked.`}
        </p>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-label="What does confidence mean?"
          className="ms-auto flex-none text-t3 transition-[color,transform] hover:text-t2 active:scale-[0.98] cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent rounded-full"
        >
          <Info className="w-4 h-4" aria-hidden />
        </button>
      </div>
      {open && (
        <p className="text-sm text-t2 mt-2.5 mb-0 ps-7">
          Confidence tells you how sure we are about each mark. Low-confidence marks are
          flagged for your teacher. Questions left blank have no confidence to report,
          because no marker looked at them.
        </p>
      )}
    </div>
  )
}
