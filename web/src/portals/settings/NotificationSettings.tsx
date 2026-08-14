/* Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4 */
import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { ErrorState } from "@/components/ui/state-views"
import { ListSkeleton } from "@/components/ui/loading-shapes"
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
import {
  settingsLoadFailureMessage,
  settingsSaveFailureMessage,
} from "@/lib/settingsOutcome"
import { SettingsFrame } from "./SettingsFrame"

/*
 * G-12 · Notification preferences, in the Study Notebook (P4.10).
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
 *
 * ── P4.10, the Study Notebook pass ─────────────────────────────────────────
 *
 * **The toggles are switches now, not checkboxes.** These preferences take
 * effect on the press: each one PUTs immediately, with no form and no save
 * button. That is the exact distinction ARIA gives `role="switch"` its own role
 * for, and the kit's `Switch` header spells it out — a checkbox says "selected,
 * applies on submit", which is a promise this screen does not keep. Assistive
 * tech announced five checkboxes in a form with no submit.
 *
 * **A failed save now names the preference it failed on.** The error rendered
 * as one line under the whole list, so a failure on the first toggle appeared
 * below the fifth, and the reader had to work out which of five changes had not
 * stuck. It sits with its own switch now (§12), and the switch in flight shows
 * its own loading state rather than the whole list merely greying out.
 *
 * The switch positions themselves were already honest and are unchanged:
 * `checked` reads from `prefs.data`, which only moves on a 200, so a failed
 * save leaves the switch where it was rather than showing a state the server
 * never accepted.
 */

