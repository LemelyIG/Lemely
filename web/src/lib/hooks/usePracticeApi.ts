import { useMutation, useQuery, type UseMutationResult, type UseQueryResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import type {
  CreatePracticeResponse,
  PracticeExport,
  PracticeFilterSet,
  PracticePreview,
  PracticeResult,
  PracticeTopics,
} from "@/lib/practiceTypes"

/*
 * React-query hooks for `/api/student/practice/*` (S-20/S-21), following
 * `usePlacementApi.ts`'s conventions exactly: one hook per endpoint, no
 * `fallback` passed to `request()` — a real backend/auth failure surfaces as
 * a query/mutation error the screen renders, never silently resolves to
 * empty data.
 */

/** Query params are snake_case on the wire (the router's own docstring:
 * FastAPI's bare `list[str] | None` param silently drops repeated query
 * values on this version — `topics`/`difficultyBands` must be repeated with
 * `URLSearchParams.append`, mirroring `useQuizPoolCount`'s identical
 * workaround). Only the JSON body/response DTOs are camelCase. */
function previewQuery(filters: PracticeFilterSet): URLSearchParams {
  const query = new URLSearchParams()
  query.set("count", String(filters.count))
  if (filters.weakTopicsOnly) query.set("weak_topics_only", "true")
  if (filters.source) query.set("source", filters.source)
  for (const topic of filters.topics) query.append("topics", topic)
  for (const band of filters.difficultyBands) query.append("difficulty_bands", band)
  return query
}

/** `GET /api/student/practice/{subjectCode}/preview` — S-20's live match
 * count for the current filter set. Re-fetches whenever any filter changes
 * (the query key is the whole filter set), so the panel always reflects
 * what "Create" would actually do — no write happens here. */
export function usePracticePreview(filters: PracticeFilterSet): UseQueryResult<PracticePreview, Error> {
  const query = previewQuery(filters)
  return useQuery({
    queryKey: [
      "practice",
      "preview",
      filters.subjectCode,
      filters.count,
      [...filters.topics].sort(),
      filters.weakTopicsOnly,
      [...filters.difficultyBands].sort(),
      filters.source ?? null,
    ],
    queryFn: () => request<PracticePreview>(`/student/practice/${filters.subjectCode}/preview?${query.toString()}`),
    enabled: !!filters.subjectCode && filters.count > 0,
  })
}

/** `GET /api/student/practice/{subjectCode}/topics` — S-20's topic-selection
 * control: real, servable topics with real counts, nested by
 * `syllabusGroup`, plus the caller's own weak topics to prefill from. */
export function usePracticeTopics(subjectCode: string): UseQueryResult<PracticeTopics, Error> {
  return useQuery({
    queryKey: ["practice", "topics", subjectCode],
    queryFn: () => request<PracticeTopics>(`/student/practice/${subjectCode}/topics`),
    enabled: !!subjectCode,
  })
}

/**
 * `POST /api/student/practice`. A 409 (the pool is genuinely empty for this
 * filter set, or `weakTopicsOnly` was requested with no weaknesses
 * recorded) throws `ApiError` whose `.detail` carries the identical
 * `PracticePreview` shape the preview query already knows how to render —
 * the caller re-shows that panel instead of a generic failure, mirroring
 * `useCreatePlacement`.
 */
export function useCreatePractice(): UseMutationResult<CreatePracticeResponse, Error, PracticeFilterSet> {
  return useMutation({
    mutationFn: (body: PracticeFilterSet) =>
      request<CreatePracticeResponse>("/student/practice", {
        method: "POST",
        body: JSON.stringify({
          subjectCode: body.subjectCode,
          count: body.count,
          topics: body.topics,
          weakTopicsOnly: body.weakTopicsOnly,
          difficultyBands: body.difficultyBands,
          source: body.source,
        } satisfies PracticeFilterSet),
      }),
  })
}

/** `GET /api/student/practice/{assignmentId}/export` — S-21's answer-free
 * print/export payload. */
export function usePracticeExport(assignmentId: string): UseQueryResult<PracticeExport, Error> {
  return useQuery({
    queryKey: ["practice", "export", assignmentId],
    queryFn: () => request<PracticeExport>(`/student/practice/${assignmentId}/export`),
    enabled: !!assignmentId,
  })
}

/** `GET /api/student/practice/{assignmentId}/result` — S-21's poll target.
 * Marking runs in the background after submit, exactly as placement's
 * does — while `marked: false`, this polls rather than making the student
 * manually refresh, stopping the moment `marked` flips true
 * (`usePlacementResult`'s identical contract). */
export function usePracticeResult(assignmentId: string): UseQueryResult<PracticeResult, Error> {
  return useQuery({
    queryKey: ["practice", "result", assignmentId],
    queryFn: () => request<PracticeResult>(`/student/practice/${assignmentId}/result`),
    enabled: !!assignmentId,
    refetchInterval: (query) => (query.state.data?.marked === false ? 4000 : false),
  })
}
