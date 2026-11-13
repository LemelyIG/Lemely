import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { ListGroup, ListRow } from "@/components/ui/list-group"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const html = (node: Parameters<typeof renderToStaticMarkup>[0]) =>
  renderToStaticMarkup(createElement(MemoryRouter, null, node))

describe("ListGroup / ListRow (brief §3.4)", () => {
  it("a labelled section with rows", () => {
    const out = html(createElement(ListGroup, { label: "Subjects", children: createElement(ListRow, { title: "Physics", to: "/student/subject/0625" }) }))
    expect(out).toMatch(/<section[^>]*aria-labelledby="[^"]+"/)
    expect(out).toContain(">Subjects<")
    expect(out).toMatch(/<a[^>]*href="\/student\/subject\/0625"/)
  })
  it("rows carry the native class and their line count", () => {
    const out = html(createElement(ListGroup, { children: createElement(ListRow, { title: "A", subtitle: "B" }) }))
    expect(out).toContain("lm-native-group")
    expect(out).toMatch(/class="[^"]*\blm-list-row\b[^"]*\blm-native-row\b[^"]*" data-lines="2"/)
  })
})

describe("grouped-list CSS (preview 4447a571, variant-a.css section 4)", () => {
  const css = readFileSync(join(SRC, "index.css"), "utf8")
  const start = css.indexOf("/* ── Native frame: grouped lists")
  const block = css.slice(start, css.indexOf("/* ── Native frame:", start + 1))
  /** The body of the `@media (max-width: 720px)` block that follows the section marker, up to its matching brace. */
  const MEDIA_OPEN = "@media (max-width: 720px) {"
  const mediaStart = css.indexOf(MEDIA_OPEN, start)
  const mediaBody = (() => {
    let depth = 1
    for (let i = mediaStart + MEDIA_OPEN.length; i < css.length; i++) {
      if (css[i] === "{") depth++
      else if (css[i] === "}" && --depth === 0) return css.slice(mediaStart + MEDIA_OPEN.length, i)
    }
    throw new Error("unterminated @media block")
  })()
  /** Selector lists of the flat rules inside the media body (no nested at-rules in this block). */
  const mediaSelectors = [...mediaBody.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/([^{}]+)\{[^{}]*\}/g)].flatMap((m) =>
    m[1].split(/,(?![^(]*\))/).map((sel) => sel.trim()),
  )
  /** Task 8: the sheet is the second scope root (sheets portal outside <main>). */
  const sheetStart = css.indexOf("/* ── Native frame: grouped lists inside sheets")
  const sheetEnd = css.indexOf("/* The student Overview's subject ledger", sheetStart)
  const sheetBlock = css.slice(sheetStart, sheetEnd)
  const sheetSelectors = [...sheetBlock.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/([^{}@]+)\{[^{}]*\}/g)].flatMap((m) =>
    m[1].split(/,(?![^(]*\))/).map((sel) => sel.trim()),
  )
  const ALLOWED_SELECTOR_START = [
    ':root[data-platform="ios"]',
    ':root[data-platform="android"]',
    ':root[data-theme="dark"][data-platform="ios"]',
    ':root[data-theme="dark"][data-platform="android"]',
    ':root:is([data-platform="ios"], [data-platform="android"])',
  ]
  /** The two rules documented as harmless outside the gate: a no-op custom property and the desktop divider. */
  const HARMLESS_UNGATED = [".lm-press { --lm-press: 1; }", ".lm-list-row + .lm-list-row { border-top: 1px solid var(--md-outline-variant); }"]

  it("the phone-width media block is found and has rules", () => {
    expect(mediaStart).toBeGreaterThan(start)
    expect(mediaSelectors.length).toBeGreaterThan(10)
  })
  it("every rule selector in the media block is gated on data-platform", () => {
    for (const sel of mediaSelectors) {
      expect(ALLOWED_SELECTOR_START.some((p) => sel.startsWith(p)), `ungated selector: ${sel}`).toBe(true)
    }
  })
  it("no lm-native- selector appears outside the media block except the two documented harmless rules", () => {
    const mediaEnd = mediaStart + MEDIA_OPEN.length + mediaBody.length + 1
    const outside = (css.slice(0, mediaStart) + css.slice(mediaEnd, sheetStart) + css.slice(sheetEnd)).replace(/\/\*[\s\S]*?\*\//g, "")
    // Task 10's classes only; other native-frame tasks own their own lm-native-* selectors.
    const offenders = [...outside.matchAll(/([^{};]+)\{/g)]
      .map((m) => m[1].trim())
      .filter((sel) => /lm-native-(card|group|row)\b/.test(sel))
    expect(offenders).toEqual([])
    for (const rule of HARMLESS_UNGATED) {
      expect(block, `documented harmless rule missing: ${rule}`).toContain(rule)
    }
  })
  it("the card and group rules are scoped to the shell's main column", () => {
    for (const sel of mediaSelectors.filter((s) => /lm-native-(card|group|row)\b/.test(s))) {
      expect(sel, `unscoped native card/group/row selector: ${sel}`).toContain(".lm-native-main ")
    }
  })
  it("page ground has one source: Task 5's --native-page tokens, none declared here", () => {
    expect(block).not.toContain("lm-native-page")
    expect(css).toMatch(/--native-page-ios: var\(--md-surface-container\)/)
    expect(css).toMatch(/--native-page-android: var\(--md-surface-container-low\)/)
  })
  it("the sheet block exists, sits after Task 10's block, and is phone-only", () => {
    expect(sheetStart).toBeGreaterThan(mediaStart)
    expect(sheetBlock).toContain("@media (max-width: 720px) {")
    expect(sheetSelectors.length).toBeGreaterThan(10)
  })
  it("every sheet rule is gated on data-platform and scoped to .lm-sheet", () => {
    for (const sel of sheetSelectors) {
      expect(ALLOWED_SELECTOR_START.some((p) => sel.startsWith(p)), `ungated sheet selector: ${sel}`).toBe(true)
      expect(sel, `unscoped sheet selector: ${sel}`).toContain(".lm-sheet ")
    }
  })
  it("sheet gutter maths: iOS inset groups need no margin, Android bleeds by the 16px body padding", () => {
    expect(sheetBlock).not.toMatch(/\.lm-sheet \{/)
    expect(sheetBlock).toMatch(/:root\[data-platform="ios"\] \.lm-sheet :is\(\.lm-native-card, \.lm-native-group\) \{[^}]*border-radius: var\(--native-group-radius-ios\)/)
    expect(sheetBlock).toMatch(/:root\[data-platform="android"\] \.lm-sheet \.lm-native-group \{[^}]*border-radius: 0;[^}]*margin-inline: calc\(-1 \* var\(--space-4\)\)/)
    expect(sheetBlock).toMatch(/:root\[data-platform="ios"\] \.lm-sheet \.lm-native-row \+ \.lm-native-row::before \{[^}]*inset-inline: var\(--native-sep-inset-ios\) 0/)
    for (const n of [1, 2, 3]) {
      expect(sheetBlock).toMatch(new RegExp(`\\.lm-sheet \\.lm-native-row\\[data-lines="${n}"\\] \\{[^}]*min-height: var\\(--native-row-${n}-android\\)`))
    }
  })
  it("iOS: 16px page margin, 12px groups, 44px rows, hairline separators inset 16px", () => {
    expect(block).toMatch(/:root\[data-platform="ios"\] \.lm-native-main \{[^}]*padding-left: max\(var\(--native-group-inset-ios\), env\(safe-area-inset-left\)\)/)
    expect(block).toMatch(/:root\[data-platform="ios"\] \.lm-native-main :is\(\.lm-native-card, \.lm-native-group\) \{[^}]*border-radius: var\(--native-group-radius-ios\)/)
    expect(block).toMatch(/:root\[data-platform="ios"\] \.lm-native-main \.lm-native-row \{[^}]*min-height: var\(--native-row-min-ios\)/)
    expect(block).toMatch(/:root\[data-platform="ios"\] \.lm-native-main \.lm-native-row \+ \.lm-native-row::before \{[^}]*inset-inline: var\(--native-sep-inset-ios\) 0;[^}]*block-size: var\(--native-hairline\);[^}]*background: var\(--md-outline\)/)
  })
  it("divider reset: a native group's own rows drop their desktop dividers", () => {
    expect(block).toMatch(/:root:is\(\[data-platform="ios"\], \[data-platform="android"\]\) \.lm-native-main \.lm-native-group > \.lm-native-row \{[^}]*border-top: 0;[^}]*border-bottom: 0/)
  })
  it("Android: full-bleed, square, 14px gutter kept as a transparent border on cards, 56/72/88 rows, no separators", () => {
    expect(block).toMatch(/:root\[data-platform="android"\] \.lm-native-main \.lm-native-card:not\(\[data-native-bleed="off"\]\) \{[^}]*inline-size: calc\(100% \+ var\(--native-bleed-l\) \+ var\(--native-bleed-r\)\);[^}]*margin-left: calc\(-1 \* var\(--native-bleed-l\)\);[^}]*margin-right: calc\(-1 \* var\(--native-bleed-r\)\);[^}]*border-left: var\(--native-bleed-l\) solid transparent;\s*border-right: var\(--native-bleed-r\) solid transparent/)
    expect(block).toMatch(/:root\[data-platform="android"\] \.lm-native-main \.lm-native-group \{[^}]*margin-left: calc\(-1 \* var\(--native-bleed-l\)\)/)
    for (const n of [1, 2, 3]) {
      expect(block).toMatch(new RegExp(`:root\\[data-platform="android"\\] \\.lm-native-main \\.lm-native-row\\[data-lines="${n}"\\] \\{[^}]*min-height: var\\(--native-row-${n}-android\\)`))
    }
    expect(block).toMatch(/:root\[data-platform="android"\] \.lm-native-main \.lm-list-row \+ \.lm-list-row \{[^}]*border-top: 0/)
  })
})