/** Copy for each push state. Kept beside the screen so the three stay comparable. */
function pushStateCopy(kind: string): { heading: string; body: string } {
  switch (kind) {
    case "unavailable":
      return {
        heading: "Push notifications are off for this deployment",
        body: "This server has no push keys configured, so nothing can be sent to your device. Your notifications still arrive in your inbox, so you are not missing any of them.",
      }
    case "unsupported":
      return {
        heading: "This browser cannot show push notifications",
        body: "Your notifications still arrive in your inbox. To get them on your device, open Lemely in a browser that supports notifications, or install it to your home screen.",
      }
    case "denied":
      return {
        heading: "You have blocked notifications for Lemely",
        body: "We cannot ask again from here. Browsers only let you undo this yourself. Open the padlock or site-settings icon next to the address bar and allow notifications, then reload this page.",
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
  /** Which toggle is mid-flight, so its own switch can show it. */
  const [savingKey, setSavingKey] = useState<NotificationPrefKey | null>(null)
  /** A failed toggle, kept against the key that failed so the message renders
   * beside its own switch rather than under the whole list. */
  const [toggleError, setToggleError] = useState<{
    key: NotificationPrefKey
    message: string
  } | null>(null)

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
    setSavingKey(key)
    setToggleError(null)
    // One key, never the whole object — see `useUpdateNotificationPreferences`.
    update.mutate(
      { [key]: value },
      {
        onError: (error) => setToggleError({ key, message: settingsSaveFailureMessage(error) }),
        onSettled: () => setSavingKey(null),
      },
    )
  }

  const handleQuietHoursSave = () => {
    const result = quietHoursUpdate(quietStart, quietEnd)
    if (!result.ok) {
      setQuietError(result.message)
      return
    }
    setQuietError(null)
    update.mutate(result.update, {
      onError: (error) => setQuietError(settingsSaveFailureMessage(error)),
    })
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
          : "This device cannot show a notification yet. Turn push on above first.",
      )
    })
  }

  const loaded = prefs.data ?? null
  const summary = loaded ? quietHoursSummary(loaded.quietHoursStart, loaded.quietHoursEnd) : null

  return (
    <SettingsFrame
      title="Notifications"
      intro="Choose what you want to hear about, and when. Everything you switch on arrives in your inbox whether or not this device can show pop-ups."
    >
      <section aria-labelledby="types-heading" className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <h2 id="types-heading" className="text-display-sm text-ink">
            What you get told about
          </h2>
          <p className="max-w-[65ch] text-body-sm text-ink-muted">
            Switching one off stops it reaching you at all. It will not appear in your inbox
            either.
          </p>
        </div>

        {prefs.isPending ? <ListSkeleton rows={4} /> : null}

        {prefs.isError ? (
          <ErrorState
            heading="We couldn't load your notification settings"
            body={settingsLoadFailureMessage(prefs.error)}
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
                className="rounded-lg border border-rule bg-paper-raised p-4 sm:p-5"
              >
                <Switch
                  label={toggle.label}
                  description={toggle.description}
                  checked={valueFor(loaded, toggle.key) === true}
                  // Only the switch in flight says so. The rest are disabled
                  // because the mutation replaces the whole preference object
                  // on success, so two in-flight changes could clobber each
                  // other — but "disabled" and "saving" are different facts and
                  // are now shown differently.
                  state={savingKey === toggle.key ? "loading" : undefined}
                  error={toggleError?.key === toggle.key ? toggleError.message : undefined}
                  disabled={update.isPending && savingKey !== toggle.key}
                  onCheckedChange={(next) => handleToggle(toggle.key, next)}
                />
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section aria-labelledby="quiet-heading" className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <h2 id="quiet-heading" className="text-display-sm text-ink">
            Quiet hours
          </h2>
          <p className="max-w-[65ch] text-body-sm text-ink-muted">
            Nothing pops up on your device between these times. Notifications still arrive in
            your inbox, so you will see them when you next look.
          </p>
        </div>

        <div className="flex flex-col gap-4 rounded-lg border border-rule bg-paper-raised p-4 sm:p-5">
          <div className="flex flex-wrap items-start gap-3">
            <Input
              label="From"
              type="time"
              value={quietStart}
              onChange={(event) => setQuietStart(event.target.value)}
              wrapperClassName="w-36"
            />
            <Input
              label="To"
              type="time"
              value={quietEnd}
              onChange={(event) => setQuietEnd(event.target.value)}
              // The error rides the second field rather than the first: an
              // invalid range is a fact about the pair, and the end time is the
              // one a reader is most likely to have just typed.
              error={quietError ?? undefined}
              wrapperClassName="w-36"
            />
            <Button
              type="button"
              onClick={handleQuietHoursSave}
              disabled={update.isPending}
              // Aligns the button with the fields rather than their labels.
              className="mt-6"
            >
              {update.isPending ? "Saving…" : "Save quiet hours"}
            </Button>
          </div>
          {/* Body rung, not the data face. The first pass put this on
              `data-sm` reasoning that it is "two clock times and a duration";
              the capture round showed it is a full sentence wearing the mono
              face, and a sentence set in tabular numerals reads as machine
              output. The times inside it are already unambiguous. */}
          {summary ? <p className="text-body-sm text-ink-faint">{summary}</p> : null}
        </div>
      </section>

      <section aria-labelledby="device-heading" className="flex flex-col gap-4">
        <h2 id="device-heading" className="text-display-sm text-ink">
          This device
        </h2>
        <div className="flex flex-col gap-3 rounded-lg border border-rule bg-paper-raised p-4 sm:p-5">
          <div className="flex flex-col gap-1">
            <p className="text-body-md text-ink">{copy.heading}</p>
            <p className="max-w-[65ch] text-body-sm text-ink-muted">{copy.body}</p>
          </div>

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
            <>
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="ghost" onClick={handleDisablePush} disabled={pushBusy}>
                  {pushBusy ? "Turning off…" : "Turn off for this device"}
                </Button>
                <Button type="button" variant="ghost" onClick={handleTestNotification}>
                  Show a test notification
                </Button>
              </div>
              {/* Deliberately worded as a device check, not a delivery test: no
                  route in this backend sends a test push, and on a build with no
                  VAPID keys none could. What it proves is permission, the service
                  worker and the operating system — the half that actually breaks. */}
              {/* Prose, so the body rung rather than the data face: this is a
                  sentence about what the button proves, not a value. */}
              <p className="text-body-sm text-ink-faint">
                A test notification is shown by this device itself. It does not check that the
                server can reach you.
              </p>
            </>
          ) : null}

          {testResult ? (
            <p role="status" className="text-body-sm text-ink-muted">
              {testResult}
            </p>
          ) : null}
          {pushError ? (
            <p role="status" className="text-body-sm text-err">
              {pushError}
            </p>
          ) : null}
        </div>
      </section>
    </SettingsFrame>
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
