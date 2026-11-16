// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { act, render, renderHook, screen, waitFor } from "@testing-library/react"
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

/**
 * A mutation with react-query's state machine in miniature: `mutate` records its variables and
 * settles by `plan(callNumber)`, `reset` clears the result, and every change re-renders.
 */
function stateful(plan: (call: number) => Settle | "pending") {
  const m = fakeMutation() as ReturnType<typeof fakeMutation> & { variables?: unknown; calls: number }
  m.calls = 0
  const clear = () => Object.assign(m, { isPending: false, isSuccess: false, isError: false, data: undefined, error: null })
  m.reset = vi.fn(() => {
    clear()
    s.bumps.forEach((b) => b())
  })
  m.mutate = vi.fn((vars: unknown, opts?: { onSuccess?: (d: unknown) => void }) => {
    m.calls += 1
    m.variables = vars
    clear()
    const out = plan(m.calls)
    if (out === "pending") m.isPending = true
    else if ("ok" in out) {
      m.isSuccess = true
      m.data = out.ok
      opts?.onSuccess?.(out.ok)
    } else {
      m.isError = true
      m.error = out.err
    }
    s.bumps.forEach((b) => b())
  })
  return m
}
const settling = (settle: Settle) => stateful(() => settle)

const sessionStore = () => {
  const m = new Map<string, string>()
  vi.stubGlobal("sessionStorage", { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) })
  return m
}

