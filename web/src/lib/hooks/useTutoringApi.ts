import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { ApiError, request } from "@/lib/api"
import { isAccessEnded } from "@/lib/tutoring/apiErrors"
import {
  studentIdOfDetailKey,
  tutoringKeys,
  type AccessLogParams,
  type AdminReportsParams,
  type AdminTutorsParams,
  type BookingsParams,
  type DirectoryParams,
  type ModerationParams,
  type PageParams,
  type PublicDirectoryParams,
  type SlotsParams,
  type TutorBookingsParams,
} from "@/lib/tutoring/queryKeys"
import type {
  AccessLogPage,
  AdminApprove,
  AdminNote,
  AdminReply,
  AdminReview,
  AdminTutorDetail,
  AdminTutorPage,
  AreaList,
  AvailabilityReplace,
  AvailabilityRule,
  Block,
  BlockCreate,
  Blocks,
  Booking,
  BookingAccept,
  BookingCreate,
  BookingReason,
  BookingsPage,
  ClassAccess,
  DirectoryPage,
  Evidence,
  Grant,
  GrantCreate,
  Grants,
  ModerationPage,
  MyReview,
  Note,
  NoteCreate,
  NotesPage,
  Outcomes,
  PublicDirectoryPage,
  PublicTutorCard,
  Reply,
  ReplyCreate,
  ReplyModerate,
  ReportCreate,
  ReportDetail,
  ReportPage,
  ReportReceipt,
  ReportResolve,
  ReviewCreate,
  ReviewModerate,
  ReviewsPage,
  ReviewUpdate,
  Slots,
  TutorOwnProfile,
  TutorPreview,
  TutorProfile,
  TutorProfileCreate,
  TutorProfileUpdate,
  TutorReviewsPage,
  TutorStudentDetail,
  TutorStudentPage,
  TutoringSettings,
  TutoringSettingsUpdate,
} from "@/lib/tutoringTypes"

/*
 * T11 · one react-query hook per tutoring route, 70 in all, in the order of
 * `docs/tutoring/SPEC.md` §b.2: public (P1-P3), logged-in directory and
 * booking request (SP1-SP6), student (S1-S17), tutor (T1-T21), parent
 * (PA1-PA7), safety (R1, B1-B3), platform admin (A1-A12). Types come from
 * `lib/tutoringTypes.ts`; query keys from `lib/tutoring/queryKeys.ts`; the
 * refusal codes a failed call can carry from `lib/tutoring/apiErrors.ts`
 * (`tutoringErrorOf(error)`).
 *
 * Conventions, as in `useParentApi.ts` and `useSchoolApi.ts`: no `fallback`
 * passed to `request()` (a refusal must reach the screen as an error, never
 * as an empty list), one hook per endpoint, and every mutation invalidates the
 * reads its result makes stale.
 *
 * `tests/unit/tutoringQueryKeys.test.ts` reads this file as text and compares
 * it with SPEC §c.1. That is why every hook makes its one API call through the
 * local `call` helper with the method and path as literals, and why a read
 * names its key factory in its first lines. Keep to that shape.
 *
 * ── Lists ────────────────────────────────────────────────────────────────────
 *
 * Cursor-paged lists take `cursor` and `limit` in their params object and
 * return one page with `nextCursor`. A screen that wants "load more" holds the
 * cursor in state and appends pages itself.
 *
 * ── Nothing here is persisted ────────────────────────────────────────────────
 *
 * Every key is under "tutoring", which is not on the persist allowlist
 * (`lib/offline/persistAllowlist.ts`), because every non-public tutoring
 * response is `private, no-store` (SPEC §b.5).
 *
 * ── Reads that are audited are never served from cache ──────────────────────
 *
 * T19 and T20 write a `tutor_access_audit` row on every read, A2 a
 * `tutoring_admin_access` row per signed evidence URL, A10 a `report_thread_view`
 * row. A cached copy shown without a request would be a read nobody logged
 * (and, for A2, a download link that has expired). Those four hooks therefore
 * refetch on every mount, do not refetch on reconnect, and drop their data the
 * moment nothing is showing it (`AUDITED_READ`).
 */

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE"

interface CallOptions {
  /** Query-string parameters; `undefined` and `null` members are left out. */
  query?: object
  /** JSON body. */
  body?: unknown
  /** Multipart body (T6). */
  form?: FormData
}

type QueryScalar = string | number | boolean

/**
 * `?a=1&a=2&b=x` from a params object, or "" when nothing is set. Arrays repeat
 * the name (`mode`, `day` and `timeOfDay` are repeatable, SPEC §b.2); empty
 * values are skipped.
 */
export function tutoringQueryString(query: object | undefined): string {
  const search = new URLSearchParams()
  for (const [name, value] of Object.entries(query ?? {}) as [string, unknown][]) {
    const values = Array.isArray(value) ? (value as unknown[]) : [value]
    for (const item of values) {
      if (item === undefined || item === null || item === "") continue
      search.append(name, String(item as QueryScalar))
    }
  }
  const text = search.toString()
  return text === "" ? "" : `?${text}`
}

