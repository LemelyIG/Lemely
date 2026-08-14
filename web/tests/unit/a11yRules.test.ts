import { readdirSync, readFileSync, statSync } from "node:fs"
import { join, relative as pathRelative } from "node:path"
import { describe, expect, it } from "vitest"

/**
 * The accessibility gate (P6.4 part 2): the five §6.4 sweep items, as structure.
 *
 * ── Why this gate exists even though the sweep found nothing ───────────────
 *
 * REDESIGN-MISSION §5 Phase 6 item 4 names five things beyond contrast:
 * focus-visible everywhere, keyboard-completable flows, alt text, aria-labels
 * on icon-only buttons, and semantic landmarks. Swept at source across every
 * `.tsx` under `src/`, **all five already held** — nine icon-only controls, all
 * nine named; every `<img>` carrying an `alt`; every `<nav>` labelled; a global
 * `:focus-visible` rule with not one suppression anywhere; and the only click
 * handlers on non-interactive hosts being two dialog scrims whose keyboard
 * equivalent is the Escape their own dialog implements.
 *
 * That is a good result and a fragile one. Every one of those properties holds
 * because somebody was careful, and nothing in the repo would notice the first
 * time somebody was not. D6.3's standing lesson from the failure-copy family —
 * six passes to close because the fix was a list and not a rule — says a sweep
 * that finds a class of thing should end in a gate that walks the tree. So this
 * gate does not record a cleanup. It records the properties, so the *next* icon
 * button without a name fails here rather than in a rendered audit three phases
 * later, on whichever route happens to render it.
 *
 * ── Why a source gate when axe already runs ───────────────────────────────
 *
 * The same argument `contrastRules.test.ts` makes: axe sees only what a route
 * it audits happens to render, and it found 2 of that phase's 11 accent
 * misuses. `scripts/audit.mjs` covers 41 routes; the product has 48. The two
 * measure different things and both still run.
 *
 * ── The lexer is the load-bearing part, and it is why there is a test for it ─
 *
 * The first draft of this scan was written without one, and reported
 * `Classes.tsx`'s scrollable table as a keyboard defect. It is not: the element
 * carries `tabIndex`, `role` and `aria-label`, with a comment above them saying
 * so. The comment is what broke it — it contains the word `axe's`, and a naive
 * character scan treats that apostrophe as opening a string, swallows the tag
 * terminator, and runs the "open tag" on for another forty lines until it finds
 * an unrelated `onClick`.
 *
 * A false positive is the harmless direction of that bug. The same swallow in a
 * file whose comments happen to pair their apostrophes makes the tag *end*
 * early, or vanish, and the finding is silently never reported — a gate that
 * reads a comment as code is exactly D6.1's "a check reporting zero and a check
 * reporting nonsense are both consistent with a green ledger row". This repo
 * hit the same class of thing twice before (`elevationScale.test.ts` on
 * backticked class names in prose, `contrastRules.test.ts` after it), so the
 * lexer is shared in shape with those, and `describe("the lexer")` below pins
 * the apostrophe case specifically, with the exact comment that produced it.
 */

const ROOT = join(import.meta.dirname, "..", "..")
const SRC = join(ROOT, "src")

function sourceFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) {
      out.push(...sourceFiles(path))
      continue
    }
    if (entry.endsWith(".tsx")) out.push(path)
  }
  return out
}

function relativeTo(absolute: string): string {
  return pathRelative(ROOT, absolute).split("\\").join("/")
}

/** Blanks comments, preserving offsets and line numbers, so a `//` comment that
 * quotes prose (`axe's`, `doesn't`) cannot be read as code. Same shape as
 * `contrastRules.test.ts`/`elevationScale.test.ts`; see the header. */
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
      out += c === "\n" ? "\n" : " "
      i += 1
      continue
    }

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

type Element = {
  /** The open tag, `<button ... >`, attributes included. */
  openTag: string
  /** Everything between the open and close tags; `""` for a self-closing tag. */
  inner: string
  selfClosing: boolean
  index: number
}

