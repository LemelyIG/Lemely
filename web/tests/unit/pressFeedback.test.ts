import { readdirSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { pressOrigin } from "@/lib/pressFeedback"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const css = readFileSync(join(SRC, "index.css"), "utf8")
const read = (p: string) => readFileSync(join(SRC, p), "utf8")

describe("pressOrigin", () => {
  it("the ripple starts at the touch point and covers the farthest corner", () => {
    expect(pressOrigin({ left: 10, top: 20, width: 100, height: 40 }, 10, 20)).toEqual({ x: "0px", y: "0px", r: `${Math.ceil(Math.hypot(100, 40))}px` })
    expect(pressOrigin({ left: 0, top: 0, width: 100, height: 40 }, 50, 20)).toEqual({ x: "50px", y: "20px", r: `${Math.ceil(Math.hypot(50, 20))}px` })
  })
})

describe("press CSS (preview 4447a571, variant-a.css section 5)", () => {
  const block = css.slice(css.indexOf("/* ── Native frame: press states"))
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
