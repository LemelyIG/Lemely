import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
export const css = readFileSync(join(SRC, "index.css"), "utf8")

const TOKENS = [
  // header
  "--native-large-title-size", "--native-large-title-lh", "--native-large-title-pad",
  "--native-inline-title-size", "--native-inline-title-lh",
  "--native-bar-h-ios", "--native-bar-h-android", "--native-bar-pad-inline",
  "--native-title-inset-ios", "--native-title-inset-ios-wide", "--native-title-inset-detail-ios",
  "--native-iconbtn-ios", "--native-iconbtn-android", "--native-bar-icon",
  // tab bar
  "--native-tabbar-h-ios", "--native-tabbar-h-android", "--native-tab-label-ios", "--native-tab-label-android",
  "--native-tab-icon", "--native-tab-pill-w", "--native-tab-pill-h", "--native-tab-press-opacity-ios",
  // sheets
  "--native-grabber-w-ios", "--native-grabber-h-ios", "--native-grabber-gap-ios",
  "--native-grabber-w-android", "--native-grabber-h-android", "--native-grabber-gap-android",
  "--native-sheet-medium", "--native-sheet-large-ios", "--native-sheet-large-android",
  "--native-sheet-scale-back", "--native-sheet-backdrop", "--native-action-row-h",
  "--dur-sheet-ios", "--dur-sheet-android",
  "--ease-ios-spring", "--ease-m3-emphasized", "--ease-m3-emphasized-decelerate",
  // grouped content
  "--native-group-radius-ios", "--native-group-inset-ios", "--native-gutter-android", "--native-sep-inset-ios",
  "--native-row-min-ios", "--native-row-1-android", "--native-row-2-android", "--native-row-3-android",
  // glass
  "--native-glass-mix", "--native-glass-saturate", "--native-hairline",
  // press
  "--native-press-dim", "--native-press-ink-light", "--native-press-ink-dark", "--native-press-scale",
  "--native-state-pressed", "--native-ripple-dur",
  // gestures
  "--native-parallax", "--native-ptr-threshold", "--native-ptr-hold-ios", "--native-ptr-hold-android",
]

function tokenBlock(): string {
  const start = css.indexOf("/* ── Native frame tokens")
  if (start < 0) return ""
  const open = css.indexOf(":root {", start)
  return css.slice(open, css.indexOf("\n}", open) + 2)
}

describe("native frame tokens (Task 0)", () => {
  it("one :root block declares every token once", () => {
    const block = tokenBlock()
    expect(block).not.toBe("")
    for (const t of TOKENS) {
      expect(block, t).toMatch(new RegExp(`${t}:\\s*[^;]+;`))
      expect(css.split(`${t}:`).length - 1, `${t} declared once`).toBe(1)
    }
  })

  it("the large title is display size (Bricolage is allowed at 28px and up)", () => {
    const size = tokenBlock().match(/--native-large-title-size:\s*(\d+)px/)
    expect(Number(size?.[1])).toBeGreaterThanOrEqual(28)
  })
})

describe("platform variants (Task 1)", () => {
  it("declares ios:, android: and native: on html[data-platform]", () => {
    expect(css).toContain('@custom-variant ios (&:where([data-platform="ios"], [data-platform="ios"] *));')
    expect(css).toContain('@custom-variant android (&:where([data-platform="android"], [data-platform="android"] *));')
    expect(css).toMatch(
      /@custom-variant native \{\s*@media \(max-width: 720px\) \{\s*&:where\(\[data-platform="ios"\], \[data-platform="ios"\] \*, \[data-platform="android"\], \[data-platform="android"\] \*\) \{\s*@slot;/,
    )
  })
  it("720 stays one below --breakpoint-shell-sm", () => {
    expect(css).toContain("--breakpoint-shell-sm: 721px;")
  })
})
