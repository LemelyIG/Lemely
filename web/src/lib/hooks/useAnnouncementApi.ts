import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import type {
  AnnouncementReadReceipt,
  StudentAnnouncementsPage,
  StudentExamCalendar,
  UnreadAnnouncementCount,
} from "@/lib/announcementTypes"

/*
 * React-query hooks over S-28's endpoints (P5.5 chunks B and C).
 *
 * Follows useDeviceApi.ts's conventions: one hook per endpoint and **no
 * `fallback` passed to `request()`**. That matters more here than usual — a
 * swallowed failure would render as "no announcements" and "no exams", both of
 * which are *claims* rather than absences of data. A student who quietly never
 * sees a teacher's notice because a fetch failed is worse served than one shown
 * an error they can retry.
 */

const ANNOUNCEMENTS_KEY = ["student", "announcements"] as const
const UNREAD_KEY = ["student", "announcements", "unread-count"] as const
const CALENDAR_KEY = ["student", "exam-calendar"] as const

export function useAnnouncements(): UseQueryResult<
  StudentAnnouncementsPage,
  Error
> {
  return useQuery({
    queryKey: ANNOUNCEMENTS_KEY,
    queryFn: () => request<StudentAnnouncementsPage>("/student/announcements"),
  })
}

/**
 * The navigation badge's count. Its own endpoint rather than
 * `announcements.filter(unread).length` — the list is `LIMIT`-ed server-side,
 * so a derived count would silently under-report once a student has more
 * unread notices than one page holds.
 */
export function useUnreadAnnouncementCount(): UseQueryResult<
  UnreadAnnouncementCount,
  Error
> {
  return useQuery({
    queryKey: UNREAD_KEY,
    queryFn: () =>
      request<UnreadAnnouncementCount>("/student/announcements/unread-count"),
  })
}

export function useMarkAnnouncementRead(): UseMutationResult<
  AnnouncementReadReceipt,
  Error,
  string
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (announcementId: string) =>
      request<AnnouncementReadReceipt>(
        `/student/announcements/${announcementId}/read`,
        { method: "POST" },
      ),
    // Both keys, because the badge and the list carry the same fact and a
    // stale badge over a list the student has visibly just read is the exact
    // inconsistency they will notice first.
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ANNOUNCEMENTS_KEY })
      void queryClient.invalidateQueries({ queryKey: UNREAD_KEY })
    },
  })
}

export function useExamCalendar(): UseQueryResult<StudentExamCalendar, Error> {
  return useQuery({
    queryKey: CALENDAR_KEY,
    queryFn: () => request<StudentExamCalendar>("/student/exam-calendar"),
  })
}
