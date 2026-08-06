import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request, streamActivity } from "@/lib/api"
import type {
  ClassList,
  ClassSummary,
  CreateClassRequest,
  GradingQueue,
  Overview,
  PaperDetail,
  PaperList,
  SchemeList,
  SchemeRow,
  TeacherPipelineFrame,
  UpdateClassRequest,
  UploadResponse,
} from "@/lib/teacherTypes"

/*
 * React-query hooks + plain async helpers wrapping the teacher-portal API
 * (`lemely/web/routers/teacher.py`, `lemely/web/routers/classes.py`). Follows
 * `useStudentApi.ts`'s conventions: one hook per endpoint, no `fallback`
 * passed to `request()` — a real backend/auth failure must surface as a
 * query/mutation error the screen can render, never silently resolve to
 * empty data.
 *
 * Scope: the 7 grading-console endpoints wired in P2.8 (overview, papers
 * list/detail, grading queue, schemes list/upload, paper
 * upload/extract/grade) plus the P3.7 chunk B class-list surface
 * (`GET /teacher/classes`, `POST/PATCH/DELETE /classes/{id}` — T-01/T-02).
 * The class-detail/roster/analytics endpoints (`GET /classes/{id}`,
 * `/roster`, `/analytics`) and AI-quiz endpoints are out of scope — chunks
 * c/d own T-03..T-06.
 */

export function useTeacherOverview(): UseQueryResult<Overview, Error> {
  return useQuery({
    queryKey: ["teacher", "overview"],
    queryFn: () => request<Overview>("/teacher/overview"),
  })
}

// ── Classes (T-01 class cards, T-02 classes list) ───────────────────────────

export function useTeacherClasses(): UseQueryResult<ClassList, Error> {
  return useQuery({
    queryKey: ["teacher", "classes"],
    queryFn: () => request<ClassList>("/teacher/classes"),
  })
}

/** `POST /classes` (T-02 create-class action). Invalidates the classes list. */
export function useCreateClass(): UseMutationResult<ClassSummary, Error, CreateClassRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateClassRequest) =>
      request<ClassSummary>("/classes", {
        method: "POST",
        body: JSON.stringify(body satisfies CreateClassRequest),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "classes"] })
    },
  })
}

/** `PATCH /classes/{classId}` (rename / change subject). Invalidates the classes list. */
export function useUpdateClass(): UseMutationResult<
  ClassSummary,
  Error,
  { classId: string; body: UpdateClassRequest }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ classId, body }) =>
      request<ClassSummary>(`/classes/${classId}`, {
        method: "PATCH",
        body: JSON.stringify(body satisfies UpdateClassRequest),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "classes"] })
    },
  })
}

/** `DELETE /classes/{classId}`. Invalidates the classes list. */
export function useDeleteClass(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (classId: string) =>
      request<void>(`/classes/${classId}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "classes"] })
    },
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
