import { readdirSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installPressFeedback, parseDelay, pressOrigin } from "@/lib/pressFeedback"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const css = readFileSync(join(SRC, "index.css"), "utf8")
const block = css.slice(css.indexOf("/* ── Native frame: press states"))
const read = (p: string) => readFileSync(join(SRC, p), "utf8")

describe("pressOrigin", () => {
  it("the ripple starts at the touch point and covers the farthest corner", () => {
    expect(pressOrigin({ left: 10, top: 20, width: 100, height: 40 }, 10, 20)).toEqual({ x: "0px", y: "0px", r: `${Math.ceil(Math.hypot(100, 40))}px` })
    expect(pressOrigin({ left: 0, top: 0, width: 100, height: 40 }, 50, 20)).toEqual({ x: "50px", y: "20px", r: `${Math.ceil(Math.hypot(50, 20))}px` })
  })
})

/*
 * installPressFeedback against a minimal fake DOM. The runner is `environment: "node"`
 * (see vitest.config.ts) and jsdom is not installed; adding it would be a recorded
 * dependency decision, so the few DOM members the module touches are faked here.
 */
type Handler = (e: unknown) => void
class FakeEl {
  classes = new Set<string>()
  attrs = new Map<string, string>()
  props = new Map<string, string>()
  disabled = false
  children: FakeEl[] = []
  rect = { left: 0, top: 0, width: 100, height: 40 }
  style = { setProperty: (k: string, v: string) => void this.props.set(k, v) }
  parent: FakeEl | null
  constructor(parent: FakeEl | null = null, cls = "") {
    this.parent = parent
    cls.split(" ").filter(Boolean).forEach((c) => this.classes.add(c))
    parent?.children.push(this)
  }
  setAttribute(k: string, v: string) { this.attrs.set(k, v) }
  removeAttribute(k: string) { this.attrs.delete(k) }
  hasAttribute(k: string) { return this.attrs.has(k) }
  getAttribute(k: string) { return this.attrs.get(k) ?? null }
  getBoundingClientRect() { return this.rect }
  matches(sel: string): boolean {
    return sel.split(", ").some((part) =>
      part === ".lm-press" ? this.classes.has("lm-press")
      : part === ".lm-press-delay" ? this.classes.has("lm-press-delay")
      : part === '[aria-disabled="true"]' ? this.attrs.get("aria-disabled") === "true"
      : part === ":disabled" ? this.disabled : false)
  }
  closest(sel: string): FakeEl | null {
    for (let n: FakeEl | null = this; n; n = n.parent) if (n.matches(sel)) return n
    return null
  }
  contains(o: FakeEl): boolean { for (let n: FakeEl | null = o; n; n = n.parent) if (n === this) return true; return false }
  querySelectorAll(sel: string): FakeEl[] { return this.children.flatMap((c) => [...(c.matches(sel) ? [c] : []), ...c.querySelectorAll(sel)]) }
}
class FakeRoot {
  handlers = new Map<string, Set<Handler>>()
  addEventListener(t: string, h: Handler) { (this.handlers.get(t) ?? this.handlers.set(t, new Set()).get(t)!).add(h) }
  removeEventListener(t: string, h: Handler) { this.handlers.get(t)?.delete(h) }
  fire(type: string, target: FakeEl | null = null, x = 0, y = 0) { this.handlers.get(type)?.forEach((h) => h({ type, target, clientX: x, clientY: y })) }
  get listenerCount() { return [...this.handlers.values()].reduce((n, s) => n + s.size, 0) }
}
const setup = () => {
  const root = new FakeRoot()
  const dispose = installPressFeedback(root as unknown as Document)
  const row = new FakeEl(null, "lm-press")
  return { root, dispose, row }
}

