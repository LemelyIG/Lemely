/* Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4 */
import { useState } from "react"
import { DeviceMobile } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import { EmptyState } from "@/components/ui/state-views"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { useAuth } from "@/lib/auth/AuthContext"
import { deviceTitle, lastActiveLabel } from "@/lib/devices"
import { useDevices, useRevokeDevice } from "@/lib/hooks/useDeviceApi"
import {
  DEVICE_ALREADY_GONE,
  settingsLoadFailureMessage,
  settingsSaveFailureMessage,
} from "@/lib/settingsOutcome"
import { SettingsFrame } from "./SettingsFrame"

/*
 * G-11 · Account and devices — the devices section, in the Study Notebook
 * (P4.10).
 *
 * Role-agnostic by design: every account is subject to the same 3-device limit
 * (D1.11), so this route is reachable by all five roles rather than living
 * inside one portal. `SettingsFrame` carries the consequences of that; see its
 * header.
 *
 * Scope, stated rather than implied: the UI spec's G-11 also lists profile,
 * password change, linked relationships, subscription summary and delete
 * account. Those have no P5.7 backend behind them (subscription is G-14, a
 * later surface), so they are **not stubbed here** — a settings row that does
 * nothing is worse than an absent one. This screen ships the part that is real.
 *
 * No location column: the backend stores no IP and has no geo-IP source
 * (D5.12 §5). Each row shows what we actually hold — the browser's own
 * description of itself, with the raw string in `title`, and a coarse
 * last-active time.
 *
 * ── P4.10, and the finding that made this surface worth doing ──────────────
 *
 * **A sign-out that did not happen reported nothing at all.**
 *
 * `DELETE /me/devices/{id}` never raises. A device id that does not exist, is
 * already revoked, or belongs to another account all answer `200 {removed:
 * false}`, deliberately, so the route cannot be used to test whether an id
 * exists on somebody else's account (`schemas_devices.py`). React-query
 * therefore runs `onSuccess` for a sign-out that did not occur, the list
 * invalidates, the row comes back, and before this pass the screen said
 * nothing whatsoever.
 *
 * That is the same shape as surface 3's two deletes that could not fail out
 * loud, but it lands somewhere worse: this is the one screen in the product a
 * reader opens *because* they think somebody else is signed in to their
 * account. "I pressed sign out and the device is still listed" is precisely
 * the moment they need a sentence, and `removed: false` is the only signal
 * that distinguishes "already gone" from "still there". It is rendered now.
 *
 * **The current device is confirmed; the others are not.** C-24's
 * `consequence` prop is overridable because not every destructive action is
 * irreversible, and these two genuinely differ: signing out a phone you left
 * at school costs that phone one sign-in, while signing out the browser you
 * are reading this in ends the session mid-sentence. Only the second gets a
 * modal, and its consequence says what really happens rather than the
 * default's "cannot be undone", which would be false.
 *
 * **Failures sit with the row that produced them.** The revoke error used to
 * render as one line at the bottom of the section, below every device, so a
 * failure on the third row appeared under the fifth. §12 puts an error
 * adjacent to the control that caused it.
 */

/**
 * The section this screen renders, with no frame around it — mounted at
 * `/teacher/settings/devices` and `/student/settings/devices` inside
 * `PortalSettingsLayout`, which supplies its own `<h1>`/nav/chrome, in
 * addition to the framed `DeviceSettings` below for the top-level
 * `/settings/devices` lane (parent and admin still use that one).
 *
 * The intro paragraph moved in here from `SettingsFrame`'s `intro` prop
 * because it depends on `devices.data` (the account's device limit), which
 * only this section's own query has — behaviour is otherwise identical to
 * the framed version, and the framed `DeviceSettings` below no longer needs
 * to know that fact to pass a static `intro` instead.
 */
