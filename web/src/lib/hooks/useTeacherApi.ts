import { useEffect, useState } from "react"
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { fetchBlobUrl, request, streamActivity } from "@/lib/api"
import type {
  AcknowledgeAtRiskRequest,
  AnnouncementCreateRequest,
  AnnouncementCreateResponse,
  AnnouncementList,
  AtRiskFlag,
  AtRiskList,
  BulkApproveResponse,
  ClassAnalytics,
  ClassDetail,
  ClassList,
  ClassSummary,
  CreateClassRequest,
  CreateQuizAssignmentRequest,
  CreateQuizRequest,
  DismissReviewRequest,
  EnrollStudentRequest,
  GenerateQuizQuestionsResponse,
  Overview,
  PaperDetail,
  PaperKind,
  PaperList,
  QuizAssignment,
  QuizAssignmentList,
  QuizAssignmentResults,
  QuizDetail,
  QuizList,
  QuizPoolCount,
  QuizSummary,
  ResolveReviewRequest,
  ReviewItemDetail,
  ReviewQueueItem,
  ReviewQueueList,
  RosterEntry,
  SchemeList,
  SchemeRow,
  SetQuizStatusRequest,
  StudentDetail,
  TeacherPipelineFrame,
  UpdateClassRequest,
  UpdateQuizDraftRequest,
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
 * P3.8 chunk c adds `/api/teacher/quizzes/*` (T-09,
 * `lemely/web/routers/quiz.py`'s `router`, not `student_router` — the
 * student quiz-taking endpoints have no teacher-side consumer). Every quiz
 * mutation invalidates both this quiz's own detail query and the quizzes
 * list, matching the fan-out `useResolveReviewItem` already established for
 * "a write here can change what several other queries show". Announcement
 * endpoints remain a later P3.8 chunk's to add.
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

// ── Quiz builder (T-09) ──────────────────────────────────────────────────

/** `GET /teacher/quizzes` (the quiz-list screen). Owned quizzes, newest first. */
export function useTeacherQuizzes(): UseQueryResult<QuizList, Error> {
  return useQuery({
    queryKey: ["teacher", "quizzes"],
    queryFn: () => request<QuizList>("/teacher/quizzes"),
  })
}

/** `POST /teacher/quizzes` (step 1, collected on the quiz-list screen's
 * "New quiz" form — see `CreateQuizRequest`'s doc for why `subjectCode`
 * lives here and nowhere else). Invalidates the quizzes list. */
export function useCreateQuiz(): UseMutationResult<QuizSummary, Error, CreateQuizRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateQuizRequest) =>
      request<QuizSummary>("/teacher/quizzes", {
        method: "POST",
        body: JSON.stringify(body satisfies CreateQuizRequest),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "quizzes"] })
    },
  })
}

/** `GET /teacher/quizzes/{quizId}` — the builder's single fetch (quiz +
 * every materialized question, included and removed). */
export function useQuizDetail(quizId: string | undefined): UseQueryResult<QuizDetail, Error> {
  return useQuery({
    queryKey: ["teacher", "quiz", quizId],
    queryFn: () => request<QuizDetail>(`/teacher/quizzes/${quizId}`),
    enabled: !!quizId,
  })
}

/**
 * `GET /teacher/quizzes/pool-count` (T-09 steps 3/4's live count). Query
 * params are real **snake_case** on the wire (`subject_code`,
 * `requested_count`, `target_grade`, `topics`, `source`) — not a typo to
 * "fix" to camelCase. `topics` is repeated once per value
 * (`URLSearchParams.append`), matching FastAPI's `list[str] | None` param.
 * Step 3 calls this with only `subjectCode`/`targetGrade` set (to read
 * `byBand`, which depends on nothing else) using whatever `requestedCount`
 * the quiz already has (0 before step 4 is ever visited — `allocate_difficulty`
 * defines an all-zero mix for a non-positive count, which the screen must
 * label as "choose a question count in the next step", not render as a
 * shortfall). Step 4 calls it again with `source` set for the real
 * `matching` count.
 */
export function useQuizPoolCount(params: {
  subjectCode: string | undefined
  requestedCount: number
  targetGrade?: string | null
  topics?: string[]
  source?: string | null
}): UseQueryResult<QuizPoolCount, Error> {
  const { subjectCode, requestedCount, targetGrade, topics, source } = params
  const topicsKey = topics && topics.length > 0 ? topics.join("") : null
  const query = new URLSearchParams()
  if (subjectCode) query.set("subject_code", subjectCode)
  query.set("requested_count", String(requestedCount))
  if (targetGrade) query.set("target_grade", targetGrade)
  if (source) query.set("source", source)
  for (const topic of topics ?? []) query.append("topics", topic)
  return useQuery({
    queryKey: [
      "teacher",
      "quiz-pool-count",
      subjectCode ?? null,
      requestedCount,
      targetGrade ?? null,
      topicsKey,
      source ?? null,
    ],
    queryFn: () => request<QuizPoolCount>(`/teacher/quizzes/pool-count?${query.toString()}`),
    enabled: !!subjectCode,
  })
}

