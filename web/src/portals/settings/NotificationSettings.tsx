import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { ErrorState } from "@/components/ui/state-views"
import { useAuth } from "@/lib/auth/AuthContext"
import { portalPathForRole } from "@/lib/auth/RequireAuth"
import {
  NOTIFICATION_TOGGLES,
  quietHoursSummary,
  quietHoursUpdate,
  timeInputValue,
  type NotificationPrefKey,
  type NotificationPreferences,
} from "@/lib/notificationPrefs"
import {
  useBrowserPushSubscription,
  useNotificationPreferences,
  useSubscribeToPush,
  useUnsubscribeFromPush,
  useUpdateNotificationPreferences,
} from "@/lib/hooks/useNotificationPrefsApi"
import { usePushConfig } from "@/lib/hooks/useNotificationApi"
import {
  currentPushPermission,
  currentPushSubscription,
  pushSupported,
  resolvePushState,
  showLocalTestNotification,
  subscribeToPush,
  unsubscribeFromPush,
} from "@/lib/push/pushEnable"

/*
 * G-12 · Notification preferences (P5.9 chunk C).
 *
 * Top-level at `/settings/notifications` rather than inside a portal subtree,
 * for the same reason G-11 is: the API is role-agnostic. Every role has these
 * preferences, and `at_risk_alert` belongs to the **teacher and parent** — a
 * student-portal mount would have put the toggle out of reach of the only two
 * roles it applies to.
 *
 * Two things this screen is careful not to overstate.
 *
 * **The five toggles are the whole enum.** UI spec §G-12 also lists a "weekly
 * summary"; there is no such notification type, column, sender or row, so it is
 * absent here rather than mocked (UI spec §1.4). That gap is reported, not
 * papered over.
 *
 * **Push is off in this build and says so.** No VAPID keys are configured, so
 * `GET /notifications/push/config` answers `available: false` by design (D5.9
 * §4) and the enable control is replaced by a plain statement of that fact —
 * distinct from the browser having denied permission, which is the reader's to
 * fix and is worded that way. Neither state touches the toggles above, because
 * the inbox is the source of truth (D5.9 §1): a reader with no push at all still
 * receives every notification at G-13.
 */

/** Copy for each push state. Kept beside the screen so the three stay comparable. */
function pushStateCopy(kind: string): { heading: string; body: string } {
  switch (kind) {
    case "unavailable":
      return {
        heading: "Push notifications are off for this deployment",
        body: "This server has no push keys configured, so nothing can be sent to your device. Your notifications still arrive in your inbox — you are not missing any of them.",
      }
    case "unsupported":
      return {
        heading: "This browser cannot show push notifications",
        body: "Your notifications still arrive in your inbox. To get them on your device, open Lemely in a browser that supports notifications, or install it to your home screen.",
      }
    case "denied":
      return {
        heading: "You have blocked notifications for Lemely",
        body: "We cannot ask again from here — browsers only let you undo this yourself. Open the padlock or site-settings icon next to the address bar and allow notifications, then reload this page.",
      }
    case "enabled":
      return {
        heading: "Push notifications are on for this device",
        body: "Notifications will appear on this device as well as in your inbox.",
      }
    default:
      return {
        heading: "Get notifications on this device",
        body: "Your browser will ask for permission. You can turn this off again here at any time.",
      }
  }
}

