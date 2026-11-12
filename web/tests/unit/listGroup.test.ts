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
  it("every native rule sits inside the phone-width media block", () => {
    const media = block.indexOf("@media (max-width: 720px) {")
    expect(media).toBeGreaterThan(-1)
    expect(block.slice(0, media)).not.toContain("lm-native-")
  })
  it("page ground has one source: Task 5's --native-page tokens, none declared here", () => {
    expect(block).not.toContain("lm-native-page")
    expect(css).toMatch(/--native-page-ios: var\(--md-surface-container\)/)
    expect(css).toMatch(/--native-page-android: var\(--md-surface-container-low\)/)
  })
  it("iOS: 16px page margin, 12px groups, 44px rows, hairline separators inset 16px", () => {
    expect(block).toMatch(/:root\[data-platform="ios"\] \.lm-native-main \{[^}]*padding-inline: var\(--native-group-inset-ios\)/)
    expect(block).toMatch(/:root\[data-platform="ios"\] :is\(\.lm-native-card, \.lm-native-group\) \{[^}]*border-radius: var\(--native-group-radius-ios\)/)
    expect(block).toMatch(/:root\[data-platform="ios"\] \.lm-native-row \{[^}]*min-height: var\(--native-row-min-ios\)/)
    expect(block).toMatch(/:root\[data-platform="ios"\] \.lm-native-row \+ \.lm-native-row::before \{[^}]*inset-inline: var\(--native-sep-inset-ios\) 0;[^}]*block-size: var\(--native-hairline\);[^}]*background: var\(--md-outline\)/)
  })
  it("Android: full-bleed, square, 14px gutter kept as a transparent border on cards, 56/72/88 rows, no separators", () => {
    expect(block).toMatch(/:root\[data-platform="android"\] \.lm-native-card \{[^}]*margin-inline: calc\(-1 \* var\(--native-gutter-android\)\);[^}]*border-inline: var\(--native-gutter-android\) solid transparent/)
    expect(block).toMatch(/:root\[data-platform="android"\] \.lm-native-group \{[^}]*margin-inline: calc\(-1 \* var\(--native-gutter-android\)\)/)
    for (const n of [1, 2, 3]) {
      expect(block).toMatch(new RegExp(`:root\\[data-platform="android"\\] \\.lm-native-row\\[data-lines="${n}"\\] \\{[^}]*min-height: var\\(--native-row-${n}-android\\)`))
    }
    expect(block).toMatch(/:root\[data-platform="android"\] \.lm-list-row \+ \.lm-list-row \{[^}]*border-top: 0/)
  })
})

describe("Card on the native frame", () => {
  const card = readFileSync(join(SRC, "components/ui/card.tsx"), "utf8")
  it("carries the native card class; design A classes unchanged", () => {
    expect(card).toContain('"bg-surface-container-lowest border border-outline-variant rounded-lg lm-native-card"')
  })
})