function call<T>(method: Method, path: string, options: CallOptions = {}): Promise<T> {
  const url = `${path}${tutoringQueryString(options.query)}`
  if (options.form !== undefined) return request<T>(url, { method, body: options.form })
  if (options.body !== undefined) {
    return request<T>(url, { method, body: JSON.stringify(options.body) })
  }
  return request<T>(url, { method })
}

/**
 * A refusal (4xx) is the server's answer, not a hiccup: asking again gets the
 * same one, and for the audited reads asking again would be a second read.
 * Network failures and 5xx get the client's usual single retry.
 */
function retryUnlessRefused(failureCount: number, error: Error): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
  return failureCount < 1
}

/** See "Reads that are audited" in the header. */
const AUDITED_READ = {
  staleTime: 0,
  gcTime: 0,
  refetchOnMount: "always",
  refetchOnReconnect: false,
} as const

type Keys = readonly (readonly unknown[])[]

function invalidateAll(queryClient: QueryClient, keys: Keys): void {
  for (const queryKey of keys) void queryClient.invalidateQueries({ queryKey })
}

// ── T20: a ended grant drops the cached student detail ──────────────────────

const guardedClients = new WeakSet<QueryClient>()

/**
 * Make a 403 `access_ended` on T20 remove the data the cache holds for that
 * student (SPEC §b.2 T20, SC-11). The grant ended, so the detail the tutor was
 * allowed to see a moment ago may no longer be shown, not even for the instant
 * before a refetch answers.
 *
 * Done by watching the query cache rather than inside the query function, for
 * two reasons: it covers every fetch of that key whoever starts it, and
 * removing a query that a mounted screen is observing makes the observer build
 * a fresh one on its next render and fetch again, which would repeat the 403
 * in a loop. Here the entry stays, in its error state, with its data cleared.
 * The tutor's student list is marked stale too, so the student leaves it.
 *
 * Installed once per client; the first `useTutorStudent` on a client installs it.
 */
export function installAccessEndedGuard(queryClient: QueryClient): void {
  if (guardedClients.has(queryClient)) return
  guardedClients.add(queryClient)
  queryClient.getQueryCache().subscribe((event) => {
    if (event.type !== "updated" || event.action.type !== "error") return
    if (studentIdOfDetailKey(event.query.queryKey) === null) return
    if (!isAccessEnded(event.action.error)) return
    event.query.setState({ data: undefined, dataUpdatedAt: 0 })
    invalidateAll(queryClient, [tutoringKeys.tutorStudentsScope()])
  })
}

// ═════════════════════════════════════════════════════════════════════════════
// Public (P1-P3): no auth, `Cache-Control: public, max-age=60`
// ═════════════════════════════════════════════════════════════════════════════

/** P1 · `GET /api/public/tutors`. `facets` come on the first page only. */
export function usePublicTutors(
  params: PublicDirectoryParams = {},
): UseQueryResult<PublicDirectoryPage, Error> {
  return useQuery({
    queryKey: tutoringKeys.publicTutors(params),
    queryFn: () => call<PublicDirectoryPage>("GET", "/public/tutors", { query: params }),
    retry: retryUnlessRefused,
  })
}

/** P2 · `GET /api/public/tutors/{tutor_id}`. 404 for every tutor that is hidden. */
export function usePublicTutor(tutorId: string): UseQueryResult<PublicTutorCard, Error> {
  return useQuery({
    queryKey: tutoringKeys.publicTutor(tutorId),
    queryFn: () => call<PublicTutorCard>("GET", `/public/tutors/${tutorId}`),
    retry: retryUnlessRefused,
  })
}

/** P3 · `GET /api/public/tutoring-areas`. */
export function usePublicTutoringAreas(): UseQueryResult<AreaList, Error> {
  return useQuery({
    queryKey: tutoringKeys.publicAreas(),
    queryFn: () => call<AreaList>("GET", "/public/tutoring-areas"),
    retry: retryUnlessRefused,
  })
}

// ═════════════════════════════════════════════════════════════════════════════
// Logged-in directory and booking request (SP1-SP6): student or parent
// ═════════════════════════════════════════════════════════════════════════════

/** SP1 · `GET /api/tutors`. P1's filters plus `day` and `timeOfDay`. */
export function useTutorDirectory(
  params: DirectoryParams = {},
): UseQueryResult<DirectoryPage, Error> {
  return useQuery({
    queryKey: tutoringKeys.directoryTutors(params),
    queryFn: () => call<DirectoryPage>("GET", "/tutors", { query: params }),
    retry: retryUnlessRefused,
  })
}

/** SP2 · `GET /api/tutors/{tutor_id}`. Needs a confirmed email (403 `email_unverified`). */
export function useTutorProfile(tutorId: string): UseQueryResult<TutorProfile, Error> {
  return useQuery({
    queryKey: tutoringKeys.tutorProfile(tutorId),
    queryFn: () => call<TutorProfile>("GET", `/tutors/${tutorId}`),
    retry: retryUnlessRefused,
  })
}

/** SP3 · `GET /api/tutors/{tutor_id}/reviews`. Newest first. */
export function useTutorReviews(
  tutorId: string,
  params: PageParams = {},
): UseQueryResult<ReviewsPage, Error> {
  return useQuery({
    queryKey: tutoringKeys.tutorReviews(tutorId, params),
    queryFn: () => call<ReviewsPage>("GET", `/tutors/${tutorId}/reviews`, { query: params }),
    retry: retryUnlessRefused,
  })
}

