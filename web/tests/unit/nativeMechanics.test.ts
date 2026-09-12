import { readFileSync, readdirSync, statSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"

import { describe, expect, it } from "vitest"

/**
 * Native touch, viewport and safe-area mechanics (A1). Reads the built
 * sources as text, the same pattern `fontPreload.test.ts` uses for
 * `index.html` — these are CSS/meta invariants with no runtime to exercise.
 */

const ROOT = fileURLToPath(new URL("../../", import.meta.url))
const SRC = join(ROOT, "src")

const html = readFileSync(join(ROOT, "index.html"), "utf8")
const css = readFileSync(join(SRC, "index.css"), "utf8")

describe("viewport meta", () => {
  it("declares viewport-fit=cover and interactive-widget=resizes-content", () => {
    expect(html).toContain(
      '<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover, interactive-widget=resizes-content" />',
    )
  })
})

describe("html, body base rule", () => {
  const match = css.match(/html,\s*body\s*\{([\s\S]*?)\}/)

  it("exists", () => {
    expect(match).not.toBeNull()
  })

  const body = match ? match[1] : ""

  it("keeps overflow-x: clip", () => {
    expect(body).toContain("overflow-x: clip")
  })

  it("disables the tap-highlight flash", () => {
    expect(body).toContain("-webkit-tap-highlight-color: transparent")
  })

  it("contains rubber-band scroll to the page's own axis", () => {
    expect(body).toContain("overscroll-behavior-y: contain")
  })
})

describe("(pointer: coarse) touch-action", () => {
  const match = css.match(/@media \(pointer: coarse\) \{([\s\S]*)/)

  it("adds touch-action: manipulation to the existing 44px selector list", () => {
    expect(match).not.toBeNull()
    const block = match ? match[1] : ""
    const firstRule = block.match(/textarea\s*\{([\s\S]*?)\}/)
    expect(firstRule).not.toBeNull()
    expect(firstRule ? firstRule[1] : "").toContain("touch-action: manipulation")
  })
})

describe(".lm-scroll", () => {
  it("contains overscroll-behavior: contain", () => {
    const match = css.match(/\.lm-scroll\s*\{([\s\S]*?)\}/)
    expect(match).not.toBeNull()
    expect(match ? match[1] : "").toContain("overscroll-behavior: contain")
  })
})

describe("--fs-field token", () => {
  it("is defined at 16px", () => {
    expect(css).toContain("--fs-field: 16px")
  })
})

describe("text-field utility on native form fields", () => {
  const input = readFileSync(join(SRC, "components/ui/input.tsx"), "utf8")
  const textarea = readFileSync(join(SRC, "components/ui/textarea.tsx"), "utf8")

  it("input.tsx uses text-field, not text-body-md, on the native element", () => {
    expect(input).toContain("text-field")
    expect(input).not.toContain("text-body-md")
  })

  it("textarea.tsx uses text-field, not text-body-md, on the native element", () => {
    expect(textarea).toContain("text-field")
    expect(textarea).not.toContain("text-body-md")
  })
})

describe("safe-area insets", () => {
  it("index.css uses env(safe-area-inset-*) at least once", () => {
    expect(css).toMatch(/env\(safe-area-inset-/)
  })

  it("index.css gates standalone-only chrome behind @media (display-mode: standalone)", () => {
    expect(css).toContain("@media (display-mode: standalone)")
  })
})

describe(".lm-app-header standalone inset is additive, not destructive", () => {
  // Unlayered CSS beats a layered Tailwind utility (py-4, py-2.5) regardless
  // of specificity, so a bare `padding-top: env(...)` here would zero out a
  // header's existing padding-top instead of adding to it. The fix reads a
  // custom property with a 0px fallback in both rules, so a header that
  // never sets the property is unaffected and one that does gets base + inset.
  const blocks = [...css.matchAll(/\.lm-app-header\s*\{([\s\S]*?)\}/g)].map((m) => m[1])

  it("declares exactly a base rule and a standalone rule", () => {
    expect(blocks.length).toBe(2)
  })

  it("the base rule reads --lm-app-header-pt instead of a fixed value", () => {
    expect(blocks[0]).toContain("padding-top: var(--lm-app-header-pt, 0px)")
  })

  it("the standalone rule adds the safe-area inset to the custom property", () => {
    expect(blocks[1]).toContain(
      "padding-top: calc(var(--lm-app-header-pt, 0px) + env(safe-area-inset-top))",
    )
  })
})

describe(".lm-app-header-pt-* named utilities", () => {
  // §14 rule 3 forbids an arbitrary value, and an inline `style` prop setting
  // a raw spacing literal is the same violation in a different syntax — the
  // .lm-safe-bottom utility a few lines below this one in index.css exists
  // for exactly this reason. Named classes instead, matching how Tailwind's
  // own `py-4`/`py-2.5` resolve their spacing.
  it("index.css defines lm-app-header-pt-4 and lm-app-header-pt-2\\.5 off the --spacing scale", () => {
    expect(css).toContain(".lm-app-header-pt-4 {")
    expect(css).toContain("--lm-app-header-pt: calc(var(--spacing) * 4)")
    expect(css).toContain(".lm-app-header-pt-2\\.5 {")
    expect(css).toContain("--lm-app-header-pt: calc(var(--spacing) * 2.5)")
  })
})

describe("headers keep their existing padding while opting into the additive inset", () => {
  function headerLine(file: string): string {
    const source = readFileSync(join(SRC, file), "utf8")
    const line = source.split("\n").find((l) => l.includes("lm-app-header"))
    expect(line, `${file}: no line contains lm-app-header`).toBeDefined()
    return line ?? ""
  }

  it("student's header replaces py-4 with pb-4 and lm-app-header-pt-4, no inline style", () => {
    const line = headerLine("portals/student/index.tsx")
    expect(line).toContain("pb-4")
    expect(line).not.toMatch(/(?<!p)\bpy-4\b/)
    expect(line).toContain("lm-app-header-pt-4")
    const source = readFileSync(join(SRC, "portals/student/index.tsx"), "utf8")
    expect(source).not.toContain("--lm-app-header-pt")
  })

  it("teacher's header replaces py-2.5 with pb-2.5 and lm-app-header-pt-2.5, no inline style", () => {
    const line = headerLine("portals/teacher/index.tsx")
    expect(line).toContain("pb-2.5")
    expect(line).not.toMatch(/\bpy-2\.5\b/)
    expect(line).toContain("lm-app-header-pt-2.5")
    const source = readFileSync(join(SRC, "portals/teacher/index.tsx"), "utf8")
    expect(source).not.toContain("--lm-app-header-pt")
  })

  it("admin's header replaces py-2.5 with pb-2.5 and lm-app-header-pt-2.5, no inline style", () => {
    const line = headerLine("portals/admin/index.tsx")
    expect(line).toContain("pb-2.5")
    expect(line).not.toMatch(/\bpy-2\.5\b/)
    expect(line).toContain("lm-app-header-pt-2.5")
    const source = readFileSync(join(SRC, "portals/admin/index.tsx"), "utf8")
    expect(source).not.toContain("--lm-app-header-pt")
  })

  it("marketing's header is untouched — it had no py-* to lose", () => {
    const line = headerLine("portals/marketing/index.tsx")
    expect(line).not.toContain("lm-app-header-pt")
  })
})

describe("lm-nav-chrome coverage", () => {
  const CHROME_FILES = [
    "components/ui/nav-drawer.tsx",
    "components/ui/nav-shells.tsx",
    "portals/student/index.tsx",
    "portals/teacher/index.tsx",
    "portals/admin/index.tsx",
    "portals/marketing/index.tsx",
  ]

  it.each(CHROME_FILES)("%s applies lm-nav-chrome", (file) => {
    const source = readFileSync(join(SRC, file), "utf8")
    expect(source).toContain("lm-nav-chrome")
  })

  it("nav-drawer.tsx applies it to both the dialog panel and the trigger", () => {
    const source = readFileSync(join(SRC, "components/ui/nav-drawer.tsx"), "utf8")
    const count = (source.match(/lm-nav-chrome/g) ?? []).length
    expect(count).toBe(2)
  })
})

describe("apple-mobile-web-app-status-bar-style", () => {
  it("is declared as default, not black-translucent", () => {
    expect(html).toContain(
      '<meta name="apple-mobile-web-app-status-bar-style" content="default" />',
    )
  })
})

describe("min-h-dvh alone, no min-h-screen fallback", () => {
  // dvh has been baseline-supported (Safari 15.4+, Chrome 108+) for years by
  // 2026, so pairing it with a min-h-screen "fallback" bought nothing — worse,
  // it was a silent no-op: Tailwind v4 emits `.min-h-screen` after
  // `.min-h-dvh` in its own sorted utilities output regardless of source
  // order, both are single-class selectors at equal specificity with neither
  // behind @media/@supports, and later-in-cascade wins at equal specificity.
  // `.min-h-screen`'s 100vh always applied; `.min-h-dvh` never did anything.
  function* walk(dir: string): Generator<string> {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry)
      if (statSync(full).isDirectory()) yield* walk(full)
      else if (/\.tsx?$/.test(full)) yield full
    }
  }

  const offenders: string[] = []
  for (const file of walk(SRC)) {
    const text = readFileSync(file, "utf8")
    text.split("\n").forEach((line, i) => {
      if (!line.includes("min-h-screen")) return
      if (line.includes("<aside")) return
      const trimmed = line.trim()
      // Prose in JSDoc/// comments quotes `min-h-screen` as a class name
      // without applying it — not a live class list to flag.
      if (trimmed.startsWith("*") || trimmed.startsWith("//")) return
      offenders.push(`${file.slice(SRC.length + 1)}:${i + 1}`)
    })
  }

  it("has no class-list min-h-screen left outside an <aside> sidebar", () => {
    expect(offenders).toEqual([])
  })

  const DVH_SITES = [
    "components/route-error.tsx",
    "portals/misc/FullPageState.tsx",
    "portals/parent/index.tsx",
    "portals/auth/Login.tsx",
    "portals/student/index.tsx",
    "portals/settings/SettingsFrame.tsx",
    "portals/teacher/index.tsx",
    "portals/admin/index.tsx",
    "portals/marketing/index.tsx",
  ]

  it.each(DVH_SITES)("%s still sizes with min-h-dvh", (file) => {
    const source = readFileSync(join(SRC, file), "utf8")
    expect(source).toContain("min-h-dvh")
  })
})
