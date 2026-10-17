import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import type {
  CreatePlacementRequest,
  CreatePlacementResponse,
  PlacementAvailability,
  PlacementResult,
  SaveAnswerRequest,
  SaveAnswerResponse,
  StudentQuizTake,
  SubmitQuizResponse,
} from "@/lib/placementTypes"

/*
 * React-query hooks for `/api/student/placement/*` (S-03/S-05) and the
 * `/api/student/quizzes/{assignmentId}/...` take/save/submit routes S-04
 * reuses verbatim (D4.6 §4). Follows useMeApi.ts's conventions: one hook per
 * endpoint, no `fallback` passed to `request()` — a real backend/auth
 * failure surfaces as a query/mutation error the screen renders, never
 * silently resolves to empty data.
 */

// ── `/api/student/placement/*` ──────────────────────────────────────────

export function usePlacementAvailability(
  subjectCode: string,
): UseQueryResult<PlacementAvailability, Error> {
  return useQuery({
    queryKey: ["placement", "availability", subjectCode],
    queryFn: () =>
      request<PlacementAvailability>(`/student/placement/${subjectCode}/availability`),
    enabled: !!subjectCode,
  })
}

/**
 * Availability for several subjects at once, one query per subject, sharing
 * the exact cache key `usePlacementAvailability` uses — so this and any
 * per-subject row reading the same code hit one cached fetch, not two.
 *
 * The onboarding placement-choice step (`QuestionnaireStep.tsx`,
 * `onboardingData.ts`'s `firstAvailablePlacementSubject`) needs this: when
 * the student skips the choice, the routing decision must prefer an
 * enrolled subject that actually has placement questions, and that means
 * knowing every enrolled subject's availability, not just the one the
 * student happened to look at.
 *
 * `useQueries` (not a `.map()` of `useQuery` calls, and not `useQuery`
 * inside a loop) is the react-query-blessed way to run a *dynamic-length*
 * list of queries from one hook call — the list of enrolled subjects can
 * change in length between renders, which would break the Rules of Hooks
 * if each query were its own `useQuery`. This is one hook call regardless
 * of how many `subjectCodes` are passed.
 */
export function usePlacementAvailabilities(
  subjectCodes: readonly string[],
): UseQueryResult<PlacementAvailability, Error>[] {
  return useQueries({
    queries: subjectCodes.map((subjectCode) => ({
      queryKey: ["placement", "availability", subjectCode],
      queryFn: () =>
        request<PlacementAvailability>(`/student/placement/${subjectCode}/availability`),
      enabled: !!subjectCode,
    })),
  })
}

/**
 * `POST /api/student/placement`. A 409 (assembly not viable — a race with
 * `usePlacementAvailability`'s snapshot, e.g. the pool was exhausted by a
 * concurrent placement between load and click) throws `ApiError` whose
 * `.detail` carries the identical `PlacementAvailabilityDTO` shape S-03
 * already knows how to render — the caller re-shows that panel instead of a
 * generic failure. Invalidates the availability query on success so a
 * re-visit of S-03 for this subject reflects the new state.
 */
export function useCreatePlacement(): UseMutationResult<
  CreatePlacementResponse,
  Error,
  CreatePlacementRequest
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CreatePlacementRequest) =>
      request<CreatePlacementResponse>("/student/placement", {
        method: "POST",
        body: JSON.stringify(body satisfies CreatePlacementRequest),
      }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["placement", "availability", variables.subjectCode],
      })
    },
  })
}

export function usePlacementResult(
  assignmentId: string,
): UseQueryResult<PlacementResult, Error> {
  return useQuery({
    queryKey: ["placement", "result", assignmentId],
    queryFn: () => request<PlacementResult>(`/student/placement/${assignmentId}/result`),
    enabled: !!assignmentId,
    // Marking runs in the background after submit (`docs/quiz-model.md`
    // §4.2) — while `marked: false`, S-05 polls rather than making the
    // student manually refresh to find out their own result finished.
    // Stops the moment `marked` flips true.
    refetchInterval: (query) => (query.state.data?.marked === false ? 4000 : false),
  })
}

// ── `/api/student/quizzes/{assignmentId}/...` (reused verbatim by placement) ─

export function useStudentQuizTake(
  assignmentId: string,
): UseQueryResult<StudentQuizTake, Error> {
  return useQuery({
    queryKey: ["student", "quiz-take", assignmentId],
    queryFn: () => request<StudentQuizTake>(`/student/quizzes/${assignmentId}`),
    enabled: !!assignmentId,
  })
}

export function useSaveQuizAnswer(
  assignmentId: string,
): UseMutationResult<SaveAnswerResponse, Error, { questionRef: string; body: SaveAnswerRequest }> {
  return useMutation({
    mutationFn: ({ questionRef, body }) =>
      request<SaveAnswerResponse>(
        `/student/quizzes/${assignmentId}/answers/${questionRef}`,
        { method: "PUT", body: JSON.stringify(body satisfies SaveAnswerRequest) },
      ),
  })
}

export function useSubmitQuiz(
  assignmentId: string,
): UseMutationResult<SubmitQuizResponse, Error, void> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      request<SubmitQuizResponse>(`/student/quizzes/${assignmentId}/submit`, {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["student", "quiz-take", assignmentId] })
    },
  })
}
