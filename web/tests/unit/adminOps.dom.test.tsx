// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { fx } from "./support/billingFixtures"
import { errorQuery, fakeMutation, okQuery } from "./support/billingRender"

/*
 * The payments screen in a real DOM: reconcile needs a reason and sends the payment id, the
 * answer is announced, the status filter and Load more drive the list query, and a refused read
 * is a refusal, not an empty list.
 */

type Fake = ReturnType<typeof fakeMutation>
const s = vi.hoisted(() => ({
  statuses: [] as unknown[],
  payments: null as unknown,
  problems: null as unknown,
  reconcile: null as unknown,
}))
vi.mock("@/lib/hooks/useAdminBillingApi", () => ({
  useAdminPayments: (status: unknown) => {
    s.statuses.push(status)
    return s.payments
  },
  useProblemQueue: () => s.problems,
  useReconcilePayment: () => s.reconcile,
  useRefundPayment: () => fakeMutation(),
  useVoidPayment: () => fakeMutation(),
}))

import { ReasonedFormDialog } from "@/portals/admin/screens/billing/ReasonedFormDialog"
import { Payments } from "@/portals/admin/screens/billing/Payments"

const infinite = (items: unknown[], more = false, fetchNextPage = vi.fn()) => ({
  ...okQuery({ pages: [{ items, nextCursor: more ? "c1" : null }], pageParams: [null] }),
  hasNextPage: more,
  isFetchingNextPage: false,
  fetchNextPage,
})
const queueWith = (over: object) => ({ mismatches: [], stalePending: [], missingCallbacks: [], hmacFailures: [], hmacFailures24h: 0, refundsNeedingAttention: [], ...over })
const pending = { ...fx.adminPayment, id: "pay2", status: "pending" as const, paidAt: null, paymobOrderId: "PM-2" }
const stale = { ...fx.adminPayment, id: "pay8", status: "pending" as const, paidAt: null, paymobOrderId: "PM-8" }
const reconcile = () => s.reconcile as Fake
const tree = () => h(QueryClientProvider, { client: new QueryClient() }, h(MemoryRouter, null, h(Payments)))
const dlg = () => screen.getByRole("dialog")

beforeEach(() => {
  s.statuses = []
  s.payments = infinite([fx.adminPayment, pending])
  s.problems = okQuery(queueWith({ stalePending: [stale] }))
  s.reconcile = fakeMutation()
})

