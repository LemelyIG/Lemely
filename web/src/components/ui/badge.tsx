import type { HTMLAttributes, ReactNode } from "react"
import { cn } from "@/lib/utils"

/*
 * The sticker set (DESIGN.md §3.5/§12): "Tags and badges. Pastel fill with
 * its paired text colour, `radius-full`, `eyebrow` type, tight padding. This
 * is the ONLY place pills are legal." Everywhere else in the system
 * `radius-full` on anything is a gate failure (§6) — this file is the single
 * legal exception, which is also why it exists as its own component rather
 * than a variant bolted onto `Chip`: a reviewer scanning for a stray
 * `rounded-full` should be able to grep this file and stop, not chase it
 * through every component that happens to render a coloured pill.
 *
 * Two variant families:
 *   - pastel (rose/amber/sage/sky/lilac/clay): decorative/categorical —
 *     subject coding, generic tagging. No implied status.
 *   - semantic (ok/warn/err/info): status — pairs a wash fill with its ink
 *     text, same tokens as everywhere else "correct/uncertain/wrong/notice"
 *     is expressed in the product.
 * `subject-tag.tsx` is the one sanctioned way to reach the pastel variants
 * for a *subject* specifically — it fixes the subject->pastel mapping so a
 * screen never picks a subject's colour at the call site (§3.8).
 */

export type BadgeTone =
  | "rose"
  | "amber"
  | "sage"
  | "sky"
  | "lilac"
  | "clay"
  | "ok"
  | "warn"
  | "err"
  | "info"

const toneClasses: Record<BadgeTone, string> = {
  rose: "bg-pastel-rose text-pastel-rose-ink",
  amber: "bg-pastel-amber text-pastel-amber-ink",
  sage: "bg-pastel-sage text-pastel-sage-ink",
  sky: "bg-pastel-sky text-pastel-sky-ink",
  lilac: "bg-pastel-lilac text-pastel-lilac-ink",
  clay: "bg-pastel-clay text-pastel-clay-ink",
  ok: "bg-ok-wash text-ok",
  warn: "bg-warn-wash text-warn",
  err: "bg-err-wash text-err",
  info: "bg-info-wash text-info",
}

export interface BadgeProps extends Omit<HTMLAttributes<HTMLSpanElement>, "children"> {
  tone?: BadgeTone
  /** Decorative glyph rendered before the label. Optional, but recommended
   * for the semantic tones: DESIGN.md §3.6 requires colour to never carry
   * meaning alone, and while the text label already satisfies that on its
   * own, a paired icon gives a second, faster-scanning signal for "correct"
   * vs "wrong" in a dense table. Always `aria-hidden` — the label text is
   * the accessible name. */
  icon?: ReactNode
  children: ReactNode
}

/**
 * A single pastel or semantic pill. Sentence-case label expected (§3 gate 9)
 * — this component does not transform casing itself, since `text-eyebrow`
 * already renders it uppercase visually while the DOM/accessibility tree
 * keeps the sentence-case text a screen reader announces normally.
 */
export function Badge({ tone = "info", icon, children, className, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-9px py-3px text-eyebrow leading-none",
        toneClasses[tone],
        className,
      )}
      {...props}
    >
      {icon ? (
        <span aria-hidden className="flex shrink-0 items-center [&>svg]:h-3 [&>svg]:w-3">
          {icon}
        </span>
      ) : null}
      {children}
    </span>
  )
}

/**
 * Semantic alias kept distinct from `Badge` at the call-site level even
 * though it renders the same component: a caller reaching for "Tag" is
 * making a categorical statement ("this is Physics"), a caller reaching for
 * "Badge" is making a status statement ("this is correct"). The type union
 * still allows either tone from either name — the split is naming intent for
 * readers of the call site, not a functional restriction.
 */
export const Tag = Badge
