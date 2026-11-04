import { readdirSync, readFileSync, statSync } from "node:fs"
import { join, relative as pathRelative } from "node:path"
import { describe, expect, it } from "vitest"
import { stripComments } from "./support/jsxSource"

/**
 * The contrast gate (v5 Abyss): gold is a fill, never a text colour.
 *
 * The Study Notebook version of this gate said "`text-accent` (terracotta,
 * 4.34:1) is for fills and large text only". That rule is retired with the
 * terracotta accent: Abyss `primary` is 12:1 on `surface`, so there is no
 * size limit to enforce on it.
 *
 * The rule with the same shape in v5 is gold. `tertiary` (`oklch(0.80 0.13
 * 80)`) is a reward colour for XP, streaks and medium confidence, and on
 * `surface` it is roughly 1.7:1 at any size. DESIGN.md pairs it with
 * `on-tertiary-container` for text. So no class expression may use
 * `text-tertiary` itself.
 *
 * It checks one class expression at a time, so a parent's colour and a child's
 * size are not related by it. axe, on a rendered page, covers that case.
 */

const ROOT = join(import.meta.dirname, "..", "..")
const SRC = join(ROOT, "src")
const INDEX_CSS = readFileSync(join(SRC, "index.css"), "utf8")

function sourceFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) {
      out.push(...sourceFiles(path))
      continue
    }
    if (entry.endsWith(".ts") || entry.endsWith(".tsx")) out.push(path)
  }
  return out
}

function relativeTo(absolute: string): string {
  return pathRelative(ROOT, absolute).split("\\").join("/")
}

/** Every balanced class-expression group: `cn(...)`, `cva(...)`, `className="..."`. */
function classGroups(source: string): { text: string; index: number }[] {
  const out: { text: string; index: number }[] = []
  const opener = /\b(?:cn|cva|buttonVariants)\s*\(/g
  let match: RegExpExecArray | null
  while ((match = opener.exec(source)) !== null) {
    let depth = 1
    let i = opener.lastIndex
    while (i < source.length && depth > 0) {
      if (source[i] === "(") depth++
      else if (source[i] === ")") depth--
      i++
    }
    out.push({ text: source.slice(match.index, i), index: match.index })
  }
  for (const plain of source.matchAll(/className="([^"]*)"/g)) {
    out.push({ text: plain[1], index: plain.index ?? 0 })
  }
  return out
}

function lineOf(source: string, index: number): number {
  return source.slice(0, index).split("\n").length
}

/** A class token, allowing a variant prefix (`hover:`, `md:`) and refusing a
 * longer identifier that merely starts the same way (`text-accent-ink`). */
function hasClass(text: string, name: string): boolean {
  return new RegExp(`(?:^|[\\s:"'\`])${name}(?![\\w-])`).test(text)
}

const FILES = sourceFiles(SRC)

describe("the gold text rule is a real vocabulary", () => {
  it("index.css still defines the gold pair the rule names", () => {
    expect(/^\s*--md-tertiary\s*:/m.test(INDEX_CSS)).toBe(true)
    expect(/^\s*--md-on-tertiary-container\s*:/m.test(INDEX_CSS)).toBe(true)
  })

  it("finds source files to check", () => {
    expect(FILES.length).toBeGreaterThan(100)
  })

  it("the class matcher sees `text-tertiary` and not its `-container` relatives", () => {
    expect(hasClass('cn("text-tertiary font-bold")', "text-tertiary")).toBe(true)
    expect(hasClass('cn("hover:text-tertiary")', "text-tertiary")).toBe(true)
    expect(hasClass('cn("text-on-tertiary-container")', "text-tertiary")).toBe(false)
    expect(hasClass('cn("text-tertiary-container")', "text-tertiary")).toBe(false)
  })
})

describe("gold (`tertiary`) is not used as a text colour", () => {
  it("no class expression sets `text-tertiary`", () => {
    const offenders: string[] = []
    for (const file of FILES) {
      const source = stripComments(readFileSync(file, "utf8"))
      for (const group of classGroups(source)) {
        if (!hasClass(group.text, "text-tertiary")) continue
        offenders.push(`${relativeTo(file)}:${lineOf(source, group.index)} — text-tertiary`)
      }
    }
    // `bg-tertiary`, `fill-tertiary` and `border-tertiary` are untouched: gold
    // is a fill and an icon colour. Only a text colour is forbidden, and the
    // text role for gold is `on-tertiary-container`.
    expect(offenders).toEqual([])
  })
})
