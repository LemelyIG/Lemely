import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request, streamActivity } from "@/lib/api"
import type { LinkedParent, ParentLinkList } from "@/lib/parentTypes"
import type {
  CorrectRequest,
  Overview,
  Result,
  Standings,
  StudentCorrectFrame,
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

/*
 * Parent links (D3.11). The student is the initiator on both ends — a link row
 * IS the grant, there is no pending state and no approval step — so all three
 * of these live on the student side. The parent portal has no mutation for
 * them and must not grow one.
 *
 * The DTO mirrors are in `lib/parentTypes.ts` beside the parent-facing ones:
 * these are the two ends of one relationship, not two unrelated features.
 */

export function useParentLinks(): UseQueryResult<ParentLinkList, Error> {
  return useQuery({
    queryKey: ["student", "parent-links"],
    queryFn: () => request<ParentLinkList>("/student/parent-links"),
  })
}

export function useLinkParent(): UseMutationResult<LinkedParent, Error, { phone: string }> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ phone }: { phone: string }) =>
      request<LinkedParent>("/student/parent-links", {
        method: "POST",
        body: JSON.stringify({ phone }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["student", "parent-links"] })
    },
  })
}

export function useUnlinkParent(): UseMutationResult<void, Error, { parentId: string }> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ parentId }: { parentId: string }) =>
      request<void>(`/student/parent-links/${parentId}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["student", "parent-links"] })
    },
  })
}

export function useStandings(): UseQueryResult<Standings, Error> {
  return useQuery({
    queryKey: ["student", "standings"],
    queryFn: () => request<Standings>("/student/standings"),
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
