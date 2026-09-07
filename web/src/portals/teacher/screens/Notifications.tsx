/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V3 */
import { Link, useNavigate } from "react-router-dom"
import { Card, CardBody } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { Eyebrow } from "@/components/ui/primitives"
import { EmptyState } from "@/components/ui/state-views"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Button } from "@/components/ui/button"
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from "@/lib/hooks/useNotificationApi"
import type { Notification } from "@/lib/notificationTypes"
import {
  STAFF_INBOX_ERROR,
  TEACHER_INBOX_EMPTY,
  isInboxEmpty,
  showMarkAllRead,
  staffDestinationFor,
  staffTypeLabel,
} from "@/lib/staffInbox"
import { formatAge } from "@/portals/student/screens/Notifications"
import { cn } from "@/lib/utils"

/*
 * The teacher's inbox (push-delivery spec §6). Only `at_risk_alert` reaches a
 * teacher, raised by `_alert_teachers_and_parents` for a student they teach,
 * so a row links to that student's page. The API is the same role-agnostic
 * `/api/notifications` the student inbox reads; `tests/test_web_notifications.py`
 * pins that every role can open its own.
 *
 * A per-portal screen, not a shared one: the same alert reads differently to
 * a teacher and a parent, and the student inbox is deliberately not extracted
 * to serve three audiences. What is shared is the pure module and the
 * components that already exist (`QueryState`, `ListSkeleton`, `EmptyState`).
 * `formatAge` is imported from the student screen rather than copied: it is a
 * pure export with its own tests, and two relative-age rules would drift.
 *
 * The stamp above, derived rather than copied: S5 because every element here
 * is specific to the one notification type a teacher actually receives — the
 * chip tone, the "Open student" verb, the empty-state sentence. V3 is honest:
 * this is a list of one row shape, and inventing variety in a queue of alerts
 * would be decoration. R4 for what is absent — no filters, no bulk selection,
 * no counts the server does not already publish.
 */

function NotificationRow({ notification }: { notification: Notification }) {
  const navigate = useNavigate()
  const markRead = useMarkNotificationRead()
  const unread = notification.readAt === null
  const destination = staffDestinationFor("teacher", notification)

  const open = (): void => {
    if (unread) markRead.mutate(notification.notificationId)
    if (destination !== null) void navigate(destination)
  }

  return (
    <Card className={cn("transition-colors", unread && "border-s-2 border-s-accent")}>
      <CardBody className="flex flex-col gap-2">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            {/* <h2>: these rows sit directly under the page's <h1>, the same
                outline the student inbox documents. */}
            <h2 className="text-body-lg font-medium text-ink">{notification.title}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-body-sm text-ink-faint">
              <Chip tone={notification.type === "at_risk_alert" ? "warn" : "neutral"}>
                {staffTypeLabel(notification.type)}
              </Chip>
              <time dateTime={notification.createdAt}>{formatAge(notification.createdAt)}</time>
            </div>
          </div>
          {unread ? (
            <Chip tone="warn" className="flex-none">
              Unread
            </Chip>
          ) : null}
        </div>

        {notification.body !== null ? (
          <p className="max-w-[65ch] text-body-md text-ink-muted">{notification.body}</p>
        ) : null}

        <div className="flex flex-wrap gap-2">
          {destination !== null ? (
            <Button size="sm" onClick={open}>
              Open student
            </Button>
          ) : null}
          {unread ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => markRead.mutate(notification.notificationId)}
              disabled={markRead.isPending}
            >
              Mark as read
            </Button>
          ) : null}
        </div>
      </CardBody>
    </Card>
  )
}

export function TeacherNotifications() {
  const query = useNotifications()
  const markAll = useMarkAllNotificationsRead()

  return (
    <div className="flex flex-col gap-4">
      {/* Outside QueryState, in every state: a heading is what the page IS. */}
      <div>
        <Eyebrow>Inbox</Eyebrow>
        <h1 className="text-display-md text-ink">Notifications</h1>
      </div>
      <QueryState
        query={query}
        skeleton={<ListSkeleton rows={3} />}
        error={STAFF_INBOX_ERROR}
        isEmpty={isInboxEmpty}
        empty={<EmptyState heading={TEACHER_INBOX_EMPTY.heading} body={TEACHER_INBOX_EMPTY.body} />}
      >
        {(data) => (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-end justify-end gap-3">
              <div className="flex items-center gap-3">
                <Link
                  to="/teacher/settings/notifications"
                  className="text-body-sm text-accent-ink hover:underline"
                >
                  Notification settings
                </Link>
                {showMarkAllRead(data) ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => markAll.mutate()}
                    disabled={markAll.isPending}
                  >
                    Mark all as read
                  </Button>
                ) : null}
              </div>
            </div>

            <div className="flex flex-col gap-3">
              {data.notifications.map((notification) => (
                <NotificationRow key={notification.notificationId} notification={notification} />
              ))}
            </div>
          </div>
        )}
      </QueryState>
    </div>
  )
}
