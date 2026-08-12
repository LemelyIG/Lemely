import { describe, expect, it } from "vitest"
import { describeUserAgent, deviceTitle, lastActiveLabel } from "@/lib/devices"
import { isDeviceLimitChallenge } from "@/lib/deviceTypes"
import type { Device } from "@/lib/deviceTypes"

/*
 * G-10/G-11's rendering helpers (P5.7 chunk B).
 *
 * The three things worth pinning here all have the same shape: a screen that
 * asks a user to sign a device out must not overstate what it knows about that
 * device. A user-agent string is a hint, `last_seen_at` moves only when a
 * request is made, and a 409 body arrives as unvalidated JSON.
 */

function device(overrides: Partial<Device> = {}): Device {
  return {
    deviceId: "11111111-1111-1111-1111-111111111111",
    label: null,
    userAgent: null,
    lastActiveAt: "2026-08-10T09:00:00+00:00",
    isCurrent: false,
    ...overrides,
  }
}

describe("describeUserAgent", () => {
  it("names a browser and platform when the string says both", () => {
    const ua =
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    expect(describeUserAgent(ua)).toBe("Chrome on Mac")
  })

  it("prefers the browser that actually sent the request over the ones it impersonates", () => {
    // Every Chromium UA also contains "Safari" and Edge's contains "Chrome" —
    // the order of the table is the whole correctness of this function.
    const edge = "Mozilla/5.0 (Windows NT 10.0) Chrome/126.0 Safari/537.36 Edg/126.0"
    expect(describeUserAgent(edge)).toBe("Edge on Windows")
  })

  it("says it does not know rather than guessing", () => {
    expect(describeUserAgent(null)).toBe("Unknown device")
    expect(describeUserAgent("curl/8.4.0")).toBe("Unknown device")
  })
})

describe("deviceTitle", () => {
  it("uses an explicit label when one exists", () => {
    expect(deviceTitle(device({ label: "School iPad", userAgent: "Chrome/126.0" }))).toBe(
      "School iPad",
    )
  })

  it("falls back to the user agent, never to the device id", () => {
    const title = deviceTitle(device({ userAgent: "Mozilla/5.0 (iPhone) Safari/605" }))
    expect(title).toBe("Safari on iPhone")
    expect(title).not.toContain("1111")
  })
})

describe("lastActiveLabel", () => {
  const now = new Date("2026-08-10T12:00:00+00:00")

  it("rounds down to a whole unit", () => {
    expect(lastActiveLabel("2026-08-10T11:59:40+00:00", now)).toBe("Active just now")
    expect(lastActiveLabel("2026-08-10T11:30:00+00:00", now)).toBe("Active 30 minutes ago")
    expect(lastActiveLabel("2026-08-10T09:00:00+00:00", now)).toBe("Active 3 hours ago")
    expect(lastActiveLabel("2026-08-08T09:00:00+00:00", now)).toBe("Active 2 days ago")
  })

  it("singularises so a device is never 'Active 1 hours ago'", () => {
    expect(lastActiveLabel("2026-08-10T11:00:00+00:00", now)).toBe("Active 1 hour ago")
  })

  it("admits an unparseable stamp instead of rendering NaN", () => {
    expect(lastActiveLabel("not-a-date", now)).toBe("Last active: unknown")
  })
})

describe("isDeviceLimitChallenge", () => {
  it("accepts the real 409 body", () => {
    expect(
      isDeviceLimitChallenge({
        reason: "device_limit_reached",
        maxDevices: 3,
        devices: [device()],
        oldestDeviceId: device().deviceId,
      }),
    ).toBe(true)
  })

  it("rejects every other error detail, including FastAPI's plain string", () => {
    // `/auth/login`'s other failure is a 401 whose detail is a string. Treating
    // that as a challenge would show G-10 to someone who typed a wrong password
    // — and hand them a list of somebody's devices.
    expect(isDeviceLimitChallenge("Invalid credentials")).toBe(false)
    expect(isDeviceLimitChallenge(null)).toBe(false)
    expect(isDeviceLimitChallenge(undefined)).toBe(false)
    expect(isDeviceLimitChallenge({ reason: "device_limit_reached" })).toBe(false)
  })
})
