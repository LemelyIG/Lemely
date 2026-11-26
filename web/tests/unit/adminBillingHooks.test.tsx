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
import { PartialSaveError, adminBillingFailureMessage } from "@/lib/adminBillingModel"
import { adminBillingKeys, useForgiveDebt, useRefundPayment, useUpdateFreeAllowances, useVoidPayment } from "@/lib/hooks/useAdminBillingApi"

const req = vi.mocked(request)

function mount() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  const invalidate = vi.spyOn(client, "invalidateQueries")
  const wrapper = ({ children }: { children: ReactNode }) => h(QueryClientProvider, { client }, children)
  return { ...renderHook(() => useUpdateFreeAllowances(), { wrapper }), invalidate }
}

const student = { audience: "student" as const, units: 400, validDays: null, expectedVersion: 2, reason: "starter allowance" }
const teacher = { audience: "teacher" as const, units: 1200, validDays: 30, expectedVersion: 3, reason: "starter allowance" }
const saved = (audience: string, units: number) => ({ audience, creditPackId: "p", units, validDays: null })

beforeEach(() => req.mockReset())

describe("useUpdateFreeAllowances", () => {
  it("sends the audiences one after the other, in order, and only those given", async () => {
    const order: string[] = []
    let releaseFirst: () => void = () => undefined
    req.mockImplementationOnce(async (_path, init) => {
      order.push("student:start")
      await new Promise<void>((resolve) => (releaseFirst = resolve))
      order.push("student:end")
      return saved("student", JSON.parse(String((init as RequestInit).body)).units)
    })
    req.mockImplementationOnce(async () => {
      order.push("teacher:start")
      return saved("teacher", 1200)
    })
    const { result } = mount()
    const done = result.current.mutateAsync([student, teacher])
    await waitFor(() => expect(order).toEqual(["student:start"]))
    // The second request must not start while the first is in flight.
    expect(req).toHaveBeenCalledTimes(1)
    releaseFirst()
    await done
    expect(order).toEqual(["student:start", "student:end", "teacher:start"])
    expect(req.mock.calls.map((c) => [c[0], (c[1] as RequestInit).method])).toEqual([
      ["/admin/billing/free-allowances", "PUT"],
      ["/admin/billing/free-allowances", "PUT"],
    ])
  })

  it("names the saved allowance when the second request fails, and still refetches the catalogue", async () => {
    req.mockResolvedValueOnce(saved("student", 400))
    req.mockRejectedValueOnce(new ApiError(422, "x", { code: "units_rejected", message: "The database refused these units." }))
    const { result, invalidate } = mount()
    const error = await result.current.mutateAsync([student, teacher]).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(PartialSaveError)
    const partial = error as PartialSaveError
    expect(partial.saved).toEqual(["the student free allowance"])
    expect(partial.failed).toBe("the teacher signup credits")
    expect(partial.rows).toEqual([saved("student", 400)])
    expect(adminBillingFailureMessage(partial, "save")).toBe(
      "the student free allowance was saved, but the teacher signup credits was not. The database refused these units.",
    )
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["admin", "billing", "catalogue"] }))
  })

  it("rethrows the original error, not a partial one, when the first request fails", async () => {
    const refusal = new ApiError(403, "Forbidden")
    req.mockRejectedValueOnce(refusal)
    const { result } = mount()
    await expect(result.current.mutateAsync([student, teacher])).rejects.toBe(refusal)
    expect(req).toHaveBeenCalledTimes(1)
  })
})

function mountWith<T>(hook: () => T) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  const invalidate = vi.spyOn(client, "invalidateQueries")
  const wrapper = ({ children }: { children: ReactNode }) => h(QueryClientProvider, { client }, children)
  return { ...renderHook(hook, { wrapper }), invalidate, client }
}

describe("refetching what a failed write may have changed", () => {
  const refusal = () => new ApiError(409, "Conflict", { code: "refund_in_flight", message: "A refund is open." })

  it("refetches the billing data after a refused refund, so Refund is not offered on a stale row", async () => {
    req.mockRejectedValueOnce(refusal())
    const { result, invalidate } = mountWith(() => useRefundPayment())
    await expect(result.current.mutateAsync({ id: "pay1", body: { amountMinor: null, reason: "duplicate" } })).rejects.toBeInstanceOf(ApiError)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: adminBillingKeys.all })
  })

  it("refetches after a dropped void and after a successful one", async () => {
    req.mockRejectedValueOnce(new ApiError(0, "net", undefined))
    const dropped = mountWith(() => useVoidPayment())
    await expect(dropped.result.current.mutateAsync({ id: "pay1", body: { reason: "mistake" } })).rejects.toBeInstanceOf(ApiError)
    expect(dropped.invalidate).toHaveBeenCalledWith({ queryKey: adminBillingKeys.all })
    req.mockResolvedValueOnce({ id: "pay1" })
    const ok = mountWith(() => useVoidPayment())
    await ok.result.current.mutateAsync({ id: "pay1", body: { reason: "mistake" } })
    expect(ok.invalidate).toHaveBeenCalledWith({ queryKey: adminBillingKeys.all })
  })

  it("refetches the customer after a failed ledger write and stores the answer after a good one", async () => {
    req.mockRejectedValueOnce(new ApiError(503, "down", undefined))
    const failed = mountWith(() => useForgiveDebt("u2"))
    await expect(failed.result.current.mutateAsync({ id: "u2", body: { units: null, reason: "estimator bug" } })).rejects.toBeInstanceOf(ApiError)
    expect(failed.invalidate).toHaveBeenCalledWith({ queryKey: adminBillingKeys.customer("u2") })
    const answer = { user: { id: "u2" } }
    req.mockResolvedValueOnce(answer)
    const good = mountWith(() => useForgiveDebt("u2"))
    await good.result.current.mutateAsync({ id: "u2", body: { units: null, reason: "estimator bug" } })
    expect(good.client.getQueryData(adminBillingKeys.customer("u2"))).toEqual(answer)
    expect(good.invalidate).not.toHaveBeenCalled()
  })
})
