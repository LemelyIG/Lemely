import { DownloadSimple, Export } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { useInstallPrompt } from "@/lib/pwa/useInstallPrompt"
import { SettingsFrame } from "./SettingsFrame"

/*
 * Packet A7 — the settings-page route for a reader who dismissed
 * `InstallBanner` and wants to install later. Top-level only
 * (`/settings/install`, alongside `/settings/profile` and its two
 * siblings) — every role reaches it here; unlike `DeviceSettings` and
 * `NotificationSettings` it has no portal-scoped duplicate, since the
 * banner it backs up is only pushed at the student and teacher shells to
 * begin with (see `InstallBanner.tsx`'s own header).
 *
 * Reachable even while dismissed: the 14-day cooldown only hides the
 * *banner*, on the theory that a reader who came looking for this screen on
 * purpose is not the reader the cooldown is protecting from being nagged.
 */
export function InstallSettings() {
  const { canInstall, promptInstall, isIos, isStandalone } = useInstallPrompt()

  return (
    <SettingsFrame
      title="Install Lemely"
      intro="Add Lemely to your home screen for faster access and offline marking."
    >
      <div className="flex flex-col gap-4 rounded-lg border border-rule bg-paper-raised p-4 sm:p-5">
        {isStandalone ? (
          <p className="text-body-sm text-ink-muted">
            Lemely is already installed on this device.
          </p>
        ) : canInstall ? (
          <>
            <p className="text-body-sm text-ink-muted">
              Install Lemely as an app for faster access and offline marking.
            </p>
            <Button
              type="button"
              onClick={() => void promptInstall()}
              className="self-start"
            >
              <DownloadSimple size={16} aria-hidden="true" />
              Install Lemely
            </Button>
          </>
        ) : isIos ? (
          <p className="flex items-start gap-2 text-body-sm text-ink-muted">
            <Export size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
            Tap the Share icon in Safari's toolbar, then choose "Add to Home Screen".
          </p>
        ) : (
          <p className="text-body-sm text-ink-muted">
            Your browser doesn't support installing Lemely as an app yet. You can still use every
            feature from a regular browser tab.
          </p>
        )}
      </div>
    </SettingsFrame>
  )
}