export function NotificationSettings() {
  const { session } = useAuth()
  const prefs = useNotificationPreferences()
  const update = useUpdateNotificationPreferences()
  const pushConfig = usePushConfig()
  const subscription = useBrowserPushSubscription(currentPushSubscription)
  const subscribe = useSubscribeToPush()
  const unsubscribe = useUnsubscribeFromPush()

  const [quietStart, setQuietStart] = useState("")
  const [quietEnd, setQuietEnd] = useState("")
  const [quietError, setQuietError] = useState<string | null>(null)
  const [pushBusy, setPushBusy] = useState(false)
  const [pushError, setPushError] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<string | null>(null)

  // Seed the two time inputs from the server exactly once per loaded value.
  // They are uncontrolled-by-the-server after that: a reader half-way through
  // typing a start time must not have the field yanked back by a refetch.
  const loadedStart = prefs.data ? timeInputValue(prefs.data.quietHoursStart) : null
  const loadedEnd = prefs.data ? timeInputValue(prefs.data.quietHoursEnd) : null
  useEffect(() => {
    if (loadedStart === null || loadedEnd === null) return
    setQuietStart(loadedStart)
    setQuietEnd(loadedEnd)
  }, [loadedStart, loadedEnd])

  const pushState = resolvePushState({
    supported: pushSupported(),
    // Unknown availability is treated as unavailable rather than assumed
    // present: offering an enable button that cannot work is the exact thing
    // UI spec §G-12 calls "toggles that silently do nothing".
    available: pushConfig.data?.available ?? false,
    permission: currentPushPermission(),
    subscribed: subscription.data != null,
  })
  const copy = pushStateCopy(pushState.kind)

  const handleToggle = (key: NotificationPrefKey, value: boolean) => {
    // One key, never the whole object — see `useUpdateNotificationPreferences`.
    update.mutate({ [key]: value })
  }

  const handleQuietHoursSave = () => {
    const result = quietHoursUpdate(quietStart, quietEnd)
    if (!result.ok) {
      setQuietError(result.message)
      return
    }
    setQuietError(null)
    update.mutate(result.update)
  }

  const handleEnablePush = () => {
    const publicKey = pushConfig.data?.publicKey
    if (publicKey == null) return
    setPushBusy(true)
    setPushError(null)
    void subscribeToPush(publicKey)
      .then((payload) => {
        if (payload === null) {
          // A refused prompt is a choice, not a failure. Re-reading the real
          // permission below is what keeps the screen honest either way.
          setPushError("Push was not enabled. Your browser did not grant permission.")
          return
        }
        subscribe.mutate(payload)
      })
      .catch(() => {
        setPushError("We couldn't enable push on this device.")
      })
      .finally(() => {
        setPushBusy(false)
        void subscription.refetch()
      })
  }

  const handleDisablePush = () => {
    setPushBusy(true)
    setPushError(null)
    void unsubscribeFromPush()
      .then((endpoint) => {
        if (endpoint !== null) unsubscribe.mutate(endpoint)
      })
      .catch(() => {
        setPushError("We couldn't turn push off on this device.")
      })
      .finally(() => {
        setPushBusy(false)
        void subscription.refetch()
      })
  }

  const handleTestNotification = () => {
    void showLocalTestNotification().then((shown) => {
      setTestResult(
        shown
          ? "Sent to this device. If nothing appeared, your system notification settings are blocking it."
          : "This device cannot show a notification yet — turn push on above first.",
      )
    })
  }

  const loaded = prefs.data ?? null
  const summary = loaded
    ? quietHoursSummary(loaded.quietHoursStart, loaded.quietHoursEnd)
    : null

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-160 flex-col gap-6 px-4 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="text-display-sm">Notifications</h1>
        <p className="text-body-md text-t2">
          Choose what you want to hear about, and when. Everything you switch on
          arrives in your inbox whether or not this device can show pop-ups.
        </p>
        {session ? (
          <Link
            to={portalPathForRole(session.role)}
            className="text-body-md text-accent hover:underline"
          >
            ← Back
          </Link>
        ) : null}
      </header>

      <section aria-labelledby="types-heading" className="flex flex-col gap-3">
        <h2 id="types-heading" className="text-display-xs">
          What you get told about
        </h2>
        <p className="text-body-md text-t2">
          Switching one off stops it reaching you at all — it will not appear in
          your inbox either.
        </p>

        {prefs.isPending ? (
          <p className="text-body-md text-t2">Loading your preferences…</p>
        ) : null}

        {prefs.isError ? (
          <ErrorState
            heading="We couldn't load your notification settings"
            body={prefs.error.message}
            action={{ label: "Try again", onClick: () => void prefs.refetch() }}
          />
        ) : null}

        {loaded ? (
          <ul className="flex flex-col gap-2">
            {NOTIFICATION_TOGGLES.filter(
              // `atRiskAlert` arrives as `null` for every role but teacher and
              // parent, and that null means "no such preference for you" rather
              // than "off". Rendering it unchecked would offer a switch the
              // router answers with a 422.
              (toggle) => valueFor(loaded, toggle.key) !== null,
            ).map((toggle) => (
              <li
                key={toggle.key}
                className="flex flex-col gap-1 rounded-md border border-border p-4"
              >
                <Checkbox
                  label={toggle.label}
                  checked={valueFor(loaded, toggle.key) === true}
                  disabled={update.isPending}
                  onChange={(event) => handleToggle(toggle.key, event.target.checked)}
                />
                <span className="text-xs text-t2">{toggle.description}</span>
              </li>
            ))}
          </ul>
        ) : null}

        {update.isError ? (
          <p className="text-xs text-err">
            {update.error.message || "We couldn't save that change."}
          </p>
        ) : null}
      </section>

      <section aria-labelledby="quiet-heading" className="flex flex-col gap-3">
        <h2 id="quiet-heading" className="text-display-xs">
          Quiet hours
        </h2>
        <p className="text-body-md text-t2">
          Nothing pops up on your device between these times. Notifications still
          arrive in your inbox, so you will see them when you next look.
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-body-md">
            From
            <input
              type="time"
              value={quietStart}
              onChange={(event) => setQuietStart(event.target.value)}
              className="rounded-md border border-border bg-surface px-3 py-2 text-body-md"
            />
          </label>
          <label className="flex flex-col gap-1 text-body-md">
            To
            <input
              type="time"
              value={quietEnd}
              onChange={(event) => setQuietEnd(event.target.value)}
              className="rounded-md border border-border bg-surface px-3 py-2 text-body-md"
            />
          </label>
          <Button type="button" onClick={handleQuietHoursSave} disabled={update.isPending}>
            {update.isPending ? "Saving…" : "Save quiet hours"}
          </Button>
        </div>
        {quietError ? <p className="text-xs text-err">{quietError}</p> : null}
        {summary ? <p className="text-xs text-t2">{summary}</p> : null}
      </section>

      <section aria-labelledby="device-heading" className="flex flex-col gap-3">
        <h2 id="device-heading" className="text-display-xs">
          This device
        </h2>
        <div className="flex flex-col gap-2 rounded-md border border-border p-4">
          <p className="text-body-md">{copy.heading}</p>
          <p className="text-xs text-t2">{copy.body}</p>

          {pushState.kind === "prompt" ? (
            <Button
              type="button"
              className="self-start"
              onClick={handleEnablePush}
              disabled={pushBusy || pushConfig.data?.publicKey == null}
            >
              {pushBusy ? "Turning on…" : "Turn on for this device"}
            </Button>
          ) : null}

          {pushState.kind === "enabled" ? (
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={handleDisablePush}
                disabled={pushBusy}
              >
                {pushBusy ? "Turning off…" : "Turn off for this device"}
              </Button>
              <Button type="button" variant="ghost" onClick={handleTestNotification}>
                Show a test notification
              </Button>
            </div>
          ) : null}

          {/* Deliberately worded as a device check, not a delivery test: no
              route in this backend sends a test push, and on a build with no
              VAPID keys none could. What it proves is permission, the service
              worker and the operating system — the half that actually breaks. */}
          {pushState.kind === "enabled" ? (
            <p className="text-xs text-t2">
              A test notification is shown by this device itself. It does not
              check that the server can reach you.
            </p>
          ) : null}

          {testResult ? <p className="text-xs text-t2">{testResult}</p> : null}
          {pushError ? <p className="text-xs text-err">{pushError}</p> : null}
        </div>
      </section>
    </main>
  )
}

/**
 * Read one toggle off the loaded preferences.
 *
 * Returns `null` only for `atRiskAlert` on a role that has no such preference —
 * the distinction the filter above depends on, kept as a function so the null
 * cannot be flattened to `false` by a stray `??`.
 */
function valueFor(prefs: NotificationPreferences, key: NotificationPrefKey): boolean | null {
  return prefs[key]
}
