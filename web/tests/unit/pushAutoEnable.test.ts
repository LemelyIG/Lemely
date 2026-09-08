import { describe, expect, it } from "vitest"
import {
  autoEnableAttemptKey,
  decideAutoEnable,
  readAutoEnableAttempt,
  writeAutoEnableAttempt,
  type AutoEnableInputs,
} from "@/lib/push/pushAutoEnable"

/*
 * The rules for asking a reader something they did not ask to be asked.
 *
 * Every case below is a state a real browser reaches, and the two that matter
 * most are the ones that look alike: `granted` with no subscription (repair it
 * silently, every time) and `default` after one attempt (never again). Getting
 * either backwards produces a failure with no symptom — a reader who believes
 * push is on while every send fails, or a browser that suppresses our prompt
 * for good because we asked on every load.
 */

const BASE: AutoEnableInputs = {
  supported: true,
  available: true,
  permission: "default",
  subscribed: false,
  attempted: false,
}

const inputs = (overrides: Partial<AutoEnableInputs>): AutoEnableInputs => ({
  ...BASE,
  ...overrides,
})

describe("decideAutoEnable", () => {
  it("asks when the deployment can push and the reader has not been asked", () => {
    expect(decideAutoEnable(BASE)).toEqual({ kind: "enable", interrupts: true })
  })

  it("does not ask when the server has no keys, even on a capable browser", () => {
    expect(decideAutoEnable(inputs({ available: false }))).toEqual({
      kind: "skip",
      reason: "unavailable",
    })
  })

  it("reports unavailability before unsupportedness when both are true", () => {
    // The order matters: a reader told to switch browsers would arrive at the
    // same dead end, because the server still could not sign a push.
    const decision = decideAutoEnable(inputs({ available: false, supported: false }))
    expect(decision).toEqual({ kind: "skip", reason: "unavailable" })
  })

  it("does not ask on a browser without the push APIs", () => {
    expect(decideAutoEnable(inputs({ supported: false }))).toEqual({
      kind: "skip",
      reason: "unsupported",
    })
  })

  it("never re-asks a reader who refused", () => {
    expect(decideAutoEnable(inputs({ permission: "denied" }))).toEqual({
      kind: "skip",
      reason: "denied",
    })
  })

  it("does nothing when push is already on for this browser", () => {
    expect(decideAutoEnable(inputs({ permission: "granted", subscribed: true }))).toEqual({
      kind: "skip",
      reason: "already-enabled",
    })
  })

  it("re-subscribes silently when permission is granted but the subscription is gone", () => {
    expect(decideAutoEnable(inputs({ permission: "granted", subscribed: false }))).toEqual({
      kind: "enable",
      interrupts: false,
    })
  })

  it("re-subscribes silently even after an earlier attempt", () => {
    // The once-only marker is a ceiling on interruptions, and this path shows
    // no dialog. Gating it would make a dropped subscription permanent.
    expect(
      decideAutoEnable(inputs({ permission: "granted", subscribed: false, attempted: true })),
    ).toEqual({ kind: "enable", interrupts: false })
  })

  it("asks at most once per browser while the permission stays default", () => {
    // A dismissed prompt leaves the permission at `default` forever, so the
    // marker is the only thing standing between this and a prompt per load.
    expect(decideAutoEnable(inputs({ attempted: true }))).toEqual({
      kind: "skip",
      reason: "already-asked",
    })
  })
})

describe("autoEnableAttemptKey", () => {
  it("varies with the VAPID key, so rotating the pair re-arms one attempt", () => {
    const first = autoEnableAttemptKey("BEFZeV8gPcr8pfaQdRwMX2KibKCks7ywvCz5")
    const second = autoEnableAttemptKey("BAAAAAAAPcr8pfaQdRwMX2KibKCks7ywvCz5")
    expect(first).not.toEqual(second)
  })

  it("is stable for the same key", () => {
    const key = "BEFZeV8gPcr8pfaQdRwMX2KibKCks7ywvCz5"
    expect(autoEnableAttemptKey(key)).toEqual(autoEnableAttemptKey(key))
  })

  it("ignores characters past the discriminating prefix", () => {
    // Two subscriptions of the same key must share one marker whatever the
    // rest of the key looks like.
    expect(autoEnableAttemptKey("0123456789abcdefXXXX")).toEqual(
      autoEnableAttemptKey("0123456789abcdefYYYY"),
    )
  })

  it("returns null for an empty key rather than a bare prefix", () => {
    expect(autoEnableAttemptKey("")).toBeNull()
  })
})

/** A `localStorage` that throws on every access, as Safari's private mode does. */
function hostileStorage(): Storage {
  const refuse = () => {
    throw new DOMException("The quota has been exceeded.", "QuotaExceededError")
  }
  return {
    get length(): number {
      return refuse()
    },
    clear: refuse,
    getItem: refuse,
    key: refuse,
    removeItem: refuse,
    setItem: refuse,
  } as unknown as Storage
}

/** The smallest `Storage` that behaves, since the unit runner has no DOM. */
function memoryStorage(): Storage {
  const map = new Map<string, string>()
  return {
    get length(): number {
      return map.size
    },
    clear: () => map.clear(),
    getItem: (key: string) => map.get(key) ?? null,
    key: (index: number) => [...map.keys()][index] ?? null,
    removeItem: (key: string) => void map.delete(key),
    setItem: (key: string, value: string) => void map.set(key, value),
  } as unknown as Storage
}

describe("the attempt marker", () => {
  it("reads back what was written", () => {
    const store = memoryStorage()
    expect(readAutoEnableAttempt(store, "k")).toBe(false)
    writeAutoEnableAttempt(store, "k")
    expect(readAutoEnableAttempt(store, "k")).toBe(true)
  })

  it("treats a store that throws as 'not yet asked' rather than crashing", () => {
    // Failing closed here would mean never asking on a private window; the
    // permission itself still stops a second prompt.
    expect(readAutoEnableAttempt(hostileStorage(), "k")).toBe(false)
  })

  it("swallows a refused write", () => {
    expect(() => writeAutoEnableAttempt(hostileStorage(), "k")).not.toThrow()
  })
})