/**
 * Every occurrence of one JSX tag, with its attributes and its children.
 *
 * Brace-depth aware (an attribute value may be an arbitrary expression) and
 * quote aware, and it counts nested same-name tags so `<div>`-in-`<div>` closes
 * against the right terminator. Run it on `stripComments` output, never on raw
 * source.
 */
function elements(source: string, tag: string): Element[] {
  const out: Element[] = []
  const opener = new RegExp(`<${tag}(?=[\\s/>])`, "g")
  let match: RegExpExecArray | null

  while ((match = opener.exec(source)) !== null) {
    let i = match.index + 1 + tag.length
    let depth = 0
    let quote: string | null = null
    let openEnd = -1
    let selfClosing = false

    for (; i < source.length; i++) {
      const c = source[i]
      if (quote) {
        if (c === quote && source[i - 1] !== "\\") quote = null
        continue
      }
      if (c === '"' || c === "'" || c === "`") {
        quote = c
        continue
      }
      if (c === "{") depth++
      else if (c === "}") depth--
      else if (c === ">" && depth === 0) {
        selfClosing = source[i - 1] === "/"
        openEnd = i
        break
      }
    }
    if (openEnd < 0) continue

    const openTag = source.slice(match.index, openEnd + 1)
    if (selfClosing) {
      out.push({ openTag, inner: "", selfClosing: true, index: match.index })
      continue
    }

    let level = 1
    const boundary = new RegExp(`<${tag}(?=[\\s/>])|</${tag}>`, "g")
    boundary.lastIndex = openEnd + 1
    let b: RegExpExecArray | null
    let innerEnd = -1
    while ((b = boundary.exec(source)) !== null) {
      if (b[0].startsWith("</")) {
        level--
        if (level === 0) {
          innerEnd = b.index
          break
        }
      } else if (!source.slice(b.index, boundary.lastIndex + 200).match(/^<[^>]*\/>/)) {
        level++
      }
    }
    if (innerEnd < 0) continue

    out.push({
      openTag,
      inner: source.slice(openEnd + 1, innerEnd),
      selfClosing: false,
      index: match.index,
    })
  }

  return out
}

function lineOf(source: string, index: number): number {
  return source.slice(0, index).split("\n").length
}

/** The Phosphor icons a file imports. §3.2 item 3 fixes the product on one
 * icon library, so this is the whole icon vocabulary. */
function iconNames(source: string): Set<string> {
  const out = new Set<string>()
  for (const m of source.matchAll(
    /import\s*(?:type\s*)?\{([^}]*)\}\s*from\s*["']@phosphor-icons\/react["']/g,
  )) {
    for (const part of m[1].split(",")) {
      const name = part.trim().split(/\s+as\s+/).pop()?.trim()
      if (name) out.add(name)
    }
  }
  return out
}

const HAS_ACCESSIBLE_NAME = /\baria-label(?:ledby)?\s*=|\btitle\s*=/
const INTERACTIVE_TAGS = ["button", "Button", "a", "Link"]
/** Hosts that expose no role and take no keyboard focus on their own. */
const NON_INTERACTIVE_HOSTS = [
  "div",
  "span",
  "li",
  "td",
  "tr",
  "section",
  "article",
  "p",
  "img",
  "label",
]

const FILES = sourceFiles(SRC)
const PARSED = FILES.map((file) => ({ file, source: stripComments(readFileSync(file, "utf8")) }))

