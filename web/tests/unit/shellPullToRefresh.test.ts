import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it, vi } from "vitest"
import { PULL_MAX_PX, PULL_THRESHOLD_PX, pullDistance } from "@/components/shell/ShellPullToRefresh"
import { nativeHaptic } from "@/lib/haptics"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const read = (p: string) => readFileSync(join(SRC, p), "utf8")

describe("nativeHaptic (brief §3.5: Android only)", () => {
  it("vibrates on Android, nowhere else", () => {
    const vibrate = vi.fn(() => true)
    const nav = { vibrate }
    expect(nativeHaptic("tap", "android", nav)).toBe(true)
    expect(nativeHaptic("tap", "ios", nav)).toBe(false)
    expect(nativeHaptic("tap", "other", nav)).toBe(false)
    expect(vibrate).toHaveBeenCalledTimes(1)
    expect(vibrate).toHaveBeenCalledWith(10)
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
    expect(css).toMatch(/data-platform="ios"\] \.lm-ptr\[data-ptr="refreshing"\] \{ --pf-pull: var\(--native-ptr-hold-ios\)/)
    expect(css).toMatch(/data-platform="android"\] \.lm-ptr\[data-ptr="refreshing"\] \{ --pf-pull: var\(--native-ptr-hold-android\)/)
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
