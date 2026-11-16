import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { Switch } from "@/components/ui/switch"

/* Mock ph.css .sw: 48×28 track, 22px thumb, off = outline, on = primary, 20px travel, .2s. */
describe("Switch matches the redesign mock", () => {
  it("off: 48×28 outline track", () => {
    const out = renderToStaticMarkup(createElement(Switch, { label: "Weekly Maths email" }))
    expect(out).toMatch(/role="switch"[^>]*class="[^"]*\bh-7 w-12\b[^"]*\bbg-outline\b/)
    expect(out).toMatch(/h-\[22px\] w-\[22px\][^"]*translate-x-\[2px\]/)
  })
  it("on: primary track, thumb travels 20px", () => {
    const out = renderToStaticMarkup(createElement(Switch, { label: "Weekly Maths email", checked: true }))
    expect(out).toMatch(/aria-checked="true"[^>]*class="[^"]*\bbg-primary\b/)
    expect(out).toContain("translate-x-[22px]")
    expect(out).toContain("motion-reduce:transition-none")
  })
  it("off state edge and thumb stay visible (3:1 marks, not the 1.3:1 outline fill alone)", () => {
    const out = renderToStaticMarkup(createElement(Switch, { label: "x" }))
    expect(out).toContain("border-on-surface-variant")
    expect(out).toContain("bg-on-surface-variant")
  })
})
