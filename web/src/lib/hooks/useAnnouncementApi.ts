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

/**
 * Stamps `readAt` on one announcement within a page of the list, without
 * touching any other entry.
 *
 * `??` rather than an unconditional overwrite: the receipt endpoint is
 * idempotent and stores first-read only (`AnnouncementReadReceipt`'s own
 * doc comment), so an optimistic re-apply — the mutation firing twice before
 * the first settles — must not push the *second* click's timestamp over the
 * first. Exported so the optimistic-update decision is a plain function a
 * test can call directly, the same reasoning as `readStateFor` in
 * `Announcements.tsx`.
 */
export function applyOptimisticRead(
  page: StudentAnnouncementsPage,
  announcementId: string,
  readAt: string,
): StudentAnnouncementsPage {
  return {
    announcements: page.announcements.map((announcement) =>
      announcement.announcementId === announcementId
        ? { ...announcement, readAt: announcement.readAt ?? readAt }
        : announcement,
    ),
  }
}

interface MarkReadContext {
  previous: StudentAnnouncementsPage | undefined
}

export function useMarkAnnouncementRead(): UseMutationResult<
  AnnouncementReadReceipt,
  Error,
  string,
  MarkReadContext
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (announcementId: string) =>
      request<AnnouncementReadReceipt>(
        `/student/announcements/${announcementId}/read`,
        { method: "POST" },
      ),
    // Optimistic, because the whole point of a receipt the student can see is
    // that it survives a reload — a student who marks a notice read, then
    // reloads before the request round-trips, must not see "Mark as read"
    // again on a notice the server already holds a receipt for. Cancel first
    // so an in-flight refetch cannot land after this write and clobber it;
    // snapshot so `onError` can put the exact prior page back rather than
    // guessing at a rollback.
    onMutate: async (announcementId) => {
      await queryClient.cancelQueries({ queryKey: ANNOUNCEMENTS_KEY })
      const previous = queryClient.getQueryData<StudentAnnouncementsPage>(
        ANNOUNCEMENTS_KEY,
      )
      if (previous) {
        queryClient.setQueryData<StudentAnnouncementsPage>(
          ANNOUNCEMENTS_KEY,
          applyOptimisticRead(previous, announcementId, new Date().toISOString()),
        )
      }
      return { previous }
    },
    onError: (_error, _announcementId, context) => {
      if (context?.previous) {
        queryClient.setQueryData(ANNOUNCEMENTS_KEY, context.previous)
      }
    },
    // Both keys, because the badge and the list carry the same fact and a
    // stale badge over a list the student has visibly just read is the exact
    // inconsistency they will notice first. Still invalidated on success (on
    // top of the optimistic write above) so the receipt's *real* timestamp
    // replaces the client-clock guess once the server has spoken.
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
