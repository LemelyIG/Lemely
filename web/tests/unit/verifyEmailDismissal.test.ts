import { describe, expect, it } from "vitest"
import {
  readDismissed,
  VERIFY_EMAIL_DISMISS_KEY,
  writeDismissed,
  type BannerStorage,
} from "@/lib/verifyEmailDismissal"

/*
 * The banner's dismissal is session-scoped and must never be the reason a
 * portal shell crashes. Safari private browsing and a full quota both make
 * storage throw, so every case here is really one rule: a storage that
 * misbehaves reads as "not dismissed" and the banner shows.
 */

function fakeStorage(initial: Record<string, string> = {}): BannerStorage {
  const map = new Map(Object.entries(initial))
  return {
    getItem: (key) => map.get(key) ?? null,
    setItem: (key, value) => {
      map.set(key, value)
    },
  }
}

const throwingStorage: BannerStorage = {
  getItem: () => {
    throw new Error("SecurityError: storage is disabled")
  },
  setItem: () => {
    throw new Error("QuotaExceededError")
  },
}

describe("readDismissed", () => {
  it("is false for a fresh session", () => {
    expect(readDismissed(fakeStorage())).toBe(false)
  })

  it("is true once a dismissal has been written", () => {
    const storage = fakeStorage()
    writeDismissed(storage)
    expect(readDismissed(storage)).toBe(true)
  })

  it("reads a throwing storage as not dismissed, so the banner still shows", () => {
    expect(readDismissed(throwingStorage)).toBe(false)
  })

  it("reads an absent storage as not dismissed", () => {
    // Server-side rendering, or a browser where `sessionStorage` is not
    // exposed at all. Neither is a reason to hide the banner.
    expect(readDismissed(undefined)).toBe(false)
  })

  it("ignores a value that is not the stored marker", () => {
    expect(readDismissed(fakeStorage({ [VERIFY_EMAIL_DISMISS_KEY]: "maybe" }))).toBe(false)
  })
})

describe("writeDismissed", () => {
  it("does not throw when storage refuses the write", () => {
    expect(() => writeDismissed(throwingStorage)).not.toThrow()
  })

  it("does not throw when there is no storage at all", () => {
    expect(() => writeDismissed(undefined)).not.toThrow()
  })
})
