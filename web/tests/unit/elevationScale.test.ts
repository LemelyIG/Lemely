import { readdirSync, readFileSync, statSync } from "node:fs"
import { join, relative as pathRelative } from "node:path"
import { describe, expect, it } from "vitest"

/**
 * The elevation gate (P6.3): the §7 z-index scale, and §3.2 item 6's blur.
 *
 * `index.css` has said since Phase 2, in a comment directly above the scale,
 * that "a raw z-index outside this scale is a gate failure". No gate read it.
 * Four raw values had accumulated, and one of them was live: the per-question
 * confidence tooltip on `PaperResult`/`PracticeResult` declared `z-10`, which is
 * `--z-index-sticky`'s value, so a floating layer sat in the band this product
 * reserves for sticky table headers and portal top bars — the two things most
 * likely to be over it. Every other floating layer in the kit was already in the
 * dropdown band. Nothing could have caught it: `z-10` is a real Tailwind
 * utility that emits a real rule, so `utilityExistence.test.ts` sees a class
 * that resolves, and the token gate sees no raw colour. It resolves to the
 * *wrong* thing, which is D4.6's shape rather than D4.1's.
 *
 * ── Two design decisions worth stating ─────────────────────────────────────
 *
 * 1. **It walks `src/` rather than reading a file list.** P4.10's finding was
 *    that the three hand-maintained gate lists only grow by hand, so a file no
 *    surface claims is a file no gate reads; P6.2 hit it again on
 *    `CameraCapture.tsx`. Three of the four offenders here live in kit
 *    components that no screen renders, which is exactly the population a list
 *    built from surface work would never contain.
 *
 * 2. **The allowlist is derived from `index.css`, not written here.** A gate
 *    that hardcodes `nav|modal|toast|…` keeps passing after someone renames a
 *    token, while checking names the product no longer has. The scale is read
 *    out of the stylesheet every run, so the two cannot drift apart, and the
 *    first test below fails if the scale is emptied or moved.
 */

const ROOT = join(import.meta.dirname, "..", "..")
const SRC = join(ROOT, "src")
const INDEX_CSS = readFileSync(join(SRC, "index.css"), "utf8")

/** Every `.ts`/`.tsx` under `src/`, found rather than listed. */
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

/** The rung names the §7 scale actually defines, read off `index.css`.
 *
 * Tailwind v4 turns a `--z-index-<name>` theme entry into a `z-<name>` utility,
 * so these names ARE the permitted vocabulary. */
function scaleRungs(): string[] {
  return [...INDEX_CSS.matchAll(/^\s*--z-index-([a-z0-9-]+)\s*:/gm)].map((m) => m[1])
}

const RUNGS = scaleRungs()

/**
 * Blanks every comment, preserving line numbers and every other character.
 *
 * ── Why this is here, and why it is a state machine rather than a regex ────
 *
 * The first draft of this gate scanned raw source and reported six offenders.
 * All six were prose. Five were comments *this phase wrote* explaining the fix
 * ("`z-dropdown`, not the raw `z-10` this carried"), and the sixth was the best
 * comment in the file it lives in — `celebration.tsx` explaining that it
 * deliberately uses DOM order instead of a `z-*` utility, because "a raw `z-1`
 * outside the scale is exactly what that gate exists to catch".
 *
 * So the gate's own first run flagged the one component that had reasoned its
 * way to the right answer, and the cheapest way to make it green would have
 * been to delete the reasoning. That is D6.3's finding — a gate that reports
 * good work teaches people to launder it — arriving one phase later in the
 * gate written to honour it.
 *
 * Restricting the match to quoted spans is not enough on its own: these files
 * quote class names inside comments with backticks, which is indistinguishable
 * from a template literal to anything that does not track comment state. Hence
 * a real (small) lexer.
 */
function stripComments(source: string): string {
  let out = ""
  let i = 0
  type State = "code" | "line" | "block" | "single" | "double" | "template"
  let state: State = "code"

  while (i < source.length) {
    const c = source[i]
    const n = source[i + 1]

    if (state === "code") {
      if (c === "/" && n === "/") {
        state = "line"
        out += "  "
        i += 2
        continue
      }
      if (c === "/" && n === "*") {
        state = "block"
        out += "  "
        i += 2
        continue
      }
      if (c === "'") state = "single"
      else if (c === '"') state = "double"
      else if (c === "`") state = "template"
      out += c
      i += 1
      continue
    }

    if (state === "line") {
      if (c === "\n") {
        state = "code"
        out += c
      } else {
        out += " "
      }
      i += 1
      continue
    }

    if (state === "block") {
      if (c === "*" && n === "/") {
        state = "code"
        out += "  "
        i += 2
        continue
      }
      // Newlines are kept so reported line numbers stay true to the file.
      out += c === "\n" ? "\n" : " "
      i += 1
      continue
    }

    // Inside a string literal.
    if (c === "\\") {
      out += c + (source[i + 1] ?? "")
      i += 2
      continue
    }
    if (
      (state === "single" && c === "'") ||
      (state === "double" && c === '"') ||
      (state === "template" && c === "`")
    ) {
      state = "code"
    }
    out += c
    i += 1
  }

  return out
}

/** Blanks CSS comments, preserving line numbers. */
function stripCssComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, (match) => match.replace(/[^\n]/g, " "))
}

/**
 * Class-position tokens matching `matcher`, in comment-free source.
 *
 * Still scoped to quoted spans, which is where Tailwind classes live in this
 * codebase (`className="…"`, `cn("…", …)`). The left-hand `(?:^|[\s:])` refuses
 * `.z-10` inside a CSS selector string and the tail of an identifier; the `:`
 * admits variant prefixes (`md:z-nav`, `motion-safe:backdrop-blur-nav`).
 */