describe("Card on the native frame", () => {
  const card = readFileSync(join(SRC, "components/ui/card.tsx"), "utf8")
  it("carries the native card class; design A classes unchanged", () => {
    expect(card).toContain('"bg-surface-container-lowest border border-outline-variant rounded-lg lm-native-card"')
  })
})

describe("native class and data-lines hooks stay on the shared components", () => {
  const read = (rel: string) => readFileSync(join(SRC, rel), "utf8")
  it("SettingsRows: the group and each row carry lm-native-group / lm-native-row and data-lines", () => {
    const src = read("portals/settings/SettingsRows.tsx")
    expect(src).toContain('"lm-native-group flex flex-col')
    expect(src).toContain('"lm-native-row flex flex-col')
    expect(src).toContain("data-lines={description ? 2 : 1}")
  })
  it("loading-shapes: the skeleton list group and rows carry the native classes and data-lines", () => {
    const src = read("components/ui/loading-shapes.tsx")
    expect(src).toContain('"lm-native-group overflow-hidden')
    expect(src).toContain('data-lines="2"')
    expect(src).toContain('"lm-native-row flex items-center')
  })
  it("Subject stat tiles opt out of the native bleed so they stay side by side", () => {
    const src = readFileSync(join(SRC, "portals/student/screens/Subject.tsx"), "utf8")
    expect(src.match(/<Card data-native-bleed="off" className="min-w-33/g)).toHaveLength(2)
  })
  it("PortalShell: the main column carries lm-native-main and the page class is gone", () => {
    const src = read("components/shell/PortalShell.tsx")
    expect(src).not.toContain("lm-native-page")
    expect(src).toMatch(/className="lm-native-main @container\/home/)
  })
})
