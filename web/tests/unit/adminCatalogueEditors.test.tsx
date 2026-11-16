// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { act, fireEvent, render, screen, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import type { AdminCatalogue, AdminCreditPack, AdminPlanTier } from "@/lib/billingTypes"
import { fx } from "./support/billingFixtures"
import { errorQuery, fakeMutation, okQuery, pendingQuery } from "./support/billingRender"

/*
 * The tier and pack editors against the customers they reach: the warning, the tick that gates
 * the save, the version each write carries, and what a stale write does. The row a dialog opens
 * on is frozen: a refetch behind it changes neither the warning nor the version.
 */

const s = vi.hoisted(() => ({
  catalogue: null as unknown,
  updateTier: null as unknown,
  updatePack: null as unknown,
  other: null as unknown,
  impact: null as unknown,
  impactCalls: [] as Array<[string, number | null]>,
}))
vi.mock("@/lib/hooks/useAdminBillingApi", async () => {
  const { okQuery: ok } = await import("./support/billingRender")
  const { fx: f } = await import("./support/billingFixtures")
  return {
    useAdminCatalogue: () => s.catalogue,
    useCreateTier: () => s.other,
    useUpdateTier: () => s.updateTier,
    useSyncTier: () => s.other,
    useCreatePack: () => s.other,
    useUpdatePack: () => s.updatePack,
    useCreateRate: () => s.other,
    useCreateEstimator: () => s.other,
    useUpdateFreeAllowances: () => s.other,
    useBillingSettings: () => ok(f.billingSettings),
    useUpdateBillingSettings: () => s.other,
    useCreditRates: () => ok([f.creditRate]),
    useSetCreditRate: () => s.other,
    useClearCreditRate: () => s.other,
    useLlmPrices: () => ok(f.llmModels),
    useSetLlmPrice: () => s.other,
    useClearLlmPrice: () => s.other,
    usePackPriceImpact: (id: string, price: number | null) => {
      s.impactCalls.push([id, price])
      return s.impact
    },
  }
})
vi.mock("@/components/ui/lazy-chart", () => ({ BarChart: () => null }))

import { Catalogue } from "@/portals/admin/screens/billing/Catalogue"

type Fake = ReturnType<typeof fakeMutation>
const tier0 = fx.adminCatalogue.tiers[0] as AdminPlanTier
const pack0 = fx.adminCatalogue.packs[0] as AdminCreditPack
const catalogue = (over: Partial<AdminCatalogue> = {}) => okQuery({ ...fx.adminCatalogue, ...over })

const mount = () =>
  render(h(QueryClientProvider, { client: new QueryClient() }, h(MemoryRouter, null, h(Catalogue))))
const setField = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } })
const save = (name: string) => fireEvent.click(screen.getByRole("button", { name }))
const openTier = () => fireEvent.click(screen.getAllByRole("button", { name: "Edit student_plus_m" })[0]!)
const openPack = () => fireEvent.click(screen.getAllByRole("button", { name: "Edit pack_500" })[0]!)

beforeEach(() => {
  s.catalogue = catalogue()
  s.updateTier = fakeMutation()
  s.updatePack = fakeMutation()
  s.other = fakeMutation()
  s.impact = pendingQuery()
  s.impactCalls = []
})
afterEach(() => vi.useRealTimers())

const sent = (m: unknown) => (m as Fake).mutate.mock.calls[0]![0] as { id: string; body: Record<string, unknown> }

