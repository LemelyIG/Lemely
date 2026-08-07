/*
 * Design-token regression guards.
 *
 * Moved verbatim from `web/scripts/check-design-tokens.mjs` in P3.10 chunk e3,
 * which is exactly what that script's own header said to do once a real runner
 * existed ("If a real runner lands later, these two checks should move into it
 * verbatim and this file should go"). The script is deleted; `scripts/check.sh`
 * runs this suite in its place, so the gate count is unchanged.
 *
 * Both invariants fail *silently* in the product: no type error, no lint
 * error, no console error, no axe violation. They degrade typography to
 * whatever was inherited, which reads as "slightly off" rather than "broken",
 * so nothing else in the gate chain would ever report them.
 *
 * 1. Every custom `text-*` class we define must be classified by tailwind-merge
 *    as a FONT SIZE, not as a text COLOR. twMerge's default config knows only
 *    its own font-size names plus t-shirt-shaped suffixes; anything else
 *    beginning `text-` falls into the `text-color` group, and then
 *    `cn("text-display-md", "text-t1")` resolves as two colours in conflict and
 *    drops one. That bug was live in five shared C-* components before P3.10
 *    chunk c (trend-sparkline x2, boundary-bar, confidence-indicator,
 *    paper-identity), and the retrofit multiplied the at-risk call sites across
 *    the whole teacher portal. `lib/utils.ts` registers the names; this proves
 *    the registration actually took effect.
 *
 * 2. No arbitrary font-size / colour / radius literal may reappear in the
 *    retrofitted portals. The retrofit is only worth doing once.
 */
import { readFileSync, readdirSync, statSync } from "node:fs"
import { join, relative } from "node:path"
import { fileURLToPath } from "node:url"

import { extendTailwindMerge } from "tailwind-merge"
import { describe, expect, it } from "vitest"

const SRC = fileURLToPath(new URL("../../src/", import.meta.url))

const utils = readFileSync(join(SRC, "lib/utils.ts"), "utf8")
const block = utils.match(/CUSTOM_FONT_SIZE_CLASSES = \[([\s\S]*?)\] as const/)
const registered = block ? [...block[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]) : []

const css = readFileSync(join(SRC, "index.css"), "utf8")
const defined = new Set([
  ...[...css.matchAll(/^\.text-([a-z0-9-]+)\s*\{/gm)].map((m) => m[1]),
  ...[...css.matchAll(/^\s*--text-([a-z0-9-]+)\s*:/gm)].map((m) => m[1]),
])

describe("tailwind-merge classification of our custom type classes", () => {
  it("finds the registration block in lib/utils.ts", () => {
    // If this fails, every case below would pass vacuously over an empty list.
    expect(block, "CUSTOM_FONT_SIZE_CLASSES not found — the twMerge font-size registration is gone").not.toBeNull()
    expect(registered.length).toBeGreaterThan(0)
  })

  // Rebuilt from the *parsed* list rather than importing `cn`, so this proves
  // the registration data itself is right; `utils.test.ts` proves `cn` applies
  // it. Both halves are needed — either alone can pass while the other breaks.
  const twMerge = extendTailwindMerge({
    extend: { classGroups: { "font-size": [{ text: registered }] } },
  })

  it.each(registered)("keeps text-%s and a colour class together in both orders", (name) => {
    for (const [a, b] of [
      [`text-${name}`, "text-t1"],
      ["text-t1", `text-${name}`],
    ]) {
      const merged = twMerge(`${a} ${b}`)
      expect(merged, `twMerge("${a} ${b}") dropped a class — "text-${name}" is not registered as a font-size`)
        .toContain(a)
      expect(merged).toContain(b)
    }
  })

  it("still collapses two font sizes to the later one", () => {
    // Otherwise the registration has broken conflict resolution instead of
    // fixing classification.
    expect(twMerge("text-dense text-display-md")).toBe("text-display-md")
  })
})

describe("lib/utils.ts and index.css agree in both directions", () => {
  // Forgetting to register a newly added class is the dangerous direction (it
  // reintroduces the silent-drop bug); registering a name with no class behind
  // it is just dead config — but either way the two have drifted.
  it.each(registered)('index.css defines the registered class "text-%s"', (name) => {
    expect(defined.has(name), `lib/utils.ts registers "text-${name}", but index.css defines no such class or theme key`)
      .toBe(true)
  })

  it.each([...defined])('lib/utils.ts registers the defined class "text-%s"', (name) => {
    expect(
      registered.includes(name),
      `index.css defines "text-${name}", but lib/utils.ts does not register it as a font-size — cn() will treat it ` +
        `as a text COLOR and silently drop it or the colour beside it`,
    ).toBe(true)
  })
})

describe("no arbitrary literals in the retrofitted portals", () => {
  // `portals/student/` is deliberately absent: only its shell (index.tsx) was
  // retrofitted in P3.10 chunk c. Its screens still carry ~120 literals, which
  // is recorded as measured debt in BUILD/STATE.md rather than silently
  // claimed as clean here.
  const RETROFITTED = ["portals/teacher", "portals/parent", "components", "portals/student/index.tsx"]
  const BANNED: [RegExp, string][] = [
    [/\btext-\[[0-9.]+px\]/g, "arbitrary font size"],
    [/\brounded-\[[0-9.]+px\]/g, "arbitrary border radius"],
    [/oklch\(/g, "raw oklch colour"],
    [/#[0-9a-fA-F]{6}\b/g, "raw hex colour"],
  ]

  function* walk(dir: string): Generator<string> {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry)
      if (statSync(full).isDirectory()) yield* walk(full)
      else if (/\.tsx?$/.test(full)) yield full
    }
  }

  const files = RETROFITTED.flatMap((target) => {
    const full = join(SRC, target)
    return statSync(full).isDirectory() ? [...walk(full)] : [full]
  })

  it("has files to scan", () => {
    // Same vacuity guard as above: a mistyped path in RETROFITTED would
    // otherwise make this whole suite pass by scanning nothing.
    expect(files.length).toBeGreaterThan(0)
  })

  it.each(files.map((f) => [relative(SRC, f), f] as const))("%s uses tokens, not literals", (_label, file) => {
    const text = readFileSync(file, "utf8")
    const found: string[] = []
    for (const [pattern, label] of BANNED) {
      for (const match of text.matchAll(pattern)) {
        const line = text.slice(0, match.index).split("\n").length
        found.push(`:${line}  ${label} "${match[0]}" — use a token from index.css`)
      }
    }
    expect(found).toEqual([])
  })
})
