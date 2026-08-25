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
  CreateSchoolAdminRequest,
  CreateSchoolAdminResponse,
  CreateSchoolRequest,
  PipelineHealth,
  PlatformOverview,
  SchoolList,
  SchoolSummary,
  UpdateSchoolRequest,
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
const SCHOOLS_KEY = ["admin", "schools"] as const

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

// ── Schools (Task 22, D7.8) ─────────────────────────────────────────────────
//
// The account graph's missing first link (spec §1.1): before these four
// routes existed, no production code path created a `School` row or a
// `school_admin` account. Every mutation below invalidates SCHOOLS_KEY on
// success rather than patching the cached list by hand — the list is small
// (there is no pagination on `list_schools`, mirroring the rest of this
// console) and a refetch is the same one honesty this whole file already
// insists on for reads: the screen shows what the server just confirmed, not
// what the client assumes the write did.

/** `GET /api/admin/schools` — D7.8's list of every school on the platform,
 * with quota, seat usage and admins. No `fallback`, for the same reason
 * every other read in this file has none: an empty list here is
 * indistinguishable on screen from "there truly are no schools yet", so a
 * failed fetch must render as a failure, never as that empty state. */
export function useSchools(): UseQueryResult<SchoolList, Error> {
  return useQuery({
    queryKey: SCHOOLS_KEY,
    queryFn: () => request<SchoolList>("/admin/schools"),
  })
}

/** `POST /api/admin/schools` — create a school with an initial seat quota. */
export function useCreateSchool(): UseMutationResult<
  SchoolSummary,
  Error,
  CreateSchoolRequest
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateSchoolRequest) =>
      request<SchoolSummary>("/admin/schools", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: SCHOOLS_KEY })
    },
  })
}

/** What an update needs: which school, and the fields to change. */
export interface UpdateSchoolVariables {
  schoolId: string
  body: UpdateSchoolRequest
}

/**
 * `PATCH /api/admin/schools/{id}` — rename a school and/or change its quota.
 *
 * A quota lowered below the seats already assigned comes back as a 409;
 * `schoolUpdateFailureMessage` in `adminOutcome.ts` is what turns that into
 * copy, reading the two numbers from the caller's own state rather than the
 * server's sentence — see that function for why.
 */
export function useUpdateSchool(): UseMutationResult<
  SchoolSummary,
  Error,
  UpdateSchoolVariables
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ schoolId, body }: UpdateSchoolVariables) =>
      request<SchoolSummary>(`/admin/schools/${schoolId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: SCHOOLS_KEY })
    },
  })
}

/** What creating a school_admin needs: which school, and the account details. */
export interface CreateSchoolAdminVariables {
  schoolId: string
  body: CreateSchoolAdminRequest
}

/**
 * `POST /api/admin/schools/{id}/admins` — create a school_admin account and
 * bind it to the school in one call.
 *
 * `body.password` is never set by any caller in this console: every school_admin
 * created here gets a backend-generated `temporaryPassword`, returned once in
 * the response and never persisted anywhere the client could read it back —
 * the same one-time handling `useInviteTeacher`/`useInviteStudent`
 * (`useSchoolApi.ts`) already give their own generated credentials.
 */
export function useCreateSchoolAdmin(): UseMutationResult<
  CreateSchoolAdminResponse,
  Error,
  CreateSchoolAdminVariables
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ schoolId, body }: CreateSchoolAdminVariables) =>
      request<CreateSchoolAdminResponse>(`/admin/schools/${schoolId}/admins`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: SCHOOLS_KEY })
    },
  })
}
