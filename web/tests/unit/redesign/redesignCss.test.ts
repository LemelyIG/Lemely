import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const CSS_PATH = join(fileURLToPath(new URL("../../../", import.meta.url)), "src/components/redesign/redesign.css")

/** The CSS with every `@media (prefers-reduced-motion: no-preference) { … }` block removed (brace-balanced). */
export function outsideMotionBlocks(css: string): string {
  const OPEN = "@media (prefers-reduced-motion: no-preference)"
  let out = ""
  let i = 0
  while (i < css.length) {
    const at = css.indexOf(OPEN, i)
    if (at === -1) return out + css.slice(i)
    out += css.slice(i, at)
    let j = css.indexOf("{", at)
    let depth = 0
    for (; j < css.length; j++) {
      if (css[j] === "{") depth++
      else if (css[j] === "}" && --depth === 0) break
    }
    i = j + 1
  }
  return out
}

describe("redesign.css motion rule", () => {
  const css = readFileSync(CSS_PATH, "utf8").replace(/\/\*[\s\S]*?\*\//g, "")

  it("goes red on a planted animation outside the motion block", () => {
    expect(outsideMotionBlocks(".a{animation:x 1s}")).toMatch(/animation\s*:/)
    expect(outsideMotionBlocks("@media (prefers-reduced-motion: no-preference) { .a { animation: x 1s } }")).not.toMatch(/animation\s*:/)
  })

  it("declares every animation inside prefers-reduced-motion: no-preference", () => {
    expect(outsideMotionBlocks(css)).not.toMatch(/animation\s*:/)
  })

  it("uses only rd- class selectors", () => {
    const selectors = [...outsideMotionBlocks(css).matchAll(/(^|\})\s*([^{}@]+)\{/g)].map((m) => m[2].trim())
    const foreign = selectors.flatMap((s) => [...s.matchAll(/\.([a-zA-Z][\w-]*)/g)].map((m) => m[1])).filter((c) => !c.startsWith("rd-"))
    expect(foreign).toEqual([])
  })

  it("dark Binny never uses on-primary as the body (it is the dark ground's own ink, ~1.4:1)", () => {
    const dark = css.match(/:root\[data-theme="dark"\] \.rd-binny\s*\{([^}]*)\}/)
    expect(dark).not.toBeNull()
    expect(dark![1]).toMatch(/--rd-bn-body:\s*var\(--md-primary\)/)
    expect(dark![1]).toMatch(/--rd-bn-face:\s*var\(--md-on-primary\)/)
  })
})

describe("redesign.css ring colours", () => {
  const css = readFileSync(CSS_PATH, "utf8").replace(/\/\*[\s\S]*?\*\//g, "")
  const rule = (sel: string) => css.match(new RegExp(`${sel.replace(/\./g, "\\.")}\\s*\\{([^}]*)\\}`))?.[1] ?? ""
  it("keeps the default KeyRing arc on --md-primary (inverse-primary inverts to the surface in dark)", () => {
    expect(rule(".rd-ring-tone-tide")).toContain("var(--md-primary)")
    expect(css).not.toMatch(/rd-ring-[a-z-]+\s*\{[^}]*--md-inverse-primary/)
  })
  it("keeps partial GoldRing progress above the track, not on --md-outline", () => {
    expect(rule(".rd-ring-partial")).toContain("color-mix(in oklch, var(--md-on-surface-variant) 70%, var(--md-surface-container-highest))")
    expect(rule(".rd-ring-partial")).not.toContain("--md-outline")
  })
})
