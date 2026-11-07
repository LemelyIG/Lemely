import type { Notification } from "@/lib/notificationTypes"

/**
 * Where a student notification row goes, or null for no action. Moved out of
 * `portals/student/screens/Notifications.tsx` so the shell's bell panel can
 * use it without pulling the inbox screen into the entry chunk. Kept
 * consistent with `pushClientBridge.destinationFor`. `grade_ready` has no
 * destination on purpose (see the screen's note).
 */
export function studentDestinationFor(notification: Pick<Notification, "type" | "payload">): string | null {
  switch (notification.type) {
    case "announcement":
      return "/student/announcements"
    case "streak_warning":
      return "/student/profile"
    case "study_plan_reminder": {
      const { subjectCode, sessionId } = notification.payload
      if (!subjectCode || !sessionId) return null
      return `/student/plan/${encodeURIComponent(subjectCode)}/session/${encodeURIComponent(sessionId)}`
    }
    default:
      return null
  }
}
