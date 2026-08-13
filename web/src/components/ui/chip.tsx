/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { cva, type VariantProps } from "class-variance-authority"
import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/*
 * Status chip. Tones map to the shared semantic tokens:
 *   ok = graded / parsed / correct / finished, warn = pending / attention,
 *   err = needs-review / dropped, info = live / in progress,
 *   neutral = queued / muted, accent = brand emphasis.
 *
 * **P4.5 migrated this to Study Notebook names and added `info`.** It was the
 * last heavy consumer of the compat aliases (`bg-ok-bg`, `bg-surface-2`,
 * `text-t2`, `bg-accent-subtle`), carried forward through D4.3 and D4.4 on the
 * grounds that un-migrated screens still consume it. The rename is
 * pixel-identical by definition — `index.css` defines `--ok-bg: var(--ok-wash)`
 * and so on — so those screens are unaffected, which is the same argument that
 * retired `lib/severity.ts`'s three aliases.
 *
 * `accent` also stopped meaning "live", which is the substantive part. On the
 * Study Notebook palette the accent is a warm coral-red, so an "Assigned" quiz
 * — the healthy, working state — was rendering in the product's alert register
 * while "Closed" sat beside it in `ok` teal. A teacher scanning the list read
 * alarm on the live rows and success on the finished ones, which is backwards.
 * `info` (§3.6, the neutral-notice pair) is what "this is currently live"
 * should look like, and `accent` is left for genuine brand emphasis.
 *
 * The pill shape is one of §6's sanctioned exceptions: §12 makes tags and
 * badges "the *only* place pills are legal".
 */
/*
 * `normal-case` is a deliberate, narrow deviation from the eyebrow rung.
 *
 * §12 gives tags and badges "eyebrow type", and the rung includes
 * `text-transform: uppercase` because §4.2 defines it for "uppercase kickers
 * above headings" — one or two words, set once. A chip is not always that: this
 * component also renders status *sentences* ("Possible AI-written answer",
 * "Possible mark-scheme copying"). Uppercasing those made them wrap to two
 * lines, cost the acronym its distinction from the words around it, and read
 * as shouting. The scale, weight and tracking §12 asks for are kept; only the
 * transform is dropped. `text-label-sm` is that rung, promoted out of the
 * build-era block in P4.5 for exactly this. `normal-case` was tried first and
 * does not work: it is emitted before `.text-eyebrow` in the bundle at equal
 * specificity, so the rung's own `text-transform` wins.
 */
const chip = cva(
  "inline-flex items-center gap-1.5 rounded-full text-label-sm leading-none px-9px py-3px",
  {
    variants: {
      tone: {
        ok: "bg-ok-wash text-ok",
        warn: "bg-warn-wash text-warn",
        err: "bg-err-wash text-err",
        info: "bg-info-wash text-info",
        neutral: "bg-paper-sunk text-ink-muted",
        accent: "bg-accent-wash text-accent-ink",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
)

export interface ChipProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof chip> {}

export function Chip({ className, tone, ...props }: ChipProps) {
  return <span className={cn(chip({ tone }), className)} {...props} />
}
