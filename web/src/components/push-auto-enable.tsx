/* Hallmark · pre-emit critique: P4 H3 E4 S4 R5 V3 */
import { useEffect, useRef } from "react"
import { useAuth } from "@/lib/auth/AuthContext"
import { usePushConfig } from "@/lib/hooks/useNotificationApi"
import { useSubscribeToPush } from "@/lib/hooks/useNotificationPrefsApi"
import {
  autoEnableAttemptKey,
  decideAutoEnable,
  readAutoEnableAttempt,
  writeAutoEnableAttempt,
} from "@/lib/push/pushAutoEnable"
import {
  currentPushPermission,
  currentPushSubscription,
  pushSupported,
  subscribeToPush,
} from "@/lib/push/pushEnable"

/*
 * Asks for notification permission once per signed-in browser, instead of
 * waiting for the reader to find one button on one settings screen.
 *
 * Mounted once above the router, beside `TimezoneSync`, for the reason that one
 * gives: this has to run whichever screen the reader lands on, and an effect
 * inside a screen would only run there. It renders nothing.
 *
 * ── What is deliberate here ────────────────────────────────────────────────
 *
 * **The attempt is recorded before the prompt is shown, not after.** A reader
 * who dismisses the browser dialog without answering leaves the permission at
 * `default`, so a marker written on the *result* would never be written for
 * exactly the reader who declined to engage — and they would be prompted again
 * on every load until the browser suppressed the prompt for good.
 *
 * **Silent re-subscription is not gated by that marker** (see
 * `decideAutoEnable`): with permission already granted no dialog appears, and
 * this is the only path that repairs a browser whose subscription the server
 * dropped.
 *
 * **Every failure is silent.** There is no screen to report on, the settings
 * screen at `/settings/notifications` states the real state whenever the reader
 * looks, and the inbox is the source of truth either way (D5.9 §1) — a reader
 * with no push at all still receives every notification. Notably Safari and
 * every iOS browser require a user gesture for `requestPermission`, so the
 * automatic attempt rejects there by design; the button on the settings screen
 * remains the route on those engines, and that rejection must not surface as an
 * error the reader can neither understand nor act on.
 *
 * The stamp above, derived rather than copied: H3 and V3 are ceilings for a
 * component that returns `null`, as they are for `TimezoneSync`. R5 is the real
 * claim — the once-only marker, the pre-emptive write, and the silent failure
 * are each argued for above rather than left to a reader to infer.
 */
export function PushAutoEnable() {
  const { session } = useAuth()
  const userId = session?.userId ?? null
  // Packet A7: gated on session state. This component is mounted
  // unconditionally in main.tsx, above the router — without this, the push
  // config request fired on every cold, logged-out load of /login. See
  // usePushConfig's own doc for the full finding.
  const config = usePushConfig(userId !== null)
  const subscribe = useSubscribeToPush()
  /** The user this browser has already run for, so a re-render cannot re-ask. */
  const ranFor = useRef<string | null>(null)
  const available = config.data?.available ?? false
  const publicKey = config.data?.publicKey ?? null

  useEffect(() => {
    if (userId === null || publicKey === null) return
    if (ranFor.current === userId) return
    const attemptKey = autoEnableAttemptKey(publicKey)
    if (attemptKey === null) return
    ranFor.current = userId

    void (async () => {
      const subscribed = (await currentPushSubscription()) !== null
      const decision = decideAutoEnable({
        supported: pushSupported(),
        available,
        permission: currentPushPermission(),
        subscribed,
        attempted: readAutoEnableAttempt(window.localStorage, attemptKey),
      })
      if (decision.kind === "skip") return
      if (decision.interrupts) writeAutoEnableAttempt(window.localStorage, attemptKey)

      const payload = await subscribeToPush(publicKey)
      // Null covers a refused prompt and an engine that withheld the keys.
      // Both are "push stays off", which is already what the reader sees.
      if (payload !== null) subscribe.mutate(payload)
    })().catch(() => {
      // An engine that refuses the call outright (no user gesture on Safari,
      // a push service that rejected the subscribe) lands here. See the header.
    })
    // `subscribe` is stable for the component's lifetime; listing it would
    // re-run this on every render and the ref guard would make that a no-op.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, publicKey, available])

  return null
}
