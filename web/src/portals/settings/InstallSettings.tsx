import { DownloadSimple, Export } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { useInstallPrompt } from "@/lib/pwa/useInstallPrompt"
import { SettingsFrame } from "./SettingsFrame"

/*
 * Packet A7 — the settings-page route for a reader who dismissed
 * `InstallBanner` and wants to install later. Reachable both at the
 * top-level `/settings/install` (parent and admin's only path to it, same
 * as `ProfileSettings`'s three siblings) and, since the A7 review fix
 * (HIGH 2), inside `/student/settings/install` and `/teacher/settings/install`
 * — the two roles `InstallBanner` actually targets otherwise had no
 * navigational way back to this screen once they dismissed the banner: the
 * portal sidebar's own Settings section (`PortalSettingsLayout`) never
 * listed it, and every route under `/student|teacher/settings/*` redirects
 * away from the top-level lane (`SettingsLaneRedirect`, `routes.tsx`), so
 * the URL-only route was unreachable for exactly the audience it exists for.
 *
 * Reachable even while dismissed: the 14-day cooldown only hides the
 * *banner*, on the theory that a reader who came looking for this screen on
 * purpose is not the reader the cooldown is protecting from being nagged.
 */

/** The section this screen renders, with no frame around it — mounted
 * inside `PortalSettingsLayout` for the in-portal lane, in addition to the
 * framed `InstallSettings` below for the top-level `/settings/install` lane.
 * Same split `ProfileSettingsSection`/`ProfileSettings` uses. */
export function InstallSettingsSection() {
  const { canInstall, promptInstall, isIos, isStandalone } = useInstallPrompt()

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-rule bg-paper-raised p-4 sm:p-5">
      {isStandalone ? (
        <p className="text-body-sm text-ink-muted">Lemely is already installed on this device.</p>
      ) : canInstall ? (
        <>
          <p className="text-body-sm text-ink-muted">
            Install Lemely as an app for faster access and offline marking.
          </p>
          <Button
            type="button"
            onClick={() => void promptInstall().catch(() => {})}
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
  )
}

/** The top-level `/settings/install` route (parent and admin reach this
 * screen only through here — see `SettingsFrame`'s module header for why the
 * lane is role-agnostic). */
export function InstallSettings() {
  return (
    <SettingsFrame
      title="Install Lemely"
      intro="Add Lemely to your home screen for faster access and offline marking."
    >
      <InstallSettingsSection />
    </SettingsFrame>
  )
}
