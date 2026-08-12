import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import type {
  MarkAllReadResult,
  NotificationCounts,
  NotificationReadReceipt,
  NotificationsPage,
  PushConfig,
} from "@/lib/notificationTypes"

/*
 * React-query hooks over G-13's endpoints (P5.6 chunk C1's routes).
 *
 * Follows useAnnouncementApi.ts's conventions: one hook per endpoint and **no
 * `fallback` passed to `request()`**. The reasoning is the same one S-28 used
 * and it is if anything stronger here — a swallowed failure renders as an empty
 * inbox, which is a *claim* ("nothing has happened to you") rather than an
 * absence of data. D5.9 §1 makes the inbox row the source of truth for every
 * notification in this system; a screen that quietly shows none because a fetch
 * failed breaks exactly that guarantee.
 *
 * The path prefix is `/notifications`, not `/student/notifications` — the
 * router is role-agnostic by design, because `at_risk_alert` is addressed to a
 * teacher and a parent.
 */

const INBOX_KEY = ["notifications"] as const
const COUNTS_KEY = ["notifications", "counts"] as const
const PUSH_CONFIG_KEY = ["notifications", "push", "config"] as const

export function useNotifications(): UseQueryResult<NotificationsPage, Error> {
  return useQuery({
    queryKey: INBOX_KEY,
    queryFn: () => request<NotificationsPage>("/notifications"),
  })
}

/**
 * The badge's numbers. Its own endpoint rather than counting unread rows in the
 * page, because the list is `LIMIT`-ed server-side and a derived count would
 * stop at the page size and quietly under-report — the same trap P5.5's
 * unread-count route exists to avoid.
 */
export function useNotificationCounts(): UseQueryResult<NotificationCounts, Error> {
  return useQuery({
    queryKey: COUNTS_KEY,
    queryFn: () => request<NotificationCounts>("/notifications/counts"),
  })
}

export function useMarkNotificationRead(): UseMutationResult<
  NotificationReadReceipt,
  Error,
  string
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (notificationId: string) =>
      request<NotificationReadReceipt>(`/notifications/${notificationId}/read`, {
        method: "POST",
      }),
    // Both keys: a badge still showing unread over a list the reader has
    // visibly just opened is the first inconsistency they will notice.
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: INBOX_KEY })
      void queryClient.invalidateQueries({ queryKey: COUNTS_KEY })
    },
  })
}

export function useMarkAllNotificationsRead(): UseMutationResult<
  MarkAllReadResult,
  Error,
  void
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      request<MarkAllReadResult>("/notifications/read-all", { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: INBOX_KEY })
      void queryClient.invalidateQueries({ queryKey: COUNTS_KEY })
    },
  })
}

/**
 * Whether this deployment can send push at all.
 *
 * Read by G-12 to choose between three states rather than one grey button.
 * `available: false` is the designed answer on a build with no VAPID keys
 * (D5.9 §4) and must not be rendered as an error.
 */
export function usePushConfig(): UseQueryResult<PushConfig, Error> {
  return useQuery({
    queryKey: PUSH_CONFIG_KEY,
    queryFn: () => request<PushConfig>("/notifications/push/config"),
    // Server capability, not user data: it cannot change between renders of a
    // session, and re-asking on every window focus would be noise.
    staleTime: Infinity,
  })
}
