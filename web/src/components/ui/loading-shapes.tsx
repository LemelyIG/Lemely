import { SkeletonBlock, SkeletonCircle, SkeletonLine } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

/*
 * P3.3 · Composed loading shapes.
 *
 * DESIGN.md §12 is "skeletons, not spinners; loading states match the layout
 * they replace so nothing shifts". Phase 2 built the four primitives that make
 * that possible (`SkeletonLine/Block/Circle/Text`). What it did not build is
 * the layer above them, and without that layer every screen composes its own
 * skeleton by hand, which is how twenty-five screens end up with twenty-five
 * different ideas of what "loading" looks like — the exact drift `RouteFallback`
 * was created to undo for route chunks.
 *
 * So these are the recurring *shapes* rather than per-screen skeletons: a page
 * header, a grid of cards, a list of rows, a table. Most product screens are
 * one or two of these stacked, and a screen that is genuinely unusual should
 * still compose the primitives directly rather than bend one of these.
 *
 * Deliberately NOT a sweep of all twenty-five text loaders in the product.
 * A skeleton's only job is to have the same geometry as the thing that
 * replaces it, and Phase 4 is about to change the geometry of every one of
 * those screens. Skeletons built now against layouts that are about to be
 * redesigned would be measured against the wrong target and rebuilt anyway.
 * Phase 4 drops these in per surface as it settles each layout; the two
 * dashboards that each role lands on first are converted now, since those are
 * the loading states most readers see most often.
 *
 * Every shape announces once via a single `role="status"` region on the
 * wrapper, with `announce={false}` on the primitives inside it, so a screen
 * reader hears "Loading" one time rather than once per placeholder.
 */

/** Page heading plus its supporting line. Nearly every screen opens with this. */
export function PageHeaderSkeleton({ className }: { className?: string }) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className={cn("flex flex-col gap-3", className)}
    >
      <SkeletonLine announce={false} className="h-8" width="min(22rem, 60%)" />
      <SkeletonLine announce={false} width="min(34rem, 85%)" />
    </div>
  )
}

/**
 * A responsive grid of card placeholders, for dashboards whose main content is
 * a set of tiles (teacher class cards, subject cards, deck cards).
 */
export function CardGridSkeleton({
  count = 3,
  className,
}: {
  count?: number
  className?: string
}) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className={cn("grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3", className)}
    >
      {Array.from({ length: count }, (_, index) => (
        <div
          key={index}
          className="flex flex-col gap-3 rounded-lg border border-rule bg-paper-raised p-[18px]"
        >
          <SkeletonLine announce={false} className="h-5" width="70%" />
          <SkeletonLine announce={false} width="45%" />
          <div className="mt-2 grid grid-cols-2 gap-3">
            <SkeletonLine announce={false} className="h-6" />
            <SkeletonLine announce={false} className="h-6" />
          </div>
        </div>
      ))}
    </div>
  )
}

/**
 * A vertical list of rows inside one bordered container, each row an optional
 * avatar plus two lines and a trailing value. Matches the shape of the
 * activity feeds, rosters and queues that recur across the teacher portal.
 */
export function ListSkeleton({
  rows = 4,
  avatar = false,
  className,
}: {
  rows?: number
  avatar?: boolean
  className?: string
}) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className={cn("overflow-hidden rounded-lg border border-rule bg-paper-raised", className)}
    >
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          className="flex items-center gap-3 border-b border-rule px-5 py-3.5 last:border-b-0"
        >
          {avatar ? <SkeletonCircle announce={false} className="h-7 w-7" /> : null}
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <SkeletonLine announce={false} width="40%" />
            <SkeletonLine announce={false} className="h-3" width="65%" />
          </div>
          {/* `ms-auto`, not `ml-auto`: this pushes to the reading-end edge and
              must follow `dir` (P3.4). */}
          <SkeletonLine announce={false} className="ms-auto h-4" width="3rem" />
        </div>
      ))}
    </div>
  )
}

/**
 * A chart or panel placeholder with its title, for the two-up analytics rows.
 */
export function PanelSkeleton({
  className,
  bodyClassName,
}: {
  className?: string
  bodyClassName?: string
}) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className={cn(
        "flex flex-col gap-4 rounded-lg border border-rule bg-paper-raised px-5 py-[18px]",
        className,
      )}
    >
      <div className="flex flex-col gap-1.5">
        <SkeletonLine announce={false} className="h-5" width="45%" />
        <SkeletonLine announce={false} className="h-3" width="65%" />
      </div>
      <SkeletonBlock announce={false} className={cn("h-24", bodyClassName)} />
    </div>
  )
}
