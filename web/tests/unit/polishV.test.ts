import { readdirSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { createGlyph } from "@/portals/teacher/components/CreateSheet"

/*
 * NF polish batch, lane P1 (visual). What a Node-only test can pin about the CSS and source rules;
 * the rendered behaviour is in scripts/drift/checks-polish-v.mjs.
 */
const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const read = (p: string) => readFileSync(join(SRC, p), "utf8")
const css = read("index.css")

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name)
    return statSync(full).isDirectory() ? tsxFiles(full) : full.endsWith(".tsx") ? [full] : []
  })
}

describe("item 1: no eyebrow above a screen heading on the native frame", () => {
  it("every eyebrow that sits directly above a page heading is hidden on native", () => {
    const offenders: string[] = []
    const files = ["portals/student", "portals/teacher", "portals/parent", "portals/settings"].flatMap((d) => tsxFiles(join(SRC, d)))
    for (const file of files) {
      const lines = readFileSync(file, "utf8").split("\n")
      lines.forEach((line, i) => {
        if (!/<Eyebrow\b|text-eyebrow/.test(line)) return
        // A screen-level eyebrow: a heading follows it closely with no closing block in between.
        // Comment lines are blanked, so a `<h1>` named in a comment is not a heading.
        const window = lines.slice(i + 1, i + 12).map((l) => (/^\s*(\*|\/\/|\/\*|\{\/\*)/.test(l) ? "" : l))
        const heading = window.findIndex((l) => /<PageHeading\b|<h1\b/.test(l))
        if (heading === -1) return
        if (window.slice(0, heading).some((l) => /^\s*<\/(div|header|section)>/.test(l))) return
        if (!/native:hidden/.test(line)) offenders.push(`${file.slice(SRC.length + 1)}:${i + 1}`)
      })
    }
    expect(offenders).toEqual([])
  })
})

describe("item 2: own-text h1 is 24px in the UI face", () => {
  it("steps down to 24px, set in the sans face because Bricolage stops at 28px", () => {
    expect(css).toMatch(/--native-headline-size: 24px;/)
    expect(css).toMatch(/\[data-page-heading="own"\] \{\s*font: 800 var\(--native-headline-size\) \/ var\(--native-headline-lh\) var\(--font-sans\);/)
  })
})

describe("items 4 and 14: the FAB owns its scroll state; a sheet drag may start on a row", () => {
  it("the scroll listener lives in ScrollFab, not in the teacher layout", () => {
    expect(read("components/ui/fab.tsx")).toMatch(/export const ScrollFab/)
    const layout = read("portals/teacher/index.tsx")
    expect(layout).toMatch(/<ScrollFab\b/)
    expect(layout).not.toMatch(/useExtendedOnScroll/)
  })
  it("the iOS large-title plus is the bold weight, the others stay regular", () => {
    expect(renderToStaticMarkup(createGlyph(22, "bold"))).not.toBe(renderToStaticMarkup(createGlyph(22)))
    expect(read("portals/teacher/index.tsx")).toMatch(/\{createGlyph\(22, "bold"\)\}/)
  })
  it("the sheet no longer credits a row exclusion to the user", () => {
    const sheet = read("components/ui/bottom-sheet.tsx")
    expect(sheet).not.toMatch(/pressing a control never starts a drag/)
    expect(sheet).toMatch(/onClickCapture/)
  })
})

describe("items 10 and 24: the 48dp floor is a rule, not an important utility", () => {
  it("no class string in the Button or the at-risk list uses a `!` suffix", () => {
    for (const file of ["components/ui/button.tsx", "portals/teacher/screens/AtRiskList.tsx", "components/ui/table-or-list.tsx"]) {
      expect(read(file), file).not.toMatch(/\b(?:min-[hw]|android:[\w-]+)-\d+!/)
    }
  })
  it("the floor lives on .lm-btn in the Android native frame", () => {
    expect(css).toMatch(/\[data-platform="android"\] \.lm-btn \{\s*min-block-size: var\(--native-iconbtn-android\);\s*min-inline-size: var\(--native-iconbtn-android\);/)
    expect(read("components/ui/button.tsx")).toMatch(/"lm-btn"/)
    expect(read("components/ui/table-or-list.tsx")).toMatch(/lm-btn/)
  })
})

describe("item 11: the dark edge shadow comes from a role token", () => {
  it("is never raw black", () => {
    const dark = css.match(/:root\[data-theme="dark"\]\[data-platform\] \{[^}]*\}/)?.[0] ?? ""
    expect(dark).toMatch(/--native-edge-shadow: var\(--md-scrim\);/)
    expect(dark).not.toMatch(/--native-edge-shadow: oklch\(0 0 0\)/)
  })
})

describe("item 12: the swipe drops the top bar's old snapshot", () => {
  it("hides it like the tab bar's", () => {
    expect(css).toMatch(/\[data-direction="swipe"\]::view-transition-old\(lm-chrome-top\) \{\s*display: none;/)
  })
})

describe("item 5: a dark sheet lifts off the dim", () => {
  it("one container step up, with a top hairline, and never on the transparent action sheet", () => {
    expect(css).toMatch(/\[data-theme="dark"\] \.lm-sheet:not\(\.lm-action-sheet\) \{\s*background: var\(--md-surface-container\);\s*box-shadow: inset 0 var\(--native-hairline\) 0 var\(--md-outline-variant\);/)
  })
})
