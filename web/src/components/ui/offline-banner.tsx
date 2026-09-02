/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { WifiSlash } from "@phosphor-icons/react"
import { useOnlineStatus } from "@/lib/online"

/*
 * PR 2 part C · the "you're offline, and this page will fix itself" banner.
 *
 * Deliberately not a `StateView`/`OfflineState` (`state-views.tsx`): those
 * are terminal, centred panels for "there is nothing to show" — replacing a
 * whole screen. This banner is the opposite case, approved by product as the
 * recovery design for PR 2: the page is already showing real content (the
 * last successful fetch), offline is a slim strip *above* that content
 * saying so, and recovery is automatic — every failed query refetches itself
 * the moment `RecoveryEffects` (`components/recovery-effects.tsx`) sees the
 * connection return, announced with a "Reconnected" toast rather than
 * something this banner has to do. "Try again" exists for the reader who
 * doesn't want to wait for that.
 *
 * Amber/neutral, never red, per PRODUCT.md's accessibility section ("avoid
 * red-heavy error states") — offline is a fact about the moment, not a
 * failure the product caused. `role="status"` (polite), not `role="alert"`,
 * for the same reason `state-views.tsx`'s own `kind="offline"` picks
 * `status` over `alert`: connectivity dropping should not interrupt whatever
 * a screen reader is already reading.
 *
 * `mb-6` lives on the banner's own root, not on a wrapper the caller adds —
 * this component already returns `null` while online, so a caller-side
 * margin wrapper would still occupy layout (an empty margined `<div>`) on
 * every render where there is nothing to space. Baking the margin in here
 * means "no banner" is genuinely zero footprint.
 */

export function OfflineBanner({ onRetry }: { onRetry?: () => void }) {
  const online = useOnlineStatus()
  if (online) return null

  return (
    <div
      role="status"
      className="mb-6 flex flex-wrap items-center gap-2.5 rounded-md border border-rule bg-paper-sunk px-3.5 py-2.5"
    >
      <WifiSlash size={16} className="text-ink-muted" aria-hidden="true" />
      <p className="min-w-0 flex-1 text-body-sm text-ink">
        <span className="font-medium">You're offline.</span> Showing what loaded last. This page
        will refresh by itself when you're back online.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="shrink-0 text-body-sm text-accent-ink underline decoration-1 underline-offset-2 transition-colors hover:text-accent-hover"
      >
        Try again
      </button>
    </div>
  )
}
