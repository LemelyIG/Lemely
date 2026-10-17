/*
 * Deciding whether to enable push *without* being asked.
 *
 * G-12 shipped push as a button on one settings screen, which meant a reader
 * who never opened `/settings/notifications` was never asked for permission and
 * therefore never received a push — the whole feature was reachable only by
 * somebody already looking for it. This module is the decision half of asking
 * on the reader's behalf; `components/push-auto-enable.tsx` is the plumbing.
 *
 * Kept pure and free of browser globals for the same reason `pushDecision.ts`
 * is: there is no jsdom in the unit runner (`vitest.config.ts`), so anything
 * that touches `Notification` or `navigator` is untestable, and the rules about
 * when it is acceptable to interrupt a reader are exactly the part worth a test.
 *
 * This file must not be imported by `src/sw.ts` — see `pushEnable.ts`'s header
 * for why `tsconfig.sw.json` deliberately cannot see this directory.
 */

import type { PushPermission } from "./pushEnable"

export interface AutoEnableInputs {
  /** Service worker + `PushManager` + `Notification` all present. */
  supported: boolean
  /** Does this deployment have VAPID keys? `GET /notifications/push/config`. */
  available: boolean
  permission: PushPermission
  /** Does this browser already hold a subscription for this origin? */
  subscribed: boolean
  /**
   * Has this browser already been auto-asked for *this* VAPID key? Persisted
   * by the caller; see `autoEnableAttemptKey`.
   */
  attempted: boolean
}

export type AutoEnableDecision =
  /** Do nothing, for the stated reason. */
  | { kind: "skip"; reason: AutoEnableSkipReason }
  /**
   * Subscribe now. `interrupts` is true when the browser will show its
   * permission dialog, which is the case the caller must record an attempt for.
   */
  | { kind: "enable"; interrupts: boolean }

export type AutoEnableSkipReason =
  | "unavailable"
  | "unsupported"
  | "denied"
  | "already-enabled"
  | "already-asked"

/**
 * Whether to enable push on the reader's behalf.
 *
 * The rules, and why each one is a rule rather than a check:
 *
 * **Server availability comes first**, as it does in `resolvePushState`. A
 * build with no VAPID keys cannot sign a push, so asking for permission there
 * would spend the one prompt a browser gives us on a capability that does not
 * exist, and the reader would be left with a granted permission and nothing to
 * receive.
 *
 * **`denied` is never retried.** The browser will not re-prompt from script
 * once a reader has refused, so an attempt is not merely rude, it is a no-op
 * that costs a round trip. The settings screen already tells that reader what
 * to do in their site settings.
 *
 * **`granted` without a subscription re-subscribes silently, and ignores
 * `attempted`.** No dialog appears when permission is already granted, so this
 * interrupts nobody. It is the repair path for the case D5.9 §4 describes — a
 * `410` the server acted on, cleared site data, a new profile — where the
 * reader believes push is on and every send is failing. Gating it on the
 * once-only marker would make that state permanent on this browser.
 *
 * **`default` is asked exactly once per browser per key.** A prompt dismissed
 * rather than answered leaves the permission at `default`, so without a marker
 * this would re-prompt on every single load, which is how a browser decides to
 * suppress the prompt permanently. One ask, then the settings screen is the
 * only remaining route — that is a deliberate ceiling on how much this feature
 * gets to interrupt somebody who did not ask for it.
 */
export function decideAutoEnable(inputs: AutoEnableInputs): AutoEnableDecision {
  if (!inputs.available) return { kind: "skip", reason: "unavailable" }
  if (!inputs.supported) return { kind: "skip", reason: "unsupported" }
  if (inputs.permission === "denied") return { kind: "skip", reason: "denied" }
  if (inputs.permission === "granted") {
    return inputs.subscribed
      ? { kind: "skip", reason: "already-enabled" }
      : { kind: "enable", interrupts: false }
  }
  if (inputs.attempted) return { kind: "skip", reason: "already-asked" }
  return { kind: "enable", interrupts: true }
}

/** Prefix for the once-only marker, shared with the reader below. */
const ATTEMPT_PREFIX = "lemely.push.autoAsked."

/**
 * The `localStorage` key recording that this browser has been auto-asked.
 *
 * **Keyed on the VAPID public key, not a constant.** Rotating the pair
 * invalidates every stored subscription (`lemely.toml.example` says so in
 * capitals), so every browser must re-subscribe; a constant key would leave
 * each of them marked "already asked" and silently unreachable forever. The
 * first 16 characters are enough to distinguish two keys and keep the stored
 * name short — this is a cache-busting discriminator, not a security boundary.
 *
 * Returns null for an empty key rather than a bare prefix, so a missing config
 * value cannot collide with a real one.
 */
export function autoEnableAttemptKey(publicKey: string): string | null {
  if (publicKey === "") return null
  return `${ATTEMPT_PREFIX}${publicKey.slice(0, 16)}`
}

/**
 * Read the marker, treating an unreadable store as "not yet asked".
 *
 * `localStorage` throws rather than returning null in a Safari private window
 * and under a block-all-site-data setting. Failing closed there would mean
 * never asking on those browsers; failing open means at worst one prompt per
 * load on a browser that cannot remember anything anyway, and the reader's
 * answer is still remembered by the *permission*, which is what actually stops
 * the second prompt.
 */
export function readAutoEnableAttempt(store: Storage, key: string): boolean {
  try {
    return store.getItem(key) !== null
  } catch {
    return false
  }
}

/** Record the marker. A store that refuses writes is not an error worth surfacing. */
export function writeAutoEnableAttempt(store: Storage, key: string): void {
  try {
    store.setItem(key, new Date().toISOString())
  } catch {
    // See `readAutoEnableAttempt`: the permission itself is the durable answer.
  }
}
