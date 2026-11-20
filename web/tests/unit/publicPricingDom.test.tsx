// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { act, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import type { PublicCatalogue } from "@/lib/billingTypes"
import { errorQuery, okQuery } from "./support/billingRender"

const tier = (code: string, name: string, audience: "student" | "teacher", interval: "month" | "year", priceMinor: number) => ({
  code, name, audience, interval, priceMinor, currency: "EGP", features: [], includedSeats: audience === "teacher" ? 20 : null, extraSeatPriceMinor: audience === "teacher" ? 3000 : null,
})
const students: PublicCatalogue = {
  audience: "student",
  creditValidityMonths: 12,
  tiers: [tier("student_plus_m", "Student Plus", "student", "month", 25000), tier("student_plus_y", "Student Plus", "student", "year", 250000)],
  packs: [],
}
const teachers: PublicCatalogue = {
  audience: "teacher",
  creditValidityMonths: 12,
  tiers: [tier("teacher_pro_m", "Teacher Pro", "teacher", "month", 90000), tier("teacher_pro_y", "Teacher Pro", "teacher", "year", 900000)],
  packs: [],
}

const s = vi.hoisted(() => ({ asked: [] as string[], session: null as unknown, result: (() => null) as (audience: string) => unknown }))
vi.mock("@/lib/auth/AuthContext", () => ({ useAuth: () => ({ session: s.session }) }))
vi.mock("@/lib/hooks/useBillingApi", () => ({
  usePublicCatalogue: (audience: string) => {
    s.asked.push(audience)
    return s.result(audience)
  },
}))
vi.mock("@/portals/marketing", () => ({ MarketingFrame: (p: { children: unknown }) => h("main", null, p.children as never) }))

import { Pricing } from "@/portals/marketing/Pricing"

const open = (path = "/pricing") => render(h(MemoryRouter, { initialEntries: [path] }, h(Pricing)))

describe("Pricing toggles", () => {
  beforeEach(() => {
    s.asked = []
    s.session = null
  })

  it("starts on students monthly and switches audience and interval", async () => {
    const user = userEvent.setup()
    // The fake follows the audience asked for, like the real hook keyed on it.
    s.result = (audience) => okQuery(audience === "teacher" ? teachers : students)
    open()
    expect(screen.getByRole("radio", { name: "Students" }).getAttribute("aria-checked")).toBe("true")
    expect(screen.getByRole("radio", { name: "Monthly" }).getAttribute("aria-checked")).toBe("true")
    expect(screen.getByText(/EGP\s250\.00/)).toBeTruthy()

    await user.click(screen.getByRole("radio", { name: "Yearly" }))
    expect(screen.getByText(/EGP\s2,500\.00/)).toBeTruthy()
    expect(screen.queryByText(/EGP\s250\.00/)).toBeNull()

    await user.click(screen.getByRole("radio", { name: "Teachers" }))
    expect(s.asked.at(-1)).toBe("teacher")
    expect(screen.getByText("20 student seats included")).toBeTruthy()
    expect(screen.getByText(/EGP\s9,000\.00/)).toBeTruthy()
    // The link keeps the chosen interval.
    expect(screen.getByRole("link", { name: "Choose Teacher Pro" }).getAttribute("href")).toBe(
      `/login?next=${encodeURIComponent("/teacher/billing/plans?plan=teacher_pro_y&interval=year")}`,
    )
  })

  it("honours ?audience=teacher on arrival", () => {
    s.result = () => okQuery(teachers)
    open("/pricing?audience=teacher")
    expect(screen.getByRole("radio", { name: "Teachers" }).getAttribute("aria-checked")).toBe("true")
    expect(s.asked[0]).toBe("teacher")
  })
})

describe("Pricing rate limit countdown", () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it("counts down, keeps Try again locked until zero, then refetches on click", () => {
    const refetch = vi.fn()
    const failed = { ...errorQuery(new ApiError(429, "x", undefined, 3)), refetch }
    s.result = () => failed
    open()
    expect(screen.getByRole("timer").textContent).toContain("Too many requests. Try again in 3 seconds.")
    expect((screen.getByRole("button", { name: "Try again" }) as HTMLButtonElement).disabled).toBe(true)

    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(screen.getByRole("timer").textContent).toContain("Try again in 2 seconds.")
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(screen.getByRole("timer").textContent).toContain("Try again in 1 second.")
    expect((screen.getByRole("button", { name: "Try again" }) as HTMLButtonElement).disabled).toBe(true)

    act(() => {
      vi.advanceTimersByTime(1500)
    })
    expect(screen.getByRole("timer").textContent).toContain("You can try again now.")
    const retry = screen.getByRole("button", { name: "Try again" })
    expect((retry as HTMLButtonElement).disabled).toBe(false)
    act(() => {
      retry.click()
    })
    expect(refetch).toHaveBeenCalledTimes(1)
  })

  it("announces the reason and initial wait once, then only when Try again unlocks", () => {
    const failed = errorQuery(new ApiError(429, "x", undefined, 3))
    s.result = () => failed
    open()
    // The alert (read once) states the reason and the starting wait; it never ticks.
    expect(screen.getByRole("alert").textContent).toBe("Couldn't load prices. Too many requests. Try again in 3 seconds.")
    // The status is silent until the lock lifts; the visible timer is the only thing that ticks.
    const status = screen.getByRole("status")
    expect(status.textContent).toBe("")
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(screen.getByRole("alert").textContent).toContain("in 3 seconds")
    expect(status.textContent).toBe("")
    expect(screen.getByRole("timer").textContent).toContain("in 2 seconds")
    act(() => {
      vi.advanceTimersByTime(2500)
    })
    expect(screen.getByRole("status").textContent).toBe("You can try again now.")
    expect(screen.getByRole("alert").textContent).toContain("in 3 seconds")
  })
})

describe("Pricing links by session", () => {
  beforeEach(() => {
    s.asked = []
    s.result = () => okQuery(teachers)
  })

  it("signed out: Choose plan goes through sign-in with next, and sign-up links are shown", () => {
    s.session = null
    open("/pricing?audience=teacher")
    const next = encodeURIComponent("/teacher/billing/plans?plan=teacher_pro_m&interval=month")
    expect(screen.getByRole("link", { name: "Choose Teacher Pro" }).getAttribute("href")).toBe(`/login?next=${next}`)
    expect(screen.getByRole("link", { name: /New to Lemely\? Sign up/ }).getAttribute("href")).toBe(`/signup/teacher?next=${next}`)
    expect(screen.getByRole("link", { name: "Create a teacher account" })).toBeTruthy()
  })

  it("signed in: Choose plan goes straight to the plans page and the sign-up links are gone", () => {
    s.session = { role: "teacher" }
    open("/pricing?audience=teacher")
    expect(screen.getByRole("link", { name: "Choose Teacher Pro" }).getAttribute("href")).toBe(
      "/teacher/billing/plans?plan=teacher_pro_m&interval=month",
    )
    expect(screen.queryByRole("link", { name: /Sign up/ })).toBeNull()
    expect(screen.queryByRole("link", { name: /Create a teacher account/ })).toBeNull()
  })
})