/**
 * `PATCH /teacher/quizzes/{quizId}` (steps 1-4's "Save & continue", and
 * every step-navigation click — see `QuizBuilder.tsx`'s module doc for why
 * every navigation carries a `builderStep` PATCH). 422 when the quiz is not
 * a draft; the screen must never fire this for a non-draft quiz. Invalidates
 * this quiz's detail and the quizzes list (title/status/counts shown there
 * can all change).
 */
export function usePatchQuizDraft(
  quizId: string | undefined,
): UseMutationResult<QuizSummary, Error, UpdateQuizDraftRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateQuizDraftRequest) =>
      request<QuizSummary>(`/teacher/quizzes/${quizId}`, {
        method: "PATCH",
        body: JSON.stringify(body satisfies UpdateQuizDraftRequest),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "quiz", quizId] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "quizzes"] })
    },
  })
}

/** `POST /teacher/quizzes/{quizId}/status` — closing/archiving only (never
 * draft->assigned, which `useCreateQuizAssignment` already does server-side).
 * Consumed by T-10's results screen (`QuizResults.tsx`), deliberately not by
 * T-09's builder: closing is a decision a teacher makes once they can see the
 * class has finished, which is information only the results screen has. Same
 * invalidation as `usePatchQuizDraft`. */
export function useSetQuizStatus(
  quizId: string | undefined,
): UseMutationResult<QuizSummary, Error, SetQuizStatusRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: SetQuizStatusRequest) =>
      request<QuizSummary>(`/teacher/quizzes/${quizId}/status`, {
        method: "POST",
        body: JSON.stringify(body satisfies SetQuizStatusRequest),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "quiz", quizId] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "quizzes"] })
    },
  })
}

/** `POST /teacher/quizzes/{quizId}/questions/generate` (step 5). Additive —
 * `data.created` may be `[]` when the quiz already has its requested count;
 * `data.shortfall` must render verbatim, same honesty rule as pool-count.
 * Invalidates this quiz's detail (question list/count changed) and the
 * quizzes list (`questionCount` shown there). */
export function useGenerateQuizQuestions(
  quizId: string | undefined,
): UseMutationResult<GenerateQuizQuestionsResponse, Error, void> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      request<GenerateQuizQuestionsResponse>(`/teacher/quizzes/${quizId}/questions/generate`, {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "quiz", quizId] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "quizzes"] })
    },
  })
}

/** `DELETE /teacher/quizzes/{quizId}/questions/{questionRef}` (step 5's
 * per-question remove). Curates the question out (`status="removed"`) —
 * never deletes the row. Same invalidation as `useGenerateQuizQuestions`. */
export function useRemoveQuizQuestion(
  quizId: string | undefined,
): UseMutationResult<QuizSummary, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (questionRef: string) =>
      request<QuizSummary>(`/teacher/quizzes/${quizId}/questions/${questionRef}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "quiz", quizId] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "quizzes"] })
    },
  })
}

/** `GET /teacher/quizzes/{quizId}/assignments` (step 6's list — also what a
 * non-draft quiz renders read-only). `rosterSize`/`submissionCounts` are
 * live, never a frozen snapshot. */
export function useQuizAssignments(
  quizId: string | undefined,
): UseQueryResult<QuizAssignmentList, Error> {
  return useQuery({
    queryKey: ["teacher", "quiz", quizId, "assignments"],
    queryFn: () => request<QuizAssignmentList>(`/teacher/quizzes/${quizId}/assignments`),
    enabled: !!quizId,
  })
}

/**
 * `POST /teacher/quizzes/{quizId}/assignments` (step 6). **Already
 * transitions a `draft` quiz to `assigned` server-side** — the caller must
 * never also call `useSetQuizStatus` after this succeeds. 422s (rendered via
 * the mutation's own error, never pre-empted by a client-side guess beyond
 * "does this quiz have any included questions yet") cover: zero included
 * questions, `closesAt` earlier than `dueAt`, or the same class twice.
 * Invalidates this quiz's assignments and detail (status/questionCount can
 * change) and the quizzes list.
 */
export function useCreateQuizAssignment(
  quizId: string | undefined,
): UseMutationResult<QuizAssignment, Error, CreateQuizAssignmentRequest> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateQuizAssignmentRequest) =>
      request<QuizAssignment>(`/teacher/quizzes/${quizId}/assignments`, {
        method: "POST",
        body: JSON.stringify(body satisfies CreateQuizAssignmentRequest),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "quiz", quizId, "assignments"] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "quiz", quizId] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "quizzes"] })
    },
  })
}

/** `DELETE /teacher/quizzes/{quizId}/assignments/{assignmentId}` (step 6's
 * "Remove" — undoing an accidental assignment). Refused (422) once any
 * student has a submission beyond `not_started`; that error must render,
 * never be assumed to always succeed (mirrors `useRemoveStudent`'s
 * disposition — attempt, then surface a real backend refusal). Has no quiz
 * draft/status gate of its own, so this stays offered even once the quiz is
 * `assigned` — only the submission state can refuse it. Invalidates this
 * quiz's assignments list. */
export function useDeleteQuizAssignment(
  quizId: string | undefined,
): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (assignmentId: string) =>
      request<void>(`/teacher/quizzes/${quizId}/assignments/${assignmentId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "quiz", quizId, "assignments"] })
    },
  })
}