const openPlan = (go = vi.fn(), tier = up) => {
  render(
    h(MemoryRouter, null, h(PlanChangeDialog, {
      open: true, onClose: () => undefined, subscription: fx.activeSub, tier, returnTo: "/teacher/billing", go,
    })),
  )
  return go
}
const cont = () => screen.getByRole("button", { name: /Continue to payment/ }) as HTMLButtonElement
const mut = (m: unknown) => (m as { mutate: ReturnType<typeof vi.fn> }).mutate

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
  it("requests the quote and shows the continue button", () => {
    openPlan()
    expect(mut(s.quote)).toHaveBeenCalledWith({ subscriptionId: "sub1", planTierId: "t-up" })
    expect(cont()).toBeTruthy()
    expect(screen.getByRole("status").textContent).toMatch(/Pay EGP\s75\.00 now/)
  })

  it("redirects to the checkout URL and remembers the page it was opened from", async () => {
    const store = sessionStore()
    const go = openPlan()
    await userEvent.setup().click(cont())
    expect(mut(s.upgrade).mock.calls[0][0]).toEqual({ subscriptionId: "sub1", planTierId: "t-up" })
    expect(go).toHaveBeenCalledWith(good.checkoutUrl)
    expect(store.get("lemely.billing.returnTo.pay1")).toBe("/teacher/billing")
    expect(screen.queryByText(/upgraded|Plan upgraded/i)).toBeNull()
  })

  it("blocks a second click after the 201 and says where it is going", async () => {
    sessionStore()
    const go = openPlan()
    const user = userEvent.setup()
    await user.click(cont())
    expect(screen.getByRole("status").textContent).toBe("Taking you to payment…")
    expect(cont().disabled).toBe(true)
    await user.click(cont())
    expect(mut(s.upgrade)).toHaveBeenCalledTimes(1)
    expect(go).toHaveBeenCalledTimes(1)
  })

  it("starts over when the browser restores the page from its back-forward cache", async () => {
    sessionStore()
    openPlan()
    await userEvent.setup().click(cont())
    expect(cont().disabled).toBe(true)
    act(() => {
      window.dispatchEvent(Object.assign(new Event("pageshow"), { persisted: true }))
    })
    expect(cont().disabled).toBe(false)
    // A pageshow that is not a restore changes nothing.
    await userEvent.setup().click(cont())
    act(() => {
      window.dispatchEvent(Object.assign(new Event("pageshow"), { persisted: false }))
    })
    expect(cont().disabled).toBe(true)
  })

  it("never navigates on an unsafe URL and says nothing was charged", async () => {
    sessionStore()
    s.upgrade = settling({ ok: { paymentId: "pay1", checkoutUrl: "http://evil.example/pay" } })
    const go = openPlan()
    await userEvent.setup().click(cont())
    expect(go).not.toHaveBeenCalled()
    expect((await screen.findByRole("alert")).textContent).toContain("Nothing was charged")
    expect(cont().disabled).toBe(false)
  })

  it("says nothing was charged on a 503 and lets the payer try again", async () => {
    s.upgrade = settling({ err: new ApiError(503, "x", { error: "payments_unavailable", message: "x" }) })
    const go = openPlan()
    await userEvent.setup().click(cont())
    expect(go).not.toHaveBeenCalled()
    expect((await screen.findByRole("alert")).textContent).toContain("Nothing was charged")
    expect(cont().disabled).toBe(false)
  })

  it.each([
    ["upgrade_unavailable", {}],
    ["seats_not_sold", { extraSeats: 3 }],
    ["subscription_not_active", {}],
  ])("takes away Continue after a %s refusal, which would fail the same way again", async (code, extra) => {
    s.upgrade = settling({ err: new ApiError(409, "x", { error: code, message: "x", ...extra }) })
    openPlan()
    await userEvent.setup().click(cont())
    await screen.findByRole("alert")
    expect(screen.queryByRole("button", { name: /Continue to payment/ })).toBeNull()
  })

  it.each([
    ["upgrade_unavailable", { next: "cancel_and_resubscribe" }],
    ["seats_not_sold", { extraSeats: 3 }],
    ["subscription_not_active", {}],
  ])("drops the price line once %s refuses, so no price or next step is left on screen", async (code, extra) => {
    s.upgrade = settling({ err: new ApiError(409, "x", { error: code, message: "x", ...extra }) })
    openPlan()
    expect(screen.getByRole("status").textContent).toMatch(/Pay EGP\s75\.00 now/)
    await userEvent.setup().click(cont())
    await screen.findByRole("alert")
    expect(document.body.textContent).not.toMatch(/Pay EGP|confirm with your bank/)
  })

  it.each([
    ["offline", new ApiError(0, "x")],
    ["a 503", new ApiError(503, "x", { error: "payments_unavailable", message: "x" })],
  ])("offers Try again when the quote fails on %s, and asks for the quote again", async (_n, err) => {
    s.quote = Object.assign(fakeMutation({ isError: true, error: err }), { variables: { subscriptionId: "sub1", planTierId: "t-up" } })
    openPlan()
    expect(mut(s.quote)).toHaveBeenCalledTimes(1)
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }))
    expect(mut(s.quote)).toHaveBeenCalledTimes(2)
    expect(mut(s.quote).mock.calls[1][0]).toEqual({ subscriptionId: "sub1", planTierId: "t-up" })
  })

  it("offers no Try again for a terminal quote refusal", () => {
    s.quote = Object.assign(fakeMutation({ isError: true, error: new ApiError(409, "x", { error: "upgrade_unavailable", message: "x" }) }), {
      variables: { subscriptionId: "sub1", planTierId: "t-up" },
    })
    openPlan()
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull()
  })

  it("stacks the footer full width on phones", () => {
    openPlan()
    expect(cont().parentElement?.className).toMatch(/\bw-full\b.*sm:w-auto/)
  })

  it("names the extra seats held on seats_not_sold", async () => {
    s.upgrade = settling({ err: new ApiError(409, "x", { error: "seats_not_sold", message: "x", extraSeats: 3 }) })
    openPlan()
    await userEvent.setup().click(cont())
    expect((await screen.findByRole("alert")).textContent).toContain("you hold 3")
  })

  it("asks for a phone number in place, then retries the same upgrade and keeps focus in the dialog", async () => {
    sessionStore()
    s.upgrade = stateful((n) => (n === 1 ? { err: new ApiError(422, "x", { code: "phone_required", message: "x" }) } : { ok: good }))
    s.put = stateful(() => ({ ok: { phone: "+201012345678" } }))
    const go = openPlan()
    const user = userEvent.setup()
    await user.click(cont())
    expect(await screen.findByText("Add your mobile number to continue")).toBeTruthy()
    expect(screen.queryByRole("button", { name: /Continue to payment/ })).toBeNull()
    await user.type(screen.getByLabelText("Mobile number"), "01012345678")
    await user.click(screen.getByRole("button", { name: "Save and continue" }))
    await waitFor(() => expect(mut(s.upgrade)).toHaveBeenCalledTimes(2))
    expect(mut(s.upgrade).mock.calls[1][0]).toEqual(mut(s.upgrade).mock.calls[0][0])
    expect(go).toHaveBeenCalledWith(good.checkoutUrl)
    expect(document.activeElement?.getAttribute("role")).toBe("status")
  })

  it("explains cancel-and-resubscribe when the plan cannot be upgraded mid-period", async () => {
    s.upgrade = settling({ err: new ApiError(409, "x", { error: "upgrade_unavailable", message: "x", next: "cancel_and_resubscribe" }) })
    openPlan()
    await userEvent.setup().click(cont())
    expect((await screen.findByRole("alert")).textContent).toBe("Can't upgrade mid-period. Cancel at period end, then subscribe to the new plan.")
  })

  it.each([
    ["a higher-priced tier on another interval", { ...up, interval: "year" as const }],
    ["a cheaper tier on another interval", { ...fx.studentMonthly, id: "t-low-y", name: "Student Lite Yearly", priceMinor: 10000, interval: "year" as const }],
  ])("offers no change for %s", (_n, tier) => {
    openPlan(vi.fn(), tier)
    expect(screen.getByText(/bills every year/)).toBeTruthy()
    expect(screen.queryByRole("button", { name: /Continue to payment|Schedule the change/ })).toBeNull()
    expect(mut(s.quote)).not.toHaveBeenCalled()
  })
})

