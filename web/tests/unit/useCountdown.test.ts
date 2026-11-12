import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { nextCountdownTick } from "@/lib/hooks/useCountdown"

/*
 * SHOULD-FIX 10 · `useCountdown`, pinned as honestly as this suite can.
 *
 * `useCountdown` itself is a hook built entirely out of `useState` and a
 * `useEffect`-driven `setTimeout` — no DOM, no timer, and no way to mount a
 * component at all under this suite's plain-Node environment (no jsdom, see
 * `vitest.config.ts`, D3.20). What is genuinely pure and reachable here is
 * `nextCountdownTick`, extracted from the hook specifically so this file has
 * something real to assert on rather than nothing; the two behaviours the
 * SHOULD-FIX asked for beyond that — clearing the timer on unmount, and
 * stopping at zero rather than ticking on into negative numbers — are pinned
 * below as source-text gates against the hook's own implementation, not as
 * behavioural tests. A source-text gate is weaker than actually running the
 * hook and is named as such rather than dressed up as one.
 */

describe("nextCountdownTick", () => {
  it("decrements by one", () => {
    expect(nextCountdownTick(5)).toBe(4)
  })

  it("clamps at zero rather than going negative", () => {
    expect(nextCountdownTick(0)).toBe(0)
  })

  it("never returns a negative number for any nonnegative input", () => {
    for (const remaining of [1, 2, 10, 100]) {
      expect(nextCountdownTick(remaining)).toBeGreaterThanOrEqual(0)
    }
  })
})

describe("useCountdown source-text gates (hook body only — not exercised by a test)", () => {
  const source = readFileSync(
    join(import.meta.dirname, "..", "..", "src", "lib", "hooks", "useCountdown.ts"),
    "utf8",
  )

  it("clears its setTimeout on unmount (the ticking effect returns a clearTimeout cleanup)", () => {
    expect(source).toMatch(/return \(\) => window\.clearTimeout\(timer\)/)
  })

  it("stops ticking once remaining reaches zero (an early return guards the timer)", () => {
    expect(source).toMatch(/if \(remaining <= 0\) return/)
  })

  it("uses the pure, separately-pinned nextCountdownTick for the actual per-tick arithmetic", () => {
    expect(source).toContain("setRemaining(nextCountdownTick)")
  })
})
