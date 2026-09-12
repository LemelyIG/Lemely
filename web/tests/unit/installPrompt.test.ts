import { readFileSync } from "node:fs"
import { join } from "node:path"
import { afterEach, describe, expect, it, vi } from "vitest"
import {
  clearDeferredEvent,
  DISMISS_COOLDOWN_MS,
  getDeferredEventSnapshot,
  handleBeforeInstallPrompt,
  INSTALL_DISMISS_KEY,
  isIosUserAgent,
  isStandaloneDisplay,
  isWithinCooldown,
  readDismissedAt,
  shouldShowInstallAffordance,
  subscribeToDeferredEvent,
  writeDismissedAt,
  type InstallPromptStorage,
} from "@/lib/pwa/useInstallPrompt"

/**
 * Packet A7 — install prompt / iOS install sheet.
 *
 * Same shape as `serviceWorkerUpdate.test.ts`: `useInstallPrompt` is a hook
 * (real `beforeinstallprompt` listener, real `matchMedia`, real
 * `localStorage`), unreachable under this suite's plain-Node environment (no
 * jsdom, D3.20). Every decision the hook makes is pulled out as a pure,
 * directly testable function; the hook's wiring to them is pinned as
 * source-text gates at the bottom, honestly labelled as such.
 */

describe("isIosUserAgent", () => {
  it("is true for iPhone Safari", () => {
    expect(
      isIosUserAgent(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
      ),
    ).toBe(true)
  })

  it("is true for iPad Safari", () => {
    expect(
      isIosUserAgent(
        "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
      ),
    ).toBe(true)
  })

  it("is false for Android Chrome", () => {
    expect(
      isIosUserAgent(
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
      ),
    ).toBe(false)
  })

  it("is false for desktop Chrome", () => {
    expect(
      isIosUserAgent(
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      ),
    ).toBe(false)
  })
})

describe("isStandaloneDisplay", () => {
  it("is true when the display-mode media query matches", () => {
    expect(isStandaloneDisplay({ matches: true }, undefined)).toBe(true)
  })

  it("is true when navigator.standalone is set (legacy iOS)", () => {
    expect(isStandaloneDisplay({ matches: false }, true)).toBe(true)
  })

  it("is false when neither signal is present", () => {
    expect(isStandaloneDisplay({ matches: false }, undefined)).toBe(false)
    expect(isStandaloneDisplay(null, undefined)).toBe(false)
  })
})

describe("dismissal storage", () => {
  function fakeStorage(initial: Record<string, string> = {}): InstallPromptStorage {
    const store = new Map(Object.entries(initial))
    return {
      getItem: (key) => store.get(key) ?? null,
      setItem: (key, value) => {
        store.set(key, value)
      },
    }
  }

  it("reads null when nothing is stored", () => {
    expect(readDismissedAt(fakeStorage())).toBeNull()
  })

  it("round-trips a written timestamp", () => {
    const storage = fakeStorage()
    writeDismissedAt(storage, 1_000)
    expect(readDismissedAt(storage)).toBe(1_000)
  })

  it("reads null for a malformed stored value", () => {
    expect(readDismissedAt(fakeStorage({ [INSTALL_DISMISS_KEY]: "not-a-number" }))).toBeNull()
  })

  it("degrades to null when storage throws (Safari private browsing)", () => {
    const throwing: InstallPromptStorage = {
      getItem: () => {
        throw new Error("blocked")
      },
      setItem: () => {
        throw new Error("blocked")
      },
    }
    expect(readDismissedAt(throwing)).toBeNull()
    expect(() => writeDismissedAt(throwing, Date.now())).not.toThrow()
  })

  it("degrades to null when there is no storage at all", () => {
    expect(readDismissedAt(undefined)).toBeNull()
    expect(() => writeDismissedAt(undefined, Date.now())).not.toThrow()
  })
})

