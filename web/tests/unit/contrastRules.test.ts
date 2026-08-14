import { readdirSync, readFileSync, statSync } from "node:fs"
import { join, relative as pathRelative } from "node:path"
import { describe, expect, it } from "vitest"
import { stripComments } from "./support/jsxSource"

/**
 * The contrast gate (P6.4): the accent's size rule, and the pastel pairings.
 *
 * ── The rule already existed. Nothing read it. ─────────────────────────────
 *
 * `index.css` has carried this directly above the accent tokens since Phase 2:
 *
 *     --accent      4.34:1 on paper — fills, marks, large text only
 *     --accent-ink  9.75:1 on paper — any accent-coloured small text
 *
 * That is a correct and carefully measured rule, and **no gate enforced it**,
 * so `text-accent` had accumulated on 11 small-text elements: both marketing
 * eyebrows (11px, the smallest text in the product), a notification-settings
 * link, four teacher panel headings, three status counts, and two hover states
 * that made contrast *worse* than the resting colour they darkened from.
 *
 * axe found **two** of the eleven, because axe can only see what a route it
 * audits happens to render. That gap is the reason this is a source gate and
 * not a note in the audit report: the same shape as P6.3's z-index scale, where
 * a rule stated in a comment above the tokens went nine phases unenforced.
 *
 * ── Why "large text" is 24px here ─────────────────────────────────────────
 *
 * WCAG's large-text threshold is 18pt (24px), or 14pt (18.66px) when bold. This
 * gate takes the stricter reading and treats **every rung below 24px as small**,
 * including `display-sm` (19px) and `hand` (19px), because those two are only
 * exempt if they are also bold and the weight lives in a different declaration
 * from the size — so a gate that assumed boldness would be asserting something
 * it cannot see. The rungs and their sizes are read out of `index.css` rather
 * than written here, so the scale and the gate cannot drift apart.
 *
 * ── What this gate deliberately does NOT claim ────────────────────────────
 *
 * It checks one class expression at a time. A `text-body-sm` on a parent and a
 * `text-accent` on its child are the same defect and this cannot see it — the
 * measurement that catches that case is axe, on a rendered page, which is why
 * both still run. Stated here rather than left for someone to discover, because
 * a gate whose limits are unwritten gets read as proving more than it does.
 */

const ROOT = join(import.meta.dirname, "..", "..")
const SRC = join(ROOT, "src")
const INDEX_CSS = readFileSync(join(SRC, "index.css"), "utf8")

/** WCAG's large-text floor in px. Below this, text needs the full 4.5:1. */
const LARGE_TEXT_PX = 24

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

/** `--fs-<rung>: <n>px` -> `Map<rung, px>`, read off the stylesheet. */
function fontSizes(): Map<string, number> {
  const out = new Map<string, number>()
  for (const m of INDEX_CSS.matchAll(/^\s*--fs-([a-z0-9-]+)\s*:\s*([\d.]+)px\s*;/gm)) {
    out.set(m[1], Number(m[2]))
  }
  return out
}

const FONT_SIZES = fontSizes()

/**
 * The `text-*` utilities that set a size below the large-text floor.
 *
 * Derived from the `--fs-*` scale, then mapped back to the utility names the
 * markup actually uses. `label-sm` is spelled out because it reuses
 * `--fs-eyebrow` rather than declaring a rung of its own.
 */
function smallTextUtilities(): string[] {
  const out: string[] = []
  for (const [rung, px] of FONT_SIZES) {
    if (px >= LARGE_TEXT_PX) continue
    out.push(`text-${rung}`)
  }
  if (FONT_SIZES.has("eyebrow") && (FONT_SIZES.get("eyebrow") ?? 0) < LARGE_TEXT_PX) {
    out.push("text-label-sm")
  }
  return out
}

const SMALL_TEXT = smallTextUtilities()


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

describe("the accent size rule is a real vocabulary", () => {
  it("index.css still declares the type scale this gate reads", () => {
    // A scale that moved or was renamed would make every test below vacuous —
    // D6.1's "a gate reporting zero and a gate reporting nonsense are both
    // consistent with a green ledger row".
    expect(FONT_SIZES.size).toBeGreaterThan(8)
    expect(SMALL_TEXT.length).toBeGreaterThan(5)
    expect(SMALL_TEXT).toContain("text-eyebrow")
    expect(SMALL_TEXT).toContain("text-body-sm")
    expect(SMALL_TEXT).not.toContain("text-display-lg")
  })

  it("index.css still defines the accent pair the rule names", () => {
    expect(/^\s*--accent\s*:/m.test(INDEX_CSS)).toBe(true)
    expect(/^\s*--accent-ink\s*:/m.test(INDEX_CSS)).toBe(true)
  })

  it("finds source files to check", () => {
    expect(FILES.length).toBeGreaterThan(100)
  })
})

describe("--accent is not used for small text", () => {
  it("no class expression pairs `text-accent` with a sub-24px rung", () => {
    const offenders: string[] = []
    for (const file of FILES) {
      const source = stripComments(readFileSync(file, "utf8"))
      for (const group of classGroups(source)) {
        if (!hasClass(group.text, "text-accent")) continue
        const rungs = SMALL_TEXT.filter((rung) => hasClass(group.text, rung))
        if (rungs.length === 0) continue
        offenders.push(
          `${relativeTo(file)}:${lineOf(source, group.index)} — text-accent with ${rungs.join(", ")}`,
        )
      }
    }
    // `text-accent` on an icon is untouched by this and should be: an icon is a
    // non-text element and answers to the 3:1 graphics floor, which the accent
    // clears. The rule is about *text*, so it only fires when a text rung is in
    // the same expression.
    expect(offenders).toEqual([])
  })
})
