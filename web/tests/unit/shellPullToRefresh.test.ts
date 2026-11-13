import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it, vi } from "vitest"
import { PULL_MAX_PX, PULL_THRESHOLD_PX, SETTLE_MS, pullDistance } from "@/components/shell/ShellPullToRefresh"
import { nativeHaptic } from "@/lib/haptics"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const read = (p: string) => readFileSync(join(SRC, p), "utf8")

describe("nativeHaptic (brief §3.5: Android only)", () => {
  it("vibrates on Android, nowhere else", () => {
    const vibrate = vi.fn(() => true)
    const nav = { vibrate }
    expect(nativeHaptic("tap", "android", nav, true)).toBe(true)
    expect(nativeHaptic("tap", "ios", nav, true)).toBe(false)
    expect(nativeHaptic("tap", "other", nav, true)).toBe(false)
    expect(vibrate).toHaveBeenCalledTimes(1)
    expect(vibrate).toHaveBeenCalledWith(10)
  })
  it("never vibrates outside the native frame: Android at 721px and up is a tablet or a window, not the phone frame", () => {
    const vibrate = vi.fn(() => true)
    const nav = { vibrate }
    expect(nativeHaptic("tap", "android", nav, false)).toBe(false)
    expect(nativeHaptic("success", "android", nav, false)).toBe(false)
    expect(vibrate).not.toHaveBeenCalled()
    expect(nativeHaptic("tap", "android", nav, true)).toBe(true)
    expect(vibrate).toHaveBeenCalledTimes(1)
  })
  it("reads the same phone media as the frame", () => {
    expect(read("lib/haptics.ts")).toContain("PHONE_MEDIA")
    expect(read("lib/haptics.ts")).toContain("isNativeFrame(")
  })
})

describe("one pull-to-refresh, owned by the shell (D6)", () => {
  it("PortalShell wraps root pages only", () => {
    const shell = read("components/shell/PortalShell.tsx")
    expect(shell).toMatch(/<ShellPullToRefresh enabled=\{native && level === "root"\}>/)
  })
  it("the scroller contains overscroll", () => {
    expect(read("components/shell/ShellPullToRefresh.tsx")).toContain("overscroll-y-contain")
  })
  it("arms at the preview's 64px on both platforms, one number shared with the token block", () => {
    const token = read("index.css").match(/--native-ptr-threshold:\s*(\d+)px/)?.[1]
    expect(PULL_THRESHOLD_PX).toBe(Number(token))
    expect(read("components/shell/ShellPullToRefresh.tsx")).toContain("threshold: PULL_THRESHOLD_PX")
  })
  it("the visual ceiling is the token's number too", () => {
    const token = read("index.css").match(/--native-ptr-max:\s*(\d+)px/)?.[1]
    expect(PULL_MAX_PX).toBe(Number(token))
  })
  it("the disc's travel is the token's number", () => {
    const token = read("index.css").match(/--native-ptr-disc-max:\s*(\d+)px/)?.[1]
    expect(token).toBe("108")
  })
  it("the settle timer is the slow duration token", () => {
    const token = read("index.css").match(/--dur-slow:\s*(\d+)ms/)?.[1]
    expect(SETTLE_MS).toBe(Number(token))
  })
  it("screens no longer wire their own", () => {
    for (const f of ["portals/student/screens/Overview.tsx", "portals/student/screens/Notifications.tsx", "portals/student/screens/Announcements.tsx"]) {
      expect(read(f), f).not.toContain("usePullToRefresh")
      expect(read(f), f).not.toContain("PullIndicator")
    }
  })
  it("sheet snap and long-press use the Android-only haptic", () => {
    expect(read("components/ui/bottom-sheet.tsx")).toContain('nativeHaptic("tap")')
    expect(read("lib/gestures/useLongPress.ts")).toContain("nativeHaptic(")
  })
})

describe("per-platform indicators (user decision 2026-11-09)", () => {
  const css = read("index.css")
  it("iOS rests at the iOS hold token, Android at the Android one", () => {
    expect(css).toMatch(/data-platform="ios"\] \.lm-ptr\[data-ptr="refreshing"\] :is\(\.lm-ptr-gap, \.lm-ptr-content\) \{ --pf-pull: var\(--native-ptr-hold-ios\)/)
    expect(css).toMatch(/data-platform="android"\] \.lm-ptr\[data-ptr="refreshing"\] \.lm-ptr-gap \{ --pf-pull: var\(--native-ptr-hold-android\)/)
  })
  it("only iOS moves the content; Android moves the disc", () => {
    expect(css).toMatch(/data-platform="ios"\] \.lm-ptr\[data-ptr\] \.lm-ptr-content \{ translate/)
    expect(css).not.toMatch(/data-platform="android"\][^{]*\.lm-ptr-content/)
  })
  it("the indicators render per platform", () => {
    const src = read("components/shell/ShellPullToRefresh.tsx")
    expect(src).toContain("lm-ptr-ios")
    expect(src).toContain("lm-ptr-md")
  })
})

describe("pull rendering contract (impeccable pass)", () => {
  const css = read("index.css")
  it("--pf-pull does not inherit, so a pull frame never restyles the page", () => {
    expect(css).toMatch(/@property --pf-pull \{[^}]*inherits: false/)
    expect(css).toMatch(/@property --pf-pull-p \{/)
  })
  it("the custom properties are written on the gap and the content, never the surface", () => {
    const src = read("components/shell/ShellPullToRefresh.tsx")
    expect(src).not.toMatch(/surface\.current[^\n]*style\.setProperty/)
    expect(src).toContain("gapEl.style.setProperty")
    expect(src).toContain("contentEl.style.setProperty")
  })
  it("reduced motion keeps the refreshing spinner turning on both platforms", () => {
    const block = css.slice(css.lastIndexOf("@media (prefers-reduced-motion: reduce)"))
    expect(block).toMatch(/\.lm-ptr-md svg \{[^}]*animation-iteration-count: infinite !important/)
    expect(block).toMatch(/\.lm-ptr-ios \{[^}]*animation-iteration-count: infinite !important/)
  })
  it("the disc's shadow is a token built from the shadow role, not a raw colour", () => {
    expect(css).toMatch(/\.lm-ptr-md \{[^}]*box-shadow: var\(--native-elev-1\)/)
    expect(css).toMatch(/--native-elev-1:[^;]*var\(--md-shadow\)/)
  })
  it("PullIndicator is gone and the hook no longer writes --lm-pull-progress", () => {
    expect(() => read("components/ui/pull-indicator.tsx")).toThrow()
    expect(read("lib/gestures/usePullToRefresh.ts")).not.toContain("setProperty(\"--lm-pull-progress")
  })
  it("the shell computes the title level once and hands it to the bar", () => {
    expect(read("components/shell/PortalShell.tsx")).toContain("titleLevel={level}")
  })
})

describe("pullDistance", () => {
  it("is 1:1 up to the arm threshold, so armed reads as armed", () => {
    expect(pullDistance(0)).toBe(0)
    expect(pullDistance(-20)).toBe(0)
    expect(pullDistance(30)).toBe(30)
    expect(pullDistance(PULL_THRESHOLD_PX)).toBe(PULL_THRESHOLD_PX)
  })
  it("then rubber-bands toward the ceiling without reaching it", () => {
    const a = pullDistance(100)
    const b = pullDistance(300)
    expect(a).toBeGreaterThan(PULL_THRESHOLD_PX)
    expect(b).toBeGreaterThan(a)
    expect(pullDistance(10_000)).toBeLessThanOrEqual(PULL_MAX_PX)
  })
})
