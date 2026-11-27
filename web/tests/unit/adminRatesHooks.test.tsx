// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h, type ReactNode } from "react"
import { renderHook, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  request: vi.fn(),
}))

import { ApiError, request } from "@/lib/api"
import {
  adminBillingKeys,
  useBillingSettings,
  useClearCreditRate,
  useClearLlmPrice,
  useCreditRates,
  useLlmPrices,
  useSetCreditRate,
  useSetLlmPrice,
  useUpdateBillingSettings,
} from "@/lib/hooks/useAdminBillingApi"
import { fx } from "./support/billingFixtures"

const req = vi.mocked(request)

function mount<T>(hook: () => T) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } })
  const invalidate = vi.spyOn(client, "invalidateQueries")
  const wrapper = ({ children }: { children: ReactNode }) => h(QueryClientProvider, { client }, children)
  return { ...renderHook(hook, { wrapper }), invalidate }
}

beforeEach(() => req.mockReset())

describe("the eight rate calls", () => {
  it("reads settings, rates and prices without a fallback, and unwraps the lists", async () => {
    req.mockResolvedValueOnce(fx.billingSettings).mockResolvedValueOnce({ rates: [fx.creditRate] }).mockResolvedValueOnce({ models: fx.llmModels })
    const a = mount(useBillingSettings)
    const b = mount(useCreditRates)
    const c = mount(useLlmPrices)
    await waitFor(() => expect(a.result.current.data).toEqual(fx.billingSettings))
    await waitFor(() => expect(b.result.current.data).toEqual([fx.creditRate]))
    await waitFor(() => expect(c.result.current.data).toEqual(fx.llmModels))
    expect(req.mock.calls.map((x) => x[0]).sort()).toEqual(["/admin/billing/credit-rates", "/admin/billing/llm-prices", "/admin/billing/settings"])
    expect(req.mock.calls.every((x) => x.length === 1)).toBe(true)
  })

  it("writes with the verb and path of the API, and encodes the model", async () => {
    req.mockResolvedValue({})
    const settings = mount(useUpdateBillingSettings)
    const set = mount(useSetCreditRate)
    const clear = mount(useClearCreditRate)
    const price = mount(useSetLlmPrice)
    const unprice = mount(useClearLlmPrice)
    await settings.result.current.mutateAsync({ graceDays: 5, expectedVersion: 4, reason: "r" })
    await set.result.current.mutateAsync({ currency: "EGP", body: { unitsPerMinor: "10", expectedVersion: null, reason: "r" } })
    await clear.result.current.mutateAsync({ currency: "EGP", body: { expectedVersion: 2, confirmStopConversions: true, reason: "r" } })
    await price.result.current.mutateAsync({
      model: "gemini/3:pro",
      body: {
        inputUsdPerMtok: "1",
        outputUsdPerMtok: "2",
        cachedInputUsdPerMtok: null,
        cacheWrite5mUsdPerMtok: null,
        cacheWrite1hUsdPerMtok: null,
        tierThresholdTokens: null,
        tier2InputUsdPerMtok: null,
        tier2OutputUsdPerMtok: null,
        expectedVersion: null,
        reason: "r",
      },
    })
    await unprice.result.current.mutateAsync({ model: "gemini-3-pro", body: { expectedVersion: 1, reason: "r" } })
    expect(req.mock.calls.map((c) => [c[0], (c[1] as RequestInit).method])).toEqual([
      ["/admin/billing/settings", "PUT"],
      ["/admin/billing/credit-rates/EGP", "PUT"],
      ["/admin/billing/credit-rates/EGP/clear", "POST"],
      ["/admin/billing/llm-prices/gemini%2F3%3Apro", "PUT"],
      ["/admin/billing/llm-prices/gemini-3-pro/clear", "POST"],
    ])
    expect(JSON.parse(String((req.mock.calls[2][1] as RequestInit).body))).toMatchObject({ confirmStopConversions: true })
  })

  it("reloads the section after a 409 stale_write, not just after a success", async () => {
    req.mockRejectedValueOnce(new ApiError(409, "x", { code: "stale_write", message: "m" }))
    const { result, invalidate } = mount(useUpdateBillingSettings)
    await expect(result.current.mutateAsync({ graceDays: 5, expectedVersion: 1, reason: "r" })).rejects.toBeInstanceOf(ApiError)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: adminBillingKeys.settings })
  })

  it("reloads only its own section", async () => {
    req.mockResolvedValue({})
    const { result, invalidate } = mount(useSetLlmPrice)
    await result.current.mutateAsync({ model: "m", body: { expectedVersion: 1, reason: "r" } as never })
    expect(invalidate.mock.calls.map((c) => c[0])).toEqual([{ queryKey: adminBillingKeys.llmPrices }])
  })
})
