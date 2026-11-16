import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { GhostRows, Walkthrough } from "@/components/redesign"

describe("Walkthrough", () => {
  it("an ordered list of numbered tips", () => {
    const out = renderToStaticMarkup(
      createElement(Walkthrough, {
        steps: [
          { title: "Scan a Maths paper", body: "Any past paper you have tried." },
          { title: "Lemely marks it" },
        ],
      }),
    )
    expect(out).toMatch(/^<ol class="rd-walk">/)
    expect(out).toContain('<span class="rd-walk-n" aria-hidden="true">1</span>')
    expect(out).toContain("<b>Scan a Maths paper</b><span>Any past paper you have tried.</span>")
    expect(out).toContain('<span class="rd-walk-n" aria-hidden="true">2</span>')
  })
})

describe("GhostRows", () => {
  it("one loading status around rows in the hairline geometry", () => {
    const out = renderToStaticMarkup(createElement(GhostRows, { rows: 2, withLeading: true }))
    expect(out.match(/role="status"/g)).toHaveLength(1)
    expect(out).toMatch(/aria-label="Loading"/)
    expect(out.match(/class="rd-ghostrow"/g)).toHaveLength(2)
    expect(out.match(/h-9 w-9/g)).toHaveLength(2)
  })
  it("defaults to three rows without a leading block", () => {
    const out = renderToStaticMarkup(createElement(GhostRows, {}))
    expect(out.match(/class="rd-ghostrow"/g)).toHaveLength(3)
    expect(out).not.toContain("h-9 w-9")
  })
})