describe("installPressFeedback", () => {
  it("press sets the flag and the ripple origin; pointerup releases", () => {
    const { root, row } = setup()
    root.fire("pointerdown", row, 14, 14)
    expect(row.hasAttribute("data-pressed")).toBe(true)
    expect(row.props.get("--lm-press-x")).toBe("14px")
    expect(row.props.get("--lm-press-y")).toBe("14px")
    root.fire("pointerup")
    expect(row.hasAttribute("data-pressed")).toBe(false)
  })
  it("pointercancel and dragstart release; pointerleave is not listened to", () => {
    const { root, row } = setup()
    for (const type of ["pointercancel", "dragstart"]) {
      root.fire("pointerdown", row, 1, 1)
      root.fire(type)
      expect(row.hasAttribute("data-pressed"), type).toBe(false)
    }
    expect(root.handlers.has("pointerleave")).toBe(false)
  })
  it("a disabled or aria-disabled element is never pressed", () => {
    const { root, row } = setup()
    row.disabled = true
    root.fire("pointerdown", row, 1, 1)
    expect(row.hasAttribute("data-pressed")).toBe(false)
    row.disabled = false
    row.setAttribute("aria-disabled", "true")
    root.fire("pointerdown", row, 1, 1)
    expect(row.hasAttribute("data-pressed")).toBe(false)
  })
  it("a tap through a disabled child (pointer-events: none) does not light the pressable ancestor", () => {
    const { root, row } = setup()
    const child = new FakeEl(row)
    child.rect = { left: 10, top: 5, width: 30, height: 30 }
    child.disabled = true
    // pointer-events: none, so the event target is the ancestor itself
    root.fire("pointerdown", row, 20, 20)
    expect(row.hasAttribute("data-pressed")).toBe(false)
    // a tap outside the disabled child still presses the row
    root.fire("pointerdown", row, 80, 20)
    expect(row.hasAttribute("data-pressed")).toBe(true)
    root.fire("pointerup")
    // aria-disabled link inside, hit directly
    child.disabled = false
    child.setAttribute("aria-disabled", "true")
    root.fire("pointerdown", child, 20, 20)
    expect(row.hasAttribute("data-pressed")).toBe(false)
  })
  it("two pointers in a row: the first element is released when the second goes down", () => {
    const { root, row } = setup()
    const other = new FakeEl(null, "lm-press")
    root.fire("pointerdown", row, 1, 1)
    root.fire("pointerdown", other, 1, 1)
    expect(row.hasAttribute("data-pressed")).toBe(false)
    expect(other.hasAttribute("data-pressed")).toBe(true)
    root.fire("pointerup")
    expect(other.hasAttribute("data-pressed")).toBe(false)
  })
  it("a press outside any .lm-press element does nothing, and cleanup removes every listener", () => {
    const { root, row, dispose } = setup()
    root.fire("pointerdown", new FakeEl(), 1, 1)
    expect(row.hasAttribute("data-pressed")).toBe(false)
    expect(root.listenerCount).toBeGreaterThan(0)
    dispose()
    expect(root.listenerCount).toBe(0)
  })
})

describe("installPressFeedback: rows hold the highlight back (user decision: delay rows only)", () => {
  beforeEach(() => void vi.useFakeTimers())
  afterEach(() => void vi.useRealTimers())
  const rowSetup = () => {
    const s = setup()
    return { ...s, listRow: new FakeEl(null, "lm-press lm-press-delay") }
  }
  it("a hold shows the highlight only after the delay; buttons stay instant", () => {
    const { root, listRow, row } = rowSetup()
    root.fire("pointerdown", listRow, 5, 5)
    vi.advanceTimersByTime(99)
    expect(listRow.hasAttribute("data-pressed")).toBe(false)
    vi.advanceTimersByTime(1)
    expect(listRow.hasAttribute("data-pressed")).toBe(true)
    root.fire("pointerup")
    expect(listRow.hasAttribute("data-pressed")).toBe(false)
    root.fire("pointerdown", row, 5, 5)
    expect(row.hasAttribute("data-pressed")).toBe(true)
  })
  it("pointercancel before the delay (a scroll began) never shows it", () => {
    const { root, listRow } = rowSetup()
    root.fire("pointerdown", listRow, 5, 5)
    vi.advanceTimersByTime(40)
    root.fire("pointercancel")
    vi.advanceTimersByTime(500)
    expect(listRow.hasAttribute("data-pressed")).toBe(false)
  })
  it("moving past the 8px slop before the delay never shows it; within the slop still does", () => {
    const { root, listRow } = rowSetup()
    root.fire("pointerdown", listRow, 5, 5)
    root.fire("pointermove", listRow, 5, 14)
    vi.advanceTimersByTime(500)
    expect(listRow.hasAttribute("data-pressed")).toBe(false)
    root.fire("pointerup")
    root.fire("pointerdown", listRow, 5, 5)
    root.fire("pointermove", listRow, 8, 5)
    vi.advanceTimersByTime(100)
    expect(listRow.hasAttribute("data-pressed")).toBe(true)
  })
  it("a quick tap released before the delay still flashes the highlight, then clears", () => {
    const { root, listRow } = rowSetup()
    root.fire("pointerdown", listRow, 5, 5)
    vi.advanceTimersByTime(30)
    root.fire("pointerup")
    expect(listRow.hasAttribute("data-pressed")).toBe(true)
    vi.advanceTimersByTime(100)
    expect(listRow.hasAttribute("data-pressed")).toBe(false)
  })
  it("a new press ends the previous flash, and cleanup leaves nothing pending", () => {
    const { root, listRow, dispose } = rowSetup()
    root.fire("pointerdown", listRow, 5, 5)
    root.fire("pointerup")
    const other = new FakeEl(null, "lm-press lm-press-delay")
    root.fire("pointerdown", other, 5, 5)
    expect(listRow.hasAttribute("data-pressed")).toBe(false)
    dispose()
    vi.advanceTimersByTime(500)
    expect(other.hasAttribute("data-pressed")).toBe(false)
    expect(vi.getTimerCount()).toBe(0)
  })
  it("the delay is a token, and list rows opt in", () => {
    expect(css).toMatch(/--native-press-delay: 100ms;/)
    expect(read("components/ui/list-group.tsx")).toContain("lm-press-delay")
    // A fixed tab bar is not scroll content: it highlights instantly, on iOS and Material alike.
    expect(read("components/ui/nav-shells.tsx")).not.toContain("lm-press-delay")
    expect(read("components/ui/button.tsx")).not.toContain("lm-press-delay")
    expect(read("components/shell/shellStyles.ts")).not.toContain("lm-press-delay")
  })
})

