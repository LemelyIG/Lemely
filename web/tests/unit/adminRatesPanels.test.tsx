// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { fx } from "./support/billingFixtures"
import { errorQuery, fakeMutation, okQuery, pendingQuery } from "./support/billingRender"

/* The three rate panels in a real DOM: what each dialog sends, which confirmations it demands,
 * what a 409 does, and the states the panels show before there is data. */

const s = vi.hoisted(() => ({
  settings: null as unknown,
  rates: null as unknown,
  models: null as unknown,
  update: null as unknown,
  setRate: null as unknown,
  clearRate: null as unknown,
  setPrice: null as unknown,
  clearPrice: null as unknown,
}))
vi.mock("@/lib/hooks/useAdminBillingApi", () => ({
  useBillingSettings: () => s.settings,
  useUpdateBillingSettings: () => s.update,
  useCreditRates: () => s.rates,
  useSetCreditRate: () => s.setRate,
  useClearCreditRate: () => s.clearRate,
  useLlmPrices: () => s.models,
  useSetLlmPrice: () => s.setPrice,
  useClearLlmPrice: () => s.clearPrice,
}))

import { BillingRules } from "@/portals/admin/screens/billing/BillingRules"
import { CreditConversion } from "@/portals/admin/screens/billing/CreditConversion"
import { LlmPrices } from "@/portals/admin/screens/billing/LlmPrices"

type Fake = ReturnType<typeof fakeMutation>
const wrap = (el: ReturnType<typeof h>) => h(QueryClientProvider, { client: new QueryClient() }, h(MemoryRouter, null, el))
const reason = () => fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "because the market moved" } })
const saved = vi.fn(() => () => undefined)
const stale = (code: string) => new ApiError(409, "x", { code, message: "m" })

beforeEach(() => {
  s.settings = okQuery(fx.billingSettings)
  s.rates = okQuery([fx.creditRate])
  s.models = okQuery(fx.llmModels)
  for (const k of ["update", "setRate", "clearRate", "setPrice", "clearPrice"] as const) s[k] = fakeMutation()
  saved.mockClear()
})
afterEach(cleanup)

describe("Billing rules", () => {
  it("reads the values, with the hour price as the built-in rate when unset", () => {
    render(wrap(h(BillingRules, { saved })))
    expect(screen.getByText("12 months")).toBeTruthy()
    expect(screen.getByText("3 days")).toBeTruthy()
    expect(screen.getByText("200 seats")).toBeTruthy()
    expect(screen.getByText("50 EGP per USD")).toBeTruthy()
    expect(screen.getByText("Built-in rate")).toBeTruthy()
  })

  it("sends only the changed field with the version read, and nothing when nothing changed", async () => {
    const user = userEvent.setup()
    render(wrap(h(BillingRules, { saved })))
    await user.click(screen.getByRole("button", { name: "Edit billing rules" }))
    reason()
    await user.click(screen.getByRole("button", { name: "Save rules" }))
    expect((s.update as Fake).mutate).not.toHaveBeenCalled()
    expect(screen.getByText(/Nothing has changed/)).toBeTruthy()
    const grace = screen.getByLabelText("Grace days")
    await user.clear(grace)
    await user.type(grace, "5")
    await user.click(screen.getByRole("button", { name: "Save rules" }))
    await waitFor(() => expect((s.update as Fake).mutate).toHaveBeenCalledTimes(1))
    expect((s.update as Fake).mutate.mock.calls[0][0]).toEqual({ graceDays: 5, expectedVersion: 4, reason: "because the market moved" })
  })

  it("shows the hints the brief fixes", async () => {
    const user = userEvent.setup()
    render(wrap(h(BillingRules, { saved })))
    await user.click(screen.getByRole("button", { name: "Edit billing rules" }))
    expect(screen.getByText(/Also sets how many days Paymob retries a failed renewal on newly synced plans/)).toBeTruthy()
    expect(screen.getByText(/emailed this many days before they move/)).toBeTruthy()
  })

  it("on a 409 keeps the dialog open, says someone changed it, and will not submit the old version again", () => {
    s.update = fakeMutation({ isError: true, error: stale("stale_write") })
    render(wrap(h(BillingRules, { saved })))
    fireEvent.click(screen.getByRole("button", { name: "Edit billing rules" }))
    const dlg = screen.getByRole("dialog")
    expect(within(dlg).getByRole("alert").textContent).toMatch(/^Someone changed this while you were editing/)
    expect((within(dlg).getByRole("button", { name: "Save rules" }) as HTMLButtonElement).disabled).toBe(true)
  })

  it("asks for the unusual-price confirmation only after the server refuses a price", () => {
    s.update = fakeMutation({ isError: true, error: new ApiError(422, "x", { code: "unusual_price", message: "m" }) })
    render(wrap(h(BillingRules, { saved })))
    fireEvent.click(screen.getByRole("button", { name: "Edit billing rules" }))
    expect(screen.getByLabelText("This price is right. Set it anyway")).toBeTruthy()
  })

  it("shows a skeleton while loading and a retry when the read fails, with no Edit offered", () => {
    s.settings = pendingQuery()
    const { unmount } = render(wrap(h(BillingRules, { saved })))
    expect(screen.queryByRole("button", { name: "Edit billing rules" })).toBeNull()
    unmount()
    s.settings = errorQuery(new ApiError(500, "x"))
    render(wrap(h(BillingRules, { saved })))
    expect(screen.getByText("Couldn't load the billing rules")).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Edit billing rules" })).toBeNull()
  })
})