/** SP4 · `GET /api/tutors/{tutor_id}/outcomes`. */
export function useTutorOutcomes(tutorId: string): UseQueryResult<Outcomes, Error> {
  return useQuery({
    queryKey: tutoringKeys.tutorOutcomes(tutorId),
    queryFn: () => call<Outcomes>("GET", `/tutors/${tutorId}/outcomes`),
    retry: retryUnlessRefused,
  })
}

/** SP5 · `GET /api/tutors/{tutor_id}/slots`. Times are in the tutor's zone. */
export function useTutorSlots(
  tutorId: string,
  params: SlotsParams,
): UseQueryResult<Slots, Error> {
  return useQuery({
    queryKey: tutoringKeys.tutorSlots(tutorId, params),
    queryFn: () => call<Slots>("GET", `/tutors/${tutorId}/slots`, { query: params }),
    retry: retryUnlessRefused,
  })
}

/**
 * SP6 · `POST /api/bookings`. A parent sends `studentId`; only a student may
 * send `firstNote`. Refreshes the booking lists and that tutor's open slots.
 */
export function useCreateBooking(): UseMutationResult<Booking, Error, BookingCreate> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: BookingCreate) => call<Booking>("POST", "/bookings", { body }),
    onSuccess: (booking) => {
      invalidateAll(queryClient, [
        tutoringKeys.studentBookingsScope(),
        tutoringKeys.parentBookingsScope(booking.student.studentId),
        tutoringKeys.tutorSlotsScope(booking.tutor.tutorId),
      ])
    },
  })
}

// ═════════════════════════════════════════════════════════════════════════════
// Student (S1-S17)
// ═════════════════════════════════════════════════════════════════════════════

/** Variables of every booking action that takes an optional reason. */
export interface BookingActionVariables {
  bookingId: string
  body?: BookingReason
}

/** Variables of every booking action that takes nothing but the booking. */
export interface BookingIdVariables {
  bookingId: string
}

/** S1 · `GET /api/student/bookings`. */
export function useStudentBookings(
  params: BookingsParams,
): UseQueryResult<BookingsPage, Error> {
  return useQuery({
    queryKey: tutoringKeys.studentBookings(params),
    queryFn: () => call<BookingsPage>("GET", "/student/bookings", { query: params }),
    retry: retryUnlessRefused,
  })
}

/** S2 · `GET /api/student/bookings/{booking_id}`. */
export function useStudentBooking(bookingId: string): UseQueryResult<Booking, Error> {
  return useQuery({
    queryKey: tutoringKeys.studentBooking(bookingId),
    queryFn: () => call<Booking>("GET", `/student/bookings/${bookingId}`),
    retry: retryUnlessRefused,
  })
}

/** S3 · `POST /api/student/bookings/{booking_id}/cancel`. */
export function useCancelStudentBooking(): UseMutationResult<
  Booking,
  Error,
  BookingActionVariables
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ bookingId, body }: BookingActionVariables) =>
      call<Booking>("POST", `/student/bookings/${bookingId}/cancel`, { body }),
    onSuccess: (booking) => {
      invalidateAll(queryClient, [
        tutoringKeys.studentBookingsScope(),
        tutoringKeys.tutorSlotsScope(booking.tutor.tutorId),
      ])
    },
  })
}

/** S4 · `GET /api/student/bookings/{booking_id}/notes`. Oldest first. */
export function useStudentBookingNotes(
  bookingId: string,
  params: PageParams = {},
): UseQueryResult<NotesPage, Error> {
  return useQuery({
    queryKey: tutoringKeys.studentBookingNotes(bookingId, params),
    queryFn: () =>
      call<NotesPage>("GET", `/student/bookings/${bookingId}/notes`, { query: params }),
    retry: retryUnlessRefused,
  })
}

/** S5 · `POST /api/student/bookings/{booking_id}/notes`. */
export function usePostStudentBookingNote(): UseMutationResult<
  Note,
  Error,
  { bookingId: string; body: NoteCreate }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ bookingId, body }: { bookingId: string; body: NoteCreate }) =>
      call<Note>("POST", `/student/bookings/${bookingId}/notes`, { body }),
    onSuccess: (_note, { bookingId }) => {
      invalidateAll(queryClient, [tutoringKeys.studentBookingNotesScope(bookingId)])
    },
  })
}

/** S6 · `POST /api/student/bookings/{booking_id}/review`. */
export function useCreateReview(): UseMutationResult<
  MyReview,
  Error,
  { bookingId: string; body: ReviewCreate }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ bookingId, body }: { bookingId: string; body: ReviewCreate }) =>
      call<MyReview>("POST", `/student/bookings/${bookingId}/review`, { body }),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.studentBookingsScope()])
    },
  })
}

/** S7 · `PATCH /api/student/reviews/{review_id}`. */
export function useUpdateReview(): UseMutationResult<
  MyReview,
  Error,
  { reviewId: string; body: ReviewUpdate }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ reviewId, body }: { reviewId: string; body: ReviewUpdate }) =>
      call<MyReview>("PATCH", `/student/reviews/${reviewId}`, { body }),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.studentBookingsScope()])
    },
  })
}

