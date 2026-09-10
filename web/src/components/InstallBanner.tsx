import { DownloadSimple, Export, X } from "@phosphor-icons/react"
import { useInstallPrompt } from "@/lib/pwa/useInstallPrompt"

/*
 * Packet A7 — install affordance (`no-install-affordance` /
 * `emp-beforeinstallprompt-not-observed`).
 *
 * Mounted in the student and teacher shells only (`portals/student/index.tsx`,
 * `portals/teacher/index.tsx`) — the two portals a returning reader actually
 * lives in day to day, the same reasoning the manifest's `shortcuts` picked
 * "Mark a paper"/"Dashboard" for. Parent and admin sessions are comparatively
 * occasional; `InstallSettings.tsx` still reaches every role that wants it,
 * this is just not pushed at them unprompted.
 *
 * Follows `OfflineBanner`'s split: a *View* component with no hook, for a
 * dev-preview kit or a test to render without faking `beforeinstallprompt`,
 * and the hook-driven component the shells actually mount.
 */

export type InstallBannerViewVariant = "prompt" | "ios"

export function InstallBannerView({
  variant,
  onInstall,
  onDismiss,
}: {
  variant: InstallBannerViewVariant
  onInstall?: () => void
  onDismiss: () => void
}) {
  return (
    <div
      role="status"
      className="mb-6 flex flex-wrap items-center gap-2.5 rounded-md border border-rule bg-paper-sunk px-3.5 py-2.5"
    >
      {variant === "prompt" ? (
        <DownloadSimple size={16} className="text-ink-muted" aria-hidden="true" />
      ) : (
        <Export size={16} className="text-ink-muted" aria-hidden="true" />
      )}
      <p className="min-w-0 flex-1 text-body-sm text-ink">
        {variant === "prompt" ? (
          <>
            <span className="font-medium">Install Lemely.</span> Add it to your home screen for
            faster access and offline marking.
          </>
        ) : (
          <>
            <span className="font-medium">Install Lemely.</span> Tap the Share icon, then "Add to
            Home Screen".
          </>
        )}
      </p>
      {variant === "prompt" && onInstall ? (
        <button
          type="button"
          onClick={onInstall}
          className="shrink-0 text-body-sm text-accent-ink underline decoration-1 underline-offset-2 transition-[color,transform] hover:text-accent-hover active:scale-[0.98]"
        >
          Install
        </button>
      ) : null}
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss install banner"
        className="shrink-0 rounded-md p-1 text-ink-faint transition-colors hover:bg-paper-raised hover:text-ink"
      >
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  )
}

export function InstallBanner() {
  const { canInstall, promptInstall, isIos, isStandalone, dismissed, dismiss } = useInstallPrompt()

  if (isStandalone || dismissed) return null
  if (canInstall) {
    return (
      <InstallBannerView
        variant="prompt"
        onInstall={() => void promptInstall()}
        onDismiss={dismiss}
      />
    )
  }
  if (isIos) {
    return <InstallBannerView variant="ios" onDismiss={dismiss} />
  }
  return null
}