describe("Credit conversion", () => {
  it("shows the rate both ways, with who changed it", () => {
    render(wrap(h(CreditConversion, { saved })))
    expect(screen.getByText("1 EGP = 1,250 units")).toBeTruthy()
    expect(screen.getByText("12.5")).toBeTruthy()
    expect(screen.getByText("3f2a91c4")).toBeTruthy()
  })

  it("explains the empty state and offers Set rate, which creates with a null version", async () => {
    s.rates = okQuery([])
    const user = userEvent.setup()
    render(wrap(h(CreditConversion, { saved })))
    expect(screen.getByText("No rate set. Payments that would become credits stay paid and raise an alert.")).toBeTruthy()
    await user.click(screen.getByRole("button", { name: "Set rate" }))
    fireEvent.change(screen.getByLabelText("Units per piaster"), { target: { value: "10" } })
    reason()
    await user.click(screen.getByRole("button", { name: "Save rate" }))
    await waitFor(() => expect((s.setRate as Fake).mutate).toHaveBeenCalledTimes(1))
    expect((s.setRate as Fake).mutate.mock.calls[0][0]).toEqual({
      currency: "EGP",
      body: { unitsPerMinor: "10", expectedVersion: null, reason: "because the market moved" },
    })
  })

  it("replaces a rate with the version read", async () => {
    const user = userEvent.setup()
    render(wrap(h(CreditConversion, { saved })))
    await user.click(screen.getByRole("button", { name: "Set EGP rate" }))
    const input = screen.getByLabelText("Units per piaster")
    fireEvent.change(input, { target: { value: "15" } })
    reason()
    await user.click(screen.getByRole("button", { name: "Save rate" }))
    await waitFor(() => expect((s.setRate as Fake).mutate).toHaveBeenCalledTimes(1))
    expect((s.setRate as Fake).mutate.mock.calls[0][0].body).toMatchObject({ unitsPerMinor: "15", expectedVersion: 2 })
  })

  it("names what clearing does, and sends the stop confirmation with the version", async () => {
    const user = userEvent.setup()
    render(wrap(h(CreditConversion, { saved })))
    await user.click(screen.getByRole("button", { name: "Clear EGP rate" }))
    const dlg = screen.getByRole("dialog")
    expect(within(dlg).getByText("Payments that would become credits will stay paid and alert you instead.")).toBeTruthy()
    reason()
    await user.click(within(dlg).getByRole("button", { name: "Stop conversions" }))
    await waitFor(() => expect((s.clearRate as Fake).mutate).toHaveBeenCalledTimes(1))
    expect((s.clearRate as Fake).mutate.mock.calls[0][0]).toEqual({
      currency: "EGP",
      body: { expectedVersion: 2, confirmStopConversions: true, reason: "because the market moved" },
    })
  })

  it("on a 409 stays open, says someone changed it, and blocks the old version", async () => {
    s.setRate = fakeMutation({ isError: true, error: stale("stale_write") })
    const user = userEvent.setup()
    render(wrap(h(CreditConversion, { saved })))
    await user.click(screen.getByRole("button", { name: "Set EGP rate" }))
    const dlg = screen.getByRole("dialog")
    expect(within(dlg).getByRole("alert").textContent).toMatch(/Someone changed this while you were editing/)
    expect((within(dlg).getByRole("button", { name: "Save rate" }) as HTMLButtonElement).disabled).toBe(true)
  })

  it("shows an error with retry when the rates cannot be read", () => {
    s.rates = errorQuery(new ApiError(500, "x"))
    render(wrap(h(CreditConversion, { saved })))
    expect(screen.getByText("Couldn't load the conversion rates")).toBeTruthy()
  })
})

