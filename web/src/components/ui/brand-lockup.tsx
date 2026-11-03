/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import type { ElementType, ReactNode } from "react"
import { cn } from "@/lib/utils"

/*
 * The mark plus the wordmark, together, everywhere they appear together.
 *
 * Seven places drew this pairing by hand (`x-brandlockup-duplicated-5x`, the
 * ledger's stale count — Task 0's re-grep against develop found seven, not
 * five): every portal sidebar's brand row, the settings header, the login
 * screen, and the marketing header. All seven agreed on the shape — mark,
 * gap, wordmark — and would have quietly drifted apart the next time one of
 * them needed a tweak, because there was nowhere for the agreement to live.
 *
 * `size` covers the two rungs the seven sites actually used (`sm` for a
 * sidebar row, `md` for a centred auth screen); `casing` covers the one site
 * that lowercases the wordmark as a logotype rather than a sentence
 * (marketing's header, per `design-import-spec.md`); `children` is the one
 * escape hatch a caller needs for content that follows the wordmark (admin's
 * lane subtitle) rather than trying to grow this component's own contract to
 * fit one caller. It renders *inside* the wordmark's own `<span>`, stacked
 * under the word rather than beside it in the row — admin's subtitle sits
 * under "Lemely", not to its right, and the outer wrapper is a single-axis
 * `flex items-center` row that has no other way to hold a second line.
 */

export function BrandLockup({
  size = "sm",
  casing = "title",
  as = "div",
  className,
  children,
}: {
  size?: "sm" | "md"
  casing?: "title" | "lower"
  /** Retained for marketing call sites; the Clip Letters wordmark is the only identity. */
  identity?: "clip"
  as?: "div" | "span"
  className?: string
  children?: ReactNode
}) {
  const Wrapper = as as ElementType
  // The Clip Letters wordmark: the two paperclips stand in for the "l" strokes
  // of "Lemely". Self-contained so it renders outside the marketing portal.
  const clip = (
    <svg
      aria-hidden="true"
      viewBox="28 4 46 94"
      preserveAspectRatio="xMidYMax meet"
      className="h-[1.1em] w-auto shrink-0"
    >
      <path
        d="M58 34 V72 A8 8 0 0 1 42 72 V20 A14 14 0 0 1 70 20 V78 A18 18 0 0 1 34 78 V36"
        fill="none"
        stroke="currentColor"
        strokeWidth="5"
        strokeLinecap="round"
      />
    </svg>
  )
  return (
    <Wrapper
      className={cn(
        "wordmark inline-flex flex-col items-start text-primary",
        size === "sm" ? "wordmark-sm" : "wordmark-md",
        className,
      )}
      aria-label={casing === "lower" ? "lemely" : "Lemely"}
    >
      <span className="inline-flex items-end">
        {clip}
        <span aria-hidden="true" className="wordmark-letters text-on-surface">
          eme
        </span>
        {clip}
        <span aria-hidden="true" className="wordmark-letters text-on-surface">
          y
        </span>
      </span>
      {children}
    </Wrapper>
  )
}
