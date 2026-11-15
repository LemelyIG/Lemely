import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { Binny, BinnyLine } from "@/components/redesign"
import { resolveMotion } from "@/components/redesign/motion"

const html = (props: Parameters<typeof Binny>[0]) => renderToStaticMarkup(createElement(Binny, props))

describe("Binny", () => {
  it("carries mood and motion as data attributes and sizes 1:1.1", () => {
    const out = html({ mood: "happy", size: 96 })
    expect(out).toMatch(/data-mood="happy"/)
    expect(out).toMatch(/data-motion="idle"/)
    expect(out).toMatch(/width="96" height="106"/)
    expect(out).toMatch(/viewBox="0 0 200 220"/)
  })
  it("happy: both eyes are arcs, no pupils", () => {
    const out = html({ mood: "happy" })
    expect(out).toContain("M68 143 Q78 130 88 143")
    expect(out).toContain("M112 143 Q122 130 132 143")
    expect(out).not.toContain("rd-bn-pupil")
  })
  it("wink: left eye open, right an arc", () => {
    const out = html({ mood: "wink" })
    expect(out.match(/rd-bn-pupil/g)).toHaveLength(1)
    expect(out).toContain("M112 143 Q122 130 132 143")
  })
  it("open: open mouth", () => {
    expect(html({ mood: "open" })).toContain("M86 160 H114")
  })
  it("thinking: pupils look right and the mouth is flat", () => {
    const out = html({ mood: "thinking" })
    expect(out).toMatch(/cx="84" cy="141"/)
    expect(out).toMatch(/cx="128" cy="141"/)
    expect(out).toContain("M92 167 H108")
  })
  it("sad: pupils look down and the mouth frowns", () => {
    const out = html({ mood: "sad" })
    expect(out).toMatch(/cx="80" cy="145"/)
    expect(out).toContain("M90 172 Q100 163 110 172")
  })
  it("draws the clipped paper sheet behind the body", () => {
    const out = html({ mood: "open" })
    expect(out.indexOf('transform="rotate(-3 100 192)"')).toBeLessThan(out.indexOf("M40 104 H160"))
  })
  it("is hidden from assistive tech by default, an img when asked", () => {
    expect(html({ mood: "open" })).toMatch(/aria-hidden="true"/)
    const named = html({ mood: "open", "aria-hidden": false })
    expect(named).toMatch(/role="img"/)
    expect(named).toMatch(/aria-label="Binny"/)
  })
  it("roam reserves a free zone on both sides", () => {
    const out = html({ mood: "happy", motion: "roam", roamDistance: 40 })
    expect(out).toMatch(/^<span class="rd-binny-zone" style="--rd-roam:40px">/)
  })
  it("headCrop: the teacher head-and-shoulders crop, square, no paper and no mouth", () => {
    const out = html({ mood: "happy", size: 32, headCrop: true })
    expect(out).toMatch(/viewBox="30 10 140 140"/)
    expect(out).toMatch(/width="32" height="32"/)
    expect(out).toContain("M40 104 H160 L154 150 H46 Z")
    expect(out).toContain('transform="translate(0 -8)"')
    expect(out).not.toContain("rotate(-3 100 192)")
    expect(out).not.toContain("M90 163 Q100 172 110 163")
  })
  it("headCrop: the ear tilt sits on a wrapper so the CSS twitch and sad rotation compose", () => {
    const out = html({ mood: "happy", headCrop: true })
    expect(out).toMatch(/<g data-tilt="l" transform="rotate\(-6 75 100\)"><g class="rd-bn-ear rd-bn-ear-l">/)
    expect(out).toMatch(/<g data-tilt="r" transform="rotate\(6 125 100\)"><g class="rd-bn-ear rd-bn-ear-r">/)
    expect(out).not.toMatch(/class="rd-bn-ear[^"]*" transform=/)
  })
  it("uses no literal colours (tokens only)", () => {
    expect(html({ mood: "sad" })).not.toMatch(/#[0-9a-f]{3,8}\b|oklch\(/i)
  })
})

describe("resolveMotion", () => {
  it("turns every motion into none under reduced motion", () => {
    for (const m of ["idle", "hop", "roam", "pop", "none"] as const) expect(resolveMotion(m, true)).toBe("none")
    expect(resolveMotion("hop", false)).toBe("hop")
  })
})

describe("BinnyLine", () => {
  it("renders Binny at 60px beside a speech bubble", () => {
    const out = renderToStaticMarkup(createElement(BinnyLine, { mood: "happy", line: "7 marks to A*" }))
    expect(out).toMatch(/class="rd-say"/)
    expect(out).toMatch(/width="60" height="66"/)
    expect(out).toMatch(/<p class="rd-bubble">7 marks to A\*<\/p>/)
  })
})