/** S8 · `GET /api/student/tutor-grants`. Live first, then ended. */
export function useStudentTutorGrants(): UseQueryResult<Grants, Error> {
  return useQuery({
    queryKey: tutoringKeys.studentGrants(),
    queryFn: () => call<Grants>("GET", "/student/tutor-grants"),
    retry: retryUnlessRefused,
  })
}

/** S9 · `POST /api/student/tutor-grants`. 201 for a new grant, 200 for the live one. */
export function useCreateTutorGrant(): UseMutationResult<Grant, Error, GrantCreate> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: GrantCreate) => call<Grant>("POST", "/student/tutor-grants", { body }),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.studentGrants()])
    },
  })
}

/** S10 · `POST /api/student/tutor-grants/{grant_id}/revoke`. Idempotent. */
export function useRevokeTutorGrant(): UseMutationResult<
  Grant,
  Error,
  { grantId: string }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ grantId }: { grantId: string }) =>
      call<Grant>("POST", `/student/tutor-grants/${grantId}/revoke`),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.studentGrants()])
    },
  })
}

/** S11 · `GET /api/student/tutor-access-log`. */
export function useStudentTutorAccessLog(
  params: AccessLogParams = {},
): UseQueryResult<AccessLogPage, Error> {
  return useQuery({
    queryKey: tutoringKeys.studentAccessLog(params),
    queryFn: () => call<AccessLogPage>("GET", "/student/tutor-access-log", { query: params }),
    retry: retryUnlessRefused,
  })
}

/** S12 · `GET /api/student/tutoring-settings`. */
export function useStudentTutoringSettings(): UseQueryResult<TutoringSettings, Error> {
  return useQuery({
    queryKey: tutoringKeys.studentSettings(),
    queryFn: () => call<TutoringSettings>("GET", "/student/tutoring-settings"),
    retry: retryUnlessRefused,
  })
}

/** S13 · `PUT /api/student/tutoring-settings`. */
export function useUpdateStudentTutoringSettings(): UseMutationResult<
  TutoringSettings,
  Error,
  TutoringSettingsUpdate
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: TutoringSettingsUpdate) =>
      call<TutoringSettings>("PUT", "/student/tutoring-settings", { body }),
    onSuccess: (settings) => {
      queryClient.setQueryData(tutoringKeys.studentSettings(), settings)
    },
  })
}

/** S14 · `POST /api/student/bookings/{booking_id}/complete`. */
export function useCompleteStudentBooking(): UseMutationResult<
  Booking,
  Error,
  BookingIdVariables
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ bookingId }: BookingIdVariables) =>
      call<Booking>("POST", `/student/bookings/${bookingId}/complete`),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.studentBookingsScope()])
    },
  })
}

/** S15 · `POST /api/student/tutoring-safety-notice`. Idempotent. */
export function useAcknowledgeTutoringSafetyNotice(): UseMutationResult<
  TutoringSettings,
  Error,
  void
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => call<TutoringSettings>("POST", "/student/tutoring-safety-notice"),
    onSuccess: (settings) => {
      queryClient.setQueryData(tutoringKeys.studentSettings(), settings)
    },
  })
}

/** S16 · `GET /api/student/tutor-access/classes`. Classes whose teacher sees your progress. */
export function useStudentTutorAccessClasses(): UseQueryResult<ClassAccess, Error> {
  return useQuery({
    queryKey: tutoringKeys.studentClassAccess(),
    queryFn: () => call<ClassAccess>("GET", "/student/tutor-access/classes"),
    retry: retryUnlessRefused,
  })
}

/**
 * S17 · `DELETE /api/student/classes/{class_id}`. Leaves a class that has no
 * school (204). Also refreshes the student's class list, which lives under the
 * existing `["student", "classes"]` key.
 */
export function useLeaveClass(): UseMutationResult<void, Error, { classId: string }> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ classId }: { classId: string }) =>
      call<void>("DELETE", `/student/classes/${classId}`),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.studentClassAccess(), ["student", "classes"]])
    },
  })
}

// ═════════════════════════════════════════════════════════════════════════════
// Tutor (T1-T21): a teacher who owns a tutor profile
// ═════════════════════════════════════════════════════════════════════════════

/** T1 · `GET /api/tutor/profile`. 404 `no_tutor_profile` until T2 has run. */
export function useOwnTutorProfile(): UseQueryResult<TutorOwnProfile, Error> {
  return useQuery({
    queryKey: tutoringKeys.ownProfile(),
    queryFn: () => call<TutorOwnProfile>("GET", "/tutor/profile"),
    retry: retryUnlessRefused,
  })
}

/** T2 · `POST /api/tutor/profile`. Creates the draft. */
export function useCreateTutorProfile(): UseMutationResult<
  TutorOwnProfile,
  Error,
  TutorProfileCreate
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: TutorProfileCreate) =>
      call<TutorOwnProfile>("POST", "/tutor/profile", { body }),
    onSuccess: (profile) => {
      queryClient.setQueryData(tutoringKeys.ownProfile(), profile)
      invalidateAll(queryClient, [tutoringKeys.ownPreview()])
    },
  })
}