describe("tier editor", () => {
  it("warns with the customer count and the configured notice days when a term changes", () => {
    s.catalogue = catalogue({ priceChangeNoticeDays: 45 })
    mount()
    openTier()
    expect(screen.queryByText(/customers are on this plan/)).toBeNull()
    setField("Price (EGP)", "275.00")
    const note = screen.getByText(/14 customers are on this plan/)
    expect(note.textContent).toContain("after 45 days")
    expect(screen.queryByText(/Paymob can't change existing renewals/)).toBeNull()
  })

  it("adds the fixed-amount sentence only when the server says amounts cannot be updated", () => {
    s.catalogue = catalogue({ subscriptionAmountUpdatable: false })
    mount()
    openTier()
    setField("Price (EGP)", "275.00")
    expect(screen.getByText(/Paymob can't change existing renewals/)).toBeTruthy()
  })

  it("stays quiet for an edit that is not a term", () => {
    mount()
    openTier()
    setField("Name", "Student Plus Two")
    expect(screen.queryByText(/on this plan/)).toBeNull()
  })

  it("stays quiet for a tier nobody is on", () => {
    s.catalogue = catalogue({ tiers: [{ ...tier0, liveSubscriptionCount: 0, pendingMoves: 0 }] })
    mount()
    openTier()
    setField("Price (EGP)", "275.00")
    expect(screen.queryByText(/on this plan/)).toBeNull()
  })

  it("will not save a warned change until the box is ticked, then sends the version it was opened on", () => {
    mount()
    openTier()
    setField("Price (EGP)", "275.00")
    setField("Reason", "Repricing for the new term")
    save("Save tier")
    expect((s.updateTier as Fake).mutate).not.toHaveBeenCalled()
    expect(screen.getAllByText("Tick the box to confirm.").length).toBeGreaterThan(0)
    fireEvent.click(screen.getByLabelText("I understand these customers will be emailed about the change."))
    save("Save tier")
    const body = sent(s.updateTier)
    expect(body.id).toBe("t-s-m")
    expect(body.body).toMatchObject({ expectedVersion: 4, priceMinor: 27500 })
    expect(Object.keys(body.body)).not.toContain("confirmImpact")
  })

  it("saves an unwarned change without a tick", () => {
    mount()
    openTier()
    setField("Name", "Student Plus Two")
    setField("Reason", "Rename only")
    save("Save tier")
    expect(sent(s.updateTier).body).toMatchObject({ expectedVersion: 4, name: "Student Plus Two" })
  })

  it("keeps the version and the baseline it was opened on when the catalogue refetches", () => {
    const view = mount()
    openTier()
    // Someone else bumps the row to version 5 and changes the price while this dialog is open.
    s.catalogue = catalogue({ tiers: [{ ...tier0, version: 5, priceMinor: 27500 }] })
    view.rerender(h(QueryClientProvider, { client: new QueryClient() }, h(MemoryRouter, null, h(Catalogue))))
    setField("Price (EGP)", "275.00")
    // Against the frozen baseline (250.00) this is still a change; against live data it would not be.
    expect(screen.getByText(/14 customers are on this plan/)).toBeTruthy()
    setField("Reason", "Repricing for the new term")
    fireEvent.click(screen.getByLabelText("I understand these customers will be emailed about the change."))
    save("Save tier")
    expect(sent(s.updateTier).body.expectedVersion).toBe(4)
  })

  it("blocks a second submit after a stale write, in friendly words", () => {
    s.updateTier = fakeMutation({ isError: true, error: new ApiError(409, "x", { code: "stale_write", message: "This was changed by someone else. Reload and try again." }) })
    mount()
    openTier()
    expect((screen.getByRole("button", { name: "Save tier" }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText("Close this to see the current values.")).toBeTruthy()
    expect(screen.getByText(/Someone changed this while you were editing/)).toBeTruthy()
  })

  it("answers a seat price of zero with friendly words, not wire text", () => {
    s.updateTier = fakeMutation({ isError: true, error: new ApiError(409, "x", { code: "extra_seats_held", message: "extra_seats_held: 3" }) })
    mount()
    openTier()
    expect(screen.getByText("Customers hold extra seats on this plan, so the extra-seat price can't be zero.")).toBeTruthy()
    expect(screen.queryByText(/extra_seats_held/)).toBeNull()
  })
})

describe("tier card", () => {
  it("shows the terms version, the customers and who is waiting to move", () => {
    mount()
    const card = screen.getAllByText(/waiting to move/)[0]!
    expect(card.textContent).toBe("3 customers waiting to move")
    expect(screen.getAllByText("v2").length).toBeGreaterThan(0)
  })

  it("shows no waiting line when nobody is waiting", () => {
    s.catalogue = catalogue({ tiers: [{ ...tier0, pendingMoves: 0 }] })
    mount()
    expect(screen.queryByText(/waiting to move/)).toBeNull()
  })
})

describe("pack editor", () => {
  const settled = () => act(() => void vi.advanceTimersByTime(400))

  it("asks nothing while the price does not rise", () => {
    mount()
    openPack()
    setField("Price (EGP)", "100.00")
    expect(s.impactCalls.every(([, p]) => p === null)).toBe(true)
    expect(screen.queryByText(/top up automatically/)).toBeNull()
  })

  it("previews the new price once typing pauses, and counts what the server says", () => {
    vi.useFakeTimers()
    s.impact = okQuery({ autoTopupCount: 6, capBelowPriceCount: 2 })
    mount()
    openPack()
    setField("Price (EGP)", "175.00")
    expect(screen.getByText("Checking who this affects…")).toBeTruthy()
    settled()
    expect(s.impactCalls.at(-1)).toEqual(["p1", 17500])
    expect(screen.getByText("6 customers top up automatically with this pack and will be charged the new price.")).toBeTruthy()
    expect(screen.getByText("2 of them have a monthly limit below it, so their auto top-up will stop until they raise the limit.")).toBeTruthy()
  })

  it("gates the save on the tick, then sends the opened version", () => {
    vi.useFakeTimers()
    s.impact = okQuery({ autoTopupCount: 6, capBelowPriceCount: 0 })
    mount()
    openPack()
    setField("Price (EGP)", "175.00")
    settled()
    setField("Reason", "Pack price follows costs")
    save("Save pack")
    expect((s.updatePack as Fake).mutate).not.toHaveBeenCalled()
    fireEvent.click(screen.getByLabelText("I understand these customers will be charged the new price."))
    save("Save pack")
    expect(sent(s.updatePack)).toMatchObject({ id: "p1", body: { expectedVersion: 2, priceMinor: 17500 } })
  })

  it("says so when the preview cannot be read, and still asks for the tick", () => {
    vi.useFakeTimers()
    s.impact = errorQuery(new ApiError(500, "boom"))
    mount()
    openPack()
    setField("Price (EGP)", "175.00")
    settled()
    expect(screen.getByText(/Couldn't check how many auto top-ups this affects/)).toBeTruthy()
    expect(screen.getByLabelText("I understand these customers will be charged the new price.")).toBeTruthy()
  })

  it("drops the warning when no auto top-up can charge", () => {
    vi.useFakeTimers()
    s.impact = okQuery({ autoTopupCount: 0, capBelowPriceCount: 0 })
    mount()
    openPack()
    setField("Price (EGP)", "175.00")
    settled()
    expect(screen.queryByText(/top up automatically/)).toBeNull()
    expect(screen.queryByLabelText(/I understand/)).toBeNull()
  })

  it("never previews a pack nobody tops up with", () => {
    s.catalogue = catalogue({ packs: [{ ...pack0, autoTopupCount: 0 }] })
    mount()
    openPack()
    setField("Price (EGP)", "175.00")
    expect(s.impactCalls.every(([, p]) => p === null)).toBe(true)
  })

  it("blocks a second submit after a stale write", () => {
    s.updatePack = fakeMutation({ isError: true, error: new ApiError(409, "x", { code: "stale_write", message: "m" }) })
    mount()
    openPack()
    expect((screen.getByRole("button", { name: "Save pack" }) as HTMLButtonElement).disabled).toBe(true)
    const dlg = screen.getByRole("dialog")
    expect(within(dlg).getByText(/Someone changed this while you were editing/)).toBeTruthy()
  })
})
