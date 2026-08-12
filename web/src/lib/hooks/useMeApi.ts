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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: STUDENT_PROFILE_KEY })
    },
  })
}
