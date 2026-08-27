import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import type {
  ConfidenceRating,
  ConfidenceRatingsUpdate,
  EnrolmentListRequest,
  Profile,
  StudentProfile,
  StudentProfileUpdate,
  StudentProfileWithEnrolments,
  SubjectEnrolment,
} from "@/lib/meTypes"

/*
 * React-query hooks wrapping `/api/me/*` (`lemely/web/routers/me.py`), reachable
 * by every authenticated role. Follows useStudentApi.ts's conventions: one hook
 * per endpoint, no `fallback` passed to `request()` — a real backend/auth
 * failure must surface as a query error the screen can render, never silently
 * resolve to empty data.
 */

export function useProfile(): UseQueryResult<Profile, Error> {
  return useQuery({
    queryKey: ["me", "profile"],
    queryFn: () => request<Profile>("/me/profile"),
  })
}

// ── Student onboarding profile (P4.3 chunk B / P4.8 chunk A) ───────────────

const STUDENT_PROFILE_KEY = ["me", "student-profile"] as const

export function useStudentProfile(): UseQueryResult<StudentProfileWithEnrolments, Error> {
  return useQuery({
    queryKey: STUDENT_PROFILE_KEY,
    queryFn: () => request<StudentProfileWithEnrolments>("/me/student-profile"),
  })
}

export function usePatchStudentProfile(): UseMutationResult<
  StudentProfile,
  Error,
  StudentProfileUpdate
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: StudentProfileUpdate) =>
      request<StudentProfile>("/me/student-profile", {
        method: "PATCH",
        body: JSON.stringify(body satisfies StudentProfileUpdate),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: STUDENT_PROFILE_KEY })
    },
  })
}

export function usePutEnrolments(): UseMutationResult<
  SubjectEnrolment[],
  Error,
  EnrolmentListRequest
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: EnrolmentListRequest) =>
      request<SubjectEnrolment[]>("/me/student-profile/enrolments", {
        method: "PUT",
        body: JSON.stringify(body satisfies EnrolmentListRequest),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: STUDENT_PROFILE_KEY })
    },
  })
}

export function usePutConfidenceRatings(): UseMutationResult<
  ConfidenceRating[],
  Error,
  { subjectCode: string; ratings: ConfidenceRatingsUpdate["ratings"] }
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ subjectCode, ratings }) =>
      request<ConfidenceRating[]>(
        `/me/student-profile/enrolments/${subjectCode}/confidence-ratings`,
        {
          method: "PUT",
          body: JSON.stringify({ ratings } satisfies ConfidenceRatingsUpdate),
        },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: STUDENT_PROFILE_KEY })
    },
  })
}

export function useCompleteOnboarding(): UseMutationResult<StudentProfile, Error, void> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      request<StudentProfile>("/me/student-profile/complete-onboarding", { method: "POST" }),
    /*
     * Write the returned profile into the cache *synchronously*, then
     * invalidate. Invalidating alone is not enough here and the difference is
     * a trap the D7.9 gate walks straight into.
     *
     * `invalidateQueries` marks the query stale and starts a refetch without
     * blocking. `Onboarding.handleFinish` navigates the moment this mutation
     * resolves, so the very next render happens while the cache still holds
     * the pre-completion profile — `onboardingCompletedAt: null`. The student
     * portal's gate reads exactly that field and sends the student back to
     * `/student/onboard`, so finishing onboarding bounced straight back into
     * onboarding and the wizard could never be escaped.
     *
     * The endpoint already returns the updated profile, which is presumably
     * why it returns one at all. Writing it into the cached wrapper (the query
     * holds `{profile, enrolments}`; the response is just the profile) makes
     * the gate's read correct before `navigate` can run. The invalidate stays
     * so the enrolments half is refreshed too.
     *
     * Found by the E2E student journey, which sat on "Question 5 of 5" clicking
     * Finish ten times and never left the wizard.
     */
    onSuccess: (profile) => {
      queryClient.setQueryData<StudentProfileWithEnrolments>(STUDENT_PROFILE_KEY, (old) =>
        old ? { ...old, profile } : old,
      )
      queryClient.invalidateQueries({ queryKey: STUDENT_PROFILE_KEY })
    },
  })
}