describe("isWithinCooldown", () => {
  it("is false when never dismissed", () => {
    expect(isWithinCooldown(null, Date.now())).toBe(false)
  })

  it("is true just inside the 14-day cooldown", () => {
    const now = 1_000_000_000_000
    const dismissedAt = now - (DISMISS_COOLDOWN_MS - 1)
    expect(isWithinCooldown(dismissedAt, now)).toBe(true)
  })

  it("is false once the 14-day cooldown has elapsed", () => {
    const now = 1_000_000_000_000
    const dismissedAt = now - DISMISS_COOLDOWN_MS
    expect(isWithinCooldown(dismissedAt, now)).toBe(false)
  })

  it("pins the cooldown at exactly 14 days", () => {
    expect(DISMISS_COOLDOWN_MS).toBe(14 * 24 * 60 * 60 * 1000)
  })
})

describe("shouldShowInstallAffordance", () => {
  it("is true when beforeinstallprompt fired", () => {
    expect(
      shouldShowInstallAffordance({
        hasPromptEvent: true,
        isIos: false,
        isStandalone: false,
        dismissedWithinCooldown: false,
      }),
    ).toBe(true)
  })

  it("is true on iOS Safari even with no beforeinstallprompt event", () => {
    expect(
      shouldShowInstallAffordance({
        hasPromptEvent: false,
        isIos: true,
        isStandalone: false,
        dismissedWithinCooldown: false,
      }),
    ).toBe(true)
  })

  it("is false once already installed (standalone), regardless of everything else", () => {
    expect(
      shouldShowInstallAffordance({
        hasPromptEvent: true,
        isIos: true,
        isStandalone: true,
        dismissedWithinCooldown: false,
      }),
    ).toBe(false)
  })

  it("is false within the dismissal cooldown", () => {
    expect(
      shouldShowInstallAffordance({
        hasPromptEvent: true,
        isIos: false,
        isStandalone: false,
        dismissedWithinCooldown: true,
      }),
    ).toBe(false)
  })

  it("is false on a non-iOS browser with no prompt event (e.g. desktop Firefox)", () => {
    expect(
      shouldShowInstallAffordance({
        hasPromptEvent: false,
        isIos: false,
        isStandalone: false,
        dismissedWithinCooldown: false,
      }),
    ).toBe(false)
  })
})

/**
 * A7 review fix (HIGH 1) — `beforeinstallprompt` fires at most once per page
 * load, so the deferred event now lives in a module-level store shared by
 * every `useInstallPrompt()` call, rather than per-hook-instance `useState`.
 * `handleBeforeInstallPrompt`, `clearDeferredEvent`, `getDeferredEventSnapshot`
 * and `subscribeToDeferredEvent` ARE the production wiring (the real
 * `window.addEventListener("beforeinstallprompt", handleBeforeInstallPrompt)`
 * call — guarded by `typeof window !== "undefined"` for this exact plain-Node
 * suite — passes `handleBeforeInstallPrompt` straight through), so they are
 * directly testable with a fake `Event`-shaped object, no `window` required.
 */
describe("shared beforeinstallprompt store (A7 review fix HIGH 1)", () => {
  afterEach(() => {
    clearDeferredEvent()
  })

  function fakeBeforeInstallPromptEvent() {
    return {
      preventDefault: vi.fn(),
      prompt: vi.fn(),
      userChoice: Promise.resolve({ outcome: "accepted" as const }),
    } as unknown as Event
  }

  it("suppresses the browser's own mini-infobar and stashes the event", () => {
    const event = fakeBeforeInstallPromptEvent()
    handleBeforeInstallPrompt(event)
    expect(event.preventDefault).toHaveBeenCalledOnce()
    expect(getDeferredEventSnapshot()).toBe(event)
  })

  it("notifies every subscriber, not just the first to attach — the HIGH 1 bug", () => {
    const seen: string[] = []
    const unsubA = subscribeToDeferredEvent(() => seen.push("A"))
    const unsubB = subscribeToDeferredEvent(() => seen.push("B"))

    handleBeforeInstallPrompt(fakeBeforeInstallPromptEvent())

    expect(seen).toEqual(["A", "B"])
    unsubA()
    unsubB()
  })

  it("a subscriber that attaches AFTER the event already fired still reads it via the snapshot — the exact HIGH 1 regression (a lazy-loaded settings screen mounting minutes after the banner already consumed the event)", () => {
    const event = fakeBeforeInstallPromptEvent()
    handleBeforeInstallPrompt(event)

    // Simulates a second, later `useInstallPrompt()` call: subscribing does
    // not itself deliver the past event, but `useSyncExternalStore` also
    // reads `getDeferredEventSnapshot()` on mount, which is what this pins.
    expect(getDeferredEventSnapshot()).toBe(event)
  })

  it("an unsubscribed listener stops receiving notifications", () => {
    const seen: string[] = []
    const unsubscribe = subscribeToDeferredEvent(() => seen.push("x"))
    unsubscribe()

    handleBeforeInstallPrompt(fakeBeforeInstallPromptEvent())

    expect(seen).toEqual([])
  })

  it("clearDeferredEvent resets the snapshot to null and notifies subscribers", () => {
    handleBeforeInstallPrompt(fakeBeforeInstallPromptEvent())
    let notified = false
    const unsubscribe = subscribeToDeferredEvent(() => {
      notified = true
    })

    clearDeferredEvent()

    expect(getDeferredEventSnapshot()).toBeNull()
    expect(notified).toBe(true)
    unsubscribe()
  })
})

