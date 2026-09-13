import { useEffect } from "react"
import { useNotificationCounts } from "@/lib/hooks/useNotificationApi"
import { setAppBadge } from "@/lib/badging"

/*
 * Keeps the installed PWA's app-icon badge in step with the real unread
 * count (Task 7 / B5a).
 *
 * Mounted inside each authenticated portal layout, not `main.tsx`:
 * `useNotificationCounts` hits an auth-gated endpoint (`/notifications/counts`),
 * so mounting this above the router the way `PushAutoEnable`/`TimezoneSync`
 * are would fire it on every signed-out load of `/login` — the same
 * `usePushConfig(userId !== null)` guard `PushAutoEnable` documents on its
 * own header, done here by placement instead of a boolean gate. Renders
 * nothing, same shape as the rest of that family.
 */
export function BadgeSync() {
  const counts = useNotificationCounts()
  const unread = counts.data?.unread ?? 0

  useEffect(() => {
    void setAppBadge(unread)
  }, [unread])

  return null
}
