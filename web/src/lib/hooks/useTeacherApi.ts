import { useMutation, useQuery, type UseMutationResult, type UseQueryResult } from "@tanstack/react-query"
import { request, streamActivity } from "@/lib/api"
import type {
  GradingQueue,
  Overview,
  PaperDetail,
  PaperList,
  SchemeList,
  SchemeRow,
  TeacherPipelineFrame,
  UploadResponse,
} from "@/lib/teacherTypes"

/*
 * React-query hooks + plain async helpers wrapping the teacher-portal
 * grading-console API (`lemely/web/routers/teacher.py`). Follows
 * `useStudentApi.ts`'s conventions: one hook per endpoint, no `fallback`
 * passed to `request()` — a real backend/auth failure must surface as a
 * query/mutation error the screen can render, never silently resolve to
 * empty data.
 *
 * Scope: only the 7 endpoints wired in this step (overview, papers
 * list/detail, grading queue, schemes list/upload, paper
 * upload/extract/grade). Classes and AI-quiz endpoints
 * (`/teacher/classes`, `/classes/{id}`, `/quizzes/*`) are out of scope.
 */

export function useTeacherOverview(): UseQueryResult<Overview, Error> {
  return useQuery({
    queryKey: ["teacher", "overview"],
    queryFn: () => request<Overview>("/teacher/overview"),
  })
}

export function usePapers(): UseQueryResult<PaperList, Error> {
  return useQuery({
    queryKey: ["teacher", "papers"],
    queryFn: () => request<PaperList>("/papers"),
  })
}

/**
 * `GET /papers/{paperId}` returns HTTP 409 (not 404) when the paper exists
 * but hasn't been graded yet (`get_paper` in `teacher.py` raises
 * `HTTPException(409, ...)` when `entry.report is None`) — that surfaces
 * here as a normal query error; the screen decides how to render it (e.g.
 * "not graded yet" vs. a generic failure state).
 */
export function usePaperDetail(paperId: string | undefined): UseQueryResult<PaperDetail, Error> {
  return useQuery({
    queryKey: ["teacher", "paper", paperId],
    queryFn: () => request<PaperDetail>(`/papers/${paperId}`),
    enabled: !!paperId,
  })
}

export function useGradingQueue(): UseQueryResult<GradingQueue, Error> {
  return useQuery({
    queryKey: ["teacher", "gradingQueue"],
    queryFn: () => request<GradingQueue>("/grading/queue"),
  })
}

export function useSchemes(): UseQueryResult<SchemeList, Error> {
  return useQuery({
    queryKey: ["teacher", "schemes"],
    queryFn: () => request<SchemeList>("/schemes"),
  })
}

/**
 * Upload a scanned paper (+ optional mark scheme) to the grading console. Not
 * a react-query hook — mirrors `uploadScan` in `useStudentApi.ts`: builds
 * multipart `FormData` with the exact field names FastAPI's `upload_paper`
 * expects (`scan`, `mark_scheme` — the Python parameter names). Goes through
 * `request()`, which skips the JSON content-type for a `FormData` body.
 */
export async function uploadPaper(scan: File, markScheme?: File): Promise<UploadResponse> {
  const form = new FormData()
  form.append("scan", scan)
  if (markScheme) form.append("mark_scheme", markScheme)
  return request<UploadResponse>("/papers/upload", {
    method: "POST",
    body: form,
  })
}

/**
 * Stream the answer-extraction step for an uploaded paper. A thin
 * pass-through over `streamActivity` typed to the frame shapes
 * `POST /papers/{id}/extract` actually emits (see `TeacherPipelineFrame` in
 * `lib/teacherTypes.ts`). No request body — unlike the student `/correct`
 * endpoint, `paperId` here is a path param, not a JSON field.
 */
export function extractPaper(paperId: string): AsyncGenerator<TeacherPipelineFrame> {
  return streamActivity(`/papers/${paperId}/extract`, {
    method: "POST",
  }) as AsyncGenerator<TeacherPipelineFrame>
}

/**
 * Stream the grading step for an uploaded paper. A thin pass-through over
 * `streamActivity` typed to the frame shapes `POST /papers/{id}/grade`
 * actually emits (see `TeacherPipelineFrame` in `lib/teacherTypes.ts`). No
 * request body — `paperId` here is a path param, not a JSON field.
 */
export function gradePaper(paperId: string): AsyncGenerator<TeacherPipelineFrame> {
  return streamActivity(`/papers/${paperId}/grade`, {
    method: "POST",
  }) as AsyncGenerator<TeacherPipelineFrame>
}

/**
 * Upload + deterministically parse a CAIE mark-scheme PDF (`POST /schemes`,
 * no Gemini call). Builds multipart `FormData` with the exact field name
 * FastAPI's `upload_scheme` expects (`scheme_pdf`). A parse failure surfaces
 * as a normal mutation error — `upload_scheme` raises a 422 on parse
 * failure, which `request()` already turns into a thrown `ApiError`.
 */
export function useUploadScheme(): UseMutationResult<SchemeRow, Error, File> {
  return useMutation({
    mutationFn: (schemePdf: File) => {
      const form = new FormData()
      form.append("scheme_pdf", schemePdf)
      return request<SchemeRow>("/schemes", {
        method: "POST",
        body: form,
      })
    },
  })
}
