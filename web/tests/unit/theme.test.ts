import { describe, expect, it } from "vitest"
import { applyTheme, themeColorFor } from "../../src/lib/theme/applyTheme.ts"
import {
  THEME_STORAGE_KEY,
  isThemePreference,
  readThemePreference,
  resolveTheme,
} from "../../src/lib/theme/theme.ts"

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
