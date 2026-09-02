import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import type {
  AdminSchoolList,
  InviteStudentRequest,
  InviteStudentResponse,
  InviteTeacherRequest,
  InviteTeacherResponse,
  RemoveTeacherRequest,
  RemoveTeacherResponse,
  SchoolOverviewList,
  SchoolTeacherList,
  SeatUsageList,
} from "@/lib/schoolTypes"
// `MintSeatInviteRequest`/`SeatInviteCode` mirror `schemas_invites.py`, not
// `schemas_admin.py` like the rest of `adminTypes.ts` — see that file's own
// note, right above these two interfaces, for why they live there rather
// than beside `InviteStudentRequest` above.
import type { MintSeatInviteRequest, SeatInviteCode } from "@/lib/adminTypes"

/*
 * React-query hooks wrapping `/api/school/*` (`lemely/web/routers/school.py`),
 * gated to `school_admin` alone. Same conventions as useMeApi.ts: one hook per
 * endpoint, no `fallback` passed to `request()`.
 */

/**
 * `GET /api/school/seats` — every school the authenticated admin administers.
 *
 * Consumed by T-12's audience selector, which needs a real `schoolId` for a
 * school-wide announcement (`AnnouncementCreateRequest.schoolId` is required
 * whenever `schoolWide` is true, because an admin can administer several
 * schools). This route already existed and is the only client-reachable source
 * of the caller's school memberships — do not add a second one, and do not
 * enrich `/api/me/profile` with schools to avoid it.
 *
 * `enabled` gates the fetch on the caller actually being a `school_admin`: any
 * other role gets a 403 here, and firing it for every teacher would put a
 * permanent error in the query cache behind a control they can't use anyway.
 */
export function useAdminSchools(enabled: boolean): UseQueryResult<AdminSchoolList, Error> {
  return useQuery({
    queryKey: SEATS_KEY,
    queryFn: () => request<AdminSchoolList>("/school/seats"),
    enabled,
  })
}

/*
 * P4.7 (UI spec K-01…K-04). The hooks below are unconditional — no `enabled`
 * flag — because every one of them is mounted only inside the school-admin
 * portal subtree, which `RequireAuth` already gates to `school_admin`. The
 * `enabled` on `useAdminSchools` above exists because *that* one is called from
 * the teacher portal's announcement composer, where a plain teacher would 403.
 */

const SEATS_KEY = ["school", "seats"] as const
const OVERVIEW_KEY = ["school", "overview"] as const
const TEACHERS_KEY = ["school", "teachers"] as const

/**
 * `GET /api/school/seats` with the full seat rows (K-02).
 *
 * Shares `SEATS_KEY` with `useAdminSchools` on purpose: it is the same request
 * to the same route, and giving it a second key would fetch it twice and let the
 * two copies disagree after an invite. `AdminSchoolList` is a structural subset
 * of `SeatUsageList`, so the announcement composer's narrower read still type-
 * checks against the same cache entry.
 */
export function useSeatUsage(): UseQueryResult<SeatUsageList, Error> {
  return useQuery({
    queryKey: SEATS_KEY,
    queryFn: () => request<SeatUsageList>("/school/seats"),
  })
}

/** `GET /api/school/overview` — K-01's counts and school average. */
export function useSchoolOverview(): UseQueryResult<SchoolOverviewList, Error> {
  return useQuery({
    queryKey: OVERVIEW_KEY,
    queryFn: () => request<SchoolOverviewList>("/school/overview"),
  })
}

/** `GET /api/school/teachers` — K-03's staff roster. */
export function useSchoolTeachers(): UseQueryResult<SchoolTeacherList, Error> {
  return useQuery({
    queryKey: TEACHERS_KEY,
    queryFn: () => request<SchoolTeacherList>("/school/teachers"),
  })
}

/**
 * `POST /api/school/seats/invite` — create a student account on a seat.
 *
 * Invalidates the overview as well as the seats: an invite moves `seatsUsed` on
 * K-01, and leaving that stale would show a dashboard contradicting the table
 * the admin just changed.
 */
export function useInviteStudent(): UseMutationResult<
  InviteStudentResponse,
  Error,
  InviteStudentRequest
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: InviteStudentRequest) =>
      request<InviteStudentResponse>("/school/seats/invite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: SEATS_KEY })
      void queryClient.invalidateQueries({ queryKey: OVERVIEW_KEY })
    },
  })
}

/**
 * `POST /api/school/seats/invite-code` — mint a redeemable seat invite code
 * (D7.3, spec §1.2, closes BUILD/BLOCKERS.md B8), reserving its seat
 * immediately. The alternative to `useInviteStudent` above: rather than
 * creating the account outright and handing back a temporary password, this
 * mints a code the admin hands to a student, who signs themselves up and
 * sees which school they're joining before committing (`JoinWithCode.tsx`,
 * G-08) — closing the half of spec §6's acceptance bullet ("A school admin
 * can mint a seat invite code...") this product could not do until now.
 *
 * Invalidates the same two keys `useInviteStudent` does, for a sharper
 * reason here than there: the seat is reserved at *mint* time, not at
 * redemption (`InviteService.mint_seat_invite`'s own binding rule 2), so
 * `seatsUsed`/`available` move the instant this call succeeds, before any
 * student has redeemed anything. Leaving the seats table stale would show a
 * seat as free that this admin just spent.
 */
export function useMintSeatInviteCode(): UseMutationResult<
  SeatInviteCode,
  Error,
  MintSeatInviteRequest
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: MintSeatInviteRequest) =>
      request<SeatInviteCode>("/school/seats/invite-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: SEATS_KEY })
      void queryClient.invalidateQueries({ queryKey: OVERVIEW_KEY })
    },
  })
}

/** `POST /api/school/seats/{id}/revoke` — free a seat, leaving the account. */
export function useRevokeSeat(): UseMutationResult<void, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (seatId: string) =>
      request<void>(`/school/seats/${seatId}/revoke`, { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: SEATS_KEY })
      void queryClient.invalidateQueries({ queryKey: OVERVIEW_KEY })
    },
  })
}

/** `POST /api/school/teachers/invite` — add a teacher to the staff (K-03). */
export function useInviteTeacher(): UseMutationResult<
  InviteTeacherResponse,
  Error,
  InviteTeacherRequest
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: InviteTeacherRequest) =>
      request<InviteTeacherResponse>("/school/teachers/invite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: TEACHERS_KEY })
      void queryClient.invalidateQueries({ queryKey: OVERVIEW_KEY })
    },
  })
}

/**
 * `POST /api/school/teachers/{id}/remove` — remove a teacher, reassigning.
 *
 * Also invalidates the seats: a seat row names the teacher of each class the
 * student is in, and a reassignment changes that name.
 */
export function useRemoveTeacher(): UseMutationResult<
  RemoveTeacherResponse,
  Error,
  RemoveTeacherRequest
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ teacherId, ...body }: RemoveTeacherRequest) =>
      request<RemoveTeacherResponse>(`/school/teachers/${teacherId}/remove`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: TEACHERS_KEY })
      void queryClient.invalidateQueries({ queryKey: OVERVIEW_KEY })
      void queryClient.invalidateQueries({ queryKey: SEATS_KEY })
    },
  })
}
