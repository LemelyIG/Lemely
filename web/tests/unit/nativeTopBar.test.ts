import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { largeTitleCollapsed, titleLevelFor } from "@/components/shell/largeTitle"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const css = readFileSync(join(SRC, "index.css"), "utf8")
const bar = readFileSync(join(SRC, "components/shell/ShellTopBar.tsx"), "utf8")
const portalShell = readFileSync(join(SRC, "components/shell/PortalShell.tsx"), "utf8")

describe("title level comes from the trail (D2)", () => {
  it("section pages are roots, drilled-in pages are details", () => {
    expect(titleLevelFor([])).toBe("root")
    expect(titleLevelFor([{ label: "Classes" }])).toBe("root")
    expect(titleLevelFor([{ label: "Practice" }, { label: "0606" }])).toBe("detail")
  })
})

describe("one collapse threshold: the large title's bottom crossing the bar", () => {
  it.each([
    [0, 41, false],
    [40, 41, false],
    [41, 41, true],
    [300, 82, true],
  ])("scrollY %i, title %ipx -> %s", (y, h, want) => {
    expect(largeTitleCollapsed(y, h)).toBe(want)
  })
  it("an unmeasured title (0px) never reports collapsed at the top", () => {
    expect(largeTitleCollapsed(0, 0)).toBe(false)
  })
})

