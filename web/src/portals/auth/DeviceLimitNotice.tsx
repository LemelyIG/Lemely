/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
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
 *
 * P4.7's one substantive change: **"Will be signed out" was `--t2` muted text**,
 * the quietest register on the screen, marking the single row that is about to
 * be destroyed. It is a `warn` chip now. The row it sits on is also the only
 * one with a washed background, so the warning has two carriers and neither is
 * colour alone (§3.6).
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
  const oldest = challenge.devices.find((d) => d.deviceId === challenge.oldestDeviceId)

  return (
    <section
      aria-labelledby="device-limit-heading"
      className="flex w-full max-w-120 flex-col gap-5 rounded-lg border border-rule bg-paper-raised p-8"
    >
      <div className="flex flex-col gap-2">
        <h1 id="device-limit-heading" className="text-display-md text-ink">
          You&rsquo;re signed in on {challenge.maxDevices} devices
        </h1>
        <p className="text-body-md text-ink-muted">
          An account can stay signed in on {challenge.maxDevices} devices at a time, so one
          password can&rsquo;t quietly spread across a year group. Signing in here will sign
          out{" "}
          <strong className="font-medium text-ink">
            {oldest ? deviceTitle(oldest) : "the one you last used least recently"}
          </strong>
          .
        </p>
      </div>

      <ul className="flex flex-col gap-2" aria-label="Devices currently signed in">
        {challenge.devices.map((device) => {
          const willSignOut = device.deviceId === challenge.oldestDeviceId
          return (
            <li
              key={device.deviceId}
              className={`flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-md border px-4 py-3 ${
                // The row takes a firmer border, not the wash: `Chip tone="warn"`
                // is itself `bg-warn-wash`, so washing the row too would hide
                // the chip inside its own colour.
                willSignOut ? "border-warn" : "border-rule"
              }`}
            >
              <span className="flex min-w-0 flex-col">
                <span className="text-body-md text-ink" title={device.userAgent ?? undefined}>
                  {deviceTitle(device)}
                </span>
                {/* A last-seen time is a timestamp, so it sets in the data
                    face (§4) like every other one in the product. */}
                <span className="text-data-sm text-ink-faint">
                  {lastActiveLabel(device.lastActiveAt)}
                </span>
              </span>
              {willSignOut ? <Chip tone="warn">Will be signed out</Chip> : null}
            </li>
          )
        })}
      </ul>

      {error ? (
        <p role="alert" className="text-body-sm text-err">
          {error}
        </p>
      ) : null}

      <div className="flex flex-col gap-2">
        <Button type="button" variant="accent" size="lg" onClick={onConfirm} loading={isPending}>
          {isPending ? "Signing in…" : "Sign out that device and continue"}
        </Button>
        <Button type="button" variant="ghost" size="lg" onClick={onCancel} disabled={isPending}>
          Cancel
        </Button>
      </div>

      <p className="text-body-sm text-ink-faint">
        You can see and sign out your devices any time from Account &amp; devices.
      </p>
    </section>
  )
}
