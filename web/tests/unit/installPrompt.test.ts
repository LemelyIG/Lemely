import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import {
  DISMISS_COOLDOWN_MS,
  INSTALL_DISMISS_KEY,
  isIosUserAgent,
  isStandaloneDisplay,
  isWithinCooldown,
  readDismissedAt,
  shouldShowInstallAffordance,
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

describe("useInstallPrompt source-text gates (hook body only — not exercised by a test)", () => {
  const source = readFileSync(
    join(import.meta.dirname, "..", "..", "src", "lib", "pwa", "useInstallPrompt.ts"),
    "utf8",
  )

  it("prevents the browser's own mini-infobar and stashes the event", () => {
    expect(source).toMatch(/event\.preventDefault\(\)/)
  })

  it("listens for beforeinstallprompt", () => {
    expect(source).toMatch(/addEventListener\(\s*"beforeinstallprompt"/)
  })

  it("writes the dismissal timestamp when dismiss() is called", () => {
    expect(source).toMatch(/writeDismissedAt\(/)
  })
})
