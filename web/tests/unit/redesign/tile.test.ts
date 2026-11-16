import { Cards } from "@phosphor-icons/react"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { Tile } from "@/components/redesign"

const html = (p: Parameters<typeof Tile>[0]) => renderToStaticMarkup(createElement(MemoryRouter, null, createElement(Tile, p)))

describe("Tile", () => {
  it("a tinted link tile with a big faint icon in its corner", () => {
    const out = html({ icon: Cards, title: "Flashcards", status: "26 due today", tone: "violet", to: "/student/flashcards" })
    expect(out).toMatch(/<a class="rd-tile" data-tone="violet"[^>]*href="\/student\/flashcards"/)
    expect(out).toContain('<b class="rd-tile-title">Flashcards</b>')
    expect(out).toMatch(/<span class="rd-tile-art" aria-hidden="true"><svg[^>]*width="64"/)
  })
  it("a big row tile with a leading icon and a chevron", () => {
    const out = html({ icon: Cards, title: "Homework", status: "Due Friday", tone: "tide", big: true, onClick: () => {} })
    expect(out).toMatch(/<button type="button" class="rd-tile rd-tile-big" data-tone="tide">/)
    expect(out).toContain("rd-tile-ic")
    expect(out).toContain("rd-chev")
  })
  it("disabled is not a control", () => {
    const out = html({ icon: Cards, title: "Placement test", tone: "gold", to: "/x", disabled: true })
    expect(out).toMatch(/^<div class="rd-tile" data-tone="gold" aria-disabled="true">/)
    expect(out).not.toContain("href=")
  })
  it("disabled drops the click handler and stays a div even with onClick", () => {
    const out = html({ icon: Cards, title: "Placement test", tone: "sea", onClick: () => {}, disabled: true })
    expect(out).not.toContain("<button")
    expect(out).toContain('aria-disabled="true"')
  })
  it("a tile with neither route nor handler is a plain div", () => {
    expect(html({ icon: Cards, title: "Info", tone: "mint" })).toMatch(/^<div class="rd-tile" data-tone="mint">/)
  })
  it("omits the status line when none is given", () => {
    expect(html({ icon: Cards, title: "Info", tone: "mint" })).not.toContain("rd-tile-status")
  })
})

const ROOT = fileURLToPath(new URL("../../../", import.meta.url))
const css = readFileSync(join(ROOT, "src/components/redesign/redesign.css"), "utf8")
const tileCss = css.slice(css.indexOf("/* ── Tile"))
const stripped = tileCss.replace(/\/\*[\s\S]*?\*\//g, "")
const rule = (sel: string) => stripped.match(new RegExp(`${sel.replace(/[.[\]"=():-]/g, "\\$&")}\\s*\\{([^}]*)\\}`))?.[1] ?? ""

describe("Tile css", () => {
  it("has a tile block", () => {
    expect(tileCss.length).toBeGreaterThan(0)
  })
  it("holds exactly one scoped literal: the violet tone, light and dark, labelled with the decision", () => {
    const lits = [...stripped.matchAll(/oklch\(\s*[\d.]+\s+[\d.]+\s+[\d.]+\s*\)|#[0-9a-fA-F]{3,8}\b/g)].map((m) => m[0])
    expect(lits).toHaveLength(4)
    expect(rule('.rd-tile[data-tone="violet"]')).toMatch(/oklch\(0\.95 0\.03 300\)/)
    expect(rule(':root[data-theme="dark"] .rd-tile[data-tone="violet"]')).toMatch(/oklch\(0\.32 0\.05 300\)/)
    expect(tileCss).toMatch(/decision 6/i)
  })
  it("keeps the literal out of the tsx", () => {
    const tsx = readFileSync(join(ROOT, "src/components/redesign/Tile.tsx"), "utf8")
    expect(tsx).not.toMatch(/oklch|#[0-9a-fA-F]{3,8}\b/)
  })
  it("disabled is visibly muted and shows not-allowed (it is a div, so it has no hover or press rules)", () => {
    const d = rule('.rd-tile[aria-disabled="true"]')
    expect(d).toMatch(/opacity:\s*0?\.[45]/)
    expect(d).toContain("cursor: not-allowed")
    expect(d).toContain("filter: saturate(0.6)")
  })
  it("hover and press apply only to real controls, never to a div, and win over the base", () => {
    expect(stripped).toMatch(/a\.rd-tile:hover,\s*button\.rd-tile:hover\s*\{[^}]*brightness\(0\.98\)/)
    expect(stripped).toMatch(/a\.rd-tile:active,\s*button\.rd-tile:active\s*\{[^}]*scale\(0\.97\)/)
    // the 150ms press timing is the --dur-fast token (no per-state override that could lose a tie)
    expect(rule(".rd-tile")).toContain("var(--dur-fast)")
  })
  it("state rules come after the base and the big variant so they win ties", () => {
    const at = (s: string) => stripped.indexOf(s)
    expect(at("a.rd-tile:active")).toBeGreaterThan(at(".rd-tile-big {"))
    expect(at('.rd-tile[aria-disabled="true"]')).toBeGreaterThan(at(".rd-tile-big {"))
  })
  it("no unscoped hover or press rule can reach the disabled div", () => {
    expect(stripped).not.toMatch(/(^|[\s,}])\.rd-tile:(hover|active)/m)
  })
})