/** T3 · `PATCH /api/tutor/profile`. The result says whether it needs review again. */
export function useUpdateTutorProfile(): UseMutationResult<
  TutorOwnProfile,
  Error,
  TutorProfileUpdate
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: TutorProfileUpdate) =>
      call<TutorOwnProfile>("PATCH", "/tutor/profile", { body }),
    onSuccess: (profile) => {
      queryClient.setQueryData(tutoringKeys.ownProfile(), profile)
      invalidateAll(queryClient, [tutoringKeys.ownPreview()])
    },
  })
}

/** T4 · `POST /api/tutor/profile/submit`. Sends the draft for review. */
export function useSubmitTutorProfile(): UseMutationResult<TutorOwnProfile, Error, void> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => call<TutorOwnProfile>("POST", "/tutor/profile/submit"),
    onSuccess: (profile) => {
      queryClient.setQueryData(tutoringKeys.ownProfile(), profile)
      invalidateAll(queryClient, [tutoringKeys.ownPreview()])
    },
  })
}

/** T5 · `PUT /api/tutor/profile/availability`. Replaces all weekly rules (0 to 42). */
export function useReplaceTutorAvailability(): UseMutationResult<
  AvailabilityRule[],
  Error,
  AvailabilityReplace
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: AvailabilityReplace) =>
      call<AvailabilityRule[]>("PUT", "/tutor/profile/availability", { body }),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.ownProfile(), tutoringKeys.ownPreview()])
    },
  })
}

/** T6 · `POST /api/tutor/profile/evidence`. Multipart: `file`, optional `description`. */
export function useUploadTutorEvidence(): UseMutationResult<
  Evidence,
  Error,
  { file: File; description?: string }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ file, description }: { file: File; description?: string }) => {
      const form = new FormData()
      form.append("file", file)
      if (description) form.append("description", description)
      return call<Evidence>("POST", "/tutor/profile/evidence", { form })
    },
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.ownProfile()])
    },
  })
}

/** T7 · `DELETE /api/tutor/profile/evidence/{evidence_id}`. */
export function useDeleteTutorEvidence(): UseMutationResult<
  void,
  Error,
  { evidenceId: string }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ evidenceId }: { evidenceId: string }) =>
      call<void>("DELETE", `/tutor/profile/evidence/${evidenceId}`),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.ownProfile()])
    },
  })
}

/** T8 · `GET /api/tutor/profile/preview`. */
export function useTutorProfilePreview(): UseQueryResult<TutorPreview, Error> {
  return useQuery({
    queryKey: tutoringKeys.ownPreview(),
    queryFn: () => call<TutorPreview>("GET", "/tutor/profile/preview"),
    retry: retryUnlessRefused,
  })
}

/** T9 · `GET /api/tutor/bookings`. `state` is an effective state. */
export function useTutorBookings(
  params: TutorBookingsParams,
): UseQueryResult<BookingsPage, Error> {
  return useQuery({
    queryKey: tutoringKeys.tutorBookings(params),
    queryFn: () => call<BookingsPage>("GET", "/tutor/bookings", { query: params }),
    retry: retryUnlessRefused,
  })
}

/** T10 · `GET /api/tutor/bookings/{booking_id}`. Carries `studentShared`. */
export function useTutorBooking(bookingId: string): UseQueryResult<Booking, Error> {
  return useQuery({
    queryKey: tutoringKeys.tutorBooking(bookingId),
    queryFn: () => call<Booking>("GET", `/tutor/bookings/${bookingId}`),
    retry: retryUnlessRefused,
  })
}

/** T11 · `POST /api/tutor/bookings/{booking_id}/accept`. Link or place per the mode. */
export function useAcceptTutorBooking(): UseMutationResult<
  Booking,
  Error,
  { bookingId: string; body: BookingAccept }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ bookingId, body }: { bookingId: string; body: BookingAccept }) =>
      call<Booking>("POST", `/tutor/bookings/${bookingId}/accept`, { body }),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.ownBookingsScope()])
    },
  })
}

/** T12 · `POST /api/tutor/bookings/{booking_id}/decline`. */
export function useDeclineTutorBooking(): UseMutationResult<
  Booking,
  Error,
  BookingActionVariables
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ bookingId, body }: BookingActionVariables) =>
      call<Booking>("POST", `/tutor/bookings/${bookingId}/decline`, { body }),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.ownBookingsScope()])
    },
  })
}

/**
 * T13 · `POST /api/tutor/bookings/{booking_id}/cancel`. A reason is required
 * inside 24 hours of the start (422 `reason_required`); `Booking.allowedActions`
 * says `cancel_with_reason` when it is.
 */
export function useCancelTutorBooking(): UseMutationResult<
  Booking,
  Error,
  BookingActionVariables
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ bookingId, body }: BookingActionVariables) =>
      call<Booking>("POST", `/tutor/bookings/${bookingId}/cancel`, { body }),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.ownBookingsScope()])
    },
  })
}

/** T14 · `POST /api/tutor/bookings/{booking_id}/complete`. */
export function useCompleteTutorBooking(): UseMutationResult<
  Booking,
  Error,
  BookingIdVariables
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ bookingId }: BookingIdVariables) =>
      call<Booking>("POST", `/tutor/bookings/${bookingId}/complete`),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.ownBookingsScope()])
    },
  })
}