/**
 * `GET /teacher/quizzes/{quizId}/assignments/{assignmentId}/results` (T-10).
 *
 * **Per assignment, never per quiz** (§1.6) — a quiz assigned to two classes
 * has two sets of results and averaging them would describe neither cohort.
 * Every panel in the response is a projection over one server-side load, so
 * the screen renders them as given and never re-derives one from another.
 */
export function useQuizResults(
  quizId: string | undefined,
  assignmentId: string | undefined,
): UseQueryResult<QuizAssignmentResults, Error> {
  return useQuery({
    queryKey: ["teacher", "quiz", quizId, "assignments", assignmentId, "results"],
    queryFn: () =>
      request<QuizAssignmentResults>(
        `/teacher/quizzes/${quizId}/assignments/${assignmentId}/results`,
      ),
    enabled: !!quizId && !!assignmentId,
  })
}

/** `GET /teacher/announcements` (T-12) — author-scoped, newest first. */
export function useAnnouncements(): UseQueryResult<AnnouncementList, Error> {
  return useQuery({
    queryKey: ["teacher", "announcements"],
    queryFn: () => request<AnnouncementList>("/teacher/announcements"),
  })
}

/**
 * `POST /teacher/announcements` (T-12). Fan-out is **all-or-nothing** — a
 * teacher owning 9 of 10 targeted classes gets a 403 and zero rows — so the
 * composer surfaces the error rather than reporting a partial send. Sending
 * both `classIds` and `schoolWide` is a 422 by design (the audiences overlap);
 * the composer's audience control is exclusive so that state is unreachable.
 */
export function useCreateAnnouncement(): UseMutationResult<
  AnnouncementCreateResponse,
  Error,
  AnnouncementCreateRequest
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: AnnouncementCreateRequest) =>
      request<AnnouncementCreateResponse>("/teacher/announcements", {
        method: "POST",
        body: JSON.stringify(body satisfies AnnouncementCreateRequest),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "announcements"] })
    },
  })
}

/** `DELETE /teacher/announcements/{announcementId}` (T-12) — 204, so
 * `request()` must not try to parse a body (fixed in P3.7 chunk b). */
