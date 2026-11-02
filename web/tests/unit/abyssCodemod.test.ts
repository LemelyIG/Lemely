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
})
