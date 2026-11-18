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

describe("a 409 after a real submit", () => {
  it("billing rules: refetched data never changes what an open dialog sends, and a 409 then blocks it", async () => {
    const client = new QueryClient()
    const el = () => h(QueryClientProvider, { client }, h(MemoryRouter, null, h(BillingRules, { saved })))
    const user = userEvent.setup()
    const { rerender } = render(el())
    await user.click(screen.getByRole("button", { name: "Edit billing rules" }))
    const grace = screen.getByLabelText("Grace days")
    await user.clear(grace)
    await user.type(grace, "5")
    reason()
    // Another admin raises the seat ceiling and the section refetches while the dialog is open.
    s.settings = okQuery({ ...fx.billingSettings, version: 5, maxExtraSeats: 300 })
    rerender(el())
    await user.click(screen.getByRole("button", { name: "Save rules" }))
    await waitFor(() => expect((s.update as Fake).mutate).toHaveBeenCalledTimes(1))
    expect((s.update as Fake).mutate.mock.calls[0][0]).toEqual({ graceDays: 5, expectedVersion: 4, reason: "because the market moved" })
    // The server answers stale_write: the dialog stays and will not send again.
    s.update = fakeMutation({ isError: true, error: stale("stale_write") })
    rerender(el())
    const dlg = screen.getByRole("dialog")
    expect(within(dlg).getByRole("alert").textContent).toMatch(/Someone changed this while you were editing/)
    expect((within(dlg).getByRole("button", { name: "Save rules" }) as HTMLButtonElement).disabled).toBe(true)
    expect(within(dlg).getByText("Close this to see the current values.")).toBeTruthy()
  })

  it("AI price: submit, then 409, then blocked", async () => {
    const client = new QueryClient()
    const el = () => h(QueryClientProvider, { client }, h(MemoryRouter, null, h(LlmPrices, { saved })))
    const user = userEvent.setup()
    const { rerender } = render(el())
    await user.click(screen.getAllByRole("button", { name: "Edit override for gemini-2.5-flash" })[0])
    fireEvent.change(screen.getByLabelText("Input (USD per million tokens)"), { target: { value: "0.26" } })
    reason()
    await user.click(screen.getByRole("button", { name: "Save override" }))
    await waitFor(() => expect((s.setPrice as Fake).mutate).toHaveBeenCalledTimes(1))
    s.setPrice = fakeMutation({ isError: true, error: stale("stale_write") })
    rerender(el())
    expect((within(screen.getByRole("dialog")).getByRole("button", { name: "Save override" }) as HTMLButtonElement).disabled).toBe(true)
  })

  it("a ticked server-asked flat-rate box is sent on a row the page sees as flat", async () => {
    s.setPrice = fakeMutation({ isError: true, error: new ApiError(422, "x", { code: "override_drops_tier", message: "m" }) })
    const user = userEvent.setup()
    render(wrap(h(LlmPrices, { saved })))
    await user.click(screen.getAllByRole("button", { name: "Edit override for gemini-2.5-flash" })[0])
    reason()
    await user.click(screen.getByLabelText("Charge one flat rate at every length"))
    await user.click(screen.getByRole("button", { name: "Save override" }))
    await waitFor(() => expect((s.setPrice as Fake).mutate).toHaveBeenCalledTimes(1))
    expect((s.setPrice as Fake).mutate.mock.calls[0][0].body.confirmDropTier).toBe(true)
  })
})

