import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import type {
  NotificationPreferences,
  NotificationPreferencesUpdate,
} from "@/lib/notificationPrefs"
import type { PushSubscribePayload } from "@/lib/push/pushEnable"

/*
 * G-12's endpoints (P5.9 chunk C).
 *
 * Two prefixes, and they are genuinely different routers: preferences live on
 * **`/me/notification-preferences`** (`routers/me.py`, role-agnostic read,
 * role-gated `atRiskAlert`), push subscriptions on **`/notifications/push/*`*
 * (`routers/notifications.py`). Neither is under `/student` — `at_risk_alert` is
 * addressed to a teacher and a parent, so a student-scoped path would have built
 * a preferences screen two of its three audiences could not reach.
 *
 * No `fallback` is passed to `request()` anywhere here, for the same reason
 * `useNotificationApi` passes none: a swallowed failure would render as "every
 * notification type is on", which is a *claim* about the reader's settings
 * rather than an absence of data, and the reader would then believe they had
 * configured something they had not.
 */

const PREFS_KEY = ["me", "notification-preferences"] as const
const PUSH_SUBSCRIPTION_KEY = ["notifications", "push", "subscription"] as const

export function useNotificationPreferences(): UseQueryResult<NotificationPreferences, Error> {
  return useQuery({
    queryKey: PREFS_KEY,
    queryFn: () => request<NotificationPreferences>("/me/notification-preferences"),
  })
}

/**
 * Save a **partial** update.
 *
 * The caller sends only the keys it changed. That is not an optimisation: the
 * router leaves an omitted field untouched (`model_fields_set`), so a partial
 * body is what stops one toggle flip from clobbering a change made on another
 * device — and it is what keeps `atRiskAlert` out of a student's request body,
 * which the router answers with a 422 whether the value is `true` or `false`.
 *
 * The response is the full new state, so it is written straight into the cache
 * rather than triggering a refetch: the server's echo is authoritative and a
 * second round trip could only introduce a window where the switch shows its old
 * position.
 */
export function useUpdateNotificationPreferences(): UseMutationResult<
  NotificationPreferences,
  Error,
  NotificationPreferencesUpdate
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (update: NotificationPreferencesUpdate) =>
      request<NotificationPreferences>("/me/notification-preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(update),
      }),
    onSuccess: (prefs) => {
      queryClient.setQueryData(PREFS_KEY, prefs)
    },
  })
}

/**
 * Whether this browser currently holds a push subscription.
 *
 * A query rather than component state because it is a fact about the browser
 * that this screen does not own — a subscription can disappear between visits
 * (cleared site data, a new profile, a `410` the server acted on), and reading
 * it fresh is the only way the switch's position stays true.
 */
export function useBrowserPushSubscription(
  read: () => Promise<PushSubscription | null>,
): UseQueryResult<{ endpoint: string } | null, Error> {
  return useQuery({
    queryKey: PUSH_SUBSCRIPTION_KEY,
    queryFn: async () => {
      const subscription = await read()
      return subscription === null ? null : { endpoint: subscription.endpoint }
    },
  })
}

export function useSubscribeToPush(): UseMutationResult<unknown, Error, PushSubscribePayload> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: PushSubscribePayload) =>
      request<unknown>("/notifications/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PUSH_SUBSCRIPTION_KEY })
    },
  })
}

export function useUnsubscribeFromPush(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (endpoint: string) =>
      request<unknown>("/notifications/push/unsubscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PUSH_SUBSCRIPTION_KEY })
    },
  })
}
