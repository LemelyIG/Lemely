import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import type {
  ActivationQueue,
  ActivationResult,
  PipelineHealth,
  PlatformOverview,
} from "@/lib/adminTypes"

/*
 * React-query hooks over `/api/admin/*` (`lemely/web/routers/admin.py`), gated
 * to `platform_admin` alone. Same conventions as useSchoolApi.ts: one hook per
 * endpoint, and **no `fallback` passed to `request()`** anywhere in this file.
 *
 * That last point matters more here than on any other surface. A fallback turns
 * a failed read into a plausible-looking empty payload, and on this console an
 * empty payload reads as "nothing is wrong": zero open review items, zero failed
 * uploads, zero spend. The one screen whose whole job is noticing trouble must
 * never quietly report calm because the request died.
 */

const OVERVIEW_KEY = ["admin", "overview"] as const
const ACTIVATIONS_KEY = ["admin", "activations"] as const
const PIPELINE_KEY = ["admin", "pipeline"] as const

/** `GET /api/admin/overview` — X-01's counts, spend, health and signups. */
export function useAdminOverview(): UseQueryResult<PlatformOverview, Error> {
  return useQuery({
    queryKey: OVERVIEW_KEY,
    queryFn: () => request<PlatformOverview>("/admin/overview"),
  })
}

/** `GET /api/admin/activations` — X-02's manual-activation queue, oldest first. */
export function useActivationQueue(): UseQueryResult<ActivationQueue, Error> {
  return useQuery({
    queryKey: ACTIVATIONS_KEY,
    queryFn: () => request<ActivationQueue>("/admin/activations"),
  })
}

/** `GET /api/admin/pipeline` — X-03's corpus, boundary and ingestion health. */
export function usePipelineHealth(): UseQueryResult<PipelineHealth, Error> {
  return useQuery({
    queryKey: PIPELINE_KEY,
    queryFn: () => request<PipelineHealth>("/admin/pipeline"),
  })
}

/** What a decision needs: which subscription, which way, and why. */
export interface ActivationDecision {
  subscriptionId: string
  activate: boolean
  note: string | null
}

/**
 * `POST /api/admin/activations/{id}/{activate|reject}` (X-02).
 *
 * One hook for both directions rather than two, because they are one decision
 * with two outcomes and the screen renders them side by side on the same row.
 * Splitting them would put the "which way" choice in the import list instead of
 * in the data, where a reader can see it.
 *
 * A 409 here is the expected case, not an exotic one: two admins working the
 * same queue is ordinary, and the second decision is refused rather than
 * overwriting the first. The screen reports that specifically.
 */
export function useDecideActivation(): UseMutationResult<
  ActivationResult,
  Error,
  ActivationDecision
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ subscriptionId, activate, note }: ActivationDecision) =>
      request<ActivationResult>(
        `/admin/activations/${subscriptionId}/${activate ? "activate" : "reject"}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ note }),
        },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ACTIVATIONS_KEY })
    },
  })
}
