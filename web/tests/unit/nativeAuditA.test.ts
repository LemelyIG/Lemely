import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { TitledCard } from "@/components/ui/card"
import { NativeFrameProvider } from "@/lib/useNativeFrame"
import { stateDirection } from "@/lib/nav/navDirectionState"
import { resolveDirection } from "@/lib/nav/navigationDirection"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const read = (p: string) => readFileSync(join(SRC, p), "utf8")
const css = read("index.css")

describe("native shell frame fixes (audit batch A)", () => {
  it("grouped surfaces take the preview's surface-card: white in light, container-high in dark", () => {
    expect(css).toMatch(/--native-group-surface: var\(--md-surface-container-lowest\);/)
    expect(css).toMatch(/:root\[data-theme="dark"\]\[data-platform\] \{[^}]*--native-group-surface: var\(--md-surface-container-high\);/)
    expect(css).toMatch(/\.lm-native-main :is\(\.lm-native-card, \.lm-native-group\) \{[^}]*background-color: var\(--native-group-surface\);/)
  })

  it("Android cards keep 16px content with no in-card dividers; main honours the side insets", () => {
    expect(css).toMatch(/\.lm-native-card:not\(\[data-native-bleed="off"\]\) \{\s*padding-inline: calc\(var\(--space-4\) - var\(--native-gutter-android\)\);/)
    expect(css).toMatch(/> :is\(\.lm-native-card-body, \.lm-native-card-row\) \{ padding-inline: 0; \}/)
    expect(css).toMatch(/> \.lm-native-card-row \{ border-inline-start-width: 0; \}/)
    expect(css).toMatch(/divide-y"\] > \*, \.border-t, \.border-b, \.lm-native-divider\) \{\s*border-block-width: 0;/)
    expect(css).toMatch(/\[data-platform="ios"\] \.lm-native-main \{\s*padding-left: max\(var\(--native-group-inset-ios\), env\(safe-area-inset-left\)\);\s*padding-right: max\(var\(--native-group-inset-ios\), env\(safe-area-inset-right\)\);/)
    expect(css).toMatch(/\[data-platform="android"\] \.lm-native-main \{\s*--native-bleed-l: max\(var\(--native-gutter-android\), env\(safe-area-inset-left\)\);\s*--native-bleed-r: max\(var\(--native-gutter-android\), env\(safe-area-inset-right\)\);\s*padding-left: var\(--native-bleed-l\);/)
  })

  it("the tab bar clears the side insets", () => {
    expect(css).toMatch(/\.lm-native-tabbar \{\s*padding-left: env\(safe-area-inset-left\);\s*padding-right: env\(safe-area-inset-right\);/)
  })

  it("the Android emphasis tab has a fixed, pill-high layout box and lifts by paint only", () => {
    expect(css).toMatch(/\.lm-native-tab-icon\[data-emphasis\] \{\s*inline-size: var\(--native-tab-emphasis-size\);\s*block-size: var\(--native-tab-emphasis-size\);\s*margin-block: calc\(\(var\(--native-tab-pill-h\) - var\(--native-tab-emphasis-size\)\) \/ 2\);\s*translate: 0 calc\(-1 \* var\(--native-tab-emphasis-raise\)\);/)
  })

  it("an own-text page heading steps down on native phones only", () => {
    expect(css).toMatch(/\[data-page-heading="own"\] \{\s*font: 800 var\(--native-headline-size\) \/ var\(--native-headline-lh\) var\(--font-display\);/)
    expect(css).toMatch(/--native-headline-size: 28px;/)
  })

  it("the FAB is an M3 56px primary-container button above the tab bar; the iOS plus sits in the large-title row", () => {
    expect(css).toMatch(/\[data-platform="android"\] \.lm-native-fab \{\s*position: fixed;[^}]*inset-block-end: calc\(var\(--native-tabbar-h\) \+ env\(safe-area-inset-bottom\) \+ var\(--native-fab-gap\)\);\s*block-size: var\(--native-fab-size\);/)
    expect(css).toMatch(/\.lm-native-large-action > button \{[^}]*inline-size: var\(--native-iconbtn-ios\);/)
    expect(read("components/ui/fab.tsx")).toContain("bg-primary-container text-on-primary-container")
    expect(read("components/ui/fab.tsx")).toContain("native:android:inline-flex")
  })

  it("native sheet titles: iOS 17 semibold, Android Title Large; the mono eyebrow is hidden on native", () => {
    expect(css).toMatch(/\[data-platform="ios"\] \.lm-sheet \.lm-native-sheet-title \{ font: 600 var\(--native-sheet-title-ios\)/)
    expect(css).toMatch(/\[data-platform="android"\] \.lm-sheet \.lm-native-sheet-title \{ font: 400 var\(--native-sheet-title-android\)/)
    expect(read("components/shell/TopBarSheets.tsx")).toMatch(/text-eyebrow text-on-surface-variant native:hidden/)
  })

  it("the large-title action renders on iOS only (Android has the FAB)", () => {
    expect(read("components/shell/ShellTopBar.tsx")).toContain('native && platform === "ios" && level === "root" && largeTitleAction')
  })

  it("the bar's inline title is hidden from assistive technology (the page h1 carries the name)", () => {
    expect(read("components/shell/ShellTopBar.tsx")).toMatch(/<p data-shell-title aria-hidden="true"/)
  })

  it("the iOS back chevron is bold and its parts centre", () => {
    const back = read("components/shell/NativeBack.tsx")
    expect(back).toContain('<CaretLeft weight="bold"')
    expect(back).toMatch(/items-center ios:gap-0\.5/)
  })

  it("the tab badge uses the logical end edge, so RTL mirrors it", () => {
    const nav = read("components/ui/nav-shells.tsx")
    expect(nav).toContain("absolute -end-1.5 -top-1.5")
    expect(nav).not.toContain("-right-1.5")
  })

  it("the More button announces its dialog and state", () => {
    const nav = read("components/ui/nav-shells.tsx")
    expect(nav).toContain('aria-haspopup={item.popup ? "dialog" : undefined}')
    expect(nav).toContain("aria-expanded={item.popup ? item.popup.expanded : undefined}")
    expect(read("components/shell/PortalShell.tsx")).toContain("popup: { expanded: native ? moreOpen : navOpen }")
  })

  it("native phones open a More sheet; tablet and desktop keep the drawer", () => {
    const shell = read("components/shell/PortalShell.tsx")
    expect(shell).toContain("onClick: () => (native ? setMoreOpen(true) : setNavOpen(true))")
    expect(shell).toContain("open={moreOpen && native}")
    expect(shell).toContain("tabTargets.has(item.to)")
    expect(read("components/shell/MoreSheet.tsx")).toContain('<SheetTitle className="lm-native-sheet-title mb-4 text-display-md">More</SheetTitle>')
  })

  it("a pop to the tab root is a PUSH that reads as back", () => {
    expect(stateDirection({ navDirection: "back" })).toBe("back")
    expect(stateDirection({ lemelyDialog: true })).toBeUndefined()
    expect(stateDirection(null)).toBeUndefined()
    expect(read("components/shell/PortalShell.tsx")).toContain('state: { navDirection: "back" }')
    expect(read("components/root-outlet.tsx")).toContain("resolveDirection(navigationType, explicit)")
    // The explicit direction still wins over the router action (the helper's own tests pin it).
    expect(resolveDirection("PUSH", stateDirection({ navDirection: "back" }))).toBe("back")
  })

  it("hand-rolled outlined containers on the audited roots are native cards", () => {
    for (const file of [
      "components/ui/chart-frame.tsx",
      "components/ui/getting-started.tsx",
      "portals/teacher/home/TeacherSetup.tsx",
      "portals/teacher/home/AtRiskTable.tsx",
      "portals/teacher/home/NextUp.tsx",
    ])
      expect(read(file), file).toContain("lm-native-card")
  })
})

describe("TitledCard (heading leaves the card on native)", () => {
  const render = (native: boolean) =>
    renderToStaticMarkup(
      createElement(
        MemoryRouter,
        null,
        createElement(NativeFrameProvider, {
          value: { platform: native ? "ios" : "other", phone: native, native },
          children: createElement(TitledCard, { title: "Subjects this session" }, createElement("p", null, "row")),
        }),
      ),
    )
  it("keeps the display heading inside the card off the native frame", () => {
    const html = render(false)
    expect(html).toMatch(/^<div class="[^"]*lm-native-card[^"]*"><h2 class="px-6 pt-5 pb-4 text-display-md/)
  })
  it("renders a mono section label before the card on native", () => {
    const html = render(true)
    expect(html).toMatch(/^<section aria-labelledby="[^"]+" class="flex flex-col"><h2 id="[^"]+" class="lm-native-section-label text-eyebrow">Subjects this session<\/h2><div class="[^"]*lm-native-card/)
    expect(html).not.toContain("text-display-md")
  })
})
