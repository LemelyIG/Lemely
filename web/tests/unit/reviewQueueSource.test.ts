import { readdirSync, readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

const DIR = join(import.meta.dirname, "../../src/portals/teacher/screens/review")
const tsx = readdirSync(DIR).filter((f) => f.endsWith(".tsx"))

describe("review screens source", () => {
  it("uses design tokens, never raw colours", () => {
    for (const f of tsx) {
      const src = readFileSync(join(DIR, f), "utf8")
      expect(src, f).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
      expect(src, f).not.toMatch(/\boklch\(\s*0?\.\d/)
    }
  })
  it("gives every animation a reduced-motion fallback", () => {
    const css = readFileSync(join(DIR, "review.css"), "utf8")
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)/)
    for (const name of ["lm-rq-bump", "lm-rq-skel"]) {
      expect(css).toContain(`@keyframes ${name}`)
    }
    expect(css).toMatch(/prefers-reduced-motion: reduce\)[\s\S]*animation: none/)
  })
  it("never shows Binny outside the calm states", () => {
    const col = readFileSync(join(DIR, "QueueColumn.tsx"), "utf8")
    expect(col).not.toMatch(/<Binny\b/)
  })
  it("sets no text under 12px", () => {
    for (const f of tsx) {
      const src = readFileSync(join(DIR, f), "utf8")
      for (const m of src.matchAll(/text-\[(\d+(?:\.\d+)?)px\]/g)) {
        expect(Number(m[1]), `${f} ${m[0]}`).toBeGreaterThanOrEqual(12)
      }
    }
  })
  it("keeps chip height and grows only the remove hit area", () => {
    const bar = readFileSync(join(DIR, "FilterBar.tsx"), "utf8")
    expect(bar).toMatch(/after:-inset-\[13px\]/)
    expect(bar).not.toMatch(/pointer-coarse:size-/)
  })
  it("returns focus to the trigger on Escape and cycles filter items", () => {
    const bar = readFileSync(join(DIR, "FilterBar.tsx"), "utf8")
    const menu = readFileSync(join(DIR, "FilterMenu.tsx"), "utf8")
    const sort = readFileSync(join(DIR, "SortMenu.tsx"), "utf8")
    expect(bar).toMatch(/triggerRef/)
    expect(sort).toMatch(/triggerRef/)
    expect(menu).toMatch(/ArrowDown/)
    expect(menu).toMatch(/ArrowUp/)
  })
  it("collapses rows without a fixed max-height", () => {
    const css = readFileSync(join(DIR, "review.css"), "utf8")
    expect(css).not.toMatch(/max-height/)
    expect(css).toMatch(/grid-template-rows/)
  })
  it("keeps ruled lines between text lines, tied to the line height", () => {
    const css = readFileSync(join(DIR, "review.css"), "utf8")
    expect(css).toMatch(/1lh/)
  })
  it("owns the screen: flushes pending decisions on pagehide and unmount, and binds the keys", () => {
    const hook = readFileSync(join(DIR, "usePendingDecisions.ts"), "utf8")
    expect(hook).toMatch(/addEventListener\("pagehide"/)
    const screen = readFileSync(join(DIR, "ReviewQueue.tsx"), "utf8")
    expect(screen).toMatch(/usePendingDecisions\(/)
    expect(screen).toMatch(/addEventListener\("keydown"/)
    const routes = readFileSync(join(DIR, "../../index.tsx"), "utf8")
    expect(routes).not.toMatch(/screens\/Review"\)/)
    expect(routes).toMatch(/screens\/review\/ReviewQueue/)
  })
  it("anchors the undo toast in the queue column on desktop so Accept stays clear", () => {
    const bar = readFileSync(join(DIR, "UndoBar.tsx"), "utf8")
    expect(bar).toMatch(/placement/)
    const screen = readFileSync(join(DIR, "ReviewQueue.tsx"), "utf8")
    expect(screen).toMatch(/placement=/)
    expect(screen).toMatch(/overlayOpen\(document\)/)
    expect(screen).toMatch(/focusAfterDecision\(/)
  })
})
