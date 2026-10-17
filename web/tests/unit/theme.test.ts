import { describe, expect, it } from "vitest"
import { applyTheme, themeColorFor } from "../../src/lib/theme/applyTheme.ts"
import {
  THEME_STORAGE_KEY,
  isThemePreference,
  readThemePreference,
  resolveTheme,
} from "../../src/lib/theme/theme.ts"
import { themeStore } from "../../src/lib/theme/useTheme.ts"

/*
 * The pure logic behind the Appearance setting (Phase C, task C5b). No jsdom
 * in this runner (`vitest.config.ts`'s own header: pure logic and repo
 * invariants only, real DOM behaviour is the Playwright suite's job) — so
 * `applyTheme`/`themeColorFor` below are exercised against plain stand-in
 * objects that only carry the two properties (`dataset`, `content`) those
 * functions actually touch, not a real `HTMLElement`/`HTMLMetaElement`.
 */

describe("THEME_STORAGE_KEY", () => {
  it("is the documented localStorage key", () => {
    expect(THEME_STORAGE_KEY).toBe("lemely.theme")
  })
})

describe("isThemePreference", () => {
  it("accepts the three valid preferences", () => {
    expect(isThemePreference("system")).toBe(true)
    expect(isThemePreference("light")).toBe(true)
    expect(isThemePreference("dark")).toBe(true)
  })

  it("rejects anything else", () => {
    expect(isThemePreference("purple")).toBe(false)
    expect(isThemePreference("")).toBe(false)
    expect(isThemePreference(null)).toBe(false)
    expect(isThemePreference(undefined)).toBe(false)
    expect(isThemePreference(1)).toBe(false)
    expect(isThemePreference({})).toBe(false)
  })
})

describe("readThemePreference", () => {
  it("defaults to system for null", () => {
    expect(readThemePreference(null)).toBe("system")
  })

  it("defaults to system for garbage", () => {
    expect(readThemePreference("purple")).toBe("system")
    expect(readThemePreference("")).toBe("system")
    expect(readThemePreference("Dark")).toBe("system") // case-sensitive
  })

  it("passes through a valid stored preference", () => {
    expect(readThemePreference("system")).toBe("system")
    expect(readThemePreference("light")).toBe("light")
    expect(readThemePreference("dark")).toBe("dark")
  })
})

describe("resolveTheme", () => {
  it('resolves "system" against the OS signal', () => {
    expect(resolveTheme("system", true)).toBe("dark")
    expect(resolveTheme("system", false)).toBe("light")
  })

  it("an explicit preference wins over the OS signal either way", () => {
    expect(resolveTheme("light", true)).toBe("light")
    expect(resolveTheme("dark", false)).toBe("dark")
  })
})

/** A stand-in for `HTMLMetaElement`, carrying only what `themeColorFor`/
 * `applyTheme` read or write: `dataset` (`data-theme-light`/`data-theme-dark`,
 * as `themeLight`/`themeDark`) and `content`. */
function fakeMeta(themeLight?: string, themeDark?: string) {
  return {
    dataset: { themeLight, themeDark } as DOMStringMap,
    content: "",
  } as unknown as HTMLMetaElement
}

function fakeRoot() {
  return { dataset: {} as DOMStringMap } as unknown as HTMLElement
}

describe("themeColorFor", () => {
  it("returns undefined for a null meta", () => {
    expect(themeColorFor(null, "dark")).toBeUndefined()
  })

  it("reads data-theme-light for the light theme", () => {
    const meta = fakeMeta("#f8f7f4", "#141312")
    expect(themeColorFor(meta, "light")).toBe("#f8f7f4")
  })

  it("reads data-theme-dark for the dark theme", () => {
    const meta = fakeMeta("#f8f7f4", "#141312")
    expect(themeColorFor(meta, "dark")).toBe("#141312")
  })
})