describe("market reference hint", () => {
  const link = () => screen.queryAllByRole("link", { name: "Rates By Exchange Rate API" })

  it("billing rules: shows the market line and one attribution link, with no note within 10%", () => {
    render(wrap(h(BillingRules, { saved })))
    expect(screen.getByText(/^Market rate: 1 USD = 53\.74 EGP · /)).toBeTruthy()
    expect(screen.queryByText(/Yours is/)).toBeNull()
    expect(link()).toHaveLength(1)
    expect(link()[0].getAttribute("href")).toBe("https://www.exchangerate-api.com")
    expect(link()[0].getAttribute("rel")).toContain("noopener")
  })

  it("billing rules: adds a neutral note when the margin rate is more than 10% off", () => {
    s.settings = okQuery({ ...fx.billingSettings, marginEgpPerUsd: "60" })
    render(wrap(h(BillingRules, { saved })))
    expect(screen.getByText(/Yours is 12% higher\./)).toBeTruthy()
  })

  it("shows nothing at all when the reading is null", () => {
    s.settings = okQuery({ ...fx.billingSettings, marketReference: null })
    render(wrap(h(BillingRules, { saved })))
    expect(screen.queryByText(/Market rate/)).toBeNull()
    expect(link()).toHaveLength(0)
  })

  it("is only a hint: no button to use it, and a save sends exactly the edited field", async () => {
    const user = userEvent.setup()
    render(wrap(h(BillingRules, { saved })))
    // The hint is a line and a link: any button inside it, whatever its name, fails here.
    const hint = screen.getByText(/^Market rate: /).parentElement as HTMLElement
    expect(within(hint).queryAllByRole("button")).toHaveLength(0)
    expect(within(hint).queryAllByRole("link")).toHaveLength(1)
    await user.click(screen.getByRole("button", { name: "Edit billing rules" }))
    const margin = screen.getByLabelText("Margin rate (EGP per USD)") as HTMLInputElement
    expect(margin.value).toBe("50")
    const grace = screen.getByLabelText("Grace days")
    await user.clear(grace)
    await user.type(grace, "5")
    reason()
    await user.click(screen.getByRole("button", { name: "Save rules" }))
    await waitFor(() => expect((s.update as Fake).mutate).toHaveBeenCalledTimes(1))
    expect((s.update as Fake).mutate.mock.calls[0][0]).toEqual({ graceDays: 5, expectedVersion: 4, reason: "because the market moved" })
  })

  it("credit conversion: the market line and one link on the EGP row, never a comparison", () => {
    s.settings = okQuery({ ...fx.billingSettings, marketReference: { ...fx.billingSettings.marketReference!, rate: "20" } })
    render(wrap(h(CreditConversion, { saved })))
    expect(screen.getByText(/^Market rate: 1 USD = 20\.00 EGP · /)).toBeTruthy()
    expect(screen.queryByText(/Yours is/)).toBeNull()
    expect(link()).toHaveLength(1)
  })

  it("credit conversion: the market line sits straight under the value, before who changed it", () => {
    render(wrap(h(CreditConversion, { saved })))
    const value = screen.getByText("1 EGP = 1,250 units")
    const market = screen.getByText(/^Market rate: /)
    const changed = screen.getByText(/^Changed /)
    const follows = (a: Node, b: Node) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)
    expect(follows(value, market)).toBe(true)
    expect(follows(market, changed)).toBe(true)
  })

  it("credit conversion: nothing when the reading is null or the settings could not be read", () => {
    s.settings = okQuery({ ...fx.billingSettings, marketReference: null })
    const a = render(wrap(h(CreditConversion, { saved })))
    expect(screen.queryByText(/Market rate/)).toBeNull()
    a.unmount()
    s.settings = errorQuery(new ApiError(500, "x"))
    render(wrap(h(CreditConversion, { saved })))
    expect(screen.queryByText(/Market rate/)).toBeNull()
    expect(screen.getByText("1 EGP = 1,250 units")).toBeTruthy()
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
    expect(table.getAllByText("claude-haiku-5-5").length).toBe(1)
    expect(table.getByText(/No built-in price. Calls use the Flash rates/)).toBeTruthy()
    expect(table.getByText(/No built-in price. Calls to it are not priced without an override/)).toBeTruthy()
    expect(table.getAllByText("Used in the last 30 days").length).toBe(2)
    expect(table.getAllByText("Not used in the last 30 days").length).toBe(2)
    expect(table.getAllByText("$0.25").length).toBe(1)
    // The 57-character source URL has no break point, so it must be allowed to wrap.
    expect(table.getByText(/platform\.claude\.com/).className).toContain("break-all")
  })

  it("explains that a lower price lowers what customers are charged", () => {
    render(wrap(h(LlmPrices, { saved })))
    expect(screen.getByText(/lower price lowers what they are charged/)).toBeTruthy()
  })

  it("warns about a flat rate only on a tiered built-in row, and holds the save until it is ticked", async () => {
    const user = userEvent.setup()
    render(wrap(h(LlmPrices, { saved })))
    await user.click(screen.getAllByRole("button", { name: "Set override for claude-haiku-5-5" })[0])
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
    await user.click(screen.getAllByRole("button", { name: "Edit override for gemini-2.5-flash" })[0])
    expect(screen.queryByText("This override charges the same rate at every prompt length.")).toBeNull()
    expect(screen.queryByLabelText("Charge one flat rate at every length")).toBeNull()
  })

  it("asks for the unusual-price confirmation on a typo-sized price and sends it with decimal strings", async () => {
    const user = userEvent.setup()
    render(wrap(h(LlmPrices, { saved })))
    await user.click(screen.getAllByRole("button", { name: "Edit override for gemini-2.5-flash" })[0])
    const dlg = screen.getByRole("dialog")
    fireEvent.change(within(dlg).getByLabelText("Input (USD per million tokens)"), { target: { value: "0.002" } })
    reason()
    await user.click(within(dlg).getByRole("button", { name: "Save override" }))
    expect((s.setPrice as Fake).mutate).not.toHaveBeenCalled()
    await user.click(within(dlg).getByLabelText("These prices are right. Set them anyway"))
    await user.click(within(dlg).getByRole("button", { name: "Save override" }))
    await waitFor(() => expect((s.setPrice as Fake).mutate).toHaveBeenCalledTimes(1))
    expect((s.setPrice as Fake).mutate.mock.calls[0][0]).toMatchObject({
      model: "gemini-2.5-flash",
      body: { inputUsdPerMtok: "0.002", outputUsdPerMtok: "2.2", confirmUnusualPrice: true, expectedVersion: 3 },
    })
  })

  it("explains tier 2 cache scaling in the form", async () => {
    const user = userEvent.setup()
    render(wrap(h(LlmPrices, { saved })))
    await user.click(screen.getAllByRole("button", { name: "Set override for claude-haiku-5-5" })[0])
    expect(screen.getByText(/Cache prices in tier 2 scale with this/)).toBeTruthy()
  })

  it.each([
    ["gemini-3-pro-preview", /Once cleared, calls use the Flash rates/],
    ["claude-future-x", /Once cleared, calls to it are not priced without an override/],
  ])("clearing the override of %s says what a call costs afterwards, and sends the version", async (model, copy) => {
    const base = fx.llmModels.find((m) => m.model === model)!
    s.models = okQuery([{ ...base, override: { ...fx.llmModels[1].override!, model } }])
    const user = userEvent.setup()
    render(wrap(h(LlmPrices, { saved })))
    await user.click(screen.getAllByRole("button", { name: `Clear override for ${model}` })[0])
    const dlg = screen.getByRole("dialog")
    expect(within(dlg).getByText(copy)).toBeTruthy()
    reason()
    await user.click(within(dlg).getByRole("button", { name: "Clear override" }))
    await waitFor(() => expect((s.clearPrice as Fake).mutate).toHaveBeenCalledTimes(1))
    expect((s.clearPrice as Fake).mutate.mock.calls[0][0]).toEqual({ model, body: { expectedVersion: 3, reason: "because the market moved" } })
  })

  it("on a 409 stays open, says someone changed it, and blocks the old version", async () => {
    s.setPrice = fakeMutation({ isError: true, error: stale("llm_price_exists") })
    const user = userEvent.setup()
    render(wrap(h(LlmPrices, { saved })))
    await user.click(screen.getAllByRole("button", { name: "Set override for claude-haiku-5-5" })[0])
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
