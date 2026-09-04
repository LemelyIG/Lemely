import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request, streamActivity, uploadWithProgress, type UploadProgress } from "@/lib/api"
import type { LinkedParent, ParentLinkList } from "@/lib/parentTypes"
import type {
  CorrectRequest,
  Overview,
  Result,
  Standings,
  StudentCorrectFrame,
  StudentUploadResponse,
  Subject,
  UploadRun,
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

/*
 * `useStudyPlan`/`usePostStudyPlan` lived here and are gone as of P4.10 chunk
 * C. They wrapped the legacy `GET`/`POST /api/student/plan` pair, which
 * rebuilt a plan from scratch on every request and never persisted it — so a
 * plan could not be completed, regenerated, or compared against last week.
 * P4.10 chunk A rewrote S-24 onto the real, persisted
 * `/api/student/study-plan` backend (`lib/hooks/useStudyPlanApi.ts`), leaving
 * these two with no caller at all.
 *
 * The backend routes themselves were removed separately in chunk D (D4.22),
 * deliberately not inside chunk C, so that a gate failure there stayed
 * attributable to the frontend diff.
 */

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
 * names). Goes through `uploadWithProgress()` (PR 4 of the loading/error
 * programme), not `request()` — `fetch` cannot report upload progress, and a
 * phone photo of a paper can be several megabytes on a bad connection, so
 * `CorrectPaper` needs `onProgress` to show the transfer moving instead of
 * sitting on "Marking…" with nothing on screen changing until it lands.
 * `uploadWithProgress` reproduces every other behaviour `request()` has —
 * auth header, pre-emptive refresh, one-shot 401 replay, `detail`
 * extraction, `Retry-After` — see its own doc comment in `lib/api.ts`.
 */
export async function uploadScan(
  scan: File,
  markScheme?: File,
  options?: { onProgress?: (progress: UploadProgress) => void; signal?: AbortSignal },
): Promise<StudentUploadResponse> {
  const form = new FormData()
  form.append("scan", scan)
  if (markScheme) form.append("mark_scheme", markScheme)
  return uploadWithProgress<StudentUploadResponse>("/student/uploads", form, options)
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

/*
 * ── Recovering a run that outlived the tab (P6.2, audit M4) ─────────────────
 *
 * `POST /student/correct` marks on a background thread that does not stop when
 * the client disconnects, so a reload, a backgrounded tab, or a dropped signal
 * loses the *reporting* on a run, never the run. These two hooks are how the
 * screen finds it again.
 *
 * They are deliberately not one hook. `/uploads/active` stops naming a paper
 * the instant it reaches a terminal status, so a client polling only that would
 * watch its run vanish and never learn whether it was marked or failed.
 * Discovery and polling are different questions and end differently.
 */

/**
 * How often a recovered run is re-checked.
 *
 * Four seconds, not the sub-second cadence the SSE stream had. This is a
 * fallback readout for a reader who has already lost the live one, a full mark
 * takes minutes, and every poll is a request from a phone that may be on a bad
 * connection — the thing this path exists to survive. Faster polling would buy
 * a few seconds of latency on the result at the cost of the case it is for.
 */
const RUN_POLL_MS = 4000

/** Statuses that mean the run is over, whichever way it went. */
const TERMINAL: ReadonlySet<string> = new Set(["complete", "failed"])

/**
 * `GET /student/uploads/active` — this student's run in flight, or `null`.
 *
 * `null` is the ordinary answer and not an error state: most of the time
 * nothing is being marked. Runs once on mount rather than polling, because its
 * only job is discovery; once it has named a paper, `useUploadRun` follows it.
 */
export function useActiveUpload(): UseQueryResult<UploadRun | null, Error> {
  return useQuery({
    queryKey: ["student", "upload", "active"],
    queryFn: () => request<UploadRun | null>("/student/uploads/active"),
    // A run recovered from the server is stale the moment it is read, but
    // refetching it on every window focus would fight the poll below for the
    // same answer. The poll is the live one.
    staleTime: RUN_POLL_MS,
  })
}

/**
 * `GET /student/uploads/{paperId}`, polling until the run reaches a terminal
 * status and then stopping.
 *
 * `enabled` is what keeps this from running on the ordinary path: the screen
 * passes an id only when it has recovered a run it was not itself streaming.
 */
export function useUploadRun(paperId: string | undefined): UseQueryResult<UploadRun, Error> {
  return useQuery({
    queryKey: ["student", "upload", paperId],
    queryFn: () => request<UploadRun>(`/student/uploads/${paperId}`),
    enabled: !!paperId,
    refetchInterval: (query) =>
      query.state.data && TERMINAL.has(query.state.data.status) ? false : RUN_POLL_MS,
  })
}
