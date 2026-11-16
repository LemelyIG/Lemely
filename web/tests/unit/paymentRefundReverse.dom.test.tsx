// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import type { AdminPaymentRow } from "@/lib/billingTypes"
import { fakeMutation } from "./support/billingRender"

/* The refund dialog's "stop it renewing" box: where it shows, what it sends, how a refusal reads. */

const s = vi.hoisted(() => ({ refund: null as unknown, voidP: null as unknown, reconcile: null as unknown }))
vi.mock("@/lib/hooks/useAdminBillingApi", () => ({
  useRefundPayment: () => s.refund,
  useVoidPayment: () => s.voidP,
  useReconcilePayment: () => s.reconcile,
}))
import { PaymentActions } from "@/portals/admin/screens/billing/PaymentActions"

const row = (over: Partial<AdminPaymentRow> = {}): AdminPaymentRow => ({
  id: "pay1", payerUserId: "u1", beneficiaryUserId: "u1", purpose: "extra_seats", status: "paid", amountMinor: 21000, currency: "EGP",
  refundedMinor: 0, paymobOrderId: "PM-1", paymobTxnId: "T-1", planTierId: null, creditPackId: null, subscriptionId: "s1", seatQuantity: 2,
  createdAt: "2026-11-05T08:00:00Z", paidAt: "2026-11-05T08:01:00Z", refunds: [], ...over,
})

const BOX = /refund and stop it renewing/i

async function openRefund(user: ReturnType<typeof userEvent.setup>, p: AdminPaymentRow) {
  render(h(MemoryRouter, null, h(PaymentActions, { payment: p })))
  await user.click(screen.getByRole("button", { name: /^Refund / }))
  return screen.getByRole("dialog")
}

describe("refund dialog: stop it renewing", () => {
  beforeEach(() => {
    s.refund = fakeMutation()
    s.voidP = fakeMutation()
    s.reconcile = fakeMutation()
  })

  it("shows the box for seats and upgrades, not for a credit pack, and never on void", async () => {
    const user = userEvent.setup()
    const dialog = await openRefund(user, row())
    expect((within(dialog).getByRole("checkbox", { name: BOX }) as HTMLInputElement).checked).toBe(false)
    expect(dialog.textContent).not.toMatch(/undo/i)
  })

  it("leaves the box out for a purchase a reverse cannot change", async () => {
    const user = userEvent.setup()
    const dialog = await openRefund(user, row({ purpose: "credit_pack" }))
    expect(within(dialog).queryByRole("checkbox")).toBeNull()
  })

  it("has no box on the void dialog", async () => {
    const user = userEvent.setup()
    render(h(MemoryRouter, null, h(PaymentActions, { payment: row() })))
    await user.click(screen.getByRole("button", { name: /^Void / }))
    expect(within(screen.getByRole("dialog")).queryByRole("checkbox")).toBeNull()
  })

  it("sends reverseChange only when ticked", async () => {
    const user = userEvent.setup()
    const dialog = await openRefund(user, row())
    await user.type(within(dialog).getByLabelText("Reason"), "bought twice")
    await user.click(within(dialog).getByRole("button", { name: "Refund" }))
    const mutate = (s.refund as { mutate: ReturnType<typeof vi.fn> }).mutate
    expect(mutate.mock.calls[0][0]).toEqual({ id: "pay1", body: { amountMinor: 21000, reason: "bought twice" } })

    await user.click(within(dialog).getByRole("checkbox", { name: BOX }))
    await user.click(within(dialog).getByRole("button", { name: "Refund" }))
    expect(mutate.mock.calls[1][0]).toEqual({ id: "pay1", body: { amountMinor: 21000, reverseChange: true, reason: "bought twice" } })
  })

  it("stops a partial amount before any request when ticked", async () => {
    const user = userEvent.setup()
    const dialog = await openRefund(user, row())
    const amount = within(dialog).getByLabelText(/Refund amount/)
    await user.clear(amount)
    await user.type(amount, "50")
    await user.click(within(dialog).getByRole("checkbox", { name: BOX }))
    await user.type(within(dialog).getByLabelText("Reason"), "bought twice")
    await user.click(within(dialog).getByRole("button", { name: "Refund" }))
    expect(within(dialog).getByRole("alert").textContent).toContain("To stop it renewing, refund the full amount.")
    expect((s.refund as { mutate: ReturnType<typeof vi.fn> }).mutate).not.toHaveBeenCalled()
  })

  it.each([
    [422, "reverse_needs_full_refund", "To stop it renewing, refund the full amount."],
    [422, "reverse_unavailable", "This purchase can't be stopped from renewing now."],
    [409, "reverse_unavailable", "This purchase can't be stopped from renewing now."],
  ])("shows a %i %s refusal in short words, in the error colour", async (status, code, text) => {
    s.refund = fakeMutation({ isError: true, error: new ApiError(status, "x", { code, message: "raw backend text" }) })
    const user = userEvent.setup()
    const dialog = await openRefund(user, row())
    const alert = within(dialog).getByRole("alert")
    expect(alert.textContent).toContain(text)
    expect(alert.textContent).not.toContain("raw backend text")
    expect(alert.className).toMatch(/text-error/)
  })
})
