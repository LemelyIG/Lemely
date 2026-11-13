import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { TableOrList } from "@/components/ui/table-or-list"
import { NativeFrameProvider } from "@/lib/useNativeFrame"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const props = { label: "Review queue", storageKey: "t", table: createElement("table", null, "T"), list: createElement("ul", null, "L") }
const render = (native: boolean, extra: object = {}) =>
  renderToStaticMarkup(
    createElement(NativeFrameProvider, {
      value: { platform: native ? "android" : "other", phone: native, native },
      children: createElement(TableOrList, { ...props, ...extra }),
    }),
  )

describe("TableOrList (brief decision 4)", () => {
  it("off native: the table, untouched, no toggle", () => {
    const out = render(false)
    expect(out).toBe("<table>T</table>")
    expect(out).not.toContain("View table")
  })
  it("on native: the list first, with a View table escape hatch", () => {
    const out = render(true)
    expect(out).toContain("<ul>L</ul>")
    expect(out).toMatch(/<button[^>]*type="button"[^>]*>View table<\/button>/)
    expect(out).not.toContain("<table>")
  })
  it("tableHeader shows with the table off native and never in the native list view", () => {
    const header = createElement("div", null, "BULK")
    expect(render(false, { tableHeader: header })).toBe("<div>BULK</div><table>T</table>")
    expect(render(true, { tableHeader: header })).not.toContain("BULK")
  })
  it("notices follow tableHeader off native (desktop DOM unchanged) and show in the native list view too", () => {
    const header = createElement("div", null, "BULK")
    const notices = createElement("p", { role: "alert" }, "ERR")
    expect(render(false, { tableHeader: header, notices })).toBe('<div>BULK</div><p role="alert">ERR</p><table>T</table>')
    const nativeList = render(true, { tableHeader: header, notices })
    expect(nativeList).toContain('<p role="alert">ERR</p>')
    expect(nativeList).not.toContain("BULK")
  })
  it("Review and ClassRoster use it", () => {
    for (const f of ["portals/teacher/screens/Review.tsx", "portals/teacher/screens/ClassRoster.tsx"]) {
      expect(readFileSync(join(SRC, f), "utf8"), f).toContain("<TableOrList")
    }
  })
})