describe("ShellTopBar native markup", () => {
  it("marks the bar and renders an aria-hidden large title outside main (D3)", () => {
    expect(bar).toContain("lm-native-bar")
    expect(bar).toContain("data-title-level={level}")
    expect(bar).toContain("data-collapsed={collapsed}")
    expect(bar).toMatch(/<p[^>]*aria-hidden="true"[^>]*data-shell-large-title/)
    // Placement: the bar (and its large title) precede <main> in the shell.
    expect(portalShell.indexOf("<ShellTopBar")).toBeGreaterThan(-1)
    expect(portalShell.indexOf("<ShellTopBar")).toBeLessThan(portalShell.indexOf("<main"))
  })
  it("renders the native back only for details, from backFallback and the parent crumb", () => {
    expect(bar).toMatch(/level === "detail" \? \(\s*<NativeBack fallback=\{backFallback\} label=\{backLabel\}/)
  })
  it("marks the settings and account actions so details can hide them", () => {
    expect(bar).toContain('data-shell-action="settings"')
    expect(bar).toContain('data-shell-action="account"')
  })
  it("one back logic: BackControl and NativeBack share useBackAction", () => {
    const back = readFileSync(join(SRC, "components/ui/back-control.tsx"), "utf8")
    const native = readFileSync(join(SRC, "components/shell/NativeBack.tsx"), "utf8")
    expect(back).toMatch(/export function useBackAction\(fallback: string\)/)
    expect(back).toContain("useBackAction(fallback)")
    expect(native).toContain("useBackAction(fallback)")
    expect(native).not.toContain("backTarget(")
  })
})

describe("native bar CSS (preview 4447a571)", () => {
  const block = css.slice(css.indexOf("/* ── Native frame: top bar"))
  it("is sticky under the status bar, phone width and ios|android only", () => {
    expect(block).toMatch(/@media \(max-width: 720px\)/)
    expect(block).toMatch(/:root:is\(\[data-platform="ios"\], \[data-platform="android"\]\) \.lm-native-bar \{[^}]*position: sticky;[^}]*top: 0;[^}]*padding-top: env\(safe-area-inset-top\);/)
  })
  it("the bar's surface is a layer under its content, transparent at rest", () => {
    expect(block).toMatch(/\.lm-native-bar::before \{[^}]*z-index: var\(--z-index-base\);[^}]*opacity: 0;/)
    expect(block).toMatch(/\.lm-native-bar:is\(\[data-collapsed="true"\], \[data-title-level="detail"\]\[data-stuck="true"\]\)::before \{[^}]*opacity: 1;/)
  })
  it("iOS raises to glass with a hairline; Android to surface-container", () => {
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-bar::before \{[^}]*background: color-mix\(in oklch, var\(--md-surface-container-lowest\) var\(--native-glass-mix\), transparent\);[^}]*backdrop-filter: blur\(var\(--blur-nav\)\) saturate\(var\(--native-glass-saturate\)\);[^}]*border-block-end: var\(--native-hairline\) solid var\(--md-outline-variant\)/)
    expect(block).toMatch(/\[data-theme="dark"\]\[data-platform="ios"\] \.lm-native-bar::before \{[^}]*var\(--md-surface-container-low\) var\(--native-glass-mix\)/)
    expect(block).toMatch(/\[data-platform="android"\] \.lm-native-bar::before \{[^}]*background: var\(--md-surface-container\)/)
  })
  it("inline title: 17/22 Schibsted 600; iOS centred between the 144px (root) and 124px (detail) insets", () => {
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-inline-title \{[^}]*inset-inline: var\(--native-title-inset-ios\)/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-bar\[data-title-level="detail"\] \.lm-native-inline-title \{[^}]*inset-inline: var\(--native-title-inset-detail-ios\)/)
  })
  it("details show back, title and one action", () => {
    expect(block).toMatch(/\.lm-native-bar\[data-title-level="detail"\] :is\(\[data-shell-action="settings"\], \[data-shell-action="account"\]\) \{[^}]*display: none/)
  })
  it("details hide Create too; Create has left the phone bar, so no root bar needs a wide title inset", () => {
    expect(block).toMatch(/\.lm-native-bar\[data-title-level="detail"\] \[data-shell-action="create"\] \{[^}]*display: none/)
    expect(css).not.toContain("--native-title-inset-ios-wide")
    expect(block).not.toContain(":has([data-shell-action=\"create\"])")
  })
  it("the bar has no gap: the 44/48px actions butt up and the title box is inset (preview .as-bar)", () => {
    expect(block).toMatch(/\.lm-native-bar \{[^}]*gap: 0;/)
  })
  it("side safe areas widen the bar and the large title", () => {
    expect(block).toMatch(/padding-left: max\(var\(--native-bar-pad-inline\), env\(safe-area-inset-left\)\);\s*padding-right: max\(var\(--native-bar-pad-inline\), env\(safe-area-inset-right\)\)/)
    expect(block).toMatch(/padding-left: max\(var\(--space-4\), env\(safe-area-inset-left\)\)/)
  })
  it("the Android back arrow colour out-specifies the trailing-icon rule", () => {
    expect(block).toMatch(/\[data-platform="android"\] \.lm-native-bar \.lm-native-back \{ color: var\(--md-on-surface\); \}/)
  })
  it("the back control centres its parts and the iOS label is capped with an ellipsis", () => {
    expect(block).toMatch(/\.lm-native-back \{ margin-inline-end: auto; align-items: center; \}/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-back-label \{[^}]*max-inline-size: var\(--native-back-label-max\);[^}]*text-overflow: ellipsis/)
    expect(css).toMatch(/--native-back-label-max: 96px;/)
  })
  it("the iOS back rule is not out-specified by the iconbtn sizing rule", () => {
    expect(block).toMatch(/:root\[data-platform="ios"\] \.lm-native-bar \.lm-native-back \{\s*inline-size: auto;/)
  })
  it("--lm-large-title-block has a default so animation-range is valid on the first frame", () => {
    expect(block).toMatch(/:root \{ --lm-large-title-block: 0px; \}/)
  })
  it("scroll-driven fades only where supported and motion is allowed: 70-100% for the bar, the whole exit for the large title", () => {
    expect(block).toMatch(/@supports \(animation-timeline: scroll\(\)\)\s*\{\s*@media \(prefers-reduced-motion: no-preference\) and \(max-width: 720px\)/)
    expect(block).toContain("animation-timeline: scroll(root block)")
    expect(block).toContain("animation-range: calc(var(--lm-large-title-block) * 0.7) var(--lm-large-title-block)")
    expect(block).toContain("animation-range: 0px var(--lm-large-title-block)")
  })
})