describe("press delay token and disabled hit test", () => {
  beforeEach(() => void vi.useFakeTimers())
  afterEach(() => void vi.useRealTimers())
  it("parseDelay reads ms and s, and rejects anything else", () => {
    expect(parseDelay("100ms")).toBe(100)
    expect(parseDelay(" 0.1s ")).toBe(100)
    expect(parseDelay("250MS")).toBe(250)
    expect(parseDelay("-50ms")).toBe(0)
    expect(parseDelay("-0.1s")).toBe(0)
    expect(parseDelay("")).toBeNull()
    expect(parseDelay("fast")).toBeNull()
  })
  it("the token is read once at install and drives the row delay", () => {
    const root = new FakeRoot()
    let reads = 0
    installPressFeedback(root as unknown as Document, { readDelayToken: () => (reads++, "0.25s") })
    const r = new FakeEl(null, "lm-press lm-press-delay")
    root.fire("pointerdown", r, 1, 1)
    vi.advanceTimersByTime(249)
    expect(r.hasAttribute("data-pressed")).toBe(false)
    vi.advanceTimersByTime(1)
    expect(r.hasAttribute("data-pressed")).toBe(true)
    root.fire("pointerup")
    root.fire("pointerdown", r, 1, 1)
    expect(reads).toBe(1)
  })
  it("an unreadable token falls back to 100ms", () => {
    const root = new FakeRoot()
    installPressFeedback(root as unknown as Document, { readDelayToken: () => "" })
    const r = new FakeEl(null, "lm-press lm-press-delay")
    root.fire("pointerdown", r, 1, 1)
    vi.advanceTimersByTime(100)
    expect(r.hasAttribute("data-pressed")).toBe(true)
  })
  const rowWithDisabledChild = (pointerEvents: string, rect: { left: number; top: number; width: number; height: number }) => {
    const root = new FakeRoot()
    installPressFeedback(root as unknown as Document, { pointerEvents: () => pointerEvents })
    const r = new FakeEl(null, "lm-press")
    const c = new FakeEl(r)
    c.disabled = true
    c.rect = rect
    return { root, r }
  }
  it("a disabled child that takes pointer events does not suppress the row", () => {
    const { root, r } = rowWithDisabledChild("auto", { left: 10, top: 5, width: 30, height: 30 })
    root.fire("pointerdown", r, 20, 20)
    expect(r.hasAttribute("data-pressed")).toBe(true)
  })
  it("a disabled child with an empty box does not suppress the row", () => {
    const { root, r } = rowWithDisabledChild("none", { left: 20, top: 20, width: 0, height: 0 })
    root.fire("pointerdown", r, 20, 20)
    expect(r.hasAttribute("data-pressed")).toBe(true)
  })
  it("a pass-through disabled child (pointer-events none, real box) still suppresses", () => {
    const { root, r } = rowWithDisabledChild("none", { left: 10, top: 5, width: 30, height: 30 })
    root.fire("pointerdown", r, 20, 20)
    expect(r.hasAttribute("data-pressed")).toBe(false)
  })
})

