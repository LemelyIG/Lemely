import { useMutation, useQuery, type UseMutationResult, type UseQueryResult } from "@tanstack/react-query"
import { request, streamActivity } from "@/lib/api"
import type {
  CorrectRequest,
  OnboardingRequest,
  Overview,
  Result,
  Standings,
  StudentCorrectFrame,
  StudentProfile,
  StudentUploadResponse,
  StudyPlan,
  StudyPlanRequest,
  Subject,
} from "@/lib/studentTypes"

/*
 * React-query hooks + plain async helpers wrapping the student-portal API
 * (`lemely/web/routers/student.py`). Follows AuthContext.tsx's conventions:
 * one hook per endpoint, no `fallback` passed to `request()` — a real
 * backend/auth failure must surface as a query/mutation error the screen can
 * render, never silently resolve to empty data.
 */

export function useOverview(): UseQueryResult<Overview, Error> {
  return useQuery({
    queryKey: ["student", "overview"],
    queryFn: () => request<Overview>("/student/overview"),
  })
}

export function useSubject(code: string): UseQueryResult<Subject, Error> {
  return useQuery({
    queryKey: ["student", "subject", code],
    queryFn: () => request<Subject>(`/student/subject/${code}`),
    enabled: !!code,
  })
}

export function useResult(paperId: string): UseQueryResult<Result, Error> {
  return useQuery({
    queryKey: ["student", "result", paperId],
    queryFn: () => request<Result>(`/student/result/${paperId}`),
    enabled: !!paperId,
  })
}

export function useStudyPlan(): UseQueryResult<StudyPlan, Error> {
  return useQuery({
    queryKey: ["student", "plan"],
    queryFn: () => request<StudyPlan>("/student/plan"),
  })
}

export function usePostStudyPlan(): UseMutationResult<StudyPlan, Error, StudyPlanRequest> {
  return useMutation({
    mutationFn: (body: StudyPlanRequest) =>
      request<StudyPlan>("/student/plan", {
        method: "POST",
        body: JSON.stringify(body satisfies StudyPlanRequest),
      }),
  })
}

export function useStandings(): UseQueryResult<Standings, Error> {
  return useQuery({
    queryKey: ["student", "standings"],
    queryFn: () => request<Standings>("/student/standings"),
  })
}

export function usePostOnboarding(): UseMutationResult<StudentProfile, Error, OnboardingRequest> {
  return useMutation({
    mutationFn: (body: OnboardingRequest) =>
      request<StudentProfile>("/student/onboarding", {
        method: "POST",
        body: JSON.stringify(body satisfies OnboardingRequest),
      }),
  })
}

/**
 * Upload a scanned paper (+ optional mark scheme) for self-marking. Not a
 * react-query hook — `CorrectPaper` calls this directly inside its own flow
 * control (pick file -> upload -> get `paperId` -> `runCorrection`).
 *
 * Builds multipart `FormData` with the exact field names FastAPI's
 * `student_upload` expects (`scan`, `mark_scheme` — the Python parameter
 * names). Goes through `request()`, which now skips the JSON content-type
 * for a `FormData` body (see `lib/api.ts::authHeaders`) so the browser can
 * set its own multipart boundary.
 */
export async function uploadScan(
  scan: File,
  markScheme?: File,
): Promise<StudentUploadResponse> {
  const form = new FormData()
  form.append("scan", scan)
  if (markScheme) form.append("mark_scheme", markScheme)
  return request<StudentUploadResponse>("/student/uploads", {
    method: "POST",
    body: form,
  })
}

/**
 * Stream the self-mark pipeline for an uploaded paper. A thin pass-through
 * over `streamActivity` typed to the frame shapes `POST /student/correct`
 * actually emits (see `StudentCorrectFrame` in `lib/studentTypes.ts`).
 */
export function runCorrection(paperId: string): AsyncGenerator<StudentCorrectFrame> {
  return streamActivity("/student/correct", {
    method: "POST",
    body: JSON.stringify({ paperId } satisfies CorrectRequest),
  }) as AsyncGenerator<StudentCorrectFrame>
}