function classTokensIn(
  source: string,
  matcher: RegExp,
): { token: string; line: number }[] {
  const out: { token: string; line: number }[] = []
  stripComments(source)
    .split("\n")
    .forEach((text, index) => {
      for (const quoted of text.matchAll(/"([^"\n]*)"|'([^'\n]*)'|`([^`\n]*)`/g)) {
        const body = quoted[1] ?? quoted[2] ?? quoted[3] ?? ""
        for (const hit of body.matchAll(matcher)) {
          out.push({ token: hit[1], line: index + 1 })
        }
      }
    })
  return out
}

/**
 * Every balanced class-expression group in a source file: `cn(...)`, `cva(...)`
 * or a plain `className="..."`.
 *
 * Parenthesis-walked rather than regex-matched, so a nested call or a template
 * literal inside the argument list cannot end a group early. This is
 * `hoverTransition.test.ts`'s parser, and it is here for the reason that test
 * documents: a class expression routinely spans many lines, and the class that
 * governs an element sits on a different line from the one it governs. A
 * line-based check of a multi-line expression reports correct code, which is
 * D6.3's finding — and the four navbars this rule covers are one-liners *today*,
 * so a line-based version would pass now and fail the first time one of them is
 * wrapped, on a diff that changed no behaviour.
 */
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

function zTokensIn(source: string): { token: string; line: number }[] {
  return classTokensIn(source, /(?:^|[\s:])(z-[A-Za-z0-9[\]()_.-]+)/g)
}

function blurTokensIn(source: string): { token: string; line: number }[] {
  return classTokensIn(source, /(?:^|[\s:])((?:backdrop-)?blur-[A-Za-z0-9[\]()_.-]+)/g)
}

const FILES = sourceFiles(SRC)

describe("the §7 z-index scale is a real vocabulary", () => {
  it("index.css defines the seven rungs DESIGN.md §7 names", () => {
    expect(RUNGS).toEqual(["base", "sticky", "nav", "dropdown", "scrim", "modal", "toast"])
  })

  it("finds source files to check", () => {
    // A walk that silently matched nothing would make every test below vacuous
    // — D6.1's "a gate reporting zero and a gate reporting nonsense are both
    // consistent with a green ledger row".
    expect(FILES.length).toBeGreaterThan(100)
  })
})

describe("no z-index outside the scale", () => {
  it("every `z-*` class in src/ names a rung", () => {
    const offenders: string[] = []
    for (const file of FILES) {
      for (const { token, line } of zTokensIn(readFileSync(file, "utf8"))) {
        const rung = token.slice(2)
        if (!RUNGS.includes(rung)) {
          offenders.push(`${relativeTo(file)}:${line} — ${token}`)
        }
      }
    }
    expect(offenders).toEqual([])
  })

  it("no source file writes a bare `z-index:` declaration", () => {
    // The CSS-in-a-string escape hatch from the rule above. `index.css` is
    // excluded because it is where the scale is defined; every other file that
    // wants a stacking order must go through it.
    const offenders: string[] = []
    for (const file of FILES) {
      stripComments(readFileSync(file, "utf8"))
        .split("\n")
        .forEach((text, index) => {
          if (/\bz-?[iI]ndex\s*:/.test(text) && !/var\(--z-index-/.test(text)) {
            offenders.push(`${relativeTo(file)}:${index + 1} — ${text.trim()}`)
          }
        })
    }
    expect(offenders).toEqual([])
  })

  it("index.css uses the scale for every z-index it sets", () => {
    const declarations = [
      ...stripCssComments(INDEX_CSS).matchAll(/^\s*z-index\s*:\s*([^;]+);/gm),
    ].map((m) => m[1].trim())
    expect(declarations.length).toBeGreaterThan(0)
    for (const value of declarations) {
      expect(value).toMatch(/^var\(--z-index-[a-z-]+\)$/)
    }
  })
})

describe("§3.2 item 6 — blur is the navbar exception and nothing else", () => {
  it("index.css defines --blur-nav", () => {
    expect(/^\s*--blur-nav\s*:/m.test(INDEX_CSS)).toBe(true)
  })

  it("`backdrop-blur-nav` is the only blur utility in the product", () => {
    // Glassmorphism is banned outright; the sole carve-out is a subtle blur on
    // a page top bar. Before P6.3 the four top bars declared it two different
    // ways (`backdrop-blur-sm` and an arbitrary `backdrop-blur-[10px]`), which
    // is how a rule with one permitted value ends up with two.
    const offenders: string[] = []
    for (const file of FILES) {
      for (const { token, line } of blurTokensIn(readFileSync(file, "utf8"))) {
        if (token !== "backdrop-blur-nav") {
          offenders.push(`${relativeTo(file)}:${line} — ${token}`)
        }
      }
    }
    expect(offenders).toEqual([])
  })

  it("every backdrop-blur sits on an element that does not scroll", () => {
    // "Never on scrolling content" is the half of the rule a name check cannot
    // see. Checked structurally: the blur and a `sticky`/`fixed` position must
    // appear in the same balanced class expression — not merely on the same
    // line, which would report a correct navbar the moment prettier wrapped it.
    const offenders: string[] = []
    for (const file of FILES) {
      const source = stripComments(readFileSync(file, "utf8"))
      for (const group of classGroups(source)) {
        if (!group.text.includes("backdrop-blur-")) continue
        if (/\b(sticky|fixed)\b/.test(group.text)) continue
        offenders.push(`${relativeTo(file)}:${lineOf(source, group.index)}`)
      }
    }
    expect(offenders).toEqual([])
  })
})
