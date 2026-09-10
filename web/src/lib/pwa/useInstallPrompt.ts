import { useEffect, useState } from "react"

/*
 * Packet A7 — install prompt and iOS install sheet (the
 * `no-install-affordance` / `emp-beforeinstallprompt-not-observed` ledger
 * findings).
 *
 * Chromium fires `beforeinstallprompt` and lets a page defer/replay it
 * (`.prompt()`) later, on its own button. iOS Safari never fires that event
 * at all — the *only* install path there is the OS share sheet's "Add to
 * Home Screen", so `isIos` exists to switch the UI to instructions instead
 * of a button that would never do anything.
 */

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>
}

export interface InstallPromptState {
  /** True once a real, replayable `beforeinstallprompt` event is stashed. */
  canInstall: boolean
  promptInstall: () => Promise<void>
  /** UA fact — iOS Safari/WebKit, which never fires `beforeinstallprompt`. */
  isIos: boolean
  isStandalone: boolean
  /** True while within the 14-day post-dismissal cooldown. */
  dismissed: boolean
  dismiss: () => void
}

export const INSTALL_DISMISS_KEY = "lemely.installPromptDismissedAt"

/** 14 days — long enough not to nag on every visit, short enough that a
 * reader who changes their mind isn't locked out for good. */
export const DISMISS_COOLDOWN_MS = 14 * 24 * 60 * 60 * 1000

/** The slice of `Storage` this module uses, so a test can pass a two-method
 * fake rather than implementing the whole interface — same shape
 * `verifyEmailDismissal.ts`'s `BannerStorage` already uses. */
export type InstallPromptStorage = Pick<Storage, "getItem" | "setItem">

/** Every access is wrapped: Safari private browsing and a full storage
 * quota both make storage throw, and a throw here must never be the reason
 * the banner fails to render — it degrades to "never dismissed", which is a
 * strictly better failure than a blank app. */
export function readDismissedAt(storage: InstallPromptStorage | undefined): number | null {
  if (!storage) return null
  try {
    const raw = storage.getItem(INSTALL_DISMISS_KEY)
    if (raw === null) return null
    const parsed = Number(raw)
    return Number.isFinite(parsed) ? parsed : null
  } catch {
    return null
  }
}

export function writeDismissedAt(storage: InstallPromptStorage | undefined, at: number): void {
  if (!storage) return
  try {
    storage.setItem(INSTALL_DISMISS_KEY, String(at))
  } catch {
    // Deliberately empty. See the module header.
  }
}

export function isWithinCooldown(dismissedAt: number | null, now: number): boolean {
  if (dismissedAt === null) return false
  return now - dismissedAt < DISMISS_COOLDOWN_MS
}

/** iPadOS 13+ identifies as desktop Safari by default (no "iPad" in the UA),
 * but `beforeinstallprompt` still never fires there either — out of scope
 * for a UA string alone to catch; `isStandaloneDisplay` plus the real
 * `beforeinstallprompt` listener are what carry that case instead. */
export function isIosUserAgent(userAgent: string): boolean {
  return /iP(hone|ad|od)/.test(userAgent)
}

/** `display-mode: standalone` is the standard signal; `navigator.standalone`
 * is Safari's pre-standard boolean, present only there. Either one means
 * "already installed and running as an app". */
export function isStandaloneDisplay(
  mediaQuery: { matches: boolean } | null,
  navigatorStandalone: boolean | undefined,
): boolean {
  return Boolean(mediaQuery?.matches) || Boolean(navigatorStandalone)
}

export interface InstallPromptDecisionInput {
  hasPromptEvent: boolean
  isIos: boolean
  isStandalone: boolean
  dismissedWithinCooldown: boolean
}

/** Whether to show any install affordance (banner, settings entry) at all.
 * `canInstall` on the hook's own return is `hasPromptEvent && !dismissed` —
 * this is the broader question a caller like `InstallBanner` asks, since
 * iOS has no real "prompt" to gate on and shows instructions instead. */
export function shouldShowInstallAffordance(input: InstallPromptDecisionInput): boolean {
  if (input.isStandalone) return false
  if (input.dismissedWithinCooldown) return false
  return input.hasPromptEvent || input.isIos
}

export function useInstallPrompt(): InstallPromptState {
  const [deferredEvent, setDeferredEvent] = useState<BeforeInstallPromptEvent | null>(null)
  const [dismissedAt, setDismissedAt] = useState<number | null>(() =>
    readDismissedAt(typeof window === "undefined" ? undefined : window.localStorage),
  )

  useEffect(() => {
    const onBeforeInstallPrompt = (event: Event) => {
      // Stops Chromium's own default mini-infobar; this hook owns presenting
      // the affordance instead (`InstallBanner`/`InstallSettings`).
      event.preventDefault()
      setDeferredEvent(event as BeforeInstallPromptEvent)
    }
    window.addEventListener("beforeinstallprompt", onBeforeInstallPrompt)
    return () => window.removeEventListener("beforeinstallprompt", onBeforeInstallPrompt)
  }, [])

  const isIos = isIosUserAgent(window.navigator.userAgent)
  const isStandalone = isStandaloneDisplay(
    window.matchMedia?.("(display-mode: standalone)") ?? null,
    (window.navigator as Navigator & { standalone?: boolean }).standalone,
  )
  const dismissed = isWithinCooldown(dismissedAt, Date.now())

  const promptInstall = async () => {
    if (!deferredEvent) return
    await deferredEvent.prompt()
    await deferredEvent.userChoice
    // Spent either way — a browser never replays the same event twice.
    setDeferredEvent(null)
  }

  const dismiss = () => {
    const now = Date.now()
    writeDismissedAt(window.localStorage, now)
    setDismissedAt(now)
  }

  return {
    canInstall: deferredEvent !== null && !dismissed,
    promptInstall,
    isIos,
    isStandalone,
    dismissed,
    dismiss,
  }
}
