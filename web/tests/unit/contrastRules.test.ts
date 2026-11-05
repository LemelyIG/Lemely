import { readdirSync, readFileSync, statSync } from "node:fs"
import { join, relative as pathRelative } from "node:path"
import { describe, expect, it } from "vitest"
import { oklchToSrgb, readTokenBlock } from "../../vite/brandTokens"
import { stripComments } from "./support/jsxSource"

/**
 * The contrast gate (v5 Abyss): a colour role that fails AA as text is a fill.
 *
 * The Study Notebook version of this gate said "`text-accent` (terracotta,
 * 4.34:1) is for fills and large text only". The terracotta accent is gone, but
 * the rule is not: v5 still has roles under 4.5:1 on the light surfaces, and
 * they are derived here from `index.css` rather than listed by hand, so a new
 * or retuned role is caught the day it lands.
 *
 * A text-capable role (a `--color-*` utility that is not a surface, outline,
 * inverse, `on-*` or `*-container` role) under 4.5:1 on `surface` or
 * `surface-container-lowest` in either theme is "weak". Weak roles are treated
 * one of three ways:
 *
 * - it has a `-text` sibling (`success` has `success-text`): `text-<role>` is
 *   banned outright, the sibling is the text role;
 * - it is under 3:1 (gold `tertiary`, about 1.7:1): banned outright too, since
 *   no size rescues it; DESIGN.md pairs it with `on-tertiary-container`;
 * - otherwise (the `grade-*` ramp, 3 to 4.5:1): `text-<role>` is allowed only
 *   when the same class expression carries a type class of at least 24px, the
 *   WCAG large-text size, read from the ramp in `index.css`.
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

type Rgb = [number, number, number]

function luminance(rgb: Rgb): number {
  const [r, g, b] = rgb.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

/** `--color-<role>: var(--<token>)` pairs from the `@theme` block. */
function roleTokens(css: string): Map<string, string> {
  const roles = new Map<string, string>()
  for (const m of css.matchAll(/--color-([\w-]+):\s*var\(--([\w-]+)\)/g)) roles.set(m[1], m[2])
  return roles
}

const NOT_TEXT_ROLE = /^(?:surface|outline|inverse|on-|scrim)|-container(?:-|$)/

interface WeakRole {
  role: string
  worst: number
  bannedOutright: boolean
}

/** Text-capable roles under 4.5:1 on the surfaces they sit on, either theme. */
function weakRoles(css: string): WeakRole[] {
  const roles = roleTokens(css)
  const light = readTokenBlock(css, ":root")
  const dark = readTokenBlock(css, ':root[data-theme="dark"]')
  // The dark block redeclares only some tokens (the `--grade-*` ramp is declared
  // once, in :root, and inherited), so a token it omits resolves to its light
  // value and is still measured on the dark surfaces. Dark cards sit on
  // surface-container-high (DESIGN.md).
  const themes = [
    { resolve: (n: string) => light.get(n), surfaces: ["md-surface", "md-surface-container-lowest"] },
    {
      resolve: (n: string) => dark.get(n) ?? light.get(n),
      surfaces: ["md-surface", "md-surface-container-low", "md-surface-container-high"],
    },
  ]
  const out: WeakRole[] = []
  for (const [role, token] of roles) {
    if (NOT_TEXT_ROLE.test(role)) continue
    let worst = Infinity
    for (const { resolve, surfaces } of themes) {
      const fg = resolve(token)
      if (!fg) continue
      for (const surface of surfaces) {
        const bg = resolve(surface)
        if (!bg) continue
        worst = Math.min(worst, contrast(oklchToSrgb(...fg), oklchToSrgb(...bg)))
      }
    }
    if (worst >= 4.5 || worst === Infinity) continue
    out.push({ role, worst, bannedOutright: roles.has(`${role}-text`) || worst < 3 })
  }
  return out
}

