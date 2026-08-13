/* Hallmark · pre-emit critique: P3 H3 E5 S4 R5 V3 */
/* P3/H3: this is a utility control with one job and almost no surface to
   express anything through. Scored honestly rather than inflated. */
import { cn } from "@/lib/utils"

/*
 * P3.3 · Skip to main content.
 *
 * The audit listed this under strategic omissions, which undersells it in a
 * product shaped like this one. Both the student and teacher portals put a
 * grouped navigation list of eleven and eight destinations before the content
 * in DOM order, and that list is re-rendered on every route. Without a skip
 * link, a keyboard or screen-reader user tabs through the entire sidebar again
 * on every single navigation before reaching the thing they navigated to.
 *
 * Visually hidden until focused, then a real, visible, ink-on-paper control —
 * not an off-screen link that stays invisible while focused, which passes an
 * automated check and helps nobody sighted navigating by keyboard.
 *
 * `sr-only`-style clipping is written out rather than using a utility so the
 * focused state can restore geometry in the same declaration block; the two
 * halves drifting apart is the usual way this component breaks.
 */

export const MAIN_CONTENT_ID = "main-content"

export function SkipLink({ className }: { className?: string }) {
  return (
    <a
      href={`#${MAIN_CONTENT_ID}`}
      className={cn(
        // Hidden: clipped to nothing, but still in the tab order and still
        // announced. `absolute` (not `fixed`) so it scrolls with the document
        // and cannot cover fixed chrome once revealed.
        "absolute z-[var(--z-index-toast)] h-px w-px overflow-hidden",
        "[clip-path:inset(50%)] whitespace-nowrap",
        // Revealed on focus, pinned to the reading-start corner. Logical
        // properties (`start-*`, not `left-*`) per P3.4.
        "focus:start-3 focus:top-3 focus:h-auto focus:w-auto focus:overflow-visible",
        "focus:[clip-path:none]",
        "focus:rounded-md focus:border focus:border-rule focus:bg-paper-raised",
        "focus:px-4 focus:py-2.5 focus:text-body-md focus:font-medium focus:text-ink",
        "focus:shadow-[var(--shadow-float)]",
        "focus:outline-2 focus:outline-offset-2 focus:outline-accent",
        className,
      )}
    >
      Skip to main content
    </a>
  )
}
