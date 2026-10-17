/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { ArrowClockwise, WifiSlash } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"

/*
 * Task 10 (B6b) — the panel `CorrectPaper.tsx` renders when an upload was
 * queued rather than lost (`shouldQueueUpload`/`enqueueUpload`). Deliberately
 * not a `StateView`: those are exclusive answers about the *data* ("nothing
 * here", "this failed"), and this is additive — a reader who just lost
 * connection mid-upload can still see the ordinary "Marking stopped" panel
 * with its own retry, plus this banner sitting alongside it, explaining the
 * one thing that panel cannot know: the scan is not gone, it is waiting.
 *
 * `role="status"` (polite), matching `state-views.tsx`'s own `kind="offline"`
 * — connectivity dropping is a fact of the moment, not an event to interrupt
 * a screen reader over. `--info` tone: this is a neutral notice ("here's
 * what's happening"), not a warning or a failure — the queue existing is the
 * *recovery* from the failure, not a new one.
 */

/** Self-critique behind the P4 H4 E4 S4 R4 V4 stamp above (derived fresh for
 * this component, not copied from another surface):
 * - **P (purpose)** — one sentence states exactly what happened and what
 *   happens next ("It will upload on its own"), with one optional action.
 *   Nothing decorative competes with that.
 * - **H (hierarchy)** — icon, sentence, button read in one obvious order;
 *   no heading competing with the CorrectPaper page's own `<h1>`.
 * - **E (economy)** — reuses `Button`/`WifiSlash`/`ArrowClockwise`, no new
 *   primitives; the plural branch is the only conditional.
 * - **S (state)** — `role="status"` announces the count changing (queued →
 *   fewer → gone) without re-mounting anything; `onRetry` is optional so a
 *   caller with nothing meaningful to retry against yet can omit it.
 * - **R (restraint)** — no animation, no dismiss control: a queued scan is
 *   not something a reader should be able to make disappear from view
 *   before it actually uploads.
 * - **V (voice)** — "It will upload on its own" / "They'll upload on their
 *   own" is reassurance, not a status code; matches the count in the same
 *   sentence rather than a separate badge.
 */
export interface QueuedBannerProps {
  /** How many scans are currently queued. Renders nothing for `0` — a
   * caller conditionally mounting this on `count > 0` is the expected use,
   * but a stray `0` must not still show an empty queue as if one existed. */
  count: number
  /** Optional manual nudge — most of the queue drains on its own (mount,
   * `online`, a Background Sync drain from the worker), so this exists for
   * the reader who does not want to wait for one of those. */
  onRetry?: () => void
}

export function QueuedBanner({ count, onRetry }: QueuedBannerProps) {
  if (count <= 0) return null
  const message =
    count === 1
      ? "1 scan is waiting for a connection. It will upload on its own."
      : `${count} scans are waiting for a connection. They'll upload on their own.`

  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-3 rounded-lg border border-rule bg-info-wash px-4 py-3"
    >
      <WifiSlash size={18} weight="bold" className="flex-none text-info" aria-hidden="true" />
      <p className="min-w-0 flex-1 text-pretty text-body-sm text-info">{message}</p>
      {onRetry ? (
        <Button
          variant="secondary"
          size="sm"
          icon={<ArrowClockwise size={16} />}
          onClick={onRetry}
        >
          Retry now
        </Button>
      ) : null}
    </div>
  )
}