/** Type-ramp classes (`.text-display-lg`, ...) rendering at 24px or more. */
function largeTypeClasses(css: string): string[] {
  const out: string[] = []
  for (const m of css.matchAll(/\.(text-[\w-]+)\s*\{\s*font:\s*\d+\s+(\d+(?:\.\d+)?)px/g)) {
    if (Number(m[2]) >= 24) out.push(m[1])
  }
  return out
}

/** True when a class expression carries a >= 24px size at the BASE breakpoint: a
 * ramp rung, `text-[Npx]`, or `text-2xl` and up, with no variant prefix. A
 * `md:`-only large class still renders small on mobile. */
function hasLargeType(text: string, ramp: readonly string[]): boolean {
  const bare = (name: string) => new RegExp(`(?:^|[\\s"'\`])${name}(?![\\w:-])`)
  if (ramp.some((cls) => bare(cls).test(text))) return true
  for (const m of text.matchAll(/(?:^|[\s"'`])text-\[(\d+(?:\.\d+)?)px\](?![\w:-])/g)) {
    if (Number(m[1]) >= 24) return true
  }
  return bare("text-[2-9]xl").test(text)
}

/** Offenders in `source`, as `line — reason`, for the given weak roles. */
function offendersIn(source: string, weak: readonly WeakRole[], ramp: readonly string[]): string[] {
  const out: string[] = []
  for (const group of classGroups(stripComments(source))) {
    for (const { role, worst, bannedOutright } of weak) {
      const cls = `text-${role}`
      if (!hasClass(group.text, cls)) continue
      if (!bannedOutright && hasLargeType(group.text, ramp)) continue
      out.push(`${lineOf(stripComments(source), group.index)} — ${cls} (${worst.toFixed(2)}:1)`)
    }
  }
  return out
}

const WEAK = weakRoles(INDEX_CSS)
const RAMP = largeTypeClasses(INDEX_CSS)

describe("the weak-role list is derived from index.css", () => {
  const byRole = new Map(WEAK.map((w) => [w.role, w]))

  it("finds the roles v5 is known to ship under 4.5:1", () => {
    for (const role of ["success", "tertiary", "grade-a-star", "grade-a", "grade-b", "grade-c", "grade-d", "grade-e", "grade-f", "grade-g", "grade-u"]) {
      expect(byRole.has(role), `${role} should be weak`).toBe(true)
    }
  })

  it("does not flag the roles that carry text on purpose", () => {
    for (const role of ["primary", "success-text", "error", "on-surface", "on-surface-variant"]) {
      expect(byRole.has(role), `${role} should not be weak`).toBe(false)
    }
  })

  it("measures inherited tokens on the dark surfaces too", () => {
    // `--grade-*` is declared only in :root. On dark surfaces grade-a-star is ~2.4:1.
    expect(byRole.get("grade-a-star")?.worst).toBeLessThan(3)
  })

  it("bans success, tertiary and the sub-3:1 grades outright and lets the rest through at 24px+", () => {
    for (const role of ["success", "tertiary", "grade-a-star", "grade-e", "grade-f", "grade-g", "grade-u"]) {
      expect(byRole.get(role)?.bannedOutright, role).toBe(true)
    }
    for (const role of ["grade-a", "grade-b", "grade-c", "grade-d"]) {
      expect(byRole.get(role)?.bannedOutright).toBe(false)
    }
  })

  it("reads a large-type ramp out of index.css", () => {
    expect(RAMP).toContain("text-display-lg")
    expect(RAMP).not.toContain("text-body-md")
    expect(RAMP).not.toContain("text-display-sm") // 21px
  })

  it("finds source files to check", () => {
    expect(FILES.length).toBeGreaterThan(100)
  })

  it("the class matcher sees `text-tertiary` and not its relatives", () => {
    expect(hasClass('cn("text-tertiary font-bold")', "text-tertiary")).toBe(true)
    expect(hasClass('cn("hover:text-tertiary")', "text-tertiary")).toBe(true)
    expect(hasClass('cn("text-on-tertiary-container")', "text-tertiary")).toBe(false)
    expect(hasClass('cn("text-success-text")', "text-success")).toBe(false)
  })
})

describe("the rule goes red on a planted offender", () => {
  const planted = (cls: string) => `export const X = () => <p className={cn("${cls}")}>x</p>`

  it("flags bare text-success even at a large size", () => {
    expect(offendersIn(planted("text-success text-display-lg"), WEAK, RAMP)).toHaveLength(1)
  })
  it("flags text-tertiary", () => {
    expect(offendersIn(planted("text-tertiary"), WEAK, RAMP)).toHaveLength(1)
  })
  it("flags text-grade-c on small text", () => {
    expect(offendersIn(planted("text-grade-c text-body-md"), WEAK, RAMP)).toHaveLength(1)
    expect(offendersIn(planted("hover:text-grade-b"), WEAK, RAMP)).toHaveLength(1)
  })
  it("does not accept a breakpoint-prefixed large class as the exemption", () => {
    expect(offendersIn(planted("text-grade-c md:text-display-lg"), WEAK, RAMP)).toHaveLength(1)
    expect(offendersIn(planted("text-grade-c md:text-[32px]"), WEAK, RAMP)).toHaveLength(1)
  })
  it("flags text-grade-u even at a large size (under 3:1 on dark)", () => {
    expect(offendersIn(planted("text-grade-u text-display-lg"), WEAK, RAMP)).toHaveLength(1)
  })
  it("allows text-grade-c beside a 24px+ type class and text-success-text anywhere", () => {
    expect(offendersIn(planted("text-grade-c text-display-lg"), WEAK, RAMP)).toEqual([])
    expect(offendersIn(planted("text-success-text text-body-md"), WEAK, RAMP)).toEqual([])
  })
})

describe("no text role under 4.5:1 is used as small text", () => {
  it("web/src has no offending class expression", () => {
    const offenders: string[] = []
    for (const file of FILES) {
      const source = readFileSync(file, "utf8")
      for (const hit of offendersIn(source, WEAK, RAMP)) offenders.push(`${relativeTo(file)}:${hit}`)
    }
    // `bg-*`, `fill-*`, `border-*` and `ring-*` are untouched: a weak role is a
    // fill and an icon colour. Only a text colour is forbidden, and its text
    // role is the `-text` sibling (success) or `on-tertiary-container` (gold).
    expect(offenders).toEqual([])
  })
})
