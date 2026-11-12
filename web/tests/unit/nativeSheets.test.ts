import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const read = (p: string) => readFileSync(join(SRC, p), "utf8")
const css = read("index.css")

describe("BottomSheetSurface (Task 6)", () => {
  const src = read("components/ui/bottom-sheet.tsx")
  it("drags only from the grabber and header region, never from content text", () => {
    expect(src).toContain("data-sheet-drag-region")
    expect(src).not.toMatch(/onPointerDown=\{[^}]*\}[^>]*data-sheet-body/)
  })
  it("Android-only haptic on snap", () => {
    expect(src).toMatch(/readPlatform\(\) === "android"[^\n]*haptic\("tap"\)/)
  })
  it("iOS keyboard: positions by visualViewport", () => {
    expect(src).toContain("window.visualViewport")
    expect(src).toContain("--lm-keyboard-inset")
  })
})

describe("sheet CSS", () => {
  const block = css.slice(css.indexOf("/* ── Native frame: sheets"))
  it("top radius is the card radius; grabber sizes per platform", () => {
    expect(block).toMatch(/\.lm-sheet \{[^}]*border-start-start-radius: var\(--radius-card\);[^}]*border-start-end-radius: var\(--radius-card\);/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-sheet-grabber \{[^}]*inline-size: var\(--native-grabber-w-ios\);[^}]*block-size: var\(--native-grabber-h-ios\)/)
    expect(block).toMatch(/\[data-platform="android"\] \.lm-sheet-grabber \{[^}]*inline-size: var\(--native-grabber-w-android\);[^}]*block-size: var\(--native-grabber-h-android\)/)
  })
  it("iOS scales the page back at the large detent, pivoting on the visible top; reduced motion keeps it instant", () => {
    expect(block).toMatch(/:root\[data-platform="ios"\]\[data-sheet-depth\] #root \{[^}]*scale: var\(--native-sheet-scale-back\)/)
    expect(block).toMatch(/:root\[data-platform="ios"\] #root \{[^}]*transform-origin: 50% calc\(var\(--native-sheet-sy, 0px\) \+ env\(safe-area-inset-top\)\)/)
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*#root[\s\S]*transition: none/)
  })
  it("per-platform large detent, motion and grabber (preview 4447a571)", () => {
    expect(block).toMatch(/:root\[data-platform="ios"\] \{[^}]*--native-sheet-large: var\(--native-sheet-large-ios\);[^}]*--native-sheet-dur: var\(--dur-sheet-ios\);[^}]*--native-sheet-ease: var\(--ease-ios-spring\)/)
    expect(block).toMatch(/:root\[data-platform="android"\] \{[^}]*--native-sheet-large: var\(--native-sheet-large-android\);[^}]*--native-sheet-dur: var\(--dur-sheet-android\);[^}]*--native-sheet-ease: var\(--ease-m3-emphasized-decelerate\)/)
    expect(block).toMatch(/\.lm-sheet \{[^}]*background: var\(--md-surface-container-low\)/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-sheet-grabber \{[^}]*margin-block: var\(--native-grabber-gap-ios\)/)
  })
  it("the sheet sits above the keyboard", () => {
    expect(block).toContain("bottom: var(--lm-keyboard-inset, 0px)")
  })
})

describe("ui/sheet.tsx (Task 6)", () => {
  const src = read("components/ui/sheet.tsx")
  it("bottom and adaptive sheets use BottomSheetSurface on the native frame", () => {
    expect(src).toContain("useNativeFrame()")
    expect(src).toMatch(/native && \(side === "bottom" \|\| side === "adaptive"\)/)
    expect(src).toContain("<BottomSheetSurface")
  })
})
