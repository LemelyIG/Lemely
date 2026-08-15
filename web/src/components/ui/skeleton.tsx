import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/*
 * DESIGN.md §12: "Skeletons, not spinners. Loading states match the layout
 * they replace so nothing shifts (CLS < 0.1)." The Phase 1 audit found no
 * skeleton primitive anywhere in the product, so every loading state so far
 * has either been a spinner or a layout jump when data lands. These four
 * primitives are the fix: each one takes the exact box (width/height/shape)
 * of the content it stands in for, so a caller reserves space by construction
 * rather than by convention.
 *
 * Animation is opacity-only (`animate-lm-pulse`, defined in index.css §9),
 * never a transform or a background-position sweep — DESIGN.md §9.2 bans
 * animating anything but `transform`/`opacity`, and a pulse reads as "still
 * working" without implying motion that doesn't exist yet.
 *
 * Base fill is `bg-paper-sunk`: the "well" surface (§3.1), one step down from
 * the card it sits in, so the placeholder reads as an indentation rather than
 * as a competing element with its own weight.
 */

interface SkeletonBaseProps extends HTMLAttributes<HTMLDivElement> {
  /** Set false for a single skeleton inside a parent that already announces
   * "loading" (e.g. a list of ten `SkeletonLine`s under one status region).
   * Defaults to true so a lone skeleton is announced on its own. */
  announce?: boolean
}

function SkeletonBase({
  className,
  announce = true,
  style,
  ...props
}: SkeletonBaseProps) {
  return (
    <div
      role={announce ? "status" : undefined}
      aria-label={announce ? "Loading" : undefined}
      className={cn("animate-lm-pulse rounded-md bg-paper-sunk", className)}
      style={style}
      {...props}
    />
  )
}

/**
 * A single line of placeholder text. Height is pinned to a typical
 * `body-md`/`body-sm` line box (14px) so a paragraph of `SkeletonLine`s sits
 * at the same rhythm as the real copy it precedes.
 */
export function SkeletonLine({
  className,
  width,
  ...props
}: SkeletonBaseProps & { width?: string }) {
  return (
    <SkeletonBase
      className={cn("h-3.5", className)}
      style={width ? { width } : undefined}
      {...props}
    />
  )
}

/**
 * A rectangular placeholder for an arbitrary block (image, chart, table
 * region, card body). The caller supplies sizing via `className`
 * (`h-40 w-full`, `aspect-video`, …) — this component only supplies the fill,
 * shape and animation so every block placeholder in the product looks like
 * the same designed thing.
 */
export function SkeletonBlock({ className, ...props }: SkeletonBaseProps) {
  return (
    <SkeletonBase
      className={cn("h-24 w-full rounded-lg", className)}
      {...props}
    />
  )
}

/**
 * A circular placeholder for an avatar or icon badge. Square by default
 * (`h-10 w-10`); pass `className` to resize. Deliberately `rounded-full`
 * even though DESIGN.md reserves `radius-full` for "pills and circles" —
 * avatars proper are squircles (§6), but a *placeholder* for one doesn't need
 * to commit to that detail, and a plain circle reads unambiguously as "an
 * avatar is loading here" without pre-empting corner radius decisions the
 * real avatar makes.
 */
export function SkeletonCircle({ className, ...props }: SkeletonBaseProps) {
  return (
    <SkeletonBase
      className={cn("h-10 w-10 shrink-0 rounded-full", className)}
      {...props}
    />
  )
}

/**
 * A multi-line paragraph placeholder. `lines` controls how many `SkeletonLine`s
 * render; the last line is shortened to ~60% width so the block doesn't read
 * as a solid grey rectangle, matching how a real paragraph's final line is
 * usually short. Wrapped in a single `role="status"` region rather than one
 * per line, so a screen reader announces "Loading" once, not `lines` times.
 */
export function SkeletonText({
  lines = 3,
  className,
  ...props
}: SkeletonBaseProps & { lines?: number }) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className={cn("flex flex-col gap-2", className)}
      {...props}
    >
      {Array.from({ length: lines }, (_, index) => (
        <SkeletonLine
          key={index}
          announce={false}
          width={index === lines - 1 ? "60%" : undefined}
        />
      ))}
    </div>
  )
}
