// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { errorQuery, pendingQuery } from "./support/billingRender"

/*
 * The range and rate fields against the screen's own state: only a valid range reaches the report hook,
 * and the field that makes a value unsendable says so inline. The rate is the only way the
 * server learns a USD to EGP rate, so a typed rate must reach the hook.
 */

const s = vi.hoisted(() => ({ calls: [] as Array<[string, string, string | null]>, result: null as unknown }))
vi.mock("@/lib/hooks/useAdminBillingApi", () => ({
  useMarginReport: (from: string, to: string, rate: string | null = null) => {
    s.calls.push([from, to, rate])
    return s.result
  },
}))

import { Margin } from "@/portals/admin/screens/billing/Margin"

const last = () => s.calls[s.calls.length - 1]
const RATE_KEY = "lemely.admin.margin.egpPerUsd"

// Node's own `localStorage` global shadows jsdom's and is undefined without a flag, so the test
// brings its own store (as sessionExpiry.test.ts does).
const store = new Map<string, string>()
const localStorageFake = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, v),
  removeItem: (k: string) => void store.delete(k),
  clear: () => store.clear(),
}

beforeEach(() => {
  s.calls = []
  s.result = pendingQuery()
  vi.stubGlobal("localStorage", localStorageFake)
  localStorage.clear()
  vi.useFakeTimers({ toFake: ["Date"] })
  vi.setSystemTime(new Date("2026-11-05T12:00:00Z"))
})

function mount() {
  render(h(MemoryRouter, null, h(Margin)))
}

describe("Margin range", () => {
  it("starts on the last 90 UTC days", () => {
    mount()
    expect(last()).toEqual(["2026-08-08", "2026-11-05", null])
    expect((screen.getByLabelText("From") as HTMLInputElement).value).toBe("2026-08-08")
    expect((screen.getByLabelText("To") as HTMLInputElement).value).toBe("2026-11-05")
  })

  it("sends a new valid range", () => {
    mount()
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-10-01" } })
    expect(last()).toEqual(["2026-10-01", "2026-11-05", null])
  })

  it("keeps the last valid range when the start passes the end, and says why", () => {
    mount()
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-07-01" } })
    expect(last()).toEqual(["2026-08-08", "2026-11-05", null])
    expect(screen.getByText("The end day is before the start day.")).toBeTruthy()
    expect((screen.getByLabelText("To") as HTMLInputElement).value).toBe("2026-07-01")
  })

  it("keeps the last valid range while a day is cleared, then recovers", () => {
    mount()
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "" } })
    expect(last()).toEqual(["2026-08-08", "2026-11-05", null])
    expect(screen.getByText("Pick a start day.")).toBeTruthy()
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-09-01" } })
    expect(last()).toEqual(["2026-09-01", "2026-11-05", null])
    expect(screen.queryByText("Pick a start day.")).toBeNull()
  })

  it("keeps the last valid range when a typed one is over 400 days", () => {
    mount()
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2025-10-01" } })
    expect(last()).toEqual(["2026-08-08", "2026-11-05", null])
    expect(screen.getByText("A range can cover at most 400 days.")).toBeTruthy()
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2025-10-02" } })
    expect(last()).toEqual(["2025-10-02", "2026-11-05", null])
  })
})

describe("Margin rate", () => {
  const rate = () => screen.getByLabelText("EGP per USD") as HTMLInputElement

  it("sends no rate until one is typed, then sends it and remembers it", () => {
    mount()
    expect(last()[2]).toBeNull()
    fireEvent.change(rate(), { target: { value: "50" } })
    expect(last()).toEqual(["2026-08-08", "2026-11-05", "50"])
    expect(localStorage.getItem(RATE_KEY)).toBe("50")
  })

  it("starts from the rate this browser used last", () => {
    localStorage.setItem(RATE_KEY, "48.5")
    mount()
    expect(rate().value).toBe("48.5")
    expect(last()[2]).toBe("48.5")
  })

  it("ignores a stored rate that is no longer valid", () => {
    localStorage.setItem(RATE_KEY, "0")
    mount()
    expect(rate().value).toBe("")
    expect(last()[2]).toBeNull()
  })

  it("keeps the last valid rate while the typed one is not valid, and says why", () => {
    mount()
    fireEvent.change(rate(), { target: { value: "50" } })
    for (const [typed, message] of [
      ["0", "The rate must be more than 0."],
      ["10001", "The rate can be at most 10,000."],
      ["abc", "Enter a number, such as 50 or 48.5."],
    ] as const) {
      fireEvent.change(rate(), { target: { value: typed } })
      expect(last()[2]).toBe("50")
      expect(screen.getByText(message)).toBeTruthy()
      expect(localStorage.getItem(RATE_KEY)).toBe("50")
    }
  })

  it("sends no rate again once the box is cleared, and forgets it", () => {
    mount()
    fireEvent.change(rate(), { target: { value: "50" } })
    fireEvent.change(rate(), { target: { value: "" } })
    expect(last()[2]).toBeNull()
    expect(localStorage.getItem(RATE_KEY)).toBeNull()
  })
})

describe("Margin when the admin may not read it", () => {
  it("hides the range and rate fields behind the refusal", () => {
    s.result = errorQuery(new ApiError(403, "no", undefined))
    mount()
    expect(screen.getByText("You can't see money and margin")).toBeTruthy()
    expect(screen.queryByLabelText("From")).toBeNull()
    expect(screen.queryByLabelText("EGP per USD")).toBeNull()
  })
})
