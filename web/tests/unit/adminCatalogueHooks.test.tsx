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
import { adminBillingKeys, usePackPriceImpact, useUpdatePack, useUpdateTier } from "@/lib/hooks/useAdminBillingApi"

const req = vi.mocked(request)

function mountWith<T>(hook: () => T) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } })
  const invalidate = vi.spyOn(client, "invalidateQueries")
  const wrapper = ({ children }: { children: ReactNode }) => h(QueryClientProvider, { client }, children)
  return { ...renderHook(hook, { wrapper }), invalidate }
}

const stale = () => new ApiError(409, "Conflict", { code: "stale_write", message: "This was changed by someone else. Reload and try again." })
const tierBody = { expectedVersion: 4, name: "Student Plus", priceMinor: 27500, allowanceUnits: 4000, includedSeats: 0, seatAllowanceUnits: 0, extraSeatPriceMinor: 0, features: {}, isActive: true, reason: "reprice" }

beforeEach(() => req.mockReset())

describe("tier and pack writes", () => {
  it("send the version in the body, and refetch the catalogue after a stale write so the page shows what someone else saved", async () => {
    req.mockRejectedValueOnce(stale())
    const tier = mountWith(() => useUpdateTier())
    await expect(tier.result.current.mutateAsync({ id: "t1", body: tierBody })).rejects.toBeInstanceOf(ApiError)
    expect(JSON.parse(String((req.mock.calls[0]![1] as RequestInit).body))).toMatchObject({ expectedVersion: 4 })
    expect(tier.invalidate).toHaveBeenCalledWith({ queryKey: adminBillingKeys.catalogue })

    req.mockRejectedValueOnce(stale())
    const pack = mountWith(() => useUpdatePack())
    await expect(pack.result.current.mutateAsync({ id: "p1", body: { expectedVersion: 2, name: "500 credits", units: 500, priceMinor: 17500, isActive: true, reason: "reprice" } })).rejects.toBeInstanceOf(ApiError)
    expect(pack.invalidate).toHaveBeenCalledWith({ queryKey: adminBillingKeys.catalogue })
  })

  it("refetch the catalogue after a good write too", async () => {
    req.mockResolvedValueOnce({ id: "t1" })
    const tier = mountWith(() => useUpdateTier())
    await tier.result.current.mutateAsync({ id: "t1", body: tierBody })
    expect(tier.invalidate).toHaveBeenCalledWith({ queryKey: adminBillingKeys.catalogue })
  })
})

describe("usePackPriceImpact", () => {
  it("asks nothing without a price", () => {
    mountWith(() => usePackPriceImpact("p1", null))
    expect(req).not.toHaveBeenCalled()
  })

  it("asks the preview route with the price in piasters", async () => {
    req.mockResolvedValueOnce({ autoTopupCount: 6, capBelowPriceCount: 2 })
    const { result } = mountWith(() => usePackPriceImpact("p1", 17500))
    await waitFor(() => expect(result.current.data).toEqual({ autoTopupCount: 6, capBelowPriceCount: 2 }))
    expect(req.mock.calls[0]![0]).toBe("/admin/billing/packs/p1/price-impact?priceMinor=17500")
  })

  it("surfaces a failed preview as an error, never as zero", async () => {
    req.mockRejectedValueOnce(new ApiError(404, "gone", undefined))
    const { result } = mountWith(() => usePackPriceImpact("p1", 17500))
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.data).toBeUndefined()
  })
})
