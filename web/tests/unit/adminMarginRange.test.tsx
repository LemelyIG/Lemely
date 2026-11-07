// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { pendingQuery } from "./support/billingRender"

/*
 * The range fields against the screen's own state: only a valid range reaches the report hook,
 * and the field that makes a range unsendable says so inline.
 */

const s = vi.hoisted(() => ({ calls: [] as Array<[string, string]> }))
vi.mock("@/lib/hooks/useAdminBillingApi", () => ({
  useMarginReport: (from: string, to: string) => {
    s.calls.push([from, to])
    return { ...pendingQuery() }
  },
}))

import { Margin } from "@/portals/admin/screens/billing/Margin"

const last = () => s.calls[s.calls.length - 1]

beforeEach(() => {
  s.calls = []
  vi.useFakeTimers({ toFake: ["Date"] })
  vi.setSystemTime(new Date("2026-11-05T12:00:00Z"))
})

function mount() {
  render(h(MemoryRouter, null, h(Margin)))
}

describe("Margin range", () => {
  it("starts on the last 90 UTC days", () => {
    mount()
    expect(last()).toEqual(["2026-08-07", "2026-11-05"])
    expect((screen.getByLabelText("From") as HTMLInputElement).value).toBe("2026-08-07")
    expect((screen.getByLabelText("To") as HTMLInputElement).value).toBe("2026-11-05")
  })

  it("sends a new valid range", () => {
    mount()
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-10-01" } })
    expect(last()).toEqual(["2026-10-01", "2026-11-05"])
  })

  it("keeps the last valid range when the start passes the end, and says why", () => {
    mount()
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-07-01" } })
    expect(last()).toEqual(["2026-08-07", "2026-11-05"])
    expect(screen.getByText("The end day is before the start day.")).toBeTruthy()
    expect((screen.getByLabelText("To") as HTMLInputElement).value).toBe("2026-07-01")
  })

  it("keeps the last valid range while a day is cleared, then recovers", () => {
    mount()
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "" } })
    expect(last()).toEqual(["2026-08-07", "2026-11-05"])
    expect(screen.getByText("Pick a start day.")).toBeTruthy()
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-09-01" } })
    expect(last()).toEqual(["2026-09-01", "2026-11-05"])
    expect(screen.queryByText("Pick a start day.")).toBeNull()
  })
})