export function useDeleteAnnouncement(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (announcementId: string) =>
      request<void>(`/teacher/announcements/${announcementId}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "announcements"] })
    },
  })
}

/** Paper states the backend is still working on, so the client should re-ask. */
const IN_FLIGHT: ReadonlySet<PaperKind> = new Set<PaperKind>(["queued", "processing"])

/** How often to re-ask while a grading run is in flight. */
const PAPER_POLL_MS = 2000

/**
 * `GET /papers`, polling while any paper is still queued or being marked.
 *
 * Marking runs server-side now (D6.13), so the grid is the authority on how far
 * it has got — but only if it actually re-asks. Without this, a teacher who
 * reloaded the page mid-run saw a "Queued" card that never changed no matter how
 * long they waited, because nothing on the screen was fetching any more. The
 * interval stops the moment every paper reaches a terminal state, so an idle
 * console makes no requests at all.
 */
export function usePapers(): UseQueryResult<PaperList, Error> {
  return useQuery({
    queryKey: ["teacher", "papers"],
    queryFn: () => request<PaperList>("/papers"),
    refetchInterval: (query) =>
      query.state.data?.papers.some((p) => IN_FLIGHT.has(p.kind)) ? PAPER_POLL_MS : false,
  })
}

/**
 * `GET /papers/{paperId}`, polling while that paper is still being worked on.
 *
 * Answers for ungraded papers too — it carries the live pipeline and (once
 * detection lands) the detected fields, with `awardedMarks`/`maxMarks` null
 * until there are real marks. It used to 409 until a report existed, which is
 * why the Pipeline panel went blank on a mid-run refresh.
 */
export function usePaperDetail(paperId: string | undefined): UseQueryResult<PaperDetail, Error> {
  return useQuery({
    queryKey: ["teacher", "paper", paperId],
    queryFn: () => request<PaperDetail>(`/papers/${paperId}`),
    enabled: !!paperId,
    refetchInterval: (query) =>
      query.state.data && IN_FLIGHT.has(query.state.data.kind) ? PAPER_POLL_MS : false,
  })
}

/**
 * Object URL for a paper's scan thumbnail (`GET /papers/{paperId}/preview`),
 * or `null` while it loads and for a scan the server could not render.
 *
 * Fetched as a blob rather than pointed at with `<img src>`: the route is behind
 * the staff guard and `<img>` cannot carry an `Authorization` header, so a plain
 * src would 401 on every card. The alternative — a token in the query string —
 * would put a credential in nginx's access log.
 *
 * Deliberately *not* a react-query hook, unlike everything else in this file. An
 * object URL is a resource with an owner, and the only place that can revoke it
 * at exactly the right moment is the component holding it; parking one in a
 * shared cache means either leaking a blob per card or guessing at eviction. The
 * cost of owning it here is a refetch when a card remounts, which the response's
 * own `Cache-Control: private, max-age=3600` already absorbs — the scan behind a
 * paper id never changes.
 *
 * P6.3: `enabled` is how this hook is made lazy, and it has to live here rather
 * than on the `<img>`. `loading="lazy"` defers a request the *element* makes;
 * this request is made by `fetchBlobUrl` before any element exists, so the
 * attribute would have been a no-op that looked like a fix. The endpoint is a
 * live PyMuPDF render of page 1 of the stored scan, `GET /papers` is
 * unpaginated, and every card mounts one of these — so with `enabled` defaulting
 * to true the console re-rendered every scan the school has ever uploaded on
 * every visit, to fill a 64px strip most readers never scroll to. See
 * `useInViewOnce`, which is what the one call site passes in.
 */
export function useScanPreview(paperId: string, enabled = true): string | null {
  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    let objectUrl: string | null = null

    fetchBlobUrl(`/papers/${paperId}/preview`)
      .then((fetched) => {
        if (cancelled) {
          // Unmounted (or the id changed) while in flight — nothing will ever
          // render this one, so release it instead of stranding it.
          URL.revokeObjectURL(fetched)
          return
        }
        objectUrl = fetched
        setUrl(fetched)
      })
      .catch(() => {
        // A scan that cannot be rendered leaves the card's thumbnail empty,
        // which is what it looked like before previews existed. Not worth an
        // error state of its own on a grid of cards.
        if (!cancelled) setUrl(null)
      })

    return () => {
      cancelled = true
      if (objectUrl !== null) URL.revokeObjectURL(objectUrl)
    }
  }, [paperId, enabled])

  return url
}

export function useSchemes(): UseQueryResult<SchemeList, Error> {
  return useQuery({
    queryKey: ["teacher", "schemes"],
    queryFn: () => request<SchemeList>("/schemes"),
  })
}

/**
 * `POST /papers/{paperId}/regrade` — queue a paper for another marking run.
 *
 * Returns as soon as the run is queued (202); the outcome arrives through
 * `usePapers`/`usePaperDetail` polling, since marking is server-side. The
 * streaming sibling (`gradePaper`) is not used for this: holding a connection
 * open for the minutes a run takes buys nothing when the grid is already
 * watching for the result.
 */
export function useRegradePaper(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (paperId: string) =>
      request<void>(`/papers/${paperId}/regrade`, { method: "POST" }),
    onSuccess: (_data, paperId) => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "papers"] })
      queryClient.invalidateQueries({ queryKey: ["teacher", "paper", paperId] })
    },
  })
}

/**
 * Upload a scanned paper (+ optional mark scheme) to the grading console. Not
 * a react-query hook — mirrors `uploadScan` in `useStudentApi.ts`: builds
 * multipart `FormData` with the exact field names FastAPI's `upload_paper`
 * expects (`scan`, `mark_scheme` — the Python parameter names). Goes through
 * `request()`, which skips the JSON content-type for a `FormData` body.
 *
 * `detected` in the reply is always empty now: metadata detection moved off the
 * upload request and into the background grading job (D6.13), because running
 * it inline blocked the server's event loop for its whole ~60s duration. The
 * detected fields arrive via `usePaperDetail` once the job has produced them.
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
 *
 * **No screen calls this today.** The grading console used to, and driving the
 * run from a browser stream is what let one backend stall leave papers at
 * "Queued" forever with a refresh wiping the only progress readout (D6.13).
 * Marking is now a server-side job, so the console polls `GET /papers/{id}` —
 * which reports the same progress, for every paper, and survives a reload.
 *
 * Kept because the endpoint is real, tested, and the right tool for a
 * per-frame live view (warnings and model-call chatter that the polled
 * pipeline summarises away) if a screen ever wants one. Use `useRegradePaper`
 * to merely *start* a run — it returns immediately instead of holding a
 * connection open for the length of the marking.
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
