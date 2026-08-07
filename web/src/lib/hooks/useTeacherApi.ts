import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request, streamActivity } from "@/lib/api"
import type {
  AcknowledgeAtRiskRequest,
  AtRiskFlag,
  AtRiskList,
  BulkApproveResponse,
  ClassAnalytics,
  ClassDetail,
  ClassList,
  ClassSummary,
  CreateClassRequest,
  DismissReviewRequest,
  EnrollStudentRequest,
  Overview,
  PaperDetail,
  PaperList,
  ResolveReviewRequest,
  ReviewItemDetail,
  ReviewQueueItem,
  ReviewQueueList,
  RosterEntry,
  SchemeList,
  SchemeRow,
  StudentDetail,
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
 * upload/extract/grade), the P3.7 chunk B class-list surface
 * (`GET /teacher/classes`, `POST/PATCH/DELETE /classes/{id}` — T-01/T-02),
 * chunk c's `GET /classes/{id}` (T-03), `/enroll` + `/students/{id}` (roster
 * mutations), `GET /classes/{id}/analytics` (T-04), and — added chunk d —
 * `GET /teacher/students/{id}` (T-05) and `GET /teacher/at-risk` +
 * POST/DELETE `.../acknowledge[/{reason}]` (T-06). P3.8 chunk b adds
 * `/api/teacher/review/*` (T-07/T-08, `lemely/web/routers/review.py`) and
 * removes `useGradingQueue` (`GET /grading/queue`) — its only consumer was
 * the old mock-era `Review.tsx`, now replaced by the real T-07/T-08 screens;
 * `Grading.tsx` (the P2 console this chunk leaves untouched) never used it.
 * Quiz/announcement endpoints remain a later P3.8 chunk's to add.
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

/** `GET /classes/{classId}` (T-03: mastery/distribution/roster + the header fields). */
export function useClassDetail(classId: string | undefined): UseQueryResult<ClassDetail, Error> {
  return useQuery({
    queryKey: ["teacher", "class", classId],
    queryFn: () => request<ClassDetail>(`/classes/${classId}`),
    enabled: !!classId,
  })
}

/** `GET /classes/{classId}/analytics` (T-04: heatmap/topic weaknesses/trend/etc). */
export function useClassAnalytics(classId: string | undefined): UseQueryResult<ClassAnalytics, Error> {
  return useQuery({
    queryKey: ["teacher", "class", classId, "analytics"],
    queryFn: () => request<ClassAnalytics>(`/classes/${classId}/analytics`),
    enabled: !!classId,
  })
}

/**
 * `POST /classes/{classId}/enroll` — direct-add an existing, seated student
 * (T-03 "Add students"). 409s when the class has no `schoolId` or the
 * student holds no seat there (`ClassHasNoSchoolError`/`StudentNotSeatedError`
 * in `lemely/db/class_repo.py`) — the screen gates the form on `schoolId`
 * being present so it never invites a guaranteed-409 action, but a stale
 * client state can still hit this, so the mutation error still renders.
 * Invalidates both this class's detail and the classes list (student count
 * changed).
 */
export function useEnrollStudent(
  classId: string | undefined,
): UseMutationResult<RosterEntry, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (studentId: string) =>
      request<RosterEntry>(`/classes/${classId}/enroll`, {
        method: "POST",
        body: JSON.stringify({ studentId } satisfies EnrollStudentRequest),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "class", classId] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "classes"] })
    },
  })
}

/**
 * `DELETE /classes/{classId}/students/{studentId}` (T-03 roster removal).
 * Idempotent on the backend; invalidates the same two queries as enroll.
 */
export function useRemoveStudent(
  classId: string | undefined,
): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (studentId: string) =>
      request<void>(`/classes/${classId}/students/${studentId}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "class", classId] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "classes"] })
    },
  })
}

// ── Student detail, teacher view (T-05) ─────────────────────────────────────

/** `GET /teacher/students/{studentId}` (T-05: full student detail). */
export function useStudentDetail(
  studentId: string | undefined,
): UseQueryResult<StudentDetail, Error> {
  return useQuery({
    queryKey: ["teacher", "student", studentId],
    queryFn: () => request<StudentDetail>(`/teacher/students/${studentId}`),
    enabled: !!studentId,
  })
}

// ── At-risk list (T-06) ──────────────────────────────────────────────────────

/**
 * `GET /teacher/at-risk?reason=&acknowledged=` (T-06). Both are server-side
 * filters, never applied client-side against an unfiltered fetch. `reason`
 * is an `AtRiskReason` value; `acknowledged` is D3.5's caller-side filter —
 * omitting it (the default) returns every flag regardless of acknowledged
 * state, because D3.5 is explicit that acknowledged flags are never hidden
 * by default, only on request.
 */
export function useAtRiskList(params?: {
  reason?: string
  acknowledged?: boolean
}): UseQueryResult<AtRiskList, Error> {
  const reason = params?.reason
  const acknowledged = params?.acknowledged
  const query = new URLSearchParams()
  if (reason) query.set("reason", reason)
  if (acknowledged !== undefined) query.set("acknowledged", String(acknowledged))
  const qs = query.toString()
  return useQuery({
    queryKey: ["teacher", "at-risk", reason ?? null, acknowledged ?? null],
    queryFn: () => request<AtRiskList>(`/teacher/at-risk${qs ? `?${qs}` : ""}`),
  })
}

/**
 * `POST /teacher/at-risk/{studentId}/acknowledge` (T-06). Acknowledging is
 * never a dismissal (D3.5): the flag stays in every list that reads it,
 * tagged rather than removed, and a further decline re-raises it
 * unacknowledged. The backend 422s if `reason` isn't currently firing for
 * this student — a real race is possible (the list was fetched, then the
 * evidence changed before the teacher clicked), so callers must render that
 * error, not assume success. Invalidates every surface that renders a flag
 * for this student — T-06's list, T-05's own detail, and T-01's overview all
 * read acknowledged state through the same shared backend helper, so a stale
 * cache on any of them would show three different answers for one flag.
 */
export function useAcknowledgeAtRisk(
  studentId: string,
): UseMutationResult<AtRiskFlag, Error, AcknowledgeAtRiskRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: AcknowledgeAtRiskRequest) =>
      request<AtRiskFlag>(`/teacher/at-risk/${studentId}/acknowledge`, {
        method: "POST",
        body: JSON.stringify(body satisfies AcknowledgeAtRiskRequest),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "at-risk"] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "student", studentId] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "overview"] })
    },
  })
}

/**
 * `DELETE /teacher/at-risk/{studentId}/acknowledge/{reason}` (T-06). Reverts
 * an acknowledgement — idempotent on the backend, so this never itself reads
 * as a mute either direction. Same invalidation set as
 * `useAcknowledgeAtRisk`.
 */
export function useUnacknowledgeAtRisk(
  studentId: string,
): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (reason: string) =>
      request<void>(`/teacher/at-risk/${studentId}/acknowledge/${reason}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "at-risk"] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "student", studentId] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "overview"] })
    },
  })
}

