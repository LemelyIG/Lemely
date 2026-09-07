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
  PARENT_INBOX_EMPTY,
  STAFF_INBOX_ERROR,
  isInboxEmpty,
  showMarkAllRead,
  staffDestinationFor,
  staffTypeLabel,
} from "@/lib/staffInbox"
import { formatAge } from "@/portals/student/screens/Notifications"
import { cn } from "@/lib/utils"

/*
 * The parent's inbox (push-delivery spec §6). Only `at_risk_alert` reaches a
 * parent, raised by `_alert_teachers_and_parents` for their own child, so a
 * row links to that child's overview. The API is the same role-agnostic
 * `/api/notifications` the other two inboxes read.
 *
 * A per-portal screen, not a shared one: "a student you teach" and "your
 * child" are different sentences about the same row, and P-01's parent has
 * no interest in learning an interface built for someone else. What is
 * shared is the pure module and the components that already exist.
 * `formatAge` is imported from the student screen rather than copied, for the
 * reason the teacher screen gives.
 *
 * The stamp above matches the teacher screen's because the two are the same
 * artifact addressed to a different reader, and the scores were re-derived
 * rather than assumed: S5 for copy written for this reader ("See progress",
 * "your child"), V3 because one row shape repeated is what an alert queue is.
 */

function NotificationRow({ notification }: { notification: Notification }) {
  const navigate = useNavigate()
  const markRead = useMarkNotificationRead()
  const unread = notification.readAt === null
  const destination = staffDestinationFor("parent", notification)

  const open = (): void => {
    if (unread) markRead.mutate(notification.notificationId)
    if (destination !== null) void navigate(destination)
  }

  return (
    <Card className={cn("transition-colors", unread && "border-s-2 border-s-accent")}>
      <CardBody className="flex flex-col gap-2">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
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
              See progress
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

export function ParentNotifications() {
  const query = useNotifications()
  const markAll = useMarkAllNotificationsRead()

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Eyebrow>Inbox</Eyebrow>
        <h1 className="text-display-md text-ink">Notifications</h1>
      </div>
      <QueryState
        query={query}
        skeleton={<ListSkeleton rows={3} />}
        error={STAFF_INBOX_ERROR}
        isEmpty={isInboxEmpty}
        empty={<EmptyState heading={PARENT_INBOX_EMPTY.heading} body={PARENT_INBOX_EMPTY.body} />}
      >
        {(data) => (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-end justify-end gap-3">
              <div className="flex items-center gap-3">
                {/* The parent portal has no in-portal settings lane; the
                    top-level one is their only route to it. */}
                <Link
                  to="/settings/notifications"
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