describe("Reconcile", () => {
  it("needs a reason, then sends it with the payment id and nothing else", async () => {
    const user = userEvent.setup()
    render(tree())
    await user.click(screen.getByRole("button", { name: "Reconcile order PM-2" }))
    const d = dlg()
    expect(within(d).getByRole("heading", { name: "Reconcile payment" })).toBeTruthy()
    expect(within(d).getByText(/Order PM-2/)).toBeTruthy()
    await user.click(within(d).getByRole("button", { name: "Reconcile" }))
    expect(reconcile().mutate).not.toHaveBeenCalled()
    // The refusal sits on the field: focus moves to it and its description names the problem.
    const reason = within(d).getByLabelText("Reason")
    expect(reason.getAttribute("aria-invalid")).toBe("true")
    expect(document.getElementById(reason.getAttribute("aria-describedby") ?? "")?.textContent).toContain("Give a reason of at least 5 characters.")
    expect(document.activeElement).toBe(reason)
    fireEvent.change(within(d).getByLabelText("Reason"), { target: { value: "callback never arrived" } })
    await user.click(within(d).getByRole("button", { name: "Reconcile" }))
    expect(reconcile().mutate).toHaveBeenCalledTimes(1)
    expect(reconcile().mutate.mock.calls[0][0]).toEqual({ id: "pay2", body: { reason: "callback never arrived" } })
  })

  it("opens from the problem queue for that payment", async () => {
    const user = userEvent.setup()
    render(tree())
    await user.click(screen.getByRole("button", { name: "Reconcile order PM-8" }))
    expect(within(dlg()).getByText(/Order PM-8/)).toBeTruthy()
    fireEvent.change(within(dlg()).getByLabelText("Reason"), { target: { value: "stuck for two hours" } })
    await user.click(within(dlg()).getByRole("button", { name: "Reconcile" }))
    expect(reconcile().mutate.mock.calls[0][0]).toEqual({ id: "pay8", body: { reason: "stuck for two hours" } })
  })

  it("closes on Cancel without sending anything", async () => {
    const user = userEvent.setup()
    render(tree())
    await user.click(screen.getByRole("button", { name: "Reconcile order PM-2" }))
    await user.click(within(dlg()).getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(reconcile().mutate).not.toHaveBeenCalled()
  })

  it("announces what Paymob reported, in words that never call an unanswered payment failed", () => {
    s.reconcile = fakeMutation({ isSuccess: true, data: { ...pending, status: "pending" } })
    render(tree())
    const live = screen.getAllByRole("status").map((n) => n.textContent ?? "").join(" ")
    expect(live).toContain("Paymob has not reported a final result. Order PM-2 is still pending.")
    expect(live.toLowerCase()).not.toMatch(/fail|declin/)
  })

  it("says a payment is marked failed only when the server answered failed", () => {
    s.reconcile = fakeMutation({ isSuccess: true, data: { ...pending, status: "failed" } })
    render(tree())
    const live = screen.getAllByRole("status").map((n) => n.textContent ?? "").join(" ")
    expect(live).toContain("Order PM-2 is now marked failed.")
  })

  it("offers nothing to reconcile on a paid or failed payment", () => {
    s.problems = okQuery(queueWith({}))
    s.payments = infinite([fx.adminPayment, { ...fx.adminPayment, id: "pay9", status: "failed", paidAt: null, paymobOrderId: "PM-9" }])
    render(tree())
    expect(screen.queryByRole("button", { name: /^Reconcile / })).toBeNull()
  })
})

describe("the list", () => {
  it("filters by status and says so when nothing matches", async () => {
    const user = userEvent.setup()
    render(tree())
    expect(s.statuses.at(-1)).toBeNull()
    s.payments = infinite([])
    await user.selectOptions(screen.getByLabelText("Status"), "pending")
    expect(s.statuses.at(-1)).toBe("pending")
    expect(screen.getByText("No payments with this status.")).toBeTruthy()
    await user.selectOptions(screen.getByLabelText("Status"), "")
    expect(s.statuses.at(-1)).toBeNull()
    expect(screen.getByText("No payments yet.")).toBeTruthy()
  })

  it("keeps the rows after a failed page and retries it with Try again", async () => {
    const user = userEvent.setup()
    const next = vi.fn()
    s.payments = { ...infinite([fx.adminPayment, pending], true, next), status: "error", isError: true, isSuccess: false, error: new Error("boom"), isFetchNextPageError: true }
    render(tree())
    expect(screen.getByRole("alert").textContent).toBe("Couldn't load more payments.")
    expect(screen.getByRole("button", { name: "Reconcile order PM-2" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull()
    await user.click(screen.getByRole("button", { name: "Try again" }))
    expect(next).toHaveBeenCalledTimes(1)
  })

  it("loads the next page on Load more", async () => {
    const user = userEvent.setup()
    const next = vi.fn()
    s.payments = infinite([fx.adminPayment], true, next)
    render(tree())
    await user.click(screen.getByRole("button", { name: "Load more" }))
    expect(next).toHaveBeenCalledTimes(1)
  })
})

describe("a refused or failed read", () => {
  it("shows a refusal as a refusal on a 403, not as an empty queue", () => {
    s.problems = errorQuery(new ApiError(403, "no"))
    render(tree())
    expect(screen.getByText("You can't open billing payments")).toBeTruthy()
    expect(screen.queryByText("No payment problems right now.")).toBeNull()
  })

  it("keeps the list readable when only the queue fails", () => {
    s.problems = errorQuery(new ApiError(500, "boom"))
    render(tree())
    expect(screen.getByText("Couldn't load the problem queue")).toBeTruthy()
    expect(screen.queryByText("No payment problems right now.")).toBeNull()
    expect(screen.getByRole("button", { name: "Reconcile order PM-2" })).toBeTruthy()
  })
})

describe("the dialog's failure tone", () => {
  const dialogWith = (error: unknown) =>
    render(
      h(
        MemoryRouter,
        null,
        h(ReasonedFormDialog, {
          open: true,
          onClose: () => {},
          title: "Void payment",
          fields: [],
          initial: {},
          submitLabel: "Void",
          mutation: fakeMutation({ isError: true, error }) as never,
          toBody: () => ({}),
        }),
      ),
    )

  it.each([
    ["a dropped connection", new ApiError(0, "offline")],
    ["a server error", new ApiError(502, "bad gateway")],
    ["a non-API error", new TypeError("fetch failed")],
  ])("does not paint %s as an error, since the change may have saved", (_n, error) => {
    dialogWith(error)
    const note = screen.getByRole("alert")
    expect(note.className).not.toContain("text-error")
    expect(note.className).toContain("text-on-surface")
  })

  it.each([
    ["a refusal", new ApiError(409, "refund_in_flight")],
    ["a missing row", new ApiError(404, "gone")],
    ["a rate limit", new ApiError(429, "slow down")],
  ])("keeps the error colour for %s", (_n, error) => {
    dialogWith(error)
    expect(screen.getByRole("alert").className).toContain("text-error")
  })
})
