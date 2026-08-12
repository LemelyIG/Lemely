import { useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { useAuth } from "@/lib/auth/AuthContext"
import { portalPathForRole } from "@/lib/auth/RequireAuth"
import { deviceTitle, lastActiveLabel } from "@/lib/devices"
import { useDevices, useRevokeDevice } from "@/lib/hooks/useDeviceApi"

/*
 * G-11 · Account & devices — the devices section.
 *
 * Role-agnostic by design: every account is subject to the same 3-device limit
 * (D1.11), so this route is reachable by all five roles rather than living
 * inside one portal.
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
 */
export function DeviceSettings() {
  const { session, logout } = useAuth()
  const devices = useDevices()
  const revoke = useRevokeDevice()
  const [pendingId, setPendingId] = useState<string | null>(null)

  const handleSignOut = (deviceId: string) => {
    setPendingId(deviceId)
    revoke.mutate(deviceId, {
      // Signing out the device you are using invalidates this very token — the
      // next request would 401. Clearing the session here turns that into an
      // ordinary sign-out instead of a screen that mysteriously stops working.
      onSuccess: (result) => {
        if (result.wasCurrent) logout()
      },
      onSettled: () => setPendingId(null),
    })
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-160 flex-col gap-6 px-4 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="text-display-sm">Account &amp; devices</h1>
        <p className="text-body-md text-t2">
          {devices.data
            ? `You can be signed in on ${devices.data.maxDevices} devices at a time. Signing in on another one signs out whichever you used least recently.`
            : "You can be signed in on a limited number of devices at a time."}
        </p>
        <div className="flex flex-wrap items-center gap-4">
          {session ? (
            <Link
              to={portalPathForRole(session.role)}
              className="text-body-md text-accent hover:underline"
            >
              ← Back
            </Link>
          ) : null}
          {/* The two settings screens link to each other so one nav entry per
              portal reaches both (P5.9 chunk D). Without this the teacher
              sidebar and parent header would each need two. */}
          <Link
            to="/settings/notifications"
            className="text-body-md text-accent hover:underline"
          >
            Notification settings
          </Link>
        </div>
      </header>

      <section
        aria-labelledby="devices-heading"
        className="flex flex-col gap-3"
      >
        <h2 id="devices-heading" className="text-display-xs">
          Signed-in devices
        </h2>

        {devices.isPending ? (
          <p className="text-body-md text-t2">Loading your devices…</p>
        ) : null}

        {devices.isError ? (
          <ErrorState
            heading="We couldn't load your devices"
            body={devices.error.message}
            action={{
              label: "Try again",
              onClick: () => void devices.refetch(),
            }}
          />
        ) : null}

        {devices.data && devices.data.devices.length === 0 ? (
          <EmptyState
            heading="No signed-in devices"
            body="Nothing is currently signed in to this account."
          />
        ) : null}

        <ul className="flex flex-col gap-2">
          {devices.data?.devices.map((device) => (
            <li
              key={device.deviceId}
              className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-4"
            >
              <span className="flex flex-col gap-0.5">
                <span
                  className="text-body-md"
                  title={device.userAgent ?? undefined}
                >
                  {deviceTitle(device)}
                  {device.isCurrent ? (
                    <span className="ms-2 rounded-full border border-border px-2 py-0.5 text-xs text-t2">
                      This device
                    </span>
                  ) : null}
                </span>
                <span className="text-xs text-t2">
                  {lastActiveLabel(device.lastActiveAt)}
                </span>
              </span>
              <Button
                type="button"
                variant="ghost"
                onClick={() => handleSignOut(device.deviceId)}
                disabled={pendingId === device.deviceId}
              >
                {pendingId === device.deviceId
                  ? "Signing out…"
                  : device.isCurrent
                    ? "Sign out this device"
                    : "Sign out"}
              </Button>
            </li>
          ))}
        </ul>

        {revoke.isError ? (
          <p className="text-xs text-err">
            {revoke.error.message || "We couldn't sign that device out."}
          </p>
        ) : null}
      </section>
    </main>
  )
}
