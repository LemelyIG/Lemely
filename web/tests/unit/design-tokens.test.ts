import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

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