describe("the lexer this gate stands on", () => {
  it("does not read an apostrophe inside a line comment as a string", () => {
    // Verbatim from `portals/teacher/screens/Classes.tsx`, which is the source
    // that produced the false positive described in the header.
    const source = [
      "<div",
      '  className="x"',
      "  // horizontally scrollable container no keyboard user can reach is axe's",
      "  // serious `scrollable-region-focusable`. Do not strip these.",
      "  tabIndex={0}",
      '  role="region"',
      '  aria-label="Your classes"',
      ">",
      '  <button onClick={sort}>Sort</button>',
      "</div>",
    ].join("\n")
    const [div] = elements(stripComments(source), "div")
    expect(div).toBeDefined()
    expect(div.openTag).toContain("tabIndex={0}")
    // The decisive assertion: the open tag STOPS at its own `>`, so the
    // `onClick` two lines below is not attributed to it.
    expect(div.openTag).not.toContain("onClick")
  })

  it("keeps a `>` that lives inside an attribute expression out of the tag end", () => {
    const source = '<div onClick={() => go()} role="button" tabIndex={0} onKeyDown={k}>x</div>'
    const [div] = elements(stripComments(source), "div")
    expect(div.openTag).toContain("tabIndex={0}")
    expect(div.inner).toBe("x")
  })

  it("closes a nested same-name tag against the right terminator", () => {
    const source = "<div a><div b>inner</div>outer</div>"
    const [first] = elements(stripComments(source), "div")
    expect(first.inner).toBe("<div b>inner</div>outer")
  })

  it("walks the whole product", () => {
    // Non-vacuity, per D6.1: a walk that found nothing would pass every test
    // below without reading a line of the product.
    expect(FILES.length).toBeGreaterThan(100)
    expect(PARSED.some(({ source }) => iconNames(source).size > 0)).toBe(true)
  })
})

describe("icon-only controls carry an accessible name", () => {
  it("every interactive element whose only content is icons is named", () => {
    const offenders: string[] = []
    for (const { file, source } of PARSED) {
      const icons = iconNames(source)
      if (icons.size === 0) continue
      for (const tag of INTERACTIVE_TAGS) {
        for (const el of elements(source, tag)) {
          if (el.selfClosing) continue
          if (HAS_ACCESSIBLE_NAME.test(el.openTag)) continue
          if (/\baria-hidden\b/.test(el.openTag)) continue
          const inner = el.inner.trim()
          if (!inner) continue
          // Remove every self-closing element that is a known Phosphor icon.
          // Whatever survives is the control's visible text, a child component,
          // or an expression — any of which may carry the name, so the element
          // is out of scope for this rule.
          const residue = inner
            .replace(/<([A-Z][A-Za-z0-9]*)\b[^<>]*\/>/g, (whole, name: string) =>
              icons.has(name) ? "" : whole,
            )
            .replace(/<>|<\/>/g, "")
            .trim()
          if (residue !== "") continue
          offenders.push(
            `${relativeTo(file)}:${lineOf(source, el.index)} — <${tag}> renders only icons and has no aria-label/aria-labelledby/title`,
          )
        }
      }
    }
    expect(offenders).toEqual([])
  })
})

describe("every flow is completable from the keyboard", () => {
  it("a click handler on a non-interactive host is focusable and key-operable", () => {
    const offenders: string[] = []
    for (const { file, source } of PARSED) {
      for (const tag of NON_INTERACTIVE_HOSTS) {
        for (const el of elements(source, tag)) {
          if (!/\bonClick\s*=/.test(el.openTag)) continue
          // A scrim is hidden from the accessibility tree outright, and the
          // keyboard equivalent of clicking it is the Escape its own dialog
          // handles (`modal.tsx`, `nav-drawer.tsx` both do). Making it a tab
          // stop would add a focusable element that announces nothing and sits
          // between the reader and the dialog.
          if (/\baria-hidden\s*=\s*(?:"true"|\{true\})/.test(el.openTag)) continue
          const missing = [
            !/\brole\s*=/.test(el.openTag) && "role",
            !/\btabIndex\s*=/.test(el.openTag) && "tabIndex",
            !/\bonKey(?:Down|Up|Press)\s*=/.test(el.openTag) && "a key handler",
          ].filter(Boolean)
          if (missing.length === 0) continue
          offenders.push(
            `${relativeTo(file)}:${lineOf(source, el.index)} — <${tag} onClick> is missing ${missing.join(", ")}`,
          )
        }
      }
    }
    expect(offenders).toEqual([])
  })
})

