import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * Source-text pins for Task 13 (C5b) that a pure-logic unit test can't
 * otherwise reach: `shell-init.js` is plain ES5 run before any bundle exists
 * (no `theme.ts` import possible — see that file's own comment), and
 * `index.css`/`ProfileSettings.tsx`/`storage.ts` are asserted here rather
 * than through jsdom because this runner has none (`vitest.config.ts`'s own
 * header) — these are repo invariants, not component behaviour, which is
 * the Playwright suite's job (`e2e/theme.spec.ts`).
 */

const ROOT = join(import.meta.dirname, "..", "..")

describe("shell-init.js: flash-free theme init", () => {
  const source = readFileSync(join(ROOT, "public/shell-init.js"), "utf8")

  it("reads the theme storage key", () => {
    expect(source).toContain("lemely.theme")
  })

  it("resolves against the OS dark-mode media query", () => {
    expect(source).toContain("prefers-color-scheme: dark")
  })

  it("sets data-theme via the dataset API", () => {
    expect(source).toContain("dataset.theme")
  })

  it("reads the meta's dark theme-color attribute", () => {
    expect(source).toContain("data-theme-dark")
  })

  it("is wrapped in a try block — localStorage and matchMedia can both throw", () => {
    expect(source).toContain("try {")
  })

  it("implements the same three-way resolveTheme table theme.ts pins in code", () => {
    // Pins shell-init.js's inline table against theme.ts's resolveTheme so
    // the two cannot silently diverge: stored "light"/"dark" win outright,
    // anything else falls back to the OS signal.
    expect(source).toMatch(/storedTheme === "light"/)
    expect(source).toMatch(/storedTheme === "dark"/)
    expect(source).toMatch(/prefersDark \? "dark" : "light"/)
  })
})

describe("index.html: theme-color meta carries both resolved-colour attributes", () => {
  const html = readFileSync(join(ROOT, "index.html"), "utf8")

  it("declares data-theme-light on the theme-color meta", () => {
    expect(html).toMatch(/<meta[\s\S]*?name="theme-color"[\s\S]*?data-theme-light=/)
  })

  it("declares data-theme-dark on the theme-color meta", () => {
    expect(html).toMatch(/<meta[\s\S]*?name="theme-color"[\s\S]*?data-theme-dark=/)
  })
})

describe("index.css: data-theme is the single theme switch", () => {
  const css = readFileSync(join(ROOT, "src/index.css"), "utf8")

  it("has no prefers-color-scheme media query anywhere", () => {
    // Deliberate deviation from a two-selector spec (media query + data
    // attribute): one ladder, one switch, no drift between what an
    // unauthenticated OS-only reader sees and what the toggle produces — see
    // Task 13's own behaviour 4. The pre-mount shell and the theme-color meta
    // also both need the attribute regardless, so the media query would be a
    // second mechanism for the same decision.
    expect(css).not.toMatch(/prefers-color-scheme/)
  })

  it("still declares exactly one dark token block", () => {
    const matches = css.match(/:root\[data-theme="dark"\]\s*\{/g) ?? []
    expect(matches).toHaveLength(1)
  })
})

describe("ProfileSettings.tsx: Appearance setting", () => {
  it("names the Appearance section", () => {
    const source = readFileSync(join(ROOT, "src/portals/settings/ProfileSettings.tsx"), "utf8")
    expect(source).toContain("Appearance")
  })
})

describe("storage.ts: endSession does not clear the theme preference", () => {
  const source = readFileSync(join(ROOT, "src/lib/auth/storage.ts"), "utf8")

  it("endSession's body references neither THEME_STORAGE_KEY nor the lemely.theme literal", () => {
    const start = source.indexOf("export function endSession")
    expect(start).toBeGreaterThan(-1)
    const end = source.indexOf("\n}", start)
    expect(end).toBeGreaterThan(start)
    const body = source.slice(start, end)
    expect(body).not.toContain("THEME_STORAGE_KEY")
    expect(body).not.toContain("lemely.theme")
  })
})