describe("press CSS (preview 4447a571, variant-a.css section 5)", () => {
  it("one background-image layer, so it follows the radius and never clips a badge", () => {
    expect(block).toMatch(/\.lm-press\[data-pressed\] \{[^}]*background-image: radial-gradient\(circle at var\(--lm-press-x\) var\(--lm-press-y\), color-mix\(in oklch, var\(--lm-press-ink\) var\(--lm-press-layer\), transparent\) var\(--lm-press-rr\)/)
    expect(block).not.toMatch(/\.lm-press[^{]*\{[^}]*overflow: hidden/)
  })
  it("iOS: 8% toward black in light and white in dark; buttons scale to 0.97", () => {
    expect(block).toMatch(/:root\[data-platform="ios"\] \{[^}]*--lm-press-ink: var\(--native-press-ink-light\);[^}]*--lm-press-layer: var\(--native-press-dim\)/)
    expect(block).toMatch(/:root\[data-theme="dark"\]\[data-platform="ios"\] \{[^}]*--lm-press-ink: var\(--native-press-ink-dark\)/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-press-scale\[data-pressed\] \{[^}]*scale: var\(--native-press-scale\)/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-tabbar \.lm-press\[data-pressed\] \{[^}]*background-image: none;[^}]*opacity: var\(--native-tab-press-opacity-ios\)/)
  })
  it("Android: a 10% currentColor layer rippling out over 450ms", () => {
    expect(block).toMatch(/:root\[data-platform="android"\] \{[^}]*--lm-press-ink: currentColor;[^}]*--lm-press-layer: var\(--native-state-pressed\)/)
    expect(block).toMatch(/\[data-platform="android"\] \.lm-press\[data-pressed\] \{[^}]*animation: lm-ripple var\(--native-ripple-dur\) var\(--ease-m3-emphasized\)/)
  })
  it("visible in under 50ms: no transition delay on the press-in", () => {
    expect(block).not.toMatch(/\.lm-press[^{]*\{[^}]*transition-delay/)
  })
})

describe("press is applied to the primitives", () => {
  it("the scale property has its own transition, or the iOS press snaps (Tailwind v4 scale-* writes `scale`)", () => {
    const list = (src: string) => src.match(/transition-\[([^\]]*)\]/g) ?? []
    expect(list(read("components/ui/button.tsx")).some((t) => /\bscale\b/.test(t))).toBe(true)
    expect(list(read("components/shell/shellStyles.ts")).some((t) => /\bscale\b/.test(t))).toBe(true)
    expect(read("components/shell/shellStyles.ts")).toContain("duration-[var(--dur-instant)]")
  })
  it("native owns scale: the web active:scale is cancelled, and Android never scales", () => {
    expect(block).toMatch(/\.lm-press:not\(\.lm-press-scale\) \{ scale: none; \}/)
    expect(block).toMatch(/\[data-platform="android"\] \.lm-press-scale \{ scale: none; \}/)
  })
  it("NativeBack opts in to the scaling press", () => {
    expect(read("components/shell/NativeBack.tsx")).toContain("lm-press lm-press-scale")
  })
  it("buttons and shell icon buttons scale; tabs and list rows only dim", () => {
    expect(read("components/ui/button.tsx")).toContain("lm-press lm-press-scale")
    expect(read("components/shell/shellStyles.ts")).toContain("lm-press lm-press-scale")
    expect(read("components/ui/nav-shells.tsx")).toContain("lm-press")
    expect(read("components/ui/nav-shells.tsx")).not.toContain("lm-press-scale")
    expect(read("components/ui/list-group.tsx")).toContain("lm-press")
    expect(read("components/ui/list-group.tsx")).not.toContain("lm-press-scale")
  })
})

describe("no hover-only affordances on phones", () => {
  it("no element is revealed only by group-hover without a touch fallback", () => {
    const offenders: string[] = []
    const walk = (dir: string): string[] => {
      return readdirSync(dir).flatMap((f) => { const p = join(dir, f); return statSync(p).isDirectory() ? walk(p) : p.endsWith(".tsx") ? [p] : [] })
    }
    for (const file of [...walk(join(SRC, "components")), ...walk(join(SRC, "portals"))]) {
      for (const [i, line] of readFileSync(file, "utf8").split("\n").entries()) {
        if (/\bopacity-0\b/.test(line) && /group-hover:opacity-100/.test(line) && !/(pointer-coarse|focus-within|focus-visible|native):opacity-100/.test(line)) {
          offenders.push(`${file.slice(SRC.length + 1)}:${i + 1}`)
        }
      }
    }
    expect(offenders).toEqual([])
  })
})
