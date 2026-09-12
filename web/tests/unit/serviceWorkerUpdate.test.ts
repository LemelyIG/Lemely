import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it, vi } from "vitest"
import {
  UPDATE_CHECK_INTERVAL_MS,
  scheduleUpdateChecks,
  type UpdateSchedulerEnv,
} from "@/lib/pwa/updateScheduler"

/**
 * Packet A7 — gated service-worker updates.
 *
 * `useServiceWorkerUpdate` itself is a hook built on `useRegisterSW`
 * (`virtual:pwa-register/react`) plus `useState`/`useEffect` — no DOM, and no
 * way to mount a component at all under this suite's plain-Node environment
 * (no jsdom, see `vitest.config.ts`, D3.20; a hook call outside a real React
 * render throws "Invalid hook call" regardless of jsdom, since that error is
 * about the hooks dispatcher, not the DOM). What is genuinely pure and
 * reachable here is `scheduleUpdateChecks`, extracted from the hook with an
 * injectable environment so this suite has something real to assert on; the
 * hook's actual wiring to `useRegisterSW` is pinned below as source-text
 * gates, the same honesty `useCountdown.test.ts` already established for the
 * same reason.
 */

function fakeEnv(): UpdateSchedulerEnv & {
  triggerVisible: () => void
  triggerInterval: () => void
} {
  let onVisible: (() => void) | undefined
  let onInterval: (() => void) | undefined
  return {
    addVisibilityListener: vi.fn((cb: () => void) => {
      onVisible = cb
      return vi.fn()
    }),
    setInterval: vi.fn((cb: () => void) => {
      onInterval = cb
      return 1
    }),
    clearInterval: vi.fn(),
    triggerVisible: () => onVisible?.(),
    triggerInterval: () => onInterval?.(),
  }
}

describe("scheduleUpdateChecks", () => {
  it("checks for an update when the tab becomes visible", () => {
    const update = vi.fn().mockResolvedValue(undefined)
    const env = fakeEnv()

    scheduleUpdateChecks({ update }, env)
    env.triggerVisible()

    expect(update).toHaveBeenCalledTimes(1)
  })

  it("polls on a 60-minute interval", () => {
    const update = vi.fn().mockResolvedValue(undefined)
    const env = fakeEnv()

    scheduleUpdateChecks({ update }, env)

    expect(env.setInterval).toHaveBeenCalledWith(expect.any(Function), UPDATE_CHECK_INTERVAL_MS)
    expect(UPDATE_CHECK_INTERVAL_MS).toBe(60 * 60 * 1000)

    env.triggerInterval()
    expect(update).toHaveBeenCalledTimes(1)
  })

  it("returns a cleanup that removes the visibility listener and clears the interval", () => {
    const removeListener = vi.fn()
    const env: UpdateSchedulerEnv = {
      addVisibilityListener: vi.fn(() => removeListener),
      setInterval: vi.fn(() => 42),
      clearInterval: vi.fn(),
    }

    const cleanup = scheduleUpdateChecks({ update: vi.fn() }, env)
    cleanup()

    expect(removeListener).toHaveBeenCalledTimes(1)
    expect(env.clearInterval).toHaveBeenCalledWith(42)
  })

  it("swallows a failed update() check rather than throwing", () => {
    const update = vi.fn().mockRejectedValue(new Error("network error"))
    const env = fakeEnv()

    scheduleUpdateChecks({ update }, env)

    expect(() => env.triggerVisible()).not.toThrow()
  })
})

describe("useServiceWorkerUpdate source-text gates (hook body only — not exercised by a test)", () => {
  const source = readFileSync(
    join(import.meta.dirname, "..", "..", "src", "lib", "pwa", "useServiceWorkerUpdate.ts"),
    "utf8",
  )

  it("reads needRefresh off useRegisterSW's [value, setter] tuple", () => {
    expect(source).toMatch(/needRefresh:\s*\[needRefresh\]/)
  })

  it("applyUpdate calls updateServiceWorker(true) — vite-plugin-pwa's own registerSW sends the SKIP_WAITING message via workbox-window and reloads on the controlling event", () => {
    expect(source).toMatch(/updateServiceWorker\(true\)/)
  })

  it("schedules update checks once a registration becomes available", () => {
    expect(source).toMatch(/scheduleUpdateChecks\(registration\)/)
  })
})
