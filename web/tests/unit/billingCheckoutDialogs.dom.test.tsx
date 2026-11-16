// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { render, renderHook, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { fx } from "./support/billingFixtures"
import { fakeMutation } from "./support/billingRender"

/*
 * Upgrade and extra seats leave for Paymob's hosted checkout and come back to the return page.
 * Mutations are faked with `mutate` that settles like react-query does (calling the per-call
 * `onSuccess`), so these tests see what the dialog does with a 201, a 503 and a phone refusal.
 */

type Settle = { ok?: unknown; err?: unknown }
const s = vi.hoisted(() => ({
  quote: null as unknown,
  seatQuote: null as unknown,
  upgrade: null as unknown,
  addSeats: null as unknown,
  downgrade: null as unknown,
  reduce: null as unknown,
  put: null as unknown,
  bumps: [] as Array<() => void>,
}))

// Each hook subscribes its component to `s.bumps`, so a fake `mutate` that settles re-renders it.
vi.mock("@/lib/hooks/useBillingApi", async () => {
  const { useState } = await vi.importActual<typeof import("react")>("react")
  const sub = <T,>(get: () => T) => () => {
    const [, set] = useState(0)
    s.bumps.push(() => set((n) => n + 1))
    return get()
  }
  return {
    useUpgradeQuote: sub(() => s.quote),
    useUpgrade: sub(() => s.upgrade),
    useDowngrade: sub(() => s.downgrade),
    useSeatQuote: sub(() => s.seatQuote),
    useAddSeats: sub(() => s.addSeats),
    useReduceSeats: sub(() => s.reduce),
  }
})
vi.mock("@/lib/hooks/useMeApi", () => ({ usePutPhone: () => s.put }))
vi.mock("@/components/ui/modal", () => ({
  Modal: (p: { open: boolean; title: unknown; children: unknown; footer?: unknown }) =>
    p.open ? h("div", { role: "dialog" }, h("h2", null, p.title as never), p.children as never, p.footer as never) : null,
}))

import { PlanChangeDialog } from "@/portals/billing/PlanChangeDialog"
import { AddSeatsDialog } from "@/portals/teacher/screens/team/SeatCountDialogs"

const quoted = { amountMinor: 7500, currency: "EGP", allowanceUnits: 900, periodEnd: "2026-12-01T00:00:00Z" }
const up = { ...fx.studentMonthly, id: "t-up", name: "Student Max", priceMinor: 40000 }
const good = { paymentId: "pay1", checkoutUrl: "https://eg.checkout.paymob.com/?publicKey=pk&clientSecret=cs" }

/** A mutation whose `mutate` settles synchronously with `settle`, like a finished request. */
function settling(settle: Settle) {
  const m = fakeMutation()
  m.mutate = vi.fn((vars: unknown, opts?: { onSuccess?: (d: unknown) => void }) => {
    ;(m as { variables?: unknown }).variables = vars
    if ("ok" in settle) {
      m.isSuccess = true
      m.data = settle.ok
      opts?.onSuccess?.(settle.ok)
    } else {
      m.isError = true
      m.error = settle.err
    }
    s.bumps.forEach((b) => b())
  })
  return m
}

const sessionStore = () => {
  const m = new Map<string, string>()
  vi.stubGlobal("sessionStorage", { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) })
  return m
}

const openPlan = (savedCard = fx.summary.savedCard, go = vi.fn()) => {
  render(
    h(MemoryRouter, null, h(PlanChangeDialog, {
      open: true, onClose: () => undefined, subscription: fx.activeSub, tier: up, savedCard, returnTo: "/teacher/billing", go,
    })),
  )
  return go
}

beforeEach(() => {
  s.quote = Object.assign(fakeMutation({ isSuccess: true, data: quoted }), { variables: { subscriptionId: "sub1", planTierId: "t-up" } })
  s.seatQuote = fakeMutation({ isSuccess: true, data: { ...quoted, allowanceUnits: null, amountMinor: 4500 } })
  s.upgrade = settling({ ok: good })
  s.addSeats = settling({ ok: good })
  s.downgrade = fakeMutation()
  s.reduce = fakeMutation()
  s.put = fakeMutation()
  s.bumps = []
})

