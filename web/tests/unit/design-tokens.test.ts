import { readFileSync, readdirSync, statSync } from "node:fs"
import { join, relative } from "node:path"
import { fileURLToPath } from "node:url"

import { extendTailwindMerge } from "tailwind-merge"
import { describe, expect, it } from "vitest"

const SRC = fileURLToPath(new URL("../../src/", import.meta.url))

const css = readFileSync(join(__dirname, "../../src/index.css"), "utf8")
const design = readFileSync(join(__dirname, "../../../DESIGN.md"), "utf8")
const front = design.split("---")[1].split("\ntypography:")[0]
const roles = [...front.matchAll(/^  ([a-z0-9-]+): "/gm)]
  .map((m) => m[1])
  .filter((k) => !k.startsWith("dark-") && !k.startsWith("grade-") && !k.startsWith("binny-"))
  .filter((k) => !["abyss", "abyss-hover", "abyss-lip", "tide", "tide-hover", "mist-blue", "night", "white", "gold", "crimson", "crimson-on-dark", "shadow"].includes(k))

describe("token layer", () => {
  it.each(roles)("exposes --color-%s as a utility", (role) => {
    expect(css).toContain(`--color-${role}: var(--md-${role})`)
  })

  it("declares a dark value for every light role", () => {
    const light = new Set([...css.split(':root[data-theme="dark"]')[0].matchAll(/--md-([a-z0-9-]+):/g)].map((m) => m[1]))
    const dark = new Set([...css.split(':root[data-theme="dark"]')[1].split("}")[0].matchAll(/--md-([a-z0-9-]+):/g)].map((m) => m[1]))
    for (const role of ["scrim", "shadow"]) light.delete(role)
    expect([...light].filter((r) => !dark.has(r))).toEqual([])
  })

  it("loads no retired face", () => {
    for (const face of ["newsreader", "geist", "caveat"]) expect(css.toLowerCase()).not.toContain(face)
  })
})

/*
 * The composite type classes are unlayered, so any `color` they declare beats
 * every Tailwind text-colour utility beside them. `.text-metadata` once carried
 * `color: on-surface-variant` and painted the BottomNav badge grey on crimson
 * (1.16:1). Type classes set type only; colour comes from a utility.
 */
const TYPE_CLASS = /^\.(?:text-(?:display|body|label|eyebrow|data|metadata|field)[\w-]*|btn-text[\w-]*|wordmark-letters)$/

export function colouredTypeClasses(source: string): string[] {
  const hits: string[] = []
  for (const m of source.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = m[1].split(",").map((s) => s.trim().split("\n").pop()!.trim())
    if (!/(?:^|;|\s)color\s*:/.test(m[2])) continue
    hits.push(...selectors.filter((s) => TYPE_CLASS.test(s)))
  }
  return hits
}

describe("composite type classes are colourless", () => {
  it("catches a planted colour (proves the guard can go red)", () => {
    expect(colouredTypeClasses(".text-metadata {\n  font: 500 11px/1.2 x;\n  color: red;\n}")).toEqual([".text-metadata"])
    expect(colouredTypeClasses(".text-metadata {\n  background-color: red;\n}")).toEqual([])
  })

  it("finds no colour declared on a type class in index.css", () => {
    expect(colouredTypeClasses(css)).toEqual([])
  })
})

/*
 * twMerge classification guard. Every custom `text-*` font-size class must be
 * registered in lib/utils.ts, or cn() treats it as a text COLOUR and silently
 * drops it (or the colour beside it). Checked in both directions.
 */
const utils = readFileSync(join(SRC, "lib/utils.ts"), "utf8")
const block = utils.match(/CUSTOM_FONT_SIZE_CLASSES = \[([\s\S]*?)\] as const/)
const registered = block ? [...block[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]) : []
const defined = new Set([
  ...[...css.matchAll(/^\.text-([a-z0-9-]+)\s*\{/gm)].map((m) => m[1]),
  ...[...css.matchAll(/^\s*--text-([a-z0-9-]+)\s*:/gm)].map((m) => m[1]),
])

describe("tailwind-merge classification of our custom type classes", () => {
  it("finds the registration block in lib/utils.ts", () => {
    expect(block, "CUSTOM_FONT_SIZE_CLASSES not found").not.toBeNull()
    expect(registered.length).toBeGreaterThan(0)
  })

  const twMerge = extendTailwindMerge({
    extend: { classGroups: { "font-size": [{ text: registered }] } },
  })

  it.each(registered)("keeps text-%s and a colour class together in both orders", (name) => {
    for (const [a, b] of [
      [`text-${name}`, "text-on-surface"],
      ["text-on-surface", `text-${name}`],
    ]) {
      const merged = twMerge(`${a} ${b}`)
      expect(merged, `twMerge("${a} ${b}") dropped a class`).toContain(a)
      expect(merged).toContain(b)
    }
  })

  it("still collapses two font sizes to the later one", () => {
    expect(twMerge("text-dense text-display-md")).toBe("text-display-md")
  })

  it.each(registered)('index.css defines the registered class "text-%s"', (name) => {
    expect(defined.has(name), `lib/utils.ts registers "text-${name}", but index.css defines no such class or theme key`).toBe(true)
  })

  it.each([...defined])('lib/utils.ts registers the defined class "text-%s"', (name) => {
    expect(registered.includes(name), `index.css defines "text-${name}" but lib/utils.ts does not register it`).toBe(true)
  })
})

describe("--fs-field platform floor", () => {
  it("is defined at 16px", () => {
    expect(css).toContain("--fs-field: 16px")
  })

  it("is a registered font-size class, not a display/body/data type rung", () => {
    expect(registered).toContain("field")
  })
})

describe("no arbitrary literals in the retrofitted portals", () => {
  // `portals/student/` is deliberately absent: only its shell (index.tsx) was retrofitted.
  const RETROFITTED = ["portals/teacher", "portals/parent", "components", "portals/student/index.tsx"]
  const BANNED: [RegExp, string][] = [
    [/\btext-\[[0-9.]+px\]/g, "arbitrary font size"],
    [/\brounded-\[[0-9.]+px\]/g, "arbitrary border radius"],
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
    expect(files.length).toBeGreaterThan(0)
  })

  it.each(files.map((f) => [relative(SRC, f), f] as const))("%s uses tokens, not literals", (_label, file) => {
    const text = readFileSync(file, "utf8")
    const found: string[] = []
    for (const [pattern, label] of BANNED) {
      for (const match of text.matchAll(pattern)) {
        const line = text.slice(0, match.index).split("\n").length
        found.push(`:${line}  ${label} "${match[0]}" use a token from index.css`)
      }
    }
    expect(found).toEqual([])
  })
})