/** T15 · `POST /api/tutor/bookings/{booking_id}/no-show`. */
export function useMarkTutorBookingNoShow(): UseMutationResult<
  Booking,
  Error,
  BookingIdVariables
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ bookingId }: BookingIdVariables) =>
      call<Booking>("POST", `/tutor/bookings/${bookingId}/no-show`),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.ownBookingsScope()])
    },
  })
}

/** T16 · `GET /api/tutor/bookings/{booking_id}/notes`. */
export function useTutorBookingNotes(
  bookingId: string,
  params: PageParams = {},
): UseQueryResult<NotesPage, Error> {
  return useQuery({
    queryKey: tutoringKeys.tutorBookingNotes(bookingId, params),
    queryFn: () =>
      call<NotesPage>("GET", `/tutor/bookings/${bookingId}/notes`, { query: params }),
    retry: retryUnlessRefused,
  })
}

/** T17 · `POST /api/tutor/bookings/{booking_id}/notes`. */
export function usePostTutorBookingNote(): UseMutationResult<
  Note,
  Error,
  { bookingId: string; body: NoteCreate }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ bookingId, body }: { bookingId: string; body: NoteCreate }) =>
      call<Note>("POST", `/tutor/bookings/${bookingId}/notes`, { body }),
    onSuccess: (_note, { bookingId }) => {
      invalidateAll(queryClient, [tutoringKeys.tutorBookingNotesScope(bookingId)])
    },
  })
}

/** T18 · `POST /api/tutor/reviews/{review_id}/reply`. Held for moderation before it is public. */
export function useReplyToReview(): UseMutationResult<
  Reply,
  Error,
  { reviewId: string; body: ReplyCreate }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ reviewId, body }: { reviewId: string; body: ReplyCreate }) =>
      call<Reply>("POST", `/tutor/reviews/${reviewId}/reply`, { body }),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.ownReviewsScope()])
    },
  })
}

/** T19 · `GET /api/tutor/students`. Writes one `list` audit row per student shown. */
export function useTutorStudents(
  params: PageParams = {},
): UseQueryResult<TutorStudentPage, Error> {
  return useQuery({
    queryKey: tutoringKeys.tutorStudents(params),
    queryFn: () => call<TutorStudentPage>("GET", "/tutor/students", { query: params }),
    retry: retryUnlessRefused,
    ...AUDITED_READ,
  })
}

/**
 * T20 · `GET /api/tutor/students/{student_id}`. Writes a `detail` audit row
 * before the data loads. A 403 `access_ended` clears this student's cached
 * data (`installAccessEndedGuard`); a 404 means no grant ever existed.
 */
export function useTutorStudent(
  studentId: string,
): UseQueryResult<TutorStudentDetail, Error> {
  const queryClient = useQueryClient()
  installAccessEndedGuard(queryClient)
  return useQuery({
    queryKey: tutoringKeys.tutorStudent(studentId),
    queryFn: () => call<TutorStudentDetail>("GET", `/tutor/students/${studentId}`),
    retry: retryUnlessRefused,
    ...AUDITED_READ,
  })
}

/** T21 · `GET /api/tutor/reviews`. The tutor's own reviews, newest first. */
export function useOwnTutorReviews(
  params: PageParams = {},
): UseQueryResult<TutorReviewsPage, Error> {
  return useQuery({
    queryKey: tutoringKeys.ownReviews(params),
    queryFn: () => call<TutorReviewsPage>("GET", "/tutor/reviews", { query: params }),
    retry: retryUnlessRefused,
  })
}

// ═════════════════════════════════════════════════════════════════════════════
// Parent (PA1-PA7): the linked child's bookings and grants
// ═════════════════════════════════════════════════════════════════════════════

/** Variables of the parent's booking actions. */
export interface ParentBookingVariables {
  childId: string
  bookingId: string
  body?: BookingReason
}

/** PA1 · `GET /api/parent/children/{child_id}/bookings`. */
export function useParentChildBookings(
  childId: string,
  params: BookingsParams,
): UseQueryResult<BookingsPage, Error> {
  return useQuery({
    queryKey: tutoringKeys.parentBookings(childId, params),
    queryFn: () =>
      call<BookingsPage>("GET", `/parent/children/${childId}/bookings`, { query: params }),
    retry: retryUnlessRefused,
  })
}

/** PA2 · `GET /api/parent/children/{child_id}/bookings/{booking_id}`. */
export function useParentChildBooking(
  childId: string,
  bookingId: string,
): UseQueryResult<Booking, Error> {
  return useQuery({
    queryKey: tutoringKeys.parentBooking(childId, bookingId),
    queryFn: () => call<Booking>("GET", `/parent/children/${childId}/bookings/${bookingId}`),
    retry: retryUnlessRefused,
  })
}

/** PA3 · `GET /api/parent/children/{child_id}/bookings/{booking_id}/notes`. Read only. */
export function useParentChildBookingNotes(
  childId: string,
  bookingId: string,
  params: PageParams = {},
): UseQueryResult<NotesPage, Error> {
  return useQuery({
    queryKey: tutoringKeys.parentBookingNotes(childId, bookingId, params),
    queryFn: () =>
      call<NotesPage>("GET", `/parent/children/${childId}/bookings/${bookingId}/notes`, {
        query: params,
      }),
    retry: retryUnlessRefused,
  })
}

