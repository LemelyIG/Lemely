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
    expect(src).toContain('closest("[data-sheet-drag-region]")')
  })
  it("leaves header buttons, links and fields their own click", () => {
    expect(src).toContain('const INTERACTIVE = "button, a, input, select, textarea, [role=button]"')
    expect(src).toMatch(/target\.closest\(INTERACTIVE\)/)
    expect(src).toContain("e.button > 0")
  })
  it("the sheet follows the finger with no transition while dragging", () => {
    expect(src).toContain('setAttribute("data-dragging", "")')
    expect(src).toContain('removeAttribute("data-dragging")')
  })
  it("the scale-back hook is guarded on the phone media query", () => {
    expect(src).toMatch(/useSheetScaleBack[\s\S]*window\.matchMedia\(PHONE_MEDIA\)\.matches/)
  })
  it("Android-only haptic on snap", () => {
    expect(src).toContain('nativeHaptic("tap")')
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
  it("no transition while dragging; the drag region is a finger tall and owns touch-action", () => {
    expect(block).toMatch(/\.lm-sheet\[data-dragging\] \{[^}]*transition: none/)
    expect(block).toMatch(/\[data-sheet-drag-region\] \{[^}]*min-block-size: var\(--native-sheet-drag-min\);[^}]*touch-action: none/)
    expect(block).toMatch(/:root\[data-platform="ios"\] \{[^}]*--native-sheet-drag-min: var\(--native-iconbtn-ios\)/)
    expect(block).not.toMatch(/\.lm-sheet-grabber \{[^}]*touch-action/)
    expect(block).toMatch(/\.lm-sheet-grabber \{[^}]*border-radius: var\(--radius-pill\)/)
  })
  it("the iOS scale-back rules are phone-only", () => {
    expect(block).toMatch(/@media \(max-width: 720px\) \{\s*:root\[data-platform="ios"\] #root \{[\s\S]*?\[data-sheet-depth\] body \{[^}]*\}\s*\}/)
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
  it("does not forward the desktop panel class to the native surface; the body carries the inset", () => {
    const native = src.slice(src.indexOf("<BottomSheetSurface"), src.indexOf("</BottomSheetSurface>"))
    expect(native).not.toContain("className={className}")
    expect(native).toContain('bodyClassName="p-6"')
    expect(native).toContain("tabIndex={-1}")
  })
})

describe("Modal on the native frame (Task 7)", () => {
  const src = read("components/ui/modal.tsx")
  it("keeps one dialog contract and only swaps the surface", () => {
    expect(src).toContain("useNativeFrame()")
    expect(src.match(/role: "dialog"/g)?.length).toBe(1)
    expect(src).not.toContain('role="dialog"')
    expect(src).toContain("<BottomSheetSurface")
    expect(src).toMatch(/detents=\{size === "lg" \? \["medium", "large"\] : \["content"\]\}/)
    expect(src).toMatch(/dismissible=\{dismissible\}/)
  })
  it("size lg opens at medium and drags to large (D10)", () => {
    expect(src).toMatch(/initialDetent=\{size === "lg" \? "medium" : "content"\}/)
  })
  it("call sites are untouched: the public props are unchanged", () => {
    expect(src).toMatch(/export interface ModalProps \{[\s\S]*open: boolean[\s\S]*onClose: \(\) => void[\s\S]*title: ReactNode/)
  })
})

describe("ConfirmModal (Task 7)", () => {
  const src = read("components/ui/confirm-modal.tsx")
  it("iOS native uses an action sheet with Cancel in its own group", () => {
    expect(src).toMatch(/platform === "ios"[\s\S]*presentation="action-sheet"/)
    expect(src).toContain("lm-action-sheet-cancel")
  })
  it("the action sheet's visible title is aria-hidden; Modal's sr-only copy labels the dialog", () => {
    expect(src).toMatch(/<div aria-hidden="true"[^>]*>\s*<p[^>]*>\{title\}<\/p>/)
    const modal = read("components/ui/modal.tsx")
    expect(modal).toMatch(/presentation === "action-sheet"[\s\S]*<h2 id=\{titleId\} className="sr-only">/)
    expect(modal).toMatch(/<p id=\{descriptionId\} className="sr-only">/)
  })
  it("stays non-dismissible (no scrim close, no drag, no grabber)", () => {
    expect(src).toContain("dismissible={false}")
  })
  it("action-sheet rows use the native tokens", () => {
    expect(css).toMatch(/\.lm-action-sheet-row \{[^}]*min-block-size: var\(--native-action-row-h\)/)
    expect(css).toMatch(/\.lm-action-sheet-cancel \{[^}]*font-weight: 600/)
  })
})
