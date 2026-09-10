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

describe("min-h-screen always pairs with min-h-dvh", () => {
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
      // without applying it; only a real class list needs the dvh pairing.
      if (trimmed.startsWith("*") || trimmed.startsWith("//")) return
      if (!line.includes("min-h-dvh")) {
        offenders.push(`${file.slice(SRC.length + 1)}:${i + 1}`)
      }
    })
  }

  it("has no bare min-h-screen outside an <aside> sidebar", () => {
    expect(offenders).toEqual([])
  })
})
