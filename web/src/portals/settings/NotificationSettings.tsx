/* Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4 */
import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import {
  quietHoursSummary,
  quietHoursUpdate,
  timeInputValue,
  visibleToggles,
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
import { SettingsCard, SettingsRow, SettingsSection, SettingsStatus } from "./SettingsRows"

/*
 * G-12 · Notification preferences (P4.10, now v5 Abyss).
 *
 * Top-level at `/settings/notifications` rather than inside a portal subtree,
 * for the same reason G-11 is: the API is role-agnostic. Every role has these
 * preferences, and `at_risk_alert` belongs to the **teacher and parent** — a
 * student-portal mount would have put the toggle out of reach of the only two
 * roles it applies to.
 *
 * Two things this screen is careful not to overstate.
 *
 * **The toggles are the whole enum** (fourteen types, each role seeing the ones the
 * server sends it). UI spec §G-12 also lists a "weekly
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

/**
 * The section this screen renders, with no frame around it — mounted at
 * `/teacher/settings/notifications` and `/student/settings/notifications`
 * inside `PortalSettingsLayout`, which supplies its own `<h1>`/nav/chrome,
 * in addition to the framed `NotificationSettings` below for the top-level
 * `/settings/notifications` lane (parent and admin still use that one).
 */
/**
 * `showTeacherOnly` (Task 17, R10): reveals the `reviewWithdrawn` toggle,
 * which the backend sends as a plain `boolean` for every role (unlike
 * `atRiskAlert`, never nulled server-side — `notificationPrefs.ts`'s own
 * `NotificationPreferences.reviewWithdrawn` doc). Defaults to `false`, so
 * every existing mount (student, parent, admin) is unaffected by this prop
 * simply appearing; the teacher portal's own mount is the one call site
 * that passes `true`.
 */
export function NotificationSettingsSection({
  showTeacherOnly = false,
}: {
  showTeacherOnly?: boolean
} = {}) {
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
  /** The last toggle that saved, so its row can say so. */
  const [savedKey, setSavedKey] = useState<NotificationPrefKey | null>(null)
  const [quietSaving, setQuietSaving] = useState(false)
  const [quietSaved, setQuietSaved] = useState(false)
  /** A failed toggle, kept against the key that failed so the message renders
   * beside its own switch rather than under the whole list. */
  const [toggleFailure, setToggleFailure] = useState<{
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
    setSavedKey(null)
    setToggleFailure(null)
    // One key, never the whole object — see `useUpdateNotificationPreferences`.
    update.mutate(
      { [key]: value },
      {
        onError: (error) => setToggleFailure({ key, message: settingsSaveFailureMessage(error) }),
        onSuccess: () => setSavedKey(key),
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
    setQuietSaved(false)
    setQuietSaving(true)
    update.mutate(result.update, {
      onError: (error) => setQuietError(settingsSaveFailureMessage(error)),
      onSuccess: () => setQuietSaved(true),
      onSettled: () => setQuietSaving(false),
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
    <>
      <SettingsSection
        title="What you get told about"
        description="Each switch saves as you press it. Switching one off stops it reaching you at all, inbox included."
      >
        {/* No `srHeading`: the page's own `<h1>` (page lane) or the dialog
            title (teacher Settings dialog) sits above this section in every
            query state. No `isEmpty` either: the toggles are a fixed enum, so
            there is no empty shape, only the role filter below. */}
        <QueryState
          query={prefs}
          skeleton={<ListSkeleton rows={4} />}
          error={{
            heading: "We couldn't load your notification settings",
            body: settingsLoadFailureMessage,
          }}
        >
          {(data) => (
            <SettingsCard>
              <ul className="flex flex-col divide-y divide-outline-variant">
                {/* `visibleToggles` hides a toggle whose value is `null` (no
                    such preference for this role: `atRiskAlert`,
                    `reviewWithdrawn` and the eight tutoring toggles) rather
                    than rendering it unchecked, which would offer a switch the
                    router answers with a 422. `showTeacherOnly` is this
                    screen's own extra gate for `reviewWithdrawn`. */}
                {visibleToggles(data, { showTeacherOnly })
                  .map((toggle) => (
                    <li key={toggle.key} className="flex flex-col gap-2 px-4 py-4 sm:px-5">
                      <Switch
                        layout="row"
                        label={toggle.label}
                        description={toggle.description}
                        checked={valueFor(data, toggle.key) === true}
                        // Only the switch in flight says so. The rest are
                        // disabled because the mutation replaces the whole
                        // preference object on success, so two in-flight
                        // changes could clobber each other.
                        state={savingKey === toggle.key ? "loading" : undefined}
                        error={toggleFailure?.key === toggle.key ? toggleFailure.message : undefined}
                        disabled={update.isPending && savingKey !== toggle.key}
                        onCheckedChange={(next) => handleToggle(toggle.key, next)}
                      />
                      {savedKey === toggle.key && savingKey === null ? (
                        <SettingsStatus>Saved.</SettingsStatus>
                      ) : null}
                    </li>
                  ))}
              </ul>
            </SettingsCard>
          )}
        </QueryState>
      </SettingsSection>

      <SettingsSection
        title="Quiet hours"
        description="Nothing pops up on your device between these times. Notifications still arrive in your inbox, so you see them when you next look."
      >
        <SettingsCard>
          <div className="flex flex-col gap-3 px-4 py-4 sm:px-5">
            <div className="flex flex-wrap items-start gap-3">
              <Input
                label="From"
                type="time"
                value={quietStart}
                onChange={(event) => {
                  setQuietStart(event.target.value)
                  setQuietSaved(false)
                }}
                wrapperClassName="w-36"
              />
              <Input
                label="To"
                type="time"
                value={quietEnd}
                onChange={(event) => {
                  setQuietEnd(event.target.value)
                  setQuietSaved(false)
                }}
                // The error rides the second field: an invalid range is a
                // fact about the pair, and the end time is the one a reader
                // most likely just typed.
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
                {quietSaving ? "Saving…" : "Save quiet hours"}
              </Button>
            </div>
            {/* Body rung, not the data face: this is a sentence, and a
                sentence set in tabular numerals reads as machine output. */}
            {quietSaved ? <SettingsStatus>Saved.</SettingsStatus> : null}
            {summary ? <p className="text-body-sm text-on-surface-variant">{summary}</p> : null}
          </div>
        </SettingsCard>
      </SettingsSection>

      <SettingsSection
        title="This device"
        description="Pop-up notifications on this device. Your inbox gets everything either way."
      >
        <SettingsCard>
          <SettingsRow
            label={copy.heading}
            description={copy.body}
            control={
              pushState.kind === "prompt" ? (
                <Button
                  type="button"
                  onClick={handleEnablePush}
                  disabled={pushBusy || pushConfig.data?.publicKey == null}
                >
                  {pushBusy ? "Turning on…" : "Turn on for this device"}
                </Button>
              ) : pushState.kind === "enabled" ? (
                <Button type="button" variant="secondary" onClick={handleDisablePush} disabled={pushBusy}>
                  {pushBusy ? "Turning off…" : "Turn off for this device"}
                </Button>
              ) : null
            }
            status={
              <>
                {pushError ? <SettingsStatus tone="error">{pushError}</SettingsStatus> : null}
              </>
            }
          />
          {pushState.kind === "enabled" ? (
            // Worded as a device check, not a delivery test: no route in this
            // backend sends a test push, and on a build with no VAPID keys
            // none could. What it proves is permission, the service worker and
            // the operating system, the half that actually breaks.
            <SettingsRow
              label="Test notification"
              description="Shown by this device itself. It does not check that the server can reach you."
              control={
                <Button type="button" variant="ghost" onClick={handleTestNotification}>
                  Show a test notification
                </Button>
              }
              status={testResult ? <SettingsStatus>{testResult}</SettingsStatus> : null}
            />
          ) : null}
        </SettingsCard>
      </SettingsSection>
    </>
  )
}

/** The top-level `/settings/notifications` route (parent and admin still
 * reach this screen only through here — see `SettingsFrame`'s module header
 * for why the lane is role-agnostic). */
export function NotificationSettings() {
  return (
    <SettingsFrame
      title="Notifications"
      intro="Choose what you want to hear about, and when. Everything you switch on arrives in your inbox whether or not this device can show pop-ups."
    >
      <NotificationSettingsSection />
    </SettingsFrame>
  )
}

/**
 * Read one toggle off the loaded preferences.
 *
 * Returns `null` for a role-gated toggle on a role that has no such preference —
 * the distinction the filter above depends on, kept as a function so the null
 * cannot be flattened to `false` by a stray `??`.
 */
function valueFor(prefs: NotificationPreferences, key: NotificationPrefKey): boolean | null {
  return prefs[key]
}
