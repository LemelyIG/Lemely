/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V5 */
import { cn } from "@/lib/utils"

/*
 * The Lemely brand mark, inline (PR 2 part A1).
 *
 * Geometry is `web/public/brand/mark.svg`'s, transcribed rather than
 * `<img src>`'d: an inline `<svg>` can be recoloured with `currentColor`/text
 * tokens and, here, animated per-path, neither of which a static asset file
 * allows. Same two-weight idea the asset's own comment describes — "the
 * printed page, and the human correction on top of it" — carried through as
 * `text-ink` on the two ruled strokes and `text-accent` on the tick.
 *
 * `animated` is the "still loading" reading: a single small mark redrawing
 * itself in place is a legitimate one-glance answer to "is this stuck?" for
 * the rare case a whole page has nothing else to show yet (`slow-load`, PR 2's
 * `FullPageState`). It is not a general-purpose spinner — `Button`'s `loading`
 * prop and `RouteFallback` already own the ordinary in-flight cases — and its
 * one call site is deliberately kept to that single rare case.
 */

export function Mark({
  size = 24,
  animated = false,
  className,
}: {
  size?: number
  animated?: boolean
  className?: string
}) {
  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      fill="none"
      className={className}
      // Animated: this IS the content (a screen reader user needs to know the
      // page is still working), so it is a named image, not decoration.
      // Static: it is brand furniture beside a heading that already says
      // everything, so it stays out of the accessibility tree per §4.1/§8.
      role={animated ? "img" : undefined}
      aria-label={animated ? "Lemely is still loading" : undefined}
      aria-hidden={animated ? undefined : "true"}
    >
      {/* The printed page: two hairline strokes, butt caps — ruled by a
          machine, not drawn by a hand. */}
      <path
        d="M20 10V46"
        className={cn("text-ink", animated && "lm-draw-l1")}
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="butt"
      />
      <path
        d="M20 46H44"
        className={cn("text-ink", animated && "lm-draw-l2")}
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="butt"
      />
      {/* The correction: one stroke, round caps and joins — drawn by a hand
          holding a felt pen, laid across the corner last. */}
      <path
        d="M27 37L33 46L47 19"
        className={cn("text-accent", animated && "lm-draw-tick")}
        stroke="currentColor"
        strokeWidth="6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
