import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
// @ts-expect-error: plain .mjs script without types
import { rewriteClasses } from "../../scripts/abyss-codemod.mjs"

const map = JSON.parse(readFileSync(join(__dirname, "../../scripts/abyss-token-map.json"), "utf8"))

describe("abyss codemod", () => {
  it("renames a token for any colour prefix", () => {
    expect(rewriteClasses(`className="text-ink bg-paper-raised border-rule"`, map, { compat: false }))
      .toBe(`className="text-on-surface bg-surface-container-lowest border-outline-variant"`)
  })

  it("keeps variant prefixes and opacity suffixes", () => {
    expect(rewriteClasses(`"hover:bg-accent-hover dark:text-ink-muted/70 md:border-t-rule"`, map, { compat: false }))
      .toBe(`"hover:bg-primary-hover dark:text-on-surface-variant/70 md:border-t-outline-variant"`)
  })

  it("prefers a full-pair override over the token rule", () => {
    expect(rewriteClasses(`"bg-ink text-paper"`, map, { compat: false })).toBe(`"bg-inverse-surface text-inverse-on-surface"`)
  })

  it("does not touch a longer token that merely starts with a mapped one", () => {
    expect(rewriteClasses(`"text-inkwell bg-paperish"`, map, { compat: false })).toBe(`"text-inkwell bg-paperish"`)
  })

  it("applies compat names only with compat on", () => {
    expect(rewriteClasses(`"bg-surface text-t2"`, map, { compat: false })).toBe(`"bg-surface text-t2"`)
    expect(rewriteClasses(`"bg-surface text-t2"`, map, { compat: true })).toBe(`"bg-surface-container-lowest text-on-surface-variant"`)
  })

  it("is idempotent without compat", () => {
    const once = rewriteClasses(`"text-ink-faint bg-err-wash ring-focus-ring"`, map, { compat: false })
    expect(rewriteClasses(once, map, { compat: false })).toBe(once)
  })

  it("compat run then non-compat run is stable on the migration flow", () => {
    const input = `"bg-paper bg-surface text-secondary text-t2 text-ink"`
    const migrated = rewriteClasses(input, map, { compat: true })
    expect(migrated).toBe(`"bg-surface bg-surface-container-lowest text-on-surface-variant text-on-surface-variant text-on-surface"`)
    expect(rewriteClasses(migrated, map, { compat: false })).toBe(migrated)
  })

  it("leaves a new-system text-secondary alone in a non-compat run", () => {
    expect(rewriteClasses(`"text-secondary bg-secondary"`, map, { compat: false })).toBe(`"text-secondary bg-secondary"`)
  })

  it("does not re-map a value produced earlier in the same compat run", () => {
    expect(rewriteClasses(`"bg-paper"`, map, { compat: true })).toBe(`"bg-surface"`)
    expect(rewriteClasses(`"bg-paper bg-surface"`, map, { compat: true })).toBe(`"bg-surface bg-surface-container-lowest"`)
  })

  it("handles important, variant, opacity and template-literal edge forms", () => {
    expect(rewriteClasses(`"!bg-ink"`, map, { compat: false })).toBe(`"!bg-inverse-surface"`)
    expect(rewriteClasses(`"hover:!text-paper"`, map, { compat: false })).toBe(`"hover:!text-inverse-on-surface"`)
    expect(rewriteClasses(`"text-ink/[0.5]"`, map, { compat: false })).toBe(`"text-on-surface/[0.5]"`)
    expect(rewriteClasses(`"md:bg-ink"`, map, { compat: false })).toBe(`"md:bg-inverse-surface"`)
    expect(rewriteClasses("`text-ink ${x}`", map, { compat: false })).toBe("`text-on-surface ${x}`")
  })

  it("never produces a value that a non-compat run would rewrite again", () => {
    const keys = new Set(Object.keys(map.tokens))
    for (const value of Object.values(map.tokens) as string[]) {
      expect(keys.has(value)).toBe(false)
    }
    const prefixes = [...map.prefixes].sort((a: string, b: string) => b.length - a.length) as string[]
    for (const value of Object.values(map.overrides) as string[]) {
      const prefix = prefixes.find((p) => value.startsWith(`${p}-`))
      expect(prefix).toBeDefined()
      expect(keys.has(value.slice(prefix!.length + 1))).toBe(false)
    }
  })
})
