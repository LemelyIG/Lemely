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
const render = (native: boolean) =>
  renderToStaticMarkup(
    createElement(NativeFrameProvider, {
      value: { platform: native ? "android" : "other", phone: native, native },
      children: createElement(TableOrList, props),
    }),
  )

describe("TableOrList (brief decision 4)", () => {
  it("off native: the table, untouched, no toggle", () => {
    const out = render(false)
    expect(out).toContain("<table>T</table>")
    expect(out).not.toContain("View table")
  })
  it("on native: the list first, with a View table escape hatch", () => {
    const out = render(true)
    expect(out).toContain("<ul>L</ul>")
    expect(out).toMatch(/<button[^>]*type="button"[^>]*>View table<\/button>/)
    expect(out).not.toContain("<table>")
  })
  it("Review and ClassRoster use it", () => {
    for (const f of ["portals/teacher/screens/Review.tsx", "portals/teacher/screens/ClassRoster.tsx"]) {
      expect(readFileSync(join(SRC, f), "utf8"), f).toContain("<TableOrList")
    }
  })
})
