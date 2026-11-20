import { useCallback, useEffect, useState } from "react"
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

export type BlockSource = "estimate" | "start"

export interface MeteredGate {
  request: EstimateRequest | null
  estimate: UseQueryResult<EstimateResponse, Error>
  block: UsageBlock | null
  /** Where the block came from: the pre-start estimate, or a 402 from the start action itself. */
  blockSource: BlockSource | null
  /** Records a 402 usage block and returns true; returns false for any other error. */
  captureError: (err: unknown) => boolean
  clear: () => void
  /** "Try again" after the user fixed the cause (bought credits): drops the caught block and refetches. */
  retry: () => void
}

export function requestKeyOf(request: EstimateRequest | null): string | null {
  return request === null ? null : JSON.stringify(request)
}

/** A 402 for `key` as a caught block; null for any other error, or when there is no request to own it. */
export function captureBlock(err: unknown, key: string | null): CaughtBlock | null {
  if (key === null) return null
  const block = parseUsageBlock(err)
  return block === null ? null : { key, block }
}

/** A caught block belongs to one request: once the key moves on it is gone for good (A, B, A must not revive it). */
export function reconcileCaught(caught: CaughtBlock | null, key: string | null): CaughtBlock | null {
  return caught !== null && caught.key === key ? caught : null
}

/** A blocked estimate that is being refetched is stale: show neither its block nor its numbers until the answer lands. */
export function isRecheckingBlock(estimate: EstimateResponse | undefined, isFetching: boolean): boolean {
  return isFetching && Boolean(estimate?.blockedReason)
}

export function resolveBlock(
  estimate: EstimateResponse | undefined,
  caught: CaughtBlock | null,
  requestKey: string | null,
  estimateError?: unknown,
  rechecking = false,
): UsageBlock | null {
  const live = reconcileCaught(caught, requestKey)
  if (live) return live.block
  const fromError = parseUsageBlock(estimateError)
  if (fromError) return fromError
  if (!rechecking && estimate?.blockedReason) return { reason: estimate.blockedReason, estimate: null }
  return null
}

export function blockSourceOf(block: UsageBlock | null, caught: CaughtBlock | null, key: string | null): BlockSource | null {
  if (block === null) return null
  return reconcileCaught(caught, key) ? "start" : "estimate"
}

export function useMeteredGate(request: EstimateRequest | null): MeteredGate {
  const estimate = useUsageEstimate(request)
  const [caught, setCaught] = useState<CaughtBlock | null>(null)
  const key = requestKeyOf(request)
  const live = reconcileCaught(caught, key)
  // Dropping it in state (not only hiding it) is what stops a later return to the old key reviving it.
  if (live !== caught) setCaught(live)

  // A blocked answer is stale the moment the user buys credits elsewhere; never trust a cached one.
  const { refetch } = estimate
  const cachedBlocked = estimate.data?.blockedReason != null
  useEffect(() => {
    if (key !== null && cachedBlocked) void refetch()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per request, on arrival
  }, [key])

  const captureError = useCallback(
    (err: unknown) => {
      const next = captureBlock(err, key)
      if (next === null) return false
      setCaught(next)
      return true
    },
    [key],
  )
  const clear = useCallback(() => setCaught(null), [])
  const retry = useCallback(() => {
    setCaught(null)
    void refetch()
  }, [refetch])
  const block = resolveBlock(estimate.data, live, key, estimate.error, isRecheckingBlock(estimate.data, estimate.isFetching))
  return { request, estimate, block, blockSource: blockSourceOf(block, live, key), captureError, clear, retry }
}
