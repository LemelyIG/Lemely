import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { captureWaitlistUtm, readWaitlistUtm } from "@/portals/marketing/waitlist/utm"
import { sessionLabel, sessionShort } from "@/portals/admin/screens/Waitlist"

// The suite runs in the node environment. Node 22 (CI) has no sessionStorage
// global, so each test gets a fresh in-memory one.
function memoryStorage(): Storage {
  const data = new Map<string, string>()
  return {
    get length() {
      return data.size
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, String(value)),
  }
}

describe("waitlist UTM capture", () => {
  beforeEach(() => vi.stubGlobal("sessionStorage", memoryStorage()))
  afterEach(() => vi.unstubAllGlobals())

  it("keeps utm_* from the arrival URL for the tab", () => {
    captureWaitlistUtm("?utm_source=waitlist_share&utm_medium=chat&x=1")
    expect(readWaitlistUtm()).toMatchObject({ utmSource: "waitlist_share", utmMedium: "chat", utmCampaign: null })
  })

  it("first touch wins: a later URL without UTM, or with different UTM, never overwrites", () => {
    captureWaitlistUtm("?utm_source=first")
    captureWaitlistUtm("")
    captureWaitlistUtm("?utm_source=second")
    expect(readWaitlistUtm().utmSource).toBe("first")
  })

  it("reads as all-null when nothing was captured", () => {
    expect(readWaitlistUtm().utmSource).toBeNull()
  })

  it("caps a hostile value at 100 characters", () => {
    captureWaitlistUtm(`?utm_source=${"a".repeat(500)}`)
    expect(readWaitlistUtm().utmSource).toHaveLength(100)
  })
})

describe("waitlist session labels", () => {
  it("expands and abbreviates the server's session values", () => {
    expect(sessionLabel("2027-mj")).toBe("May/June 2027")
    expect(sessionLabel("2027-on")).toBe("Oct/Nov 2027")
    expect(sessionShort("2027-mj")).toBe("MJ 27")
    expect(sessionShort("2027-on")).toBe("ON 27")
  })

  it("passes unknown shapes through and dashes an empty value", () => {
    expect(sessionLabel("someday")).toBe("someday")
    expect(sessionLabel(null)).toBe("")
    expect(sessionShort(null)).toBe("-")
  })
})
