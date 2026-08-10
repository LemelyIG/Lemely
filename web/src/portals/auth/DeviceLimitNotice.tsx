import { Button } from "@/components/ui/button"
import { deviceTitle, lastActiveLabel } from "@/lib/devices"
import type { DeviceLimitChallenge } from "@/lib/deviceTypes"

/*
 * G-10 · Device limit reached.
 *
 * Shown in place of the login form when the backend answers 409 (D5.12): the
 * credential was correct, nothing has been signed in or out yet, and the user
 * is being asked to agree to the trade before it happens.
 *
 * Two things the spec is emphatic about and this component keeps:
 *   - it must not feel like an accusation. The copy states a limit and its
 *     reason ("so a shared password can't spread"), never a suspicion.
 *   - the device that will be signed out is named, and named by the *server*
 *     (`oldestDeviceId`) rather than re-derived from the timestamps here. A UI
 *     that sorted differently from the registry would promise to sign out one
 *     device and sign out another.
 *
 * There is no location line: this build stores no IP and has no geo-IP source,
 * and a guessed city beside "sign this one out" is the worst possible place to
 * invent precision (D5.12 §5, UI spec §1.4).
 */

interface DeviceLimitNoticeProps {
  challenge: DeviceLimitChallenge
  onConfirm: () => void
  onCancel: () => void
  isPending: boolean
  error?: string | null
}

export function DeviceLimitNotice({
  challenge,
  onConfirm,
  onCancel,
  isPending,
  error,
}: DeviceLimitNoticeProps) {
  const oldest = challenge.devices.find(
    (d) => d.deviceId === challenge.oldestDeviceId,
  )

  return (
    <section
      aria-labelledby="device-limit-heading"
      className="flex w-full max-w-110 flex-col gap-4 rounded-md border border-border bg-surface p-8"
    >
      <h1 id="device-limit-heading" className="text-display-sm">
        You&rsquo;re signed in on {challenge.maxDevices} devices
      </h1>
      <p className="text-body-md text-t2">
        An account can stay signed in on {challenge.maxDevices} devices at a
        time, so one password can&rsquo;t quietly spread across a year group.
        Signing in here will sign out{" "}
        <strong className="text-t1">
          {oldest
            ? deviceTitle(oldest)
            : "the one you last used least recently"}
        </strong>
        .
      </p>
      <ul
        className="flex flex-col gap-2"
        aria-label="Devices currently signed in"
      >
        {challenge.devices.map((device) => {
          const willSignOut = device.deviceId === challenge.oldestDeviceId
          return (
            <li
              key={device.deviceId}
              className="flex items-baseline justify-between gap-3 rounded border border-border px-3 py-2"
            >
              <span className="flex flex-col">
                <span
                  className="text-body-md"
                  title={device.userAgent ?? undefined}
                >
                  {deviceTitle(device)}
                </span>
                <span className="text-xs text-t2">
                  {lastActiveLabel(device.lastActiveAt)}
                </span>
              </span>
              {willSignOut ? (
                <span className="text-xs font-medium text-t2">
                  Will be signed out
                </span>
              ) : null}
            </li>
          )
        })}
      </ul>
      {error ? <p className="text-xs text-err">{error}</p> : null}
      <div className="flex flex-col gap-2">
        <Button
          type="button"
          variant="ink"
          size="lg"
          onClick={onConfirm}
          disabled={isPending}
        >
          {isPending ? "Signing in…" : "Sign out that device and continue"}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="lg"
          onClick={onCancel}
          disabled={isPending}
        >
          Cancel
        </Button>
      </div>
      <p className="text-xs text-t2">
        You can see and sign out your devices any time from Account &amp;
        devices.
      </p>
    </section>
  )
}
