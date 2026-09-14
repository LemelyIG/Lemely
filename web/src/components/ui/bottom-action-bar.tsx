/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 */
import { Link, useLocation } from "react-router-dom"
import { buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/*
 * Packet B3 (Task 4) · the thumb-zone "Correct a paper" CTA. Below the
 * `sidebar` breakpoint the header's own CTA (`student/index.tsx`'s `Header`)
 * hides — a fixed row at the very top of a tall phone is the least reachable
 * spot on the screen for a one-handed thumb — and this bar, pinned just above
 * `BottomNav`, takes over as the reachable version of the same action.
 */

export interface BottomActionBarProps {
  to: string
  label: string
  /** Pathnames on which the bar hides — the destination itself (the CTA on
   * its own screen has nothing to do) and any screen the caller judges the
   * bar would compete with, e.g. a full-screen flow. */
  hideOn: string[]
  /** Task 11 (B6): prefetch the destination's chunk on hover/touch/focus —
   * wired onto every intent event this bar's own `Link` can raise. */
  prefetch?: () => void
}

export function BottomActionBar({ to, label, hideOn, prefetch }: BottomActionBarProps) {
  const location = useLocation()
  if (hideOn.includes(location.pathname)) return null

  return (
    <div
      className={cn(
        "lm-nav-chrome lm-safe-bottom lm-bottom-action-bar sidebar:hidden fixed inset-x-0 z-nav px-page-mobile pb-3",
      )}
    >
      <Link
        to={to}
        viewTransition
        onPointerEnter={prefetch}
        onTouchStart={prefetch}
        onFocus={prefetch}
        className={cn(buttonVariants({ variant: "primary", size: "md" }), "w-full")}
      >
        {label}
      </Link>
    </div>
  )
}
