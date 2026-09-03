/* Hallmark · pre-emit critique: P4 H4 E3 S5 R5 V4 */
import type { DoodleKind } from "@/components/ui/doodle"

/*
 * Copy for every full-page state (PR 2 part A1).
 *
 * Pure and React-free on purpose: `FullPageState.tsx` reads from this table,
 * `tests/unit/fullPageStateCopy.test.ts` checks it under plain Node with no
 * DOM, and `scripts/check_copy.mjs` walks it like any other `.ts` file under
 * `src/` for the em-dash/exclamation-mark rules. Nine variants, not eight: the
 * eight `DoodleKind`s each get a real doodle, and `slow-load` (the `Mark`,
 * animated) is copy-only — it is a *duration* reading ("this is taking a
 * while"), not a distinct failure, so it has no doodle of its own.
 *
 * Every string here is the approved canvas's copy, verbatim. This file does
 * not choose wording; it only names, per variant, which of the four fixed
 * actions (`home` / `sign-in` / `reload` / `retry`) go in the primary and
 * secondary slots, and what each of those four is labelled.
 */

export type FullPageStateVariant = DoodleKind | "slow-load"

export type FullPageStateAction = "home" | "sign-in" | "reload" | "retry"

export interface FullPageStateCopy {
  /** Small kicker above the heading (`text-data-sm text-ink-faint`). Some
   * variants have none — `slow-load` — in which case the caller omits the
   * element entirely rather than rendering an empty one. */
  kicker: string
  heading: string
  body: string
  primary: FullPageStateAction | null
  secondary: FullPageStateAction | null
}

/**
 * The four action kinds every `primary`/`secondary` slot above draws from.
 * `home` and `sign-in` are role-aware/session-aware labels resolved at render
 * time in `FullPageState.tsx` ("Go to your dashboard" vs "Go to sign in" for
 * `home`, depending on whether a session exists); `reload` and `retry` are
 * fixed.
 */
export const ACTION_LABEL: Record<Exclude<FullPageStateAction, "home">, string> = {
  "sign-in": "Sign in again",
  reload: "Reload the page",
  retry: "Try again",
}

export const FULL_PAGE_STATE_COPY: Record<FullPageStateVariant, FullPageStateCopy> = {
  "not-found": {
    kicker: "404",
    heading: "We couldn't find that page",
    body: "The link may be out of date, or the address may have a typo in it. Nothing has been lost.",
    primary: "home",
    secondary: null,
  },
  crash: {
    kicker: "Error",
    heading: "Something went wrong at our end",
    body: "This page failed to load. Your work is not affected, and trying again often resolves it.",
    primary: "home",
    secondary: "reload",
  },
  offline: {
    kicker: "Offline",
    heading: "You're offline",
    body: "Lemely needs a connection to load this page. It will carry on by itself as soon as you're back online.",
    primary: null,
    secondary: "retry",
  },
  "new-version": {
    // A chunk fetch failure only means the browser could not load a piece of
    // this page — not that a deploy actually happened. `navigator.onLine`
    // (the signal `routeError.ts` gates this variant on) reads `true` behind
    // a captive portal and on flaky wifi, so asserting "a new version is
    // ready" here would often be a guess dressed up as a fact. This copy
    // describes what was actually observed and names reloading as the fix,
    // without claiming to know why loading failed.
    kicker: "Reload needed",
    heading: "This page couldn't finish loading",
    body: "Reloading usually fixes it. If Lemely was just updated, the reload picks up the new version, and nothing you typed is lost.",
    primary: "reload",
    secondary: null,
  },
  "session-ended": {
    kicker: "Signed out",
    heading: "Your session ended",
    body: "You were signed out to keep your account safe. Sign in again and we'll take you back to where you were.",
    primary: "sign-in",
    secondary: null,
  },
  "no-access": {
    kicker: "403",
    heading: "You don't have access to this page",
    body: "This page belongs to a different role. If you think you should be able to see it, ask your teacher or school admin.",
    primary: "home",
    secondary: null,
  },
  "service-trouble": {
    kicker: "Service",
    heading: "Lemely is having trouble right now",
    body: "Our service isn't answering. Your papers and results are safe. Try again in a few minutes.",
    primary: "retry",
    secondary: "home",
  },
  "too-many-requests": {
    kicker: "429",
    heading: "Slow down for a moment",
    body: "You sent more requests than Lemely can handle at once. Wait a little, then try again.",
    primary: null,
    secondary: "retry",
  },
  "slow-load": {
    kicker: "",
    heading: "Still loading",
    body: "Your connection seems slow. We're still trying, and you can reload if you'd rather start again.",
    primary: null,
    secondary: "reload",
  },
}

/** Ordered list of every variant, exactly once. The order the approved canvas
 * lists them in, and the order `dev-previews/App.tsx`'s group renders them. */
export const FULL_PAGE_STATE_VARIANTS: readonly FullPageStateVariant[] = [
  "not-found",
  "crash",
  "offline",
  "new-version",
  "session-ended",
  "no-access",
  "service-trouble",
  "too-many-requests",
  "slow-load",
]
