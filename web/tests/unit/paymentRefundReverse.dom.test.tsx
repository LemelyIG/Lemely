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
import { PaymentActions, RefundHistory } from "@/portals/admin/screens/billing/PaymentActions"

const row = (over: Partial<AdminPaymentRow> = {}): AdminPaymentRow => ({
  id: "pay1", payerUserId: "u1", beneficiaryUserId: "u1", purpose: "extra_seats", status: "paid", amountMinor: 21000, currency: "EGP",
  refundedMinor: 0, convertedToCredits: false, creditedUnits: null, paymobOrderId: "PM-1", paymobTxnId: "T-1", planTierId: null, creditPackId: null, subscriptionId: "s1", seatQuantity: 2,
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

  it("shows an unticked box for an applied seat purchase, with no credit promise in the note", async () => {
    const user = userEvent.setup()
    const dialog = await openRefund(user, row())
    expect((within(dialog).getByRole("checkbox", { name: BOX }) as HTMLInputElement).checked).toBe(false)
    expect(dialog.textContent).not.toMatch(/undo/i)
    expect(dialog.textContent).toMatch(/returns the money only/)
    expect(dialog.textContent).not.toMatch(/takes back/i)
  })

  it("leaves the box out for a purchase a reverse cannot change", async () => {
    const user = userEvent.setup()
    const dialog = await openRefund(user, row({ purpose: "credit_pack" }))
    expect(within(dialog).queryByRole("checkbox")).toBeNull()
  })

  it("shows the box for an upgrade, with the allowance in the note", async () => {
    const user = userEvent.setup()
    const dialog = await openRefund(user, row({ purpose: "upgrade_proration" }))
    expect(within(dialog).getByRole("checkbox", { name: BOX })).toBeTruthy()
    expect(dialog.textContent).toMatch(/unspent allowance/)
  })

  it("offers claw-back wording for a converted first payment, which keeps its credits otherwise", async () => {
    const user = userEvent.setup()
    const dialog = await openRefund(user, row({ purpose: "subscription_first", convertedToCredits: true, creditedUnits: 400 }))
    expect(within(dialog).getByRole("checkbox", { name: "Refund and take back the 400 credits" })).toBeTruthy()
    expect(dialog.textContent).toMatch(/credits it became/)
    expect(within(dialog).queryByRole("checkbox", { name: BOX })).toBeNull()
  })

  it("tells a pack the credits come back, and a subscription that the plan ends", async () => {
    const user = userEvent.setup()
    const dialog = await openRefund(user, row({ purpose: "credit_pack" }))
    expect(dialog.textContent).toMatch(/takes back unspent credits/)
  })

  it("shows the same box on the void dialog and sends reverseChange on void", async () => {
    const user = userEvent.setup()
    render(h(MemoryRouter, null, h(PaymentActions, { payment: row() })))
    await user.click(screen.getByRole("button", { name: /^Void / }))
    const dialog = screen.getByRole("dialog")
    expect(dialog.textContent).not.toMatch(/takes back/i)
    await user.type(within(dialog).getByLabelText("Reason"), "same day")
    await user.click(within(dialog).getByRole("checkbox", { name: /void and stop it renewing/i }))
    await user.click(within(dialog).getByRole("button", { name: "Void" }))
    const mutate = (s.voidP as { mutate: ReturnType<typeof vi.fn> }).mutate
    expect(mutate.mock.calls[0][0]).toEqual({ id: "pay1", body: { reverseChange: true, reason: "same day" } })
  })

  it("leaves the box off the void dialog of a credit pack", async () => {
    const user = userEvent.setup()
    render(h(MemoryRouter, null, h(PaymentActions, { payment: row({ purpose: "credit_pack" }) })))
    await user.click(screen.getByRole("button", { name: /^Void / }))
    expect(within(screen.getByRole("dialog")).queryByRole("checkbox")).toBeNull()
  })

  it("shows a void's 422 reverse_unavailable with the server's reason", async () => {
    s.voidP = fakeMutation({ isError: true, error: new ApiError(422, "x", { code: "reverse_unavailable", message: "The seats were bought in an earlier period." }) })
    const user = userEvent.setup()
    render(h(MemoryRouter, null, h(PaymentActions, { payment: row() })))
    await user.click(screen.getByRole("button", { name: /^Void / }))
    expect(within(screen.getByRole("dialog")).getByRole("alert").textContent).toContain("The seats were bought in an earlier period.")
  })

  it("after an earlier partial refund, the pre-filled remaining amount counts as full", async () => {
    const user = userEvent.setup()
    const dialog = await openRefund(user, row({ status: "partially_refunded", refundedMinor: 7000 }))
    expect((within(dialog).getByLabelText(/Refund amount/) as HTMLInputElement).value).toBe("140.00")
    await user.click(within(dialog).getByRole("checkbox", { name: BOX }))
    await user.type(within(dialog).getByLabelText("Reason"), "bought twice")
    await user.click(within(dialog).getByRole("button", { name: "Refund" }))
    const mutate = (s.refund as { mutate: ReturnType<typeof vi.fn> }).mutate
    expect(mutate.mock.calls[0][0]).toEqual({ id: "pay1", body: { amountMinor: 14000, reverseChange: true, reason: "bought twice" } })
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
    [422, "reverse_unavailable", "The change can't be reversed."],
    [409, "reverse_unavailable", "The change can't be reversed."],
  ])("shows a %i %s refusal in short words, in the error colour", async (status, code, text) => {
    s.refund = fakeMutation({ isError: true, error: new ApiError(status, "x", { code, message: "raw backend text" }) })
    const user = userEvent.setup()
    const dialog = await openRefund(user, row())
    const alert = within(dialog).getByRole("alert")
    expect(alert.textContent).toContain(text)
    if (code === "reverse_needs_full_refund") expect(alert.textContent).not.toContain("raw backend text")
    expect(alert.className).toMatch(/text-error/)
  })
})

describe("refund history: the reverse outcome", () => {
  const refund = (effect: string | null, reason: string | null = null) => ({
    id: "r1", kind: "refund", status: "succeeded", amountMinor: 21000, reason: "bought twice", adminUserId: "a", clawedBackUnits: 0,
    reverse: { requested: effect !== null, effect, reason }, createdAt: "2026-11-06T08:00:00Z", updatedAt: "2026-11-06T08:00:00Z",
  })
  const html = (effect: string | null, reason: string | null = null) => {
    const { container } = render(h(RefundHistory, { payment: row({ status: "refunded", refundedMinor: 21000, refunds: [refund(effect, reason)] as never }) }))
    return container.textContent ?? ""
  }

  it("says what was stopped", () => {
    expect(html("plan_ends_at_period_end")).toContain("Renewal stopped")
  })

  it("says nothing extra when no reverse was asked for", () => {
    expect(html(null)).not.toMatch(/Renewal|Credits taken|reversed|scheduled/)
  })

  it("makes a failed reverse visible, in the error colour, with its reason", () => {
    const { container } = render(h(RefundHistory, { payment: row({ status: "refunded", refunds: [refund("failed", "The seats were bought in an earlier period.")] as never }) }))
    const line = [...container.querySelectorAll("span")].find((e) => e.textContent?.startsWith("Money returned, change not reversed"))
    expect(line?.textContent).toContain("The seats were bought in an earlier period.")
    expect(line?.className).toMatch(/text-error/)
  })
})