describe("useInstallPrompt source-text gates (hook body only — not exercised by a test)", () => {
  const source = readFileSync(
    join(import.meta.dirname, "..", "..", "src", "lib", "pwa", "useInstallPrompt.ts"),
    "utf8",
  )

  it("attaches the beforeinstallprompt listener once at module scope, guarded for this no-window suite", () => {
    expect(source).toMatch(/typeof window !== "undefined"/)
    expect(source).toMatch(
      /addEventListener\(\s*"beforeinstallprompt",\s*handleBeforeInstallPrompt\s*\)/,
    )
  })

  it("reads the shared deferred-event store via useSyncExternalStore — A7 review fix HIGH 1", () => {
    expect(source).toMatch(/useSyncExternalStore\(\s*subscribeToDeferredEvent/)
  })

  it("writes the dismissal timestamp when dismiss() is called", () => {
    expect(source).toMatch(/writeDismissedAt\(/)
  })

  /*
   * A7 follow-up (post-approval MEDIUM) — the shared store (HIGH 1, above)
   * lets `InstallBanner` and `InstallSettingsSection` both render a button
   * for the same reader at once. Chromium throws if `.prompt()` is called a
   * second time on an already-spent event, and without `finally` that throw
   * skipped `clearDeferredEvent()` — leaving the module-level event
   * non-null (so `canInstall` stayed true) for an event that will never
   * resolve again: the surviving button went permanently inert with no
   * feedback.
   */
  it("clears the spent event in a finally block, even if prompt()/userChoice rejects", () => {
    const fnMatch = source.match(/const promptInstall = async \(\) => \{[\s\S]*?\n  \}/)
    expect(fnMatch).not.toBeNull()
    const body = fnMatch ? fnMatch[0] : ""
    expect(body).toMatch(/finally\s*\{/)
    // clearDeferredEvent() must be inside the finally block, not just
    // present anywhere in the function.
    const finallyMatch = body.match(/finally\s*\{([\s\S]*?)\}/)
    expect(finallyMatch).not.toBeNull()
    expect(finallyMatch ? finallyMatch[1] : "").toMatch(/clearDeferredEvent\(\)/)
  })
})

/**
 * A7 review fix (MEDIUM 1) — before this fix, `shouldShowInstallAffordance`
 * was dead code: `InstallBanner.tsx` reimplemented the same show/hide
 * decision inline, and not even identically (it ordered the prompt-vs-ios
 * check before the dismissed check, rather than after). This pins that the
 * banner's gate is now the real function, not a hand-copy of it — same
 * "not exercised by a test, pinned as a source-text gate" reasoning as the
 * hook itself, since `InstallBanner` needs jsdom to render.
 */
describe("InstallBanner source-text gate — delegates its show/hide decision to shouldShowInstallAffordance (A7 review fix MEDIUM 1)", () => {
  const bannerSource = readFileSync(
    join(import.meta.dirname, "..", "..", "src", "components", "InstallBanner.tsx"),
    "utf8",
  )

  it("imports shouldShowInstallAffordance from the hook module", () => {
    expect(bannerSource).toMatch(/import\s*{[^}]*shouldShowInstallAffordance[^}]*}\s*from\s*"@\/lib\/pwa\/useInstallPrompt"/)
  })

  it("calls it to decide whether to render at all", () => {
    expect(bannerSource).toMatch(/shouldShowInstallAffordance\(\{/)
  })
})
