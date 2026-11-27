// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { act, render, screen, fireEvent, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fx } from "./support/billingFixtures"

/*
 * The retry guard against the real hooks: a real QueryClient, a mounted `useCustomer`, and a
 * refetch the test holds open. A failed forgive-debt must show its error at once (the refetch the
 * hook starts may not delay it) and keep Submit blocked until that refetch lands, in whichever
 * order the failure and the refetch arrive.
 */

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  request: vi.fn(),
}))

import { ApiError, request } from "@/lib/api"
import { CustomerDetail } from "@/portals/admin/screens/billing/CustomerDetail"

const req = vi.mocked(request)
const emptyCatalogue = { planTiers: [], creditPacks: [], freeAllowances: [], usageRates: [], usageEstimators: [] }
const withDebt = (debt: number) => ({ ...fx.customer, balance: { ...fx.customer.balance, outstandingDebt: debt }, debts: [] })
const tick = (ms = 25) => new Promise((r) => setTimeout(r, ms))

type Route = { forgive: () => Promise<unknown>; customers: Array<() => Promise<unknown>> }
function route({ forgive, customers }: Route) {
  const queue = [...customers]
  req.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.endsWith("/catalogue")) return emptyCatalogue
    if (path.endsWith("/forgive-debt") && init?.method === "POST") return forgive()
    if (path.includes("/customers/")) {
      const next = queue.shift()
      if (!next) throw new Error("unexpected extra customer read")
      return next()
    }
    throw new Error(`unexpected request ${path}`)
  })
}

function mount() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } })
  render(
    h(QueryClientProvider, { client },
      h(MemoryRouter, { initialEntries: ["/platform/billing/customers/u2"] },
        h(Routes, null, h(Route, { path: "/platform/billing/customers/:userId", element: h(CustomerDetail) })))),
  )
}

async function failForgive(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText("Omar Hassan")
  await user.click(screen.getByRole("button", { name: "Forgive debt" }))
  const dlg = screen.getByRole("dialog")
  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "estimator over-charged this job" } })
  await user.click(within(dlg).getByRole("button", { name: "Forgive debt" }))
  return dlg
}
const submitOf = (dlg: HTMLElement) => within(dlg).getByRole("button", { name: "Forgive debt" }) as HTMLButtonElement

beforeEach(() => {
  req.mockReset()
})

describe("forgive-debt retry guard with the real hooks", () => {
  it("shows the failure at once, blocks Submit while the refetch is open, and releases when it lands", async () => {
    let land: (v: unknown) => void = () => undefined
    route({
      forgive: () => Promise.reject(new ApiError(503, "down", undefined)),
      customers: [async () => withDebt(12), () => new Promise((resolve) => (land = resolve))],
    })
    mount()
    const user = userEvent.setup()
    const dlg = await failForgive(user)

    // The error must not wait for the refetch the failed write started.
    await waitFor(() => expect(within(dlg).getByRole("alert").textContent).toMatch(/Couldn't save this change/), { timeout: 1500 })
    expect(req.mock.calls.filter((c) => String(c[0]).includes("/customers/u2") && !(c[1] as RequestInit | undefined)?.method)).toHaveLength(2)
    expect(submitOf(dlg).disabled).toBe(true)
    expect(within(dlg).getByText(/may have gone through\. Reloading this customer/)).toBeTruthy()
    fireEvent.submit(submitOf(dlg).form as HTMLFormElement)
    expect(req.mock.calls.filter((c) => (c[1] as RequestInit | undefined)?.method === "POST")).toHaveLength(1)

    await tick()
    land(withDebt(7))
    await waitFor(() => expect(submitOf(dlg).disabled).toBe(false))
    expect(within(dlg).getByText(/7 units are outstanding/)).toBeTruthy()
    expect(within(dlg).queryByText(/Reloading this customer/)).toBeNull()
  })

  it("releases when the refetch lands before the failure is reported", async () => {
    let fail: (e: unknown) => void = () => undefined
    route({
      forgive: () => new Promise((_resolve, reject) => (fail = reject)),
      customers: [async () => withDebt(12), async () => withDebt(7), async () => withDebt(7)],
    })
    mount()
    const user = userEvent.setup()
    const dlg = await failForgive(user)
    // The write is still in flight; a reload of the customer lands first.
    await tick()
    await act(async () => {
      await fx.customer
    })
    fail(new ApiError(0, "net", undefined))
    await waitFor(() => expect(within(dlg).getByRole("alert")).toBeTruthy())
    await waitFor(() => expect(submitOf(dlg).disabled).toBe(false))
  })
})
