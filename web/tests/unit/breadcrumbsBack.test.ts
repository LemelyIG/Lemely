import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { StaticRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { Breadcrumbs, type BreadcrumbsProps, type Crumb } from "@/components/ui/breadcrumbs"

/*
 * `back` is an opt-in on a shared primitive (teacher, parent, settings and admin render it too).
 * `support/breadcrumbsBaseline.json` is the markup the component rendered BEFORE `back` existed,
 * captured from the unmodified file, so "without back it renders exactly as before" is checked
 * against the old output rather than against itself.
 */
const BASELINE: Record<string, string> = JSON.parse(readFileSync(join(import.meta.dirname, "support", "breadcrumbsBaseline.json"), "utf8"))

const TRAILS: Record<string, Crumb[]> = {
  linked: [{ label: "Practice", to: "/student/practice" }, { label: "0580" }],
  unlinked: [{ label: "Practice" }, { label: "0580" }],
  three: [{ label: "Practice", to: "/student/practice" }, { label: "0580", to: "/student/practice/0580" }, { label: "Result" }],
}

const render = (props: BreadcrumbsProps) =>
  renderToStaticMarkup(createElement(StaticRouter, { location: "/x" }, createElement(Breadcrumbs, props)))

describe("Breadcrumbs without `back`", () => {
  it.each(Object.keys(TRAILS))("renders the %s trail exactly as it did before `back` existed", (name) => {
    expect(render({ items: TRAILS[name] })).toBe(BASELINE[name])
  })

  it("ignores an undefined back the same way", () => {
    expect(render({ items: TRAILS.linked, back: undefined })).toBe(BASELINE.linked)
  })
})

describe("Breadcrumbs with `back`", () => {
  const back = { label: "Back", ariaLabel: "Back", onActivate: () => {} }
  const phoneItem = (html: string) => html.match(/<li class="flex min-w-0 items-center sm:hidden">.*?<\/li>/s)?.[0] ?? ""

  it("swaps only the phone link for a button with the same caret, classes and 44px floor", () => {
    const withBack = phoneItem(render({ items: TRAILS.linked, back }))
    const before = phoneItem(BASELINE.linked)
    expect(withBack).toMatch(/^<li [^>]*><button type="button" aria-label="Back" class="[^"]*min-h-11[^"]*"/)
    expect(withBack).not.toContain("<a ")
    // The drawn caret is unchanged and mirrors in RTL (never a "‹" glyph).
    const caret = (s: string) => s.match(/<svg[^>]*rtl:scale-x-100[^>]*>/)?.[0]
    expect(caret(withBack)).toBeDefined()
    expect(caret(withBack)).toBe(caret(before))
    expect(withBack).not.toContain("‹")
  })

  it("shows the given label, and names the destination for assistive tech", () => {
    const html = phoneItem(render({ items: TRAILS.linked, back: { label: "Practice", ariaLabel: "Back to Practice", onActivate: () => {} } }))
    expect(html).toContain('aria-label="Back to Practice"')
    expect(html).toContain('<span class="truncate">Practice</span>')
  })

  it("leaves the full trail (from sm) untouched", () => {
    const withBack = render({ items: TRAILS.three, back })
    const strip = (html: string) => html.replace(/<li class="flex min-w-0 items-center sm:hidden">.*?<\/li>/s, "")
    expect(strip(withBack)).toBe(strip(BASELINE.three))
    expect(withBack).toContain('href="/student/practice"')
  })

  it("does nothing when the trail does not collapse (no linked ancestor, or collapse off)", () => {
    expect(render({ items: TRAILS.unlinked, back })).toBe(BASELINE.unlinked)
    expect(render({ items: TRAILS.linked, collapse: false, back })).toBe(render({ items: TRAILS.linked, collapse: false }))
  })
})
