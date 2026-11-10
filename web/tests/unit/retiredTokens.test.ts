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
 * Retired Study Notebook custom properties, as a CSS file, the pre-mount shell
 * in index.html or a Vite plugin would spell them. `--mark-` is listed by full
 * name because a local animation variable (`--mark-index`) shares the prefix.
 */
export const RETIRED_CSS = [
  /(?<![\w-])--(?:paper|ink|rule|accent|pastel|subject|ok|warn|err|info|confidence|t1|t2|t3)(?:-[a-z0-9-]+)?(?![\w-])/,
  /(?<![\w-])--mark-(?:correct|partial|wrong)(?:-bg)?(?![\w-])/,
  /(?<![\w-])(?:paper-grain|ruled-bg|dotted-bg|margin-rule|text-hand|font-hand|lm-confetti)(?![\w-])/,
  /Caveat|Newsreader|Geist/,
]

/** Strips CSS block, HTML and whole-line `//` comments: history may name the old system, code may not. */
function stripMarkupComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/^\s*\/\/.*$/gm, "")
}

export function retiredCssHits(source: string): string[] {
  const code = stripMarkupComments(source)
  return RETIRED_CSS.flatMap((re) => code.match(new RegExp(re.source, "g")) ?? [])
}

/** Directories excluded from the scan. dev-previews is dev scratch. */
const EXCLUDED_DIRS = ["src/dev-previews/"]

/**
 * The one sanctioned use of Caveat: the marketing paper artifact's student
 * handwriting (`--brand-hand`, scoped to the landing page, never the app).
 * Examiner marks and every UI string stay in the Abyss faces. Any other file
 * naming Caveat still fails.
 */
const CAVEAT_ALLOWED = ["src/portals/marketing/brand-tokens.css"]
const allowedHits = (file: string, hits: string[]) =>
  CAVEAT_ALLOWED.includes(file) ? hits.filter((h) => h !== "Caveat") : hits

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

describe("retired token guard: CSS, the pre-mount shell and Vite plugins", () => {
  it("catches planted retired names (proves the guard can go red)", () => {
    expect(retiredCssHits(`.x { color: var(--ink-muted); background: var(--paper); }`)).toEqual(["--ink-muted", "--paper"])
    expect(retiredCssHits(`.h { font-family: "Newsreader Variable", Georgia; }`)).toEqual(["Newsreader"])
    expect(retiredCssHits(`const css = "border-color: var(--mark-wrong-bg)"`)).toEqual(["--mark-wrong-bg"])
    expect(retiredCssHits(`<style>.m { font: 400 1rem Caveat }</style>`)).toEqual(["Caveat"])
  })

  it("lets only the marketing token file name Caveat", () => {
    expect(allowedHits("src/portals/marketing/brand-tokens.css", ["Caveat", "--paper"])).toEqual(["--paper"])
    expect(allowedHits("src/portals/marketing/brand.css", ["Caveat"])).toEqual(["Caveat"])
  })

  it("ignores comments and look-alike names", () => {
    expect(retiredCssHits(`/* the old --paper and Geist faces */\n<!-- Caveat -->\n// --ink was retired`)).toEqual([])
    expect(retiredCssHits(`.w { animation-delay: calc(var(--mark-index) * 1ms); color: var(--md-on-surface); }`)).toEqual([])
  })

  it("finds no retired name in web/src CSS, web/index.html or web/vite/*.ts", () => {
    const root = process.cwd()
    const files = [
      ...sourceFiles(join(root, "src"), ".css"),
      join(root, "index.html"),
      ...sourceFiles(join(root, "vite"), ".ts"),
    ]
    expect(files.length).toBeGreaterThan(3)
    const offenders = files
      .map((file) => ({ file: relativeTo(root, file), hits: allowedHits(relativeTo(root, file), retiredCssHits(readFileSync(file, "utf8"))) }))
      .filter((r) => r.hits.length && !EXCLUDED_DIRS.some((dir) => r.file.startsWith(dir)))
    expect(offenders).toEqual([])
  })
})
