import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { relativeTo, sourceFiles, stripComments } from "./support/jsxSource"

/** Any of these in web/src means a screen still speaks the retired Study Notebook vocabulary. */
export const RETIRED = [
  /(?<![\w-])(?:[\w-]+:)*(?:bg|text|border|ring|fill|stroke|outline|divide)-(?:paper|ink|rule|accent|pastel|subject|ok|warn|err|info|confidence|mark|t1|t2|t3)(?:-[a-z0-9-]+)?(?![\w-])/,
  /\b(?:paper-grain|ruled-bg|dotted-bg|margin-rule|text-hand|font-hand|lm-confetti)\b/,
  /Caveat|Newsreader|Geist/,
]

export function retiredHits(source: string): string[] {
  const code = stripComments(source)
  return RETIRED.flatMap((re) => {
    const m = code.match(new RegExp(re.source, "g"))
    return m ?? []
  })
}

/**
 * Directories excluded from the scan. marketing is migrated in Task 7 of
 * docs/superpowers/plans/2026-11-02-abyss-design-system-migration.md; remove
 * this exclusion then. dev-previews is dev scratch.
 */
const EXCLUDED_DIRS = ["src/portals/marketing/", "src/dev-previews/"]

describe("retired token guard", () => {
  it("catches a planted retired name (proves the guard can go red)", () => {
    expect(retiredHits(`<div className="hover:text-ink-muted bg-paper-raised" />`)).toEqual(["hover:text-ink-muted", "bg-paper-raised"])
    expect(retiredHits(`<p className="text-hand">x</p>`)).toEqual(["text-hand"])
  })

  it("ignores names that only start with a retired word", () => {
    expect(retiredHits(`<div className="text-inkwell bg-paperless" />`)).toEqual([])
  })

  it("finds no retired name anywhere in web/src", () => {
    const root = process.cwd()
    const files = [...sourceFiles(join(root, "src")), ...sourceFiles(join(root, "src"), ".ts")]
    const offenders = files
      .map((file) => ({ file: relativeTo(root, file), hits: retiredHits(readFileSync(file, "utf8")) }))
      .filter((r) => r.hits.length && !EXCLUDED_DIRS.some((dir) => r.file.startsWith(dir)))
    expect(offenders).toEqual([])
  })
})