// ── Review queue (T-07 queue list, T-08 remark) ──────────────────────────────

/**
 * `GET /teacher/review?class_id=&reason=&min_age_hours=` (T-07). All three
 * are real server-side filters (`ReviewService.list_queue`) — never applied
 * client-side against an unfiltered fetch. A malformed `classId` 422s on the
 * backend; the screen renders that as a normal query error rather than
 * hiding it.
 */
export function useReviewQueue(params?: {
  classId?: string
  reason?: string
  minAgeHours?: number
}): UseQueryResult<ReviewQueueList, Error> {
  const classId = params?.classId
  const reason = params?.reason
  const minAgeHours = params?.minAgeHours
  const query = new URLSearchParams()
  if (classId) query.set("class_id", classId)
  if (reason) query.set("reason", reason)
  if (minAgeHours !== undefined) query.set("min_age_hours", String(minAgeHours))
  const qs = query.toString()
  return useQuery({
    queryKey: ["teacher", "review", "queue", classId ?? null, reason ?? null, minAgeHours ?? null],
    queryFn: () => request<ReviewQueueList>(`/teacher/review${qs ? `?${qs}` : ""}`),
  })
}

/** `GET /teacher/review/{itemId}` (T-08 full detail). 403 out-of-scope / 404
 * unknown / 422 malformed id all surface as a normal query error. */
export function useReviewItem(itemId: string | undefined): UseQueryResult<ReviewItemDetail, Error> {
  return useQuery({
    queryKey: ["teacher", "review", "item", itemId],
    queryFn: () => request<ReviewItemDetail>(`/teacher/review/${itemId}`),
    enabled: !!itemId,
  })
}

/**
 * `POST /teacher/review/bulk-approve` (T-07). Skip-and-report, not
 * all-or-nothing (`BulkApproveResponseDTO`'s own doc) — the caller must
 * render `data.skipped`, never assume every requested id succeeded just
 * because the mutation didn't throw. Bulk-approve never overrides a mark
 * (accept-as-is only), so it cannot change any attempt total/weakness record
 * — invalidating just the review queue itself is enough, unlike `resolve`
 * below.
 */
export function useBulkApproveReview(): UseMutationResult<BulkApproveResponse, Error, string[]> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (itemIds: string[]) =>
      request<BulkApproveResponse>("/teacher/review/bulk-approve", {
        method: "POST",
        body: JSON.stringify({ itemIds }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "review"] })
    },
  })
}

/**
 * `POST /teacher/review/{itemId}/resolve` (T-08: accept as-is, or override
 * with a marks/breakdown/note). An override recomputes the attempt's total
 * and weakness records server-side (`ReviewService.resolve`'s docstring) —
 * everything that reads this student's history downstream (T-03 roster, T-04
 * class analytics/heatmap, T-05 student detail, T-06 at-risk, T-01/T-02
 * class averages) can change, so success invalidates that whole surface, not
 * just the review queue, using the resolved row's own `studentId`/`classId`
 * rather than a value threaded in from the caller.
 */
export function useResolveReviewItem(
  itemId: string | undefined,
): UseMutationResult<ReviewQueueItem, Error, ResolveReviewRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ResolveReviewRequest) =>
      request<ReviewQueueItem>(`/teacher/review/${itemId}/resolve`, {
        method: "POST",
        body: JSON.stringify(body satisfies ResolveReviewRequest),
      }),
    onSuccess: (row) => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "review"] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "student", row.studentId] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "class", row.classId] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "classes"] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "at-risk"] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "overview"] })
    },
  })
}

/**
 * `POST /teacher/review/{itemId}/dismiss` (T-08: dismiss an integrity flag).
 * Never touches the underlying `QuestionResult` (`ReviewService.dismiss`'s
 * docstring) — no attempt total, weakness record, or grade changes, so only
 * the review queue itself needs invalidating, unlike `resolve` above.
 */
export function useDismissReviewItem(
  itemId: string | undefined,
): UseMutationResult<ReviewQueueItem, Error, DismissReviewRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: DismissReviewRequest) =>
      request<ReviewQueueItem>(`/teacher/review/${itemId}/dismiss`, {
        method: "POST",
        body: JSON.stringify(body satisfies DismissReviewRequest),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "review"] })
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