/** PA4 · `POST /api/parent/children/{child_id}/bookings/{booking_id}/cancel`. */
export function useCancelParentChildBooking(): UseMutationResult<
  Booking,
  Error,
  ParentBookingVariables
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ childId, bookingId, body }: ParentBookingVariables) =>
      call<Booking>("POST", `/parent/children/${childId}/bookings/${bookingId}/cancel`, {
        body,
      }),
    onSuccess: (booking, { childId }) => {
      invalidateAll(queryClient, [
        tutoringKeys.parentBookingsScope(childId),
        tutoringKeys.tutorSlotsScope(booking.tutor.tutorId),
      ])
    },
  })
}

/** PA5 · `POST /api/parent/children/{child_id}/bookings/{booking_id}/complete`. */
export function useCompleteParentChildBooking(): UseMutationResult<
  Booking,
  Error,
  ParentBookingVariables
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ childId, bookingId }: ParentBookingVariables) =>
      call<Booking>("POST", `/parent/children/${childId}/bookings/${bookingId}/complete`),
    onSuccess: (_booking, { childId }) => {
      invalidateAll(queryClient, [tutoringKeys.parentBookingsScope(childId)])
    },
  })
}

/** PA6 · `GET /api/parent/children/{child_id}/tutor-grants`. Read only. */
export function useParentChildTutorGrants(childId: string): UseQueryResult<Grants, Error> {
  return useQuery({
    queryKey: tutoringKeys.parentGrants(childId),
    queryFn: () => call<Grants>("GET", `/parent/children/${childId}/tutor-grants`),
    retry: retryUnlessRefused,
  })
}

/** PA7 · `GET /api/parent/children/{child_id}/tutor-access-log`. */
export function useParentChildTutorAccessLog(
  childId: string,
  params: AccessLogParams = {},
): UseQueryResult<AccessLogPage, Error> {
  return useQuery({
    queryKey: tutoringKeys.parentAccessLog(childId, params),
    queryFn: () =>
      call<AccessLogPage>("GET", `/parent/children/${childId}/tutor-access-log`, {
        query: params,
      }),
    retry: retryUnlessRefused,
  })
}

// ═════════════════════════════════════════════════════════════════════════════
// Safety (R1, B1-B3): student, parent or teacher
// ═════════════════════════════════════════════════════════════════════════════

/** R1 · `POST /api/tutoring/reports`. Open to a student, parent or teacher. */
export function useCreateTutoringReport(): UseMutationResult<
  ReportReceipt,
  Error,
  ReportCreate
> {
  return useMutation({
    mutationFn: (body: ReportCreate) =>
      call<ReportReceipt>("POST", "/tutoring/reports", { body }),
  })
}

/** B1 · `GET /api/tutoring/blocks`. Active blocks only. */
export function useTutoringBlocks(): UseQueryResult<Blocks, Error> {
  return useQuery({
    queryKey: tutoringKeys.blocks(),
    queryFn: () => call<Blocks>("GET", "/tutoring/blocks"),
    retry: retryUnlessRefused,
  })
}

/** B2 · `POST /api/tutoring/blocks`. `tutorId` from a student, `studentId` from a tutor. */
export function useCreateTutoringBlock(): UseMutationResult<Block, Error, BlockCreate> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: BlockCreate) => call<Block>("POST", "/tutoring/blocks", { body }),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.blocks(), tutoringKeys.directoryScope()])
    },
  })
}

/** B3 · `DELETE /api/tutoring/blocks/{counterpart_id}`. A tutor profile id or a student id. */
export function useRemoveTutoringBlock(): UseMutationResult<
  void,
  Error,
  { counterpartId: string }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ counterpartId }: { counterpartId: string }) =>
      call<void>("DELETE", `/tutoring/blocks/${counterpartId}`),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.blocks(), tutoringKeys.directoryScope()])
    },
  })
}

// ═════════════════════════════════════════════════════════════════════════════
// Platform admin (A1-A12)
// ═════════════════════════════════════════════════════════════════════════════

/** A1 · `GET /api/admin/tutors`. `emailDelivery` says whether mail is really sent. */
export function useAdminTutors(
  params: AdminTutorsParams = {},
): UseQueryResult<AdminTutorPage, Error> {
  return useQuery({
    queryKey: tutoringKeys.adminTutors(params),
    queryFn: () => call<AdminTutorPage>("GET", "/admin/tutors", { query: params }),
    retry: retryUnlessRefused,
  })
}

/**
 * A2 · `GET /api/admin/tutors/{tutor_id}`. Issues 300 second evidence download
 * links and logs one row per link, so it is an audited read.
 */
export function useAdminTutor(tutorId: string): UseQueryResult<AdminTutorDetail, Error> {
  return useQuery({
    queryKey: tutoringKeys.adminTutor(tutorId),
    queryFn: () => call<AdminTutorDetail>("GET", `/admin/tutors/${tutorId}`),
    retry: retryUnlessRefused,
    ...AUDITED_READ,
  })
}