export function DeviceSettingsSection() {
  const { logout } = useAuth()
  const devices = useDevices()
  const revoke = useRevokeDevice()
  const [pendingId, setPendingId] = useState<string | null>(null)
  /** The device whose failure or no-op is currently worth a sentence, and what
   * to say. Keyed by device id so the message renders against its own row. */
  const [rowNotice, setRowNotice] = useState<{ id: string; message: string } | null>(null)
  /** Set only for the current device: the others are signed out immediately. */
  const [confirmingCurrent, setConfirmingCurrent] = useState<string | null>(null)

  const signOut = (deviceId: string) => {
    setPendingId(deviceId)
    setRowNotice(null)
    revoke.mutate(deviceId, {
      onSuccess: (result) => {
        // Signing out the device you are using invalidates this very token — the
        // next request would 401. Clearing the session here turns that into an
        // ordinary sign-out instead of a screen that mysteriously stops working.
        if (result.wasCurrent) {
          logout()
          return
        }
        // A 200 that removed nothing. Not an error, and not a success worth
        // staying silent about — see the module note and `DEVICE_ALREADY_GONE`.
        if (!result.removed) setRowNotice({ id: deviceId, message: DEVICE_ALREADY_GONE })
      },
      onError: (error) =>
        setRowNotice({ id: deviceId, message: settingsSaveFailureMessage(error) }),
      onSettled: () => {
        setPendingId(null)
        setConfirmingCurrent(null)
      },
    })
  }

  const handleSignOut = (deviceId: string, isCurrent: boolean) => {
    if (isCurrent) {
      setConfirmingCurrent(deviceId)
      return
    }
    signOut(deviceId)
  }

  const intro = devices.data
    ? `You can be signed in on ${devices.data.maxDevices} devices at a time. Signing in on another one signs out whichever you used least recently.`
    : "You can be signed in on a limited number of devices at a time."

  return (
    <>
      <section aria-labelledby="devices-heading" className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <h2 id="devices-heading" className="text-display-sm text-ink">
            Signed-in devices
          </h2>
          <p className="max-w-[65ch] text-body-sm text-ink-muted">{intro}</p>
        </div>

        {/* No `srHeading`: the page's own `<h1>` is rendered above this
            section unconditionally, whether by `SettingsFrame` (the
            top-level lane) or `PortalSettingsLayout` (the in-portal one), in
            every query state — an sr-only heading here would duplicate it.
            `<h1>` unconditionally, above this section, in every query state —
            an sr-only heading here would duplicate it.

            One behaviour changed here and is worth naming. The pre-conversion
            branches were sibling expressions, not exclusive ones, so a refetch
            that failed *after* a successful load showed the error panel and
            kept the list below it. `QueryState` is exclusive by design, so the
            list goes. That is the honest reading: react-query moves `status`
            to `"error"` on a failed refetch, and what is on screen at that
            point is data we can no longer vouch for — after a revoke, a device
            that is gone may still be listed, which is the one thing this
            screen must not imply. A retry is a better offer than stale rows
            presented as current. */}
        <QueryState
          query={devices}
          skeleton={<ListSkeleton rows={3} />}
          error={{
            heading: "We couldn't load your devices",
            body: settingsLoadFailureMessage,
          }}
          isEmpty={(data) => data.devices.length === 0}
          empty={
            <EmptyState
              icon={<DeviceMobile aria-hidden="true" />}
              heading="Nothing is signed in"
              body="No device currently holds a session for this account."
            />
          }
        >
          {(data) => (
            <ul className="flex flex-col gap-2">
              {data.devices.map((device) => {
                const notice = rowNotice?.id === device.deviceId ? rowNotice.message : null
                const busy = pendingId === device.deviceId
                return (
                  <li
                    key={device.deviceId}
                    className="flex flex-col gap-3 rounded-lg border border-rule bg-paper-raised p-4 sm:p-5"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <span className="flex min-w-0 flex-col gap-1">
                        <span className="flex flex-wrap items-center gap-2">
                          {/* The raw user-agent stays in `title`: a reader who
                              wants to know exactly what we hold about a device
                              can see it, rather than only our summary of it. */}
                          <span
                            className="text-body-md text-ink"
                            title={device.userAgent ?? undefined}
                          >
                            {deviceTitle(device)}
                          </span>
                          {device.isCurrent ? <Chip>This device</Chip> : null}
                        </span>
                        <span className="text-data-sm text-ink-faint">
                          {lastActiveLabel(device.lastActiveAt)}
                        </span>
                      </span>
                      <Button
                        type="button"
                        // `secondary`, not `ghost`: at rest a ghost button on a
                        // raised card is indistinguishable from a label, and this
                        // is the only action on the row.
                        variant="secondary"
                        onClick={() => handleSignOut(device.deviceId, device.isCurrent)}
                        disabled={busy}
                      >
                        {busy
                          ? "Signing out…"
                          : device.isCurrent
                            ? "Sign out this device"
                            : "Sign out"}
                      </Button>
                    </div>

                    {/* Adjacent to the row that produced it, and announced:
                        a reader who pressed a button and got no visible change
                        is exactly who needs to be told. */}
                    {notice ? (
                      <p role="status" className="text-body-sm text-ink-muted">
                        {notice}
                      </p>
                    ) : null}
                  </li>
                )
              })}
            </ul>
          )}
        </QueryState>
      </section>

      <ConfirmModal
        open={confirmingCurrent !== null}
        title="Sign out this device?"
        description="You are reading this on the device you are about to sign out."
        // Overridden: the default claims the action cannot be undone, and this
        // one plainly can — you sign in again. What it costs is the session you
        // are in right now, which is the part worth saying.
        consequence="You will be signed out straight away and will need to sign in again on this device."
        confirmLabel="Sign out"
        pendingLabel="Signing out…"
        cancelLabel="Stay signed in"
        pending={pendingId !== null}
        onConfirm={() => {
          if (confirmingCurrent !== null) signOut(confirmingCurrent)
        }}
        onCancel={() => setConfirmingCurrent(null)}
      />
    </>
  )
}

/** The top-level `/settings/devices` route (parent and admin still reach this
 * screen only through here — see `SettingsFrame`'s module header for why the
 * lane is role-agnostic). A static intro: the section itself now renders the
 * device-limit sentence once `devices.data` has loaded, so this wrapper no
 * longer needs to know that fact to pass one in. */
export function DeviceSettings() {
  return (
    <SettingsFrame
      title="Account and devices"
      intro="You can be signed in on a limited number of devices at a time."
    >
      <DeviceSettingsSection />
    </SettingsFrame>
  )
}
