/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import type { ElementType, ReactNode } from "react"
import { BrandMark } from "./brand-mark"
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
  animated,
  as = "div",
  className,
  children,
}: {
  size?: "sm" | "md"
  casing?: "title" | "lower"
  animated?: boolean
  as?: "div" | "span"
  className?: string
  children?: ReactNode
}) {
  const Wrapper = as as ElementType
  return (
    <Wrapper className={cn("flex items-center gap-2.5", className)}>
      {/* `aria-hidden`: the wordmark right beside it already says "Lemely" (or
          "lemely"), so describing the mark too would make a screen reader
          announce the brand twice. `BrandMark` hardcodes this already; it is
          repeated here so the contract reads at the call site, not just
          inside a component two files away. */}
      <BrandMark
        aria-hidden="true"
        className={size === "sm" ? "h-6 w-8 shrink-0" : "h-7 w-9 shrink-0"}
        animated={animated}
      />
      <span
        className={cn(
          size === "sm" ? "text-display-sm text-ink" : "text-display-md text-ink",
          children && "flex flex-col min-w-0",
        )}
      >
        {casing === "lower" ? "lemely" : "Lemely"}
        {children}
      </span>
    </Wrapper>
  )
}
