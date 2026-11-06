// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fx } from "./support/billingFixtures"
import { fakeMutation, okQuery } from "./support/billingRender"

/*
 * The customer view's money actions in a real DOM: the body each one sends, that grant and
 * adjust carry one idempotency key per opened dialog, that forgive-debt (which has none) is
 * never sent twice, and that an unknown refund offers a check instead of another refund.
 */

type Fake = ReturnType<typeof fakeMutation>
const s = vi.hoisted(() => ({
  customer: null as unknown,
  catalogue: null as unknown,
  m: {} as Record<"grant" | "adjust" | "forgive" | "activate" | "extend" | "cancel" | "refund" | "void" | "reconcile", unknown>,
}))
vi.mock("@/lib/hooks/useAdminBillingApi", () => ({
  useCustomer: () => s.customer,
  useAdminCatalogue: () => s.catalogue,
  useGrantCredits: () => s.m.grant,
  useAdjustBalance: () => s.m.adjust,
  useForgiveDebt: () => s.m.forgive,
  useManualActivation: () => s.m.activate,
  useExtendSubscription: () => s.m.extend,
  useAdminCancelSubscription: () => s.m.cancel,
  useRefundPayment: () => s.m.refund,
  useVoidPayment: () => s.m.void,
  useReconcilePayment: () => s.m.reconcile,
}))

import { CustomerDetail } from "@/portals/admin/screens/billing/CustomerDetail"

const mk = () => ({
  grant: fakeMutation(), adjust: fakeMutation(), forgive: fakeMutation(), activate: fakeMutation(), extend: fakeMutation(),
  cancel: fakeMutation(), refund: fakeMutation(), void: fakeMutation(), reconcile: fakeMutation(),
})
const fake = (k: keyof typeof s.m) => s.m[k] as Fake

function renderDetail() {
  return render(
    h(QueryClientProvider, { client: new QueryClient() },
      h(MemoryRouter, { initialEntries: ["/platform/billing/customers/u2"] },
        h(Routes, null, h(Route, { path: "/platform/billing/customers/:userId", element: h(CustomerDetail) })))),
  )
}
const setReason = (text = "agreed with the family") => fireEvent.change(screen.getByLabelText("Reason"), { target: { value: text } })
const change = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } })
const dlg = () => screen.getByRole("dialog")
const openAction = async (user: ReturnType<typeof userEvent.setup>, name: string) => {
  await user.click(screen.getByRole("button", { name }))
  return dlg()
}
const manual = () => ({ ...fx.customer.subscriptions[0], isManuallyActivated: true, paymobSubscriptionId: null })
const unknownRefund = {
  id: "r1", kind: "refund" as const, status: "unknown" as const, amountMinor: 25000, reason: "duplicate", adminUserId: "a1",
  clawedBackUnits: 0, createdAt: "2026-11-05T10:00:00Z", updatedAt: "2026-11-05T10:00:00Z",
}

beforeEach(() => {
  s.m = mk()
  s.customer = okQuery(fx.customer)
  s.catalogue = okQuery(fx.adminCatalogue)
})