describe("AddSeatsDialog to Paymob", () => {
  const open = (go = vi.fn()) => {
    render(h(AddSeatsDialog, { open: true, onClose: () => undefined, subscriptionId: "sub-t", perSeatMinor: 3000, returnTo: "/teacher/team", go }))
    return go
  }

  it("redirects with the team page as the return path and blocks a second click", async () => {
    const store = sessionStore()
    const go = open()
    const user = userEvent.setup()
    await user.click(cont())
    expect(mut(s.addSeats).mock.calls[0][0]).toEqual({ subscriptionId: "sub-t", seats: 1 })
    expect(go).toHaveBeenCalledWith(good.checkoutUrl)
    expect(store.get("lemely.billing.returnTo.pay1")).toBe("/teacher/team")
    expect(screen.getByRole("status").textContent).toBe("Taking you to payment…")
    await user.click(cont())
    expect(mut(s.addSeats)).toHaveBeenCalledTimes(1)
  })

  it("starts over on a restored page", async () => {
    sessionStore()
    open()
    await userEvent.setup().click(cont())
    expect(cont().disabled).toBe(true)
    act(() => {
      window.dispatchEvent(Object.assign(new Event("pageshow"), { persisted: true }))
    })
    expect(cont().disabled).toBe(false)
  })

  it("never navigates on an unsafe URL, and the stale alert goes when the count changes", async () => {
    sessionStore()
    s.addSeats = settling({ ok: { paymentId: "pay1", checkoutUrl: "javascript:alert(1)" } })
    const go = open()
    const user = userEvent.setup()
    await user.click(cont())
    expect(go).not.toHaveBeenCalled()
    expect((await screen.findByRole("alert")).textContent).toContain("Nothing was charged")
    await user.type(screen.getByLabelText("How many seats"), "2")
    expect(screen.queryByRole("alert")).toBeNull()
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

  it("the real seat-limit refusal (422 invalid_seats on the quote) says so and keeps the price button off until the count changes", async () => {
    s.seatQuote = stateful(() => ({ err: new ApiError(422, "x", { error: "invalid_seats", message: "That would pass the most extra seats allowed" }) }))
    open()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Get the price" }))
    expect((await screen.findByRole("alert")).textContent).toBe("That's over the extra-seat limit. Try fewer.")
    expect((screen.getByRole("button", { name: "Get the price" }) as HTMLButtonElement).disabled).toBe(true)
    await user.type(screen.getByLabelText("How many seats"), "0")
    expect((screen.getByRole("button", { name: "Get the price" }) as HTMLButtonElement).disabled).toBe(false)
  })

  it.each([
    ["seat_charge_overdue", 409],
    ["plan_change_pending", 409],
    ["subscription_not_active", 409],
  ])("a refused purchase (%s) disables Continue and drops the price line until the count changes", async (code, status) => {
    sessionStore()
    s.addSeats = settling({ err: new ApiError(status, "x", { error: code, message: "x" }) })
    open()
    const user = userEvent.setup()
    expect(screen.getByRole("status").textContent).toMatch(/Pay EGP/)
    await user.click(cont())
    await screen.findByRole("alert")
    expect(cont().disabled).toBe(true)
    expect(document.body.textContent).not.toMatch(/Pay EGP|confirm with your bank/)
    await user.type(screen.getByLabelText("How many seats"), "2")
    expect(screen.queryByRole("alert")).toBeNull()
  })

  it.each([
    ["offline", new ApiError(0, "x")],
    ["a 503", new ApiError(503, "x", { error: "payments_unavailable", message: "x" })],
    ["charge_in_flight", new ApiError(409, "x", { error: "charge_in_flight", message: "x" })],
  ])("a transient failure (%s) leaves Continue pressable and the price on screen, and a second try goes out", async (_n, err) => {
    sessionStore()
    s.addSeats = settling({ err })
    open()
    const user = userEvent.setup()
    await user.click(cont())
    await screen.findByRole("alert")
    expect(cont().disabled).toBe(false)
    expect(screen.getByRole("status").textContent).toMatch(/Pay EGP/)
    await user.click(cont())
    expect(mut(s.addSeats)).toHaveBeenCalledTimes(2)
  })

  it("asks for a phone number in place, then retries the same purchase", async () => {
    sessionStore()
    s.addSeats = stateful((n) => (n === 1 ? { err: new ApiError(422, "x", { code: "phone_required", message: "x" }) } : { ok: good }))
    s.put = stateful(() => ({ ok: { phone: "+201012345678" } }))
    const go = open()
    const user = userEvent.setup()
    await user.click(cont())
    await user.type(await screen.findByLabelText("Mobile number"), "01012345678")
    await user.click(screen.getByRole("button", { name: "Save and continue" }))
    await waitFor(() => expect(mut(s.addSeats)).toHaveBeenCalledTimes(2))
    expect(mut(s.addSeats).mock.calls[1][0]).toEqual({ subscriptionId: "sub-t", seats: 1 })
    expect(go).toHaveBeenCalled()
    expect(document.activeElement?.getAttribute("role")).toBe("status")
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
