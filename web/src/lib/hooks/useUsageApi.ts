import {
  useInfiniteQuery,
  useQuery,
  type InfiniteData,
  type QueryClient,
  type UseInfiniteQueryResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import { toEstimate, toUsageJob, toUsageMeter } from "@/lib/billingAdapters"
import type {
  EstimateRequest,
  EstimateResponse,
  UsageHistoryPage,
  UsageMeterView,
  WireEstimate,
  WireUsageHistory,
  WireUsageMeter,
} from "@/lib/billingTypes"

/*
 * React-query hooks over `/api/usage/*` (plan 04). The estimate writes nothing server-side
 * (spec §5.7 step 1), so it is a query keyed by the request: the same request on the same screen
 * reuses the answer for a minute. Meter and history serve the caller only (M6); a parent reads a
 * child's meter through the billing summary.
 */

export const usageApi = {
  estimate: (body: EstimateRequest) => request<WireEstimate>("/usage/estimate", { method: "POST", body: JSON.stringify(body) }),
  meter: () => request<WireUsageMeter>("/usage/meter"),
  history: (cursor: string | null) => {
    const params = new URLSearchParams({ limit: "25" })
    if (cursor) params.set("cursor", cursor)
    return request<WireUsageHistory>(`/usage/history?${params.toString()}`)
  },
}

export const usageKeys = {
  all: ["usage"] as const,
  estimate: (body: EstimateRequest) => ["usage", "estimate", body] as const,
  meter: ["usage", "meter"] as const,
  history: ["usage", "history"] as const,
}

/** `null` request = nothing to estimate yet; the query stays idle. */
export function useUsageEstimate(body: EstimateRequest | null): UseQueryResult<EstimateResponse, Error> {
  return useQuery({
    queryKey: body ? usageKeys.estimate(body) : ["usage", "estimate", "idle"],
    queryFn: async () => toEstimate(await usageApi.estimate(body as EstimateRequest)),
    enabled: body !== null,
    staleTime: 60_000,
    retry: false,
  })
}

export function useUsageMeter(): UseQueryResult<UsageMeterView, Error> {
  return useQuery({ queryKey: usageKeys.meter, queryFn: usageApi.meter, select: toUsageMeter })
}

export function useUsageHistory(): UseInfiniteQueryResult<InfiniteData<UsageHistoryPage, string | null>, Error> {
  return useInfiniteQuery({
    queryKey: usageKeys.history,
    queryFn: async ({ pageParam }) => {
      const w = await usageApi.history(pageParam)
      return { jobs: w.jobs.map(toUsageJob), nextCursor: w.nextCursor }
    },
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor,
  })
}

/** After a metered action settles: meter, credits, history and summaries all moved. */
export function invalidateUsage(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: usageKeys.all })
  void queryClient.invalidateQueries({ queryKey: ["billing", "summary"] })
}