describe("applyTheme", () => {
  it("sets root.dataset.theme to the resolved theme", () => {
    const root = fakeRoot()
    applyTheme(root, null, "dark")
    expect(root.dataset.theme).toBe("dark")
  })

  it("sets the meta's content from data-theme-dark in dark", () => {
    const root = fakeRoot()
    const meta = fakeMeta("#f8f7f4", "#141312")
    applyTheme(root, meta, "dark")
    expect(root.dataset.theme).toBe("dark")
    expect(meta.content).toBe("#141312")
  })

  it("sets the meta's content from data-theme-light in light", () => {
    const root = fakeRoot()
    const meta = fakeMeta("#f8f7f4", "#141312")
    applyTheme(root, meta, "light")
    expect(meta.content).toBe("#f8f7f4")
  })

  it("tolerates a null meta", () => {
    const root = fakeRoot()
    expect(() => applyTheme(root, null, "dark")).not.toThrow()
    expect(root.dataset.theme).toBe("dark")
  })
})

/*
 * The shared external store behind `useTheme` (C5 review fix). Two
 * independent `useState` instances — `ThemeSync` (mounted app-wide) and
 * `ProfileSettingsSection`'s Appearance fieldset (mounted only while
 * settings is open) — used to each hold their own copy of the preference,
 * so an explicit choice made through one never reached the other, and a
 * later OS change silently overrode it via the other's still-"system"
 * listener. This is the same failure a plain `useState` always has for
 * cross-instance state: no shared source of truth. `useSyncExternalStore`
 * needs a real render to exercise end-to-end (this repo's unit runner has
 * no jsdom — see the header above), so these tests exercise the extracted
 * store logic (`subscribe`/`getPreferenceSnapshot`/`setPreference`/
 * `handleStorageEvent`) directly, in isolation from React. `useTheme`
 * itself — the `useSyncExternalStore` wiring and the `applyTheme` layout
 * effect — is covered by `theme.spec.ts`'s e2e suite in a real browser.
 */
describe("themeStore (the shared store behind every useTheme() instance)", () => {
  it("notifies every subscribed listener when the preference changes", () => {
    themeStore.setPreference("light") // known baseline; a no-op change does not notify
    const calls: string[] = []
    const unsubA = themeStore.subscribe(() => calls.push("a"))
    const unsubB = themeStore.subscribe(() => calls.push("b"))

    themeStore.setPreference("dark")

    expect(calls).toEqual(["a", "b"])
    unsubA()
    unsubB()
  })

  it("getPreferenceSnapshot reflects the latest setPreference call", () => {
    themeStore.setPreference("light")
    expect(themeStore.getPreferenceSnapshot()).toBe("light")

    themeStore.setPreference("dark")
    expect(themeStore.getPreferenceSnapshot()).toBe("dark")

    themeStore.setPreference("system")
    expect(themeStore.getPreferenceSnapshot()).toBe("system")
  })

  it("a simulated storage event from another tab updates the snapshot and notifies subscribers", () => {
    themeStore.setPreference("light")
    const calls: string[] = []
    const unsub = themeStore.subscribe(() => calls.push(themeStore.getPreferenceSnapshot()))

    themeStore.handleStorageEvent({ key: THEME_STORAGE_KEY, newValue: "dark" })

    expect(themeStore.getPreferenceSnapshot()).toBe("dark")
    expect(calls).toEqual(["dark"])
    unsub()
  })

  it("ignores a storage event for an unrelated key", () => {
    themeStore.setPreference("light")
    const calls: string[] = []
    const unsub = themeStore.subscribe(() => calls.push("notified"))

    themeStore.handleStorageEvent({ key: "some.other.key", newValue: "dark" })

    expect(themeStore.getPreferenceSnapshot()).toBe("light")
    expect(calls).toEqual([])
    unsub()
  })

  it("a storage event carrying an invalid value falls back to system, same as readThemePreference", () => {
    themeStore.setPreference("dark")
    themeStore.handleStorageEvent({ key: THEME_STORAGE_KEY, newValue: "purple" })
    expect(themeStore.getPreferenceSnapshot()).toBe("system")
  })

  it("stops notifying once unsubscribed", () => {
    themeStore.setPreference("light")
    const calls: string[] = []
    const unsub = themeStore.subscribe(() => calls.push("notified"))
    unsub()

    themeStore.setPreference("dark")

    expect(calls).toEqual([])
  })
})
