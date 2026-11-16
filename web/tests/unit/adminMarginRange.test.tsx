// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { fx } from "./support/billingFixtures"
import { errorQuery, okQuery, pendingQuery } from "./support/billingRender"

/*
 * The range and rate fields against the screen's own state: only a valid range reaches the report hook,
 * and the field that makes a value unsendable says so inline. The rate is the only way the
 * server learns a USD to EGP rate, so a typed rate must reach the hook.
 */

vi.mock("@/components/ui/lazy-chart", () => ({ BarChart: () => null }))

const s = vi.hoisted(() => ({ calls: [] as Array<[string, string, string | null]>, result: null as unknown }))
vi.mock("@/lib/hooks/useAdminBillingApi", () => ({
  useMarginReport: (from: string, to: string, rate: string | null = null) => {
    s.calls.push([from, to, rate])
    return s.result
  },
}))

import { Margin } from "@/portals/admin/screens/billing/Margin"

const last = () => s.calls[s.calls.length - 1]

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
  const withDefault = (egpPerUsd: string | null, source: "settings" | "request" | null = "settings") =>
    okQuery({ ...fx.margin, egpPerUsd, egpPerUsdSource: source })

  it("sends no rate until one is typed, then sends it as an override for this visit", () => {
    mount()
    expect(last()[2]).toBeNull()
    fireEvent.change(rate(), { target: { value: "50" } })
    expect(last()).toEqual(["2026-08-08", "2026-11-05", "50"])
    expect(screen.getByText("Your override, for this visit.")).toBeTruthy()
  })

  it("shows the server's default in the box and sends nothing until it is overridden", () => {
    s.result = withDefault("48.5")
    mount()
    expect(rate().value).toBe("48.5")
    expect(last()[2]).toBeNull()
    expect(screen.getByText("The default from billing rules.")).toBeTruthy()
  })

  it("says so when no default is set", () => {
    s.result = withDefault(null, null)
    mount()
    expect(rate().value).toBe("")
    expect(screen.getByText("No default is set. Add one in billing rules, or type a rate.")).toBeTruthy()
  })

  it("keeps the default after an override is answered, and returns to it", () => {
    s.result = withDefault("48.5")
    mount()
    fireEvent.change(rate(), { target: { value: "52" } })
    s.result = withDefault("52", "request")
    fireEvent.change(rate(), { target: { value: "52.5" } })
    expect(last()[2]).toBe("52.5")
    fireEvent.click(screen.getByRole("button", { name: "Use default" }))
    expect(last()[2]).toBeNull()
    expect(rate().value).toBe("48.5")
    expect(screen.queryByRole("button", { name: "Use default" })).toBeNull()
  })

  it("does not keep the rate in the browser", () => {
    mount()
    fireEvent.change(rate(), { target: { value: "50" } })
    expect(store.size).toBe(0)
  })

  it("keeps the last valid rate while the typed one is not valid, and says why", () => {
    mount()
    fireEvent.change(rate(), { target: { value: "50" } })
    for (const [typed, message] of [
      ["0", "The rate must be more than 0."],
      ["10001", "The rate can be at most 10,000."],
      ["abc", "Enter a number, such as 50 or 48.5."],
      ["50.12345", "Use at most 4 decimal places."],
    ] as const) {
      fireEvent.change(rate(), { target: { value: typed } })
      expect(last()[2]).toBe("50")
      expect(screen.getByText(message)).toBeTruthy()
    }
  })

  it("falls back to the default once the box is cleared", () => {
    s.result = withDefault("48.5")
    mount()
    fireEvent.change(rate(), { target: { value: "50" } })
    fireEvent.change(rate(), { target: { value: "" } })
    expect(last()[2]).toBeNull()
    expect(screen.getByText("Empty uses the default, 48.5.")).toBeTruthy()
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
