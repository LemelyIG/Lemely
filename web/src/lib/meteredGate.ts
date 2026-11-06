import { useCallback, useState } from "react"
import type { UseQueryResult } from "@tanstack/react-query"
import type { EstimateRequest, EstimateResponse } from "@/lib/billingTypes"
import { useUsageEstimate } from "@/lib/hooks/useUsageApi"
import { parseUsageBlock, type UsageBlock } from "@/lib/usageBlock"

/*
 * One gate per metered start control (spec §2.4: estimate first, start only if covered).
 * The estimate can block before the start; the route's 402 can block after. Both feed the
 * same `block`, and the screen disables its start control while `block` is set.
 */

export interface CaughtBlock {
  key: string | null
  block: UsageBlock
}

export interface MeteredGate {
  request: EstimateRequest | null
  estimate: UseQueryResult<EstimateResponse, Error>
  block: UsageBlock | null
  /** Records a 402 usage block and returns true; returns false for any other error. */
  captureError: (err: unknown) => boolean
  clear: () => void
}

export function requestKeyOf(request: EstimateRequest | null): string | null {
  return request === null ? null : JSON.stringify(request)
}

export function resolveBlock(
  estimate: EstimateResponse | undefined,
  caught: CaughtBlock | null,
  requestKey: string | null,
): UsageBlock | null {
  if (caught && caught.key === requestKey) return caught.block
  if (estimate?.blockedReason) return { reason: estimate.blockedReason, estimate: null }
  return null
}

export function useMeteredGate(request: EstimateRequest | null): MeteredGate {
  const estimate = useUsageEstimate(request)
  const [caught, setCaught] = useState<CaughtBlock | null>(null)
  const key = requestKeyOf(request)
  const captureError = useCallback(
    (err: unknown) => {
      const block = parseUsageBlock(err)
      if (block === null) return false
      setCaught({ key, block })
      return true
    },
    [key],
  )
  const clear = useCallback(() => setCaught(null), [])
  return { request, estimate, block: resolveBlock(estimate.data, caught, key), captureError, clear }
}
