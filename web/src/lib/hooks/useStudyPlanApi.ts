import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import type {
  CreateStudyPlanRequest,
  CurrentStudyPlanDTO,
  StudyPlanSessionDTO,
  StudyPlanWeekDTO,
} from "@/lib/studyPlanTypes"

/*
 * React-query hooks for `/api/student/study-plan/*` (S-24/S-25), following
 * `usePracticeApi.ts`'s conventions exactly: one hook per endpoint, no
 * `fallback` passed to `request()` — a real backend/auth failure surfaces as a
 * query/mutation error the screen renders, never silently resolves to empty
 * data that would be indistinguishable from "no plan yet".
 */

const planKey = (subjectCode: string) => ["studyPlan", "current", subjectCode] as const

/**
 * `GET /api/student/study-plan/{subjectCode}`.
 *
 * **Never a 404 for a missing plan** — "no plan generated this week" comes back
 * as a successful `{generated: false}`. So a query *error* here means a real
 * failure (auth, network, server) and must be rendered as one; it must not be
 * folded into the empty state.
 */
export function useCurrentStudyPlan(subjectCode: string): UseQueryResult<CurrentStudyPlanDTO, Error> {
  return useQuery({
    queryKey: planKey(subjectCode),
    queryFn: () => request<CurrentStudyPlanDTO>(`/student/study-plan/${subjectCode}`),
    enabled: !!subjectCode,
  })
}

/**
 * `POST /api/student/study-plan` — S-24's "Rebuild this week's plan".
 *
 * Writes the 201 body straight into the current-plan cache rather than only
 * invalidating: the response *is* this week's plan (generation supersedes any
 * existing one for the same student/subject/ISO week), so re-fetching would
 * ask the server to repeat itself. It is written wrapped as
 * `{generated: true, plan}` because a just-generated refusal is still a
 * generated plan — dropping the envelope here would push the screen back into
 * the "no plan yet" branch it just left.
 */
export function useRebuildStudyPlan(): UseMutationResult<StudyPlanWeekDTO, Error, CreateStudyPlanRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateStudyPlanRequest) =>
      request<StudyPlanWeekDTO>("/student/study-plan", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: (plan) => {
      queryClient.setQueryData<CurrentStudyPlanDTO>(planKey(plan.subjectCode), {
        generated: true,
        plan,
      })
    },
  })
}

/**
 * `POST /api/student/study-plan/sessions/{sessionId}/complete`.
 *
 * The route is idempotent server-side and returns the updated session. The
 * cache is patched with **the session the server returned**, not with a
 * client-side `new Date()` — the completion timestamp is the server's fact and
 * a locally-stamped one would drift from what the next reload shows. Takes the
 * subject code alongside the id purely to locate the cache entry; the server
 * scopes the write to the authenticated caller.
 */
export function useCompleteStudyPlanSession(): UseMutationResult<
  StudyPlanSessionDTO,
  Error,
  { sessionId: string; subjectCode: string }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ sessionId }) =>
      request<StudyPlanSessionDTO>(`/student/study-plan/sessions/${sessionId}/complete`, {
        method: "POST",
      }),
    onSuccess: (session, { subjectCode }) => {
      queryClient.setQueryData<CurrentStudyPlanDTO>(planKey(subjectCode), (current) => {
        if (!current?.plan) return current
        return {
          ...current,
          plan: {
            ...current.plan,
            sessions: current.plan.sessions.map((s) => (s.id === session.id ? session : s)),
          },
        }
      })
    },
  })
}