describe("PlanChangeDialog to Paymob", () => {
  it("with no saved card, requests the quote and shows the continue button", () => {
    openPlan(null)
    expect((s.quote as { mutate: ReturnType<typeof vi.fn> }).mutate).toHaveBeenCalledWith({ subscriptionId: "sub1", planTierId: "t-up" })
    expect(screen.getByRole("button", { name: /Continue to payment \(EGP\s75\.00\)/ })).toBeTruthy()
  })

  it("redirects to the checkout URL and remembers the page it was opened from", async () => {
    const store = sessionStore()
    const go = openPlan()
    await userEvent.setup().click(screen.getByRole("button", { name: /Continue to payment/ }))
    expect((s.upgrade as { mutate: ReturnType<typeof vi.fn> }).mutate.mock.calls[0][0]).toEqual({ subscriptionId: "sub1", planTierId: "t-up" })
    expect(go).toHaveBeenCalledWith(good.checkoutUrl)
    expect(store.get("lemely.billing.returnTo.pay1")).toBe("/teacher/billing")
    expect(screen.queryByText(/upgraded|Plan upgraded/i)).toBeNull()
  })

  it("never navigates on an unsafe URL and says nothing was charged", async () => {
    s.upgrade = settling({ ok: { paymentId: "pay1", checkoutUrl: "http://evil.example/pay" } })
    const go = openPlan()
    await userEvent.setup().click(screen.getByRole("button", { name: /Continue to payment/ }))
    expect(go).not.toHaveBeenCalled()
    expect((await screen.findByRole("alert")).textContent).toContain("Nothing was charged")
  })

  it("says nothing was charged on a 503", async () => {
    s.upgrade = settling({ err: new ApiError(503, "x", { error: "payments_unavailable", message: "x" }) })
    const go = openPlan()
    await userEvent.setup().click(screen.getByRole("button", { name: /Continue to payment/ }))
    expect(go).not.toHaveBeenCalled()
    expect((await screen.findByRole("alert")).textContent).toContain("Nothing was charged")
  })

  it("asks for a phone number in place on 422 phone_required", async () => {
    s.upgrade = settling({ err: new ApiError(422, "x", { code: "phone_required", message: "x" }) })
    openPlan()
    await userEvent.setup().click(screen.getByRole("button", { name: /Continue to payment/ }))
    expect(await screen.findByText("Add your mobile number to continue")).toBeTruthy()
    expect(screen.queryByRole("button", { name: /Continue to payment/ })).toBeNull()
  })

  it("a seats_not_sold refusal names the extra seats held", async () => {
    s.upgrade = settling({ err: new ApiError(409, "x", { error: "seats_not_sold", message: "x", extraSeats: 3 }) })
    openPlan()
    await userEvent.setup().click(screen.getByRole("button", { name: /Continue to payment/ }))
    expect((await screen.findByRole("alert")).textContent).toContain("3 extra seats")
  })

  it("explains cancel-and-resubscribe when the plan cannot be upgraded mid-period", async () => {
    s.upgrade = settling({ err: new ApiError(409, "x", { error: "upgrade_unavailable", message: "x", next: "cancel_and_resubscribe" }) })
    openPlan()
    await userEvent.setup().click(screen.getByRole("button", { name: /Continue to payment/ }))
    expect((await screen.findByRole("alert")).textContent).toContain("Cancel at the end of the period and subscribe to the new plan")
  })
})

describe("AddSeatsDialog to Paymob", () => {
  const open = (savedCard = fx.team.savedCard, go = vi.fn()) => {
    render(h(AddSeatsDialog, { open: true, onClose: () => undefined, subscriptionId: "sub-t", perSeatMinor: 3000, savedCard, returnTo: "/teacher/team", go }))
    return go
  }

  it("redirects with the team page as the return path", async () => {
    const store = sessionStore()
    const go = open(null)
    await userEvent.setup().click(screen.getByRole("button", { name: /Continue to payment \(EGP\s45\.00\)/ }))
    expect((s.addSeats as { mutate: ReturnType<typeof vi.fn> }).mutate.mock.calls[0][0]).toEqual({ subscriptionId: "sub-t", seats: 1 })
    expect(go).toHaveBeenCalledWith(good.checkoutUrl)
    expect(store.get("lemely.billing.returnTo.pay1")).toBe("/teacher/team")
  })

  it("never navigates on an unsafe URL", async () => {
    s.addSeats = settling({ ok: { paymentId: "pay1", checkoutUrl: "javascript:alert(1)" } })
    const go = open()
    await userEvent.setup().click(screen.getByRole("button", { name: /Continue to payment/ }))
    expect(go).not.toHaveBeenCalled()
    expect((await screen.findByRole("alert")).textContent).toContain("Nothing was charged")
  })

  it("an out-of-range count disables the quote and keeps the payment button away", async () => {
    s.seatQuote = fakeMutation()
    open()
    const input = screen.getByLabelText("How many seats")
    const user = userEvent.setup()
    await user.clear(input)
    await user.type(input, "500")
    expect(screen.getByText("Use 100 or fewer.")).toBeTruthy()
    expect((screen.getByRole("button", { name: "Get the price" }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.queryByRole("button", { name: /Continue to payment/ })).toBeNull()
  })

  it("a seats_over_limit refusal says so and nothing was added", async () => {
    s.addSeats = settling({ err: new ApiError(409, "x", { error: "seats_over_limit", message: "x" }) })
    open()
    await userEvent.setup().click(screen.getByRole("button", { name: /Continue to payment/ }))
    expect((await screen.findByRole("alert")).textContent).toContain("past the most seats")
  })
})

describe("upgrade and seat mutations change nothing until the return page sees paid", () => {
  it("does not invalidate billing on success", async () => {
    const real = await vi.importActual<typeof import("@/lib/hooks/useBillingApi")>("@/lib/hooks/useBillingApi")
    const api = await import("@/lib/api")
    vi.spyOn(api, "request").mockResolvedValue(good)
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, "invalidateQueries")
    const wrap = ({ children }: { children: React.ReactNode }) => h(QueryClientProvider, { client: qc }, children)
    for (const hook of [real.useUpgrade, real.useAddSeats]) {
      const { result } = renderHook(() => hook(), { wrapper: wrap })
      result.current.mutate({ subscriptionId: "s1", planTierId: "t1", seats: 2 } as never)
      await waitFor(() => expect(result.current.isSuccess).toBe(true))
      expect(result.current.data).toEqual(good)
    }
    expect(spy).not.toHaveBeenCalled()
  })
})