/** Variables of the admin's decisions on a tutor. */
export interface AdminTutorDecisionVariables {
  tutorId: string
  body: AdminNote
}

/**
 * A3 · `POST /api/admin/tutors/{tutor_id}/approve`. Lists a pending profile, or
 * reinstates a suspended one. The result carries no evidence links (only A2
 * issues them), so the detail is refetched rather than replaced.
 */
export function useApproveTutor(): UseMutationResult<
  AdminTutorDetail,
  Error,
  { tutorId: string; body: AdminApprove }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ tutorId, body }: { tutorId: string; body: AdminApprove }) =>
      call<AdminTutorDetail>("POST", `/admin/tutors/${tutorId}/approve`, { body }),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.adminTutorsScope()])
    },
  })
}

/** A4 · `POST /api/admin/tutors/{tutor_id}/reject`. A note is required. */
export function useRejectTutor(): UseMutationResult<
  AdminTutorDetail,
  Error,
  AdminTutorDecisionVariables
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ tutorId, body }: AdminTutorDecisionVariables) =>
      call<AdminTutorDetail>("POST", `/admin/tutors/${tutorId}/reject`, { body }),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.adminTutorsScope()])
    },
  })
}

/** A5 · `POST /api/admin/tutors/{tutor_id}/suspend`. */
export function useSuspendTutor(): UseMutationResult<
  AdminTutorDetail,
  Error,
  AdminTutorDecisionVariables
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ tutorId, body }: AdminTutorDecisionVariables) =>
      call<AdminTutorDetail>("POST", `/admin/tutors/${tutorId}/suspend`, { body }),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.adminTutorsScope()])
    },
  })
}

/** A6 · `GET /api/admin/tutoring/moderation`. Oldest first. */
export function useAdminModeration(
  params: ModerationParams = {},
): UseQueryResult<ModerationPage, Error> {
  return useQuery({
    queryKey: tutoringKeys.adminModeration(params),
    queryFn: () => call<ModerationPage>("GET", "/admin/tutoring/moderation", { query: params }),
    retry: retryUnlessRefused,
  })
}

/** A7 · `POST /api/admin/tutoring/reviews/{review_id}/moderate`. */
export function useModerateReview(): UseMutationResult<
  AdminReview,
  Error,
  { reviewId: string; body: ReviewModerate }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ reviewId, body }: { reviewId: string; body: ReviewModerate }) =>
      call<AdminReview>("POST", `/admin/tutoring/reviews/${reviewId}/moderate`, { body }),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.adminModerationScope()])
    },
  })
}

/** A8 · `POST /api/admin/tutoring/replies/{reply_id}/moderate`. */
export function useModerateReply(): UseMutationResult<
  AdminReply,
  Error,
  { replyId: string; body: ReplyModerate }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ replyId, body }: { replyId: string; body: ReplyModerate }) =>
      call<AdminReply>("POST", `/admin/tutoring/replies/${replyId}/moderate`, { body }),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.adminModerationScope()])
    },
  })
}

/** A9 · `GET /api/admin/tutoring/reports`. Safety concerns first. */
export function useAdminTutoringReports(
  params: AdminReportsParams = {},
): UseQueryResult<ReportPage, Error> {
  return useQuery({
    queryKey: tutoringKeys.adminReports(params),
    queryFn: () => call<ReportPage>("GET", "/admin/tutoring/reports", { query: params }),
    retry: retryUnlessRefused,
  })
}

/**
 * A10 · `GET /api/admin/tutoring/reports/{report_id}`. Writes one
 * `report_thread_view` row, so it is an audited read.
 */
export function useAdminTutoringReport(
  reportId: string,
): UseQueryResult<ReportDetail, Error> {
  return useQuery({
    queryKey: tutoringKeys.adminReport(reportId),
    queryFn: () => call<ReportDetail>("GET", `/admin/tutoring/reports/${reportId}`),
    retry: retryUnlessRefused,
    ...AUDITED_READ,
  })
}

/**
 * A11 · `POST /api/admin/tutoring/reports/{report_id}/resolve`. Puts the result
 * straight into the detail entry (refetching would log another view) and marks
 * the report lists stale.
 */
export function useResolveTutoringReport(): UseMutationResult<
  ReportDetail,
  Error,
  { reportId: string; body: ReportResolve }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ reportId, body }: { reportId: string; body: ReportResolve }) =>
      call<ReportDetail>("POST", `/admin/tutoring/reports/${reportId}/resolve`, { body }),
    onSuccess: (report, { reportId }) => {
      queryClient.setQueryData(tutoringKeys.adminReport(reportId), report)
      invalidateAll(queryClient, [tutoringKeys.adminReportListScope()])
    },
  })
}

/** A12 · `POST /api/admin/tutors/{tutor_id}/close`. */
export function useCloseTutor(): UseMutationResult<
  AdminTutorDetail,
  Error,
  AdminTutorDecisionVariables
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ tutorId, body }: AdminTutorDecisionVariables) =>
      call<AdminTutorDetail>("POST", `/admin/tutors/${tutorId}/close`, { body }),
    onSuccess: () => {
      invalidateAll(queryClient, [tutoringKeys.adminTutorsScope()])
    },
  })
}
