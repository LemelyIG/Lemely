import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { NoBreakTitle } from "@/components/shell/NoBreakTitle"
import { ShellAvatar } from "@/components/shell/ShellAvatar"
import { TableOrList } from "@/components/ui/table-or-list"
import { GradeRing } from "@/portals/student/GradeRing"
import { NativeFrameProvider } from "@/lib/useNativeFrame"

describe("NF final polish, lane F1", () => {
  it("item 1: a date in a title is one unbreakable token", () => {
    const out = renderToStaticMarkup(createElement(NoBreakTitle, { title: "Physics mock moved to Thu 12 Nov", mono: true }))
    expect(out).toContain('whitespace-nowrap">12 Nov</span>')
    expect(out).toContain("font-mono")
    expect(renderToStaticMarkup(createElement(NoBreakTitle, { title: "Mock on 12 Nov" }))).not.toContain("font-mono")
  })

  it("item 2: ShellAvatar hands its size to the kit Avatar", () => {
    const sm = renderToStaticMarkup(createElement(ShellAvatar, { name: "Mariam Hassan" }))
    const md = renderToStaticMarkup(createElement(ShellAvatar, { name: "Mariam Hassan", size: "md" }))
    expect(sm).toContain("text-body-sm")
    expect(md).toContain("text-body-lg")
    expect(md).not.toContain("text-body-sm")
  })

  it("item 3: the grade ring names its grade, and its letter is not read twice", () => {
    const out = renderToStaticMarkup(createElement(GradeRing, { grade: "A*", pct: 90 }))
    expect(out).toContain('role="img"')
    expect(out).toContain('aria-label="Grade A*"')
    expect(out).toContain('<b aria-hidden="true"')
  })

  it("item 4: the native list view is a group named by the label", () => {
    const out = renderToStaticMarkup(
      createElement(NativeFrameProvider, {
        value: { platform: "android", phone: true, native: true },
        children: createElement(TableOrList, {
          label: "Your classes",
          storageKey: "t",
          table: createElement("table", null, "T"),
          list: createElement("ul", null, "L"),
        }),
      }),
    )
    expect(out).toContain('role="group" aria-label="Your classes"')
  })
})
