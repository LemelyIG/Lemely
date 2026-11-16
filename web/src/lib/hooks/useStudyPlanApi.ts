import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { ApiError, request } from "@/lib/api"
import { patchCurrentSession, patchOverviewSession } from "@/lib/studyPlanCache"
import type {
  CreateStudyPlanRequest,
  CurrentStudyPlanDTO,
  MoveSessionRequest,
  StudyPlanOverviewDTO,
  StudyPlanSessionDTO,
  StudyPlanWeekDTO,
} from "@/lib/studyPlanTypes"

/*
 * React-query hooks for `/api/student/study-plan/*`. One hook per endpoint,
 * and no `fallback` passed to `request()`: a real failure surfaces as an
 * error the screen renders, never as empty data that would read as "no plan
 * yet".
 */

export const studyPlanKeys = {
  all: ["studyPlan"] as const,
  week: ["studyPlan", "week"] as const,
  current: (subjectCode: string) => ["studyPlan", "current", subjectCode] as const,
}

/** `GET /api/student/study-plan`: this week across every enrolled subject. */
export function useStudyPlanWeek(): UseQueryResult<StudyPlanOverviewDTO, Error> {
  return useQuery({
    queryKey: studyPlanKeys.week,
    queryFn: () => request<StudyPlanOverviewDTO>("/student/study-plan"),
  })
}

/** `GET /api/student/study-plan/{subjectCode}`. Deleted in Task 14 once no screen reads it. */
export function useCurrentStudyPlan(subjectCode: string): UseQueryResult<CurrentStudyPlanDTO, Error> {
  return useQuery({
    queryKey: studyPlanKeys.current(subjectCode),
    queryFn: () => request<CurrentStudyPlanDTO>(`/student/study-plan/${subjectCode}`),
    enabled: !!subjectCode,
  })
}

/** Single-subject rebuild used by the old week screen. Deleted in Task 14. */
export function useRebuildStudyPlan(): UseMutationResult<StudyPlanWeekDTO, Error, CreateStudyPlanRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateStudyPlanRequest) =>
      request<StudyPlanWeekDTO>("/student/study-plan", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (plan) => {
      queryClient.setQueryData<CurrentStudyPlanDTO>(studyPlanKeys.current(plan.subjectCode), {
        generated: true,
        plan,
      })
      return queryClient.invalidateQueries({ queryKey: studyPlanKeys.week })
    },
  })
}

/**
 * Build or rebuild several subjects' plans, one POST each, in order.
 *
 * For the current week, each response is written to its per-subject cache
 * (wrapped as `{generated: true, plan}`, since a fresh refusal is still a
 * generated plan), then the week is refetched. A POST response carries no
 * reasons, paper counts or weak topics, so the week has to come from its own
 * route. Returning the invalidation promise keeps the mutation pending until
 * the refetch lands, which is what keeps the "Rebuilding..." banner up.
 * `week: "next"` writes nothing: next week is invisible until it starts.
 */
export function useRebuildStudyPlans(): UseMutationResult<
  StudyPlanWeekDTO[],
  Error,
  { subjectCodes: string[]; week?: "current" | "next" }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ subjectCodes, week = "current" }) => {
      const plans: StudyPlanWeekDTO[] = []
      for (const subjectCode of subjectCodes) {
        plans.push(
          await request<StudyPlanWeekDTO>("/student/study-plan", {
            method: "POST",
            body: JSON.stringify({ subjectCode, week } satisfies CreateStudyPlanRequest),
          }),
        )
      }
      return plans
    },
    onSuccess: (plans, { week = "current" }) => {
      if (week === "next") return undefined
      for (const plan of plans) {
        queryClient.setQueryData<CurrentStudyPlanDTO>(studyPlanKeys.current(plan.subjectCode), {
          generated: true,
          plan,
        })
      }
      return queryClient.invalidateQueries({ queryKey: studyPlanKeys.week })
    },
    // Plans before the failing subject are already rebuilt server-side, so the
    // cached week holds dead session ids. Refetch rather than keep them.
    onError: () => queryClient.invalidateQueries({ queryKey: studyPlanKeys.all }),
  })
}

/**
 * `POST /api/student/study-plan/sessions/{sessionId}/complete`. Idempotent
 * server-side. Patches both caches with the session the server returned.
 */
export function useCompleteStudyPlanSession(): UseMutationResult<
  StudyPlanSessionDTO,
  Error,
  { sessionId: string; subjectCode: string }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ sessionId }) =>
      request<StudyPlanSessionDTO>(`/student/study-plan/sessions/${sessionId}/complete`, { method: "POST" }),
    onSuccess: (session, { subjectCode }) => {
      queryClient.setQueryData<StudyPlanOverviewDTO>(studyPlanKeys.week, (o) => patchOverviewSession(o, session))
      queryClient.setQueryData<CurrentStudyPlanDTO>(studyPlanKeys.current(subjectCode), (c) =>
        patchCurrentSession(c, session),
      )
    },
    onError: (error) => {
      if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
        return queryClient.invalidateQueries({ queryKey: studyPlanKeys.week })
      }
      return undefined
    },
  })
}

/**
 * `POST /api/student/study-plan/sessions/{sessionId}/move`. On a 409 (the
 * plan was rebuilt, or the session is already done) the week is refetched,
 * so the screen shows the truth rather than a stale row.
 */
export function useMoveStudyPlanSession(): UseMutationResult<
  StudyPlanSessionDTO,
  Error,
  { sessionId: string; subjectCode: string; date: string }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ sessionId, date }) =>
      request<StudyPlanSessionDTO>(`/student/study-plan/sessions/${sessionId}/move`, {
        method: "POST",
        body: JSON.stringify({ date } satisfies MoveSessionRequest),
      }),
    onSuccess: (session, { subjectCode }) => {
      queryClient.setQueryData<StudyPlanOverviewDTO>(studyPlanKeys.week, (o) => patchOverviewSession(o, session))
      queryClient.setQueryData<CurrentStudyPlanDTO>(studyPlanKeys.current(subjectCode), (c) =>
        patchCurrentSession(c, session),
      )
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        return queryClient.invalidateQueries({ queryKey: studyPlanKeys.week })
      }
      return undefined
    },
  })
}