describe("grant and adjust", () => {
  it("send one request id per opened dialog, the same on a re-submit and new on a reopen", async () => {
    const user = userEvent.setup()
    renderDetail()
    let d = await openAction(user, "Grant credits")
    change("Credits to grant", "200")
    setReason()
    await user.click(within(d).getByRole("button", { name: "Grant credits" }))
    await user.click(within(d).getByRole("button", { name: "Grant credits" }))
    const calls = fake("grant").mutate.mock.calls
    expect(calls).toHaveLength(2)
    expect(calls[0][0]).toEqual({ id: "u2", body: { units: 200, validDays: 365, requestId: expect.any(String), reason: "agreed with the family" } })
    expect(calls[1][0].body.requestId).toBe(calls[0][0].body.requestId)
    await user.click(within(d).getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    d = await openAction(user, "Grant credits")
    change("Credits to grant", "200")
    setReason()
    await user.click(within(d).getByRole("button", { name: "Grant credits" }))
    expect(fake("grant").mutate.mock.calls[2][0].body.requestId).not.toBe(calls[0][0].body.requestId)
  })

  it("sends a never-expiring grant as validDays null and refuses zero units", async () => {
    const user = userEvent.setup()
    renderDetail()
    const d = await openAction(user, "Grant credits")
    change("Credits to grant", "0")
    setReason()
    await user.click(within(d).getByRole("button", { name: "Grant credits" }))
    expect(fake("grant").mutate).not.toHaveBeenCalled()
    change("Credits to grant", "5")
    change("Valid for (days, empty = never expires)", "")
    await user.click(within(d).getByRole("button", { name: "Grant credits" }))
    expect(fake("grant").mutate.mock.calls[0][0].body.validDays).toBeNull()
  })

  it("sends signed units and refuses text or zero", async () => {
    const user = userEvent.setup()
    renderDetail()
    const d = await openAction(user, "Adjust balance")
    setReason()
    for (const bad of ["abc", "0", ""]) {
      change("Units (negative to debit)", bad)
      await user.click(within(d).getByRole("button", { name: "Adjust balance" }))
    }
    expect(fake("adjust").mutate).not.toHaveBeenCalled()
    change("Units (negative to debit)", "-40")
    await user.click(within(d).getByRole("button", { name: "Adjust balance" }))
    expect(fake("adjust").mutate.mock.calls[0][0]).toEqual({ id: "u2", body: { units: -40, requestId: expect.any(String), reason: "agreed with the family" } })
  })
})

describe("forgive debt", () => {
  it("forgives everything with units null and shows the amount at stake", async () => {
    const user = userEvent.setup()
    renderDetail()
    const d = await openAction(user, "Forgive debt")
    expect(within(d).getByText(/12 units are outstanding/)).toBeTruthy()
    setReason()
    await user.click(within(d).getByRole("button", { name: "Forgive debt" }))
    expect(fake("forgive").mutate.mock.calls[0][0]).toEqual({ id: "u2", body: { units: null, reason: "agreed with the family" } })
  })

  it("sends nothing while a forgive is pending, from the button or from Enter", async () => {
    s.m.forgive = fakeMutation({ isPending: true })
    const user = userEvent.setup()
    renderDetail()
    const d = await openAction(user, "Forgive debt")
    setReason()
    const submit = within(d).getByRole("button", { name: "Forgive debt" }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    fireEvent.submit(submit.form as HTMLFormElement)
    fireEvent.click(submit)
    expect(fake("forgive").mutate).not.toHaveBeenCalled()
  })

  it("never retries on its own after a dropped connection and says to check first", async () => {
    s.m.forgive = fakeMutation({ isError: true, error: new (await import("@/lib/api")).ApiError(0, "net", undefined) })
    const user = userEvent.setup()
    renderDetail()
    const d = await openAction(user, "Forgive debt")
    expect(within(d).getByRole("alert").textContent).toMatch(/may not have been saved\. Reload this page to check before trying again/)
    expect(fake("forgive").mutate).not.toHaveBeenCalled()
  })
})

describe("subscription actions", () => {
  it("activates a plan from the catalogue for a period in days", async () => {
    const user = userEvent.setup()
    renderDetail()
    const d = await openAction(user, "Activate manually")
    change("Period (days)", "45")
    setReason("complimentary for the pilot")
    await user.click(within(d).getByRole("button", { name: "Activate" }))
    expect(fake("activate").mutate.mock.calls[0][0]).toEqual({ id: "u2", body: { planTierId: "t-s-m", periodDays: 45, reason: "complimentary for the pilot" } })
  })

  it("cancels at period end by default and now when asked, on the chosen subscription", async () => {
    const user = userEvent.setup()
    renderDetail()
    const d = await openAction(user, "Cancel subscription")
    expect(within(d).getByText(/also cancels the plan on Paymob first/)).toBeTruthy()
    setReason("asked to stop")
    await user.click(within(d).getByRole("button", { name: "Cancel subscription" }))
    expect(fake("cancel").mutate.mock.calls[0][0]).toEqual({ id: "sub1", body: { when: "period_end", reason: "asked to stop" } })
    await user.click(within(d).getByLabelText("End access now instead of at period end"))
    await user.click(within(d).getByRole("button", { name: "Cancel subscription" }))
    expect(fake("cancel").mutate.mock.calls[1][0].body.when).toBe("now")
  })

  it("extends a complimentary subscription by days", async () => {
    s.customer = okQuery({ ...fx.customer, subscriptions: [manual()] })
    const user = userEvent.setup()
    renderDetail()
    const d = await openAction(user, "Extend subscription")
    change("Days to add", "10")
    setReason("outage credit")
    await user.click(within(d).getByRole("button", { name: "Extend subscription" }))
    expect(fake("extend").mutate.mock.calls[0][0]).toEqual({ id: "sub1", body: { days: 10, reason: "outage credit" } })
  })

  it("does not open an extend dialog for a Paymob-billed plan", async () => {
    const user = userEvent.setup()
    renderDetail()
    const extend = screen.getByRole("button", { name: "Extend subscription" }) as HTMLButtonElement
    expect(extend.disabled).toBe(true)
    await user.click(extend)
    expect(screen.queryByRole("dialog")).toBeNull()
  })
})

describe("refund and void", () => {
  it("prefills what is left, refuses more than that, and sends minor units", async () => {
    const user = userEvent.setup()
    renderDetail()
    const d = await openAction(user, "Refund pay1")
    const amount = screen.getByLabelText(/Refund amount/) as HTMLInputElement
    expect(amount.value).toBe("250.00")
    setReason("duplicate charge")
    change("Refund amount (EGP, empty = everything refundable)", "300")
    await user.click(within(d).getByRole("button", { name: "Refund" }))
    expect(fake("refund").mutate).not.toHaveBeenCalled()
    expect(within(d).getByText(/Only EGP 250\.00 is left to refund/)).toBeTruthy()
    change("Refund amount (EGP, empty = everything refundable)", "100")
    await user.click(within(d).getByRole("button", { name: "Refund" }))
    expect(fake("refund").mutate.mock.calls[0][0]).toEqual({ id: "pay1", body: { amountMinor: 10000, reason: "duplicate charge" } })
  })

  it("sends nothing twice while a refund is pending", async () => {
    s.m.refund = fakeMutation({ isPending: true })
    const user = userEvent.setup()
    renderDetail()
    const d = await openAction(user, "Refund pay1")
    setReason("duplicate charge")
    const submit = within(d).getByRole("button", { name: "Refund" }) as HTMLButtonElement
    fireEvent.submit(submit.form as HTMLFormElement)
    fireEvent.click(submit)
    expect(fake("refund").mutate).not.toHaveBeenCalled()
  })

  it("voids with only a reason", async () => {
    const user = userEvent.setup()
    renderDetail()
    const d = await openAction(user, "Void pay1")
    setReason("same-day mistake")
    await user.click(within(d).getByRole("button", { name: "Void" }))
    expect(fake("void").mutate.mock.calls[0][0]).toEqual({ id: "pay1", body: { reason: "same-day mistake" } })
  })

  it("with an unknown outcome offers the check and sends no new refund", async () => {
    s.customer = okQuery({ ...fx.customer, payments: [{ ...fx.adminPayment, refunds: [unknownRefund] }] })
    const user = userEvent.setup()
    renderDetail()
    expect(screen.queryByRole("button", { name: "Refund pay1" })).toBeNull()
    expect(screen.getByText(/outcome unknown/)).toBeTruthy()
    const d = await openAction(user, "Check refund with Paymob for pay1")
    expect(within(d).getByText(/never sends a new refund/)).toBeTruthy()
    setReason("timeout on the first attempt")
    await user.click(within(d).getByRole("button", { name: "Check with Paymob" }))
    expect(fake("reconcile").mutate.mock.calls[0][0]).toEqual({ id: "pay1", body: { reason: "timeout on the first attempt" } })
    expect(fake("refund").mutate).not.toHaveBeenCalled()
  })

  it("announces an unknown result from the refund response without calling it a failure", () => {
    const answered = { ...fx.adminPayment, refunds: [unknownRefund] }
    s.m.refund = fakeMutation({ isSuccess: true, data: answered })
    renderDetail()
    const live = screen.getAllByRole("status").map((n) => n.textContent ?? "").join(" ")
    expect(live).toMatch(/outcome unknown/)
    expect(live.toLowerCase()).not.toMatch(/fail|declin/)
  })
})
