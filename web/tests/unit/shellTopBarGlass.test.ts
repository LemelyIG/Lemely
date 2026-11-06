import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const css = readFileSync(join(SRC, "index.css"), "utf8")
const bar = readFileSync(join(SRC, "components/shell/ShellTopBar.tsx"), "utf8")

/** The whole `@supports (backdrop-filter …) { … }` block that opens with
 * `.lm-shell-bar-glass`, braces balanced; "" when there is none. */
function glassBlock(): string {
  const start = css.search(/@supports \(backdrop-filter: blur\(1px\)\)[^{]*\{\s*@media \(min-width: 721px\)\s*\{\s*\.lm-shell-bar-glass\s*\{/)
  if (start < 0) return ""
  let depth = 0
  for (let i = css.indexOf("{", start); i < css.length; i++) {
    if (css[i] === "{") depth++
    else if (css[i] === "}" && --depth === 0) return css.slice(start, i + 1)
  }
  return ""
}

describe("the shell top bar is semi-translucent (portal shell Task 4a)", () => {
  it("ShellTopBar opts in and keeps its solid surfaces as the fallback", () => {
    expect(bar).toContain("lm-shell-bar-glass")
    expect(bar).toMatch(/\bbg-surface-container-lowest\b/)
    expect(bar).toMatch(/\bdark:bg-surface-container-high\b/)
  })

  it("the glass rules exist only inside the @supports block, floating bar only (not the flat phone bar)", () => {
    const block = glassBlock()
    expect(block).not.toBe("")
    expect(block).toContain("@media (min-width: 721px)")
    expect(css.replace(block, "")).not.toMatch(/\.lm-shell-bar-glass\s*\{/)
  })

  it("86% of the bar's light and dark surface, blurred by the one allowed radius", () => {
    const block = glassBlock()
    expect(block).toContain("color-mix(in oklch, var(--md-surface-container-lowest) 86%, transparent)")
    expect(block).toMatch(
      /\[data-theme="dark"\] \.lm-shell-bar-glass\s*\{[^}]*color-mix\(in oklch, var\(--md-surface-container-high\) 86%, transparent\)/,
    )
    expect(block).toContain("-webkit-backdrop-filter: blur(var(--blur-nav))")
    expect(block).toMatch(/(?<!-webkit-)backdrop-filter: blur\(var\(--blur-nav\)\)/)
  })
})