describe("images declare their alt text", () => {
  it("every <img> has an alt attribute", () => {
    // Presence, not content: `alt=""` is the correct answer for a decorative
    // mark whose name is already carried by adjacent text, and this gate cannot
    // tell that case from a lazy one. What it can tell is a *missing* alt,
    // which is a screen reader announcing a filename.
    const offenders: string[] = []
    for (const { file, source } of PARSED) {
      for (const el of elements(source, "img")) {
        // `\salt=`, not `\balt=`. A word boundary sits between the `-` and the
        // `a` of `data-alt`, so the boundary form is satisfied by any attribute
        // ending in `-alt` — the gate would have passed an image carrying
        // `data-alt` and no real alt at all. Found by inverting this rule:
        // the inversion renamed `alt` to `data-alt` and the gate stayed green.
        if (/[\s{]alt\s*=/.test(el.openTag)) continue
        offenders.push(`${relativeTo(file)}:${lineOf(source, el.index)} — <img> with no alt`)
      }
    }
    expect(offenders).toEqual([])
  })
})

describe("focus is never removed", () => {
  it("outline suppression appears only on programmatic focus targets", () => {
    // DESIGN.md §3.9, implemented as a global `:focus-visible` rule in
    // index.css. The one legitimate use of `focus:outline-none` is a
    // `tabIndex={-1}` element that exists to *receive* focus from the skip
    // link — it is not a tab stop, and ringing the whole content region would
    // paint a border around the page every time the link is used.
    const offenders: string[] = []
    for (const { file, source } of PARSED) {
      for (const m of source.matchAll(/\boutline-(?:none|hidden|0)\b/g)) {
        const index = m.index ?? 0
        // Find the open tag this class sits in, by scanning back to `<`.
        const start = source.lastIndexOf("<", index)
        const openTag = start < 0 ? "" : source.slice(start, source.indexOf(">", index) + 1)
        if (/\btabIndex\s*=\s*\{-1\}/.test(openTag)) continue
        offenders.push(
          `${relativeTo(file)}:${lineOf(source, index)} — ${m[0]} outside a tabIndex={-1} focus target`,
        )
      }
    }
    expect(offenders).toEqual([])
  })

  it("index.css still carries the global focus-visible rule the above relies on", () => {
    const css = readFileSync(join(SRC, "index.css"), "utf8")
    expect(/:focus-visible\s*\{[^}]*outline:/.test(css)).toBe(true)
  })
})

describe("landmarks are named", () => {
  it("every <nav> has an accessible name", () => {
    // Several shells render more than one navigation (a sidebar and a drawer,
    // a portal nav and a breadcrumb trail). Unnamed, they are indistinguishable
    // in a screen reader's landmark list.
    const offenders: string[] = []
    for (const { file, source } of PARSED) {
      for (const el of elements(source, "nav")) {
        if (HAS_ACCESSIBLE_NAME.test(el.openTag)) continue
        offenders.push(`${relativeTo(file)}:${lineOf(source, el.index)} — <nav> with no accessible name`)
      }
    }
    expect(offenders).toEqual([])
  })

  it("every file that renders a <main> renders exactly one, and it is the skip target", () => {
    // Keyed on rendering a `<main>` rather than on mentioning MAIN_CONTENT_ID:
    // the constant is also read by `skip-link.tsx`, which points at the target
    // and correctly renders no landmark of its own. Keying on the mention made
    // this gate demand a `<main>` from the skip link itself.
    //
    // The pairing is the point. A second `<main>` gives a page two "the
    // content" landmarks, and a `<main>` that is not `MAIN_CONTENT_ID` leaves
    // the skip link pointing at nothing — `NotFound.tsx` splits into two
    // exports over exactly this, one with a frame and one without, because
    // mounting the framed copy inside a portal would have produced both faults
    // at once.
    const shells = PARSED.map(({ file, source }) => ({
      file,
      source,
      mains: elements(source, "main"),
    })).filter(({ mains }) => mains.length > 0)
    expect(shells.length).toBeGreaterThan(4)
    const offenders: string[] = []
    for (const { file, source, mains } of shells) {
      if (mains.length !== 1) {
        offenders.push(`${relativeTo(file)} — ${mains.length} <main> landmarks, expected exactly 1`)
        continue
      }
      // The target requirement is keyed on rendering a `<SkipLink>`, not on
      // rendering a `<main>`. The first draft asked every `<main>` to carry the
      // id, and the two it caught — `Login.tsx` and `ParentLogin.tsx` — are the
      // two screens in the product with no navigation landmark at all: a brand
      // mark, a heading and a form, where the first focusable element already
      // IS the form. A skip link there is a tab stop that skips nothing, and an
      // id whose only purpose is to be its target is cargo. So the rule is the
      // one that carries a consequence: a skip link must land somewhere.
      if (!/<SkipLink\b/.test(source)) continue
      if (!/\bid=\{MAIN_CONTENT_ID\}/.test(mains[0].openTag)) {
        offenders.push(
          `${relativeTo(file)} — renders a <SkipLink> whose target <main id={MAIN_CONTENT_ID}> is missing`,
        )
      }
    }
    expect(offenders).toEqual([])
  })
})

/*
 * P6.5. `sr-only` does not mean what it says on a `<table>`.
 *
 * `ChartDataTable` renders every chart's accessible copy, and it carried
 * `sr-only` on the `<table>` itself. That class is `position:absolute;
 * width:1px; height:1px; overflow:hidden; clip-path:inset(50%)` — a 1px box on
 * a block element, and **not** on a table, because CSS auto table layout treats
 * a specified width as a minimum and expands to the content regardless. The
 * real boxes measured 357px wide on the student dashboard and 316px on the
 * profile page, off the right edge at 320px.
 *
 * Invisible (clip-path paints none of it) and silent (`overflow-x: clip` on
 * html and body suppresses the scroll), so the adapt gate's geometry pass was
 * the only thing in the repository that could see it — and it had never reached
 * those surfaces (D6.10 §1). The fix is a wrapper that honours `width: 1px`.
 *
 * This pins the wrapper, because the tempting edit is to put the class back on
 * the element it describes.
 */
describe("visually-hidden content has no geometry — P6.5", () => {
  const SOURCE = readFileSync(join(process.cwd(), "src/components/ui/chart-data-table.tsx"), "utf8")

  it("hides the chart data table with a wrapper, not with sr-only on the table", () => {
    expect(SOURCE).toMatch(/<div className=\{cn\("sr-only"/)
    expect(SOURCE).not.toMatch(/<table className=\{cn\("sr-only"/)
    expect(SOURCE).not.toMatch(/<table[^>]*"sr-only/)
  })

  /*
   * The general form, so the next component to hide a table does not repeat it.
   * `sr-only` on a `<table>`, a `<thead>`, a `<tr>` or a `<td>` is the same
   * defect: none of them shrink to a 1px box.
   */
  it("puts sr-only on no table-display element anywhere in the product", () => {
    const offenders: string[] = []
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, entry.name)
        if (entry.isDirectory()) walk(full)
        else if (entry.name.endsWith(".tsx")) {
          const source = readFileSync(full, "utf8")
          for (const m of source.matchAll(/<(table|thead|tbody|tr|th|td)\b[^>]*>/g)) {
            if (/sr-only/.test(m[0])) {
              offenders.push(`${pathRelative(process.cwd(), full)}: ${m[0].slice(0, 60)}`)
            }
          }
        }
      }
    }
    walk(join(process.cwd(), "src"))
    expect(offenders).toEqual([])
  })
})