describe("AI token prices", () => {
  it("lists every model with its built-in price, override and use", () => {
    render(wrap(h(LlmPrices, { saved })))
    const table = within(screen.getByRole("table", { hidden: true }))
    // The cards below `lg` hold the same rows in the DOM, hidden by CSS only.
    expect(table.getAllByText("gemini-3-pro").length).toBe(1)
    expect(table.getByText(/No built-in price/)).toBeTruthy()
    expect(table.getAllByText("Used in the last 30 days").length).toBe(2)
    expect(table.getByText("Not used in the last 30 days")).toBeTruthy()
    expect(table.getAllByText("$0.90").length).toBe(1)
  })

  it("explains that a lower price lowers what customers are charged", () => {
    render(wrap(h(LlmPrices, { saved })))
    expect(screen.getByText(/lower price lowers what they are charged/)).toBeTruthy()
  })

  it("warns about a flat rate only on a tiered built-in row, and holds the save until it is ticked", async () => {
    const user = userEvent.setup()
    render(wrap(h(LlmPrices, { saved })))
    await user.click(screen.getAllByRole("button", { name: "Set override for gemini-3-pro" })[0])
    const dlg = screen.getByRole("dialog")
    expect(within(dlg).queryByText("This override charges the same rate at every prompt length.")).toBeNull()
    for (const f of ["Tier 2 starts above (input tokens)", "Tier 2 input", "Tier 2 output"]) fireEvent.change(within(dlg).getByLabelText(f), { target: { value: "" } })
    expect(within(dlg).getByText("This override charges the same rate at every prompt length.")).toBeTruthy()
    reason()
    await user.click(within(dlg).getByRole("button", { name: "Save override" }))
    expect((s.setPrice as Fake).mutate).not.toHaveBeenCalled()
    await user.click(within(dlg).getByLabelText("Charge one flat rate at every length"))
    await user.click(within(dlg).getByRole("button", { name: "Save override" }))
    await waitFor(() => expect((s.setPrice as Fake).mutate).toHaveBeenCalledTimes(1))
    expect((s.setPrice as Fake).mutate.mock.calls[0][0].body).toMatchObject({ confirmDropTier: true, tierThresholdTokens: null, expectedVersion: null })
  })

  it("never shows the flat-rate warning on a flat built-in row", async () => {
    const user = userEvent.setup()
    render(wrap(h(LlmPrices, { saved })))
    await user.click(screen.getAllByRole("button", { name: "Edit override for claude-haiku-4-5" })[0])
    expect(screen.queryByText("This override charges the same rate at every prompt length.")).toBeNull()
    expect(screen.queryByLabelText("Charge one flat rate at every length")).toBeNull()
  })

  it("asks for the unusual-price confirmation on a typo-sized price and sends it with decimal strings", async () => {
    const user = userEvent.setup()
    render(wrap(h(LlmPrices, { saved })))
    await user.click(screen.getAllByRole("button", { name: "Edit override for claude-haiku-4-5" })[0])
    const dlg = screen.getByRole("dialog")
    fireEvent.change(within(dlg).getByLabelText("Input (USD per million tokens)"), { target: { value: "0.009" } })
    reason()
    await user.click(within(dlg).getByRole("button", { name: "Save override" }))
    expect((s.setPrice as Fake).mutate).not.toHaveBeenCalled()
    await user.click(within(dlg).getByLabelText("These prices are right. Set them anyway"))
    await user.click(within(dlg).getByRole("button", { name: "Save override" }))
    await waitFor(() => expect((s.setPrice as Fake).mutate).toHaveBeenCalledTimes(1))
    expect((s.setPrice as Fake).mutate.mock.calls[0][0]).toMatchObject({
      model: "claude-haiku-4-5",
      body: { inputUsdPerMtok: "0.009", outputUsdPerMtok: "4.5", confirmUnusualPrice: true, expectedVersion: 3 },
    })
  })

  it("explains tier 2 cache scaling in the form", async () => {
    const user = userEvent.setup()
    render(wrap(h(LlmPrices, { saved })))
    await user.click(screen.getAllByRole("button", { name: "Set override for gemini-3-pro" })[0])
    expect(screen.getByText(/Cache prices in tier 2 scale with this/)).toBeTruthy()
  })

  it("warns that clearing an unpriced model leaves its calls unpriced, and sends the version", async () => {
    s.models = okQuery([{ ...fx.llmModels[2], override: { ...fx.llmModels[1].override!, model: "future-model-x" } }])
    const user = userEvent.setup()
    render(wrap(h(LlmPrices, { saved })))
    await user.click(screen.getAllByRole("button", { name: "Clear override for future-model-x" })[0])
    const dlg = screen.getByRole("dialog")
    expect(within(dlg).getByText(/Once cleared, calls to it are not priced/)).toBeTruthy()
    reason()
    await user.click(within(dlg).getByRole("button", { name: "Clear override" }))
    await waitFor(() => expect((s.clearPrice as Fake).mutate).toHaveBeenCalledTimes(1))
    expect((s.clearPrice as Fake).mutate.mock.calls[0][0]).toEqual({ model: "future-model-x", body: { expectedVersion: 3, reason: "because the market moved" } })
  })

  it("on a 409 stays open, says someone changed it, and blocks the old version", async () => {
    s.setPrice = fakeMutation({ isError: true, error: stale("llm_price_exists") })
    const user = userEvent.setup()
    render(wrap(h(LlmPrices, { saved })))
    await user.click(screen.getAllByRole("button", { name: "Set override for gemini-3-pro" })[0])
    const dlg = screen.getByRole("dialog")
    expect(within(dlg).getByRole("alert").textContent).toMatch(/override was set/)
    expect((within(dlg).getByRole("button", { name: "Save override" }) as HTMLButtonElement).disabled).toBe(true)
  })

  it("shows an empty line, a skeleton and an error", () => {
    s.models = okQuery([])
    const a = render(wrap(h(LlmPrices, { saved })))
    expect(screen.getByText(/No models yet/)).toBeTruthy()
    a.unmount()
    s.models = errorQuery(new ApiError(500, "x"))
    render(wrap(h(LlmPrices, { saved })))
    expect(screen.getByText("Couldn't load the AI prices")).toBeTruthy()
  })
})
