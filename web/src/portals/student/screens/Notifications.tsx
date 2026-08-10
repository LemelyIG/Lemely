import { Link, useNavigate } from "react-router-dom"
import { Card, CardBody } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { Eyebrow } from "@/components/ui/primitives"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { Button } from "@/components/ui/button"
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from "@/lib/hooks/useNotificationApi"
import type { Notification } from "@/lib/notificationTypes"
import { cn } from "@/lib/utils"

/*
 * G-13 · The notification inbox (P5.9 chunk B).
 *
 * D5.9 §1 makes the inbox row the source of truth for every notification in
 * this system: a push is one *delivery* of a row that already exists, never the
 * notification itself. This screen is therefore the canonical surface — a
 * reader who never enables push, or whose browser denies it, or who uses a
 * build with no VAPID keys (which is every build this repo currently produces),
 * misses nothing by coming here instead.
 *
 * That is also why the empty state is worded as a fact about *them* rather than
 * about the feature: an empty inbox means nothing has happened yet, not that
 * notifications are broken or switched off.
 *
 * The route is portal-mounted for the student, but the underlying API is
 * role-agnostic on purpose — `at_risk_alert` is addressed to a teacher and a
 * parent — so nothing in this file assumes a student.
 */

/** How each type is labelled. The five values are the whole enum (D5.9). */
const TYPE_LABELS: Record<string, string> = {
  grade_ready: "Marked",
  announcement: "Announcement",
  streak_warning: "Streak",
  study_plan_reminder: "Study plan",
  at_risk_alert: "Needs attention",
}

/**
 * A notification of an unrecognised type still renders, with its raw type as
 * the label. An inbox that failed closed on one unknown row — because a newer
 * backend grew a sixth type — would hide every notification beside it, which is
 * strictly worse than showing one with an unpolished chip.
 */
export function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type
}

/**
 * Where a notification's "Open" action goes, or null for no action at all.
 *
 * **Only `announcement` has a destination, and `grade_ready` deliberately does
 * not — that is a measured constraint, not an oversight.** `grade_ready`'s
 * payload carries `uploadId` (the upload's UUID, `routers/student.py:891`), and
 * the only per-paper screen is `/student/result/:paperId`, whose `paperId` is a
 * **history record index**, not an id: `student_result` does `int(paper_id)` and
 * 404s on anything else (`routers/student.py:487`). So an "Open" button here
 * would be a guaranteed 404 dressed up as a link. There is no route that maps an
 * upload id to its result, and inventing one is not this screen's job.
 *
 * The three remaining types have no screen of their own either. A notification
 * with no destination renders with no action rather than a control that goes
 * somewhere unrelated — the title and body already carry the information, and
 * that is what D5.9 §2 means by "a notification is a pointer".
 *
 * Kept deliberately consistent with `pushClientBridge.destinationFor` so that
 * tapping a push and tapping the same row in this inbox land in the same place.
 */
export function destinationFor(notification: Notification): string | null {
  switch (notification.type) {
    case "announcement":
      return "/student/announcements"
    default:
      return null
  }
}

/**
 * A relative age, at day granularity and no finer.
 *
 * Deliberately not an hour-precise "3 hours ago": the same reasoning S-28's
 * countdown and S-29's week boundary used — a number the reader watches must
 * not move while they are looking at it, and an inbox is re-read often enough
 * for a drifting timestamp to be noticeable. The exact instant stays available
 * in the `<time dateTime>` attribute for anyone who needs it.
 */
export function formatAge(iso: string, now: Date = new Date()): string {
  const created = new Date(iso)
  if (Number.isNaN(created.getTime())) return ""
  const days = Math.floor((now.getTime() - created.getTime()) / 86_400_000)
  if (days <= 0) return "Today"
  if (days === 1) return "Yesterday"
  if (days < 7) return `${days} days ago`
  const weeks = Math.floor(days / 7)
  if (weeks === 1) return "1 week ago"
  if (weeks < 5) return `${weeks} weeks ago`
  return created.toLocaleDateString(undefined, { day: "numeric", month: "short" })
}

function NotificationRow({ notification }: { notification: Notification }) {
  const navigate = useNavigate()
  const markRead = useMarkNotificationRead()
  const unread = notification.readAt === null
  const destination = destinationFor(notification)

  const open = (): void => {
    if (unread) markRead.mutate(notification.notificationId)
    if (destination !== null) void navigate(destination)
  }

  return (
    <Card
      className={cn(
        "transition-colors",
        // Same unread marker as S-28's, for the same reason: a bold title
        // fights the heading hierarchy and stops reading as emphasis once
        // three in a row are unread.
        unread && "border-l-2 border-l-accent",
      )}
    >
      <CardBody className="flex flex-col gap-2">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="text-body-lg font-medium text-t1">{notification.title}</h3>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-2xs text-t3">
              <Chip tone={notification.type === "at_risk_alert" ? "warn" : "neutral"}>
                {typeLabel(notification.type)}
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
          <p className="text-body text-t2">{notification.body}</p>
        ) : null}

        <div className="flex flex-wrap gap-2">
          {destination !== null ? (
            <Button size="sm" onClick={open}>
              Open
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

export function Notifications() {
  const { data, isPending, isError, refetch } = useNotifications()
  const markAll = useMarkAllNotificationsRead()

  if (isPending) {
    return <div className="text-body text-t3">Loading your notifications…</div>
  }

  if (isError) {
    return (
      <ErrorState
        heading="Notifications could not be loaded"
        // An empty inbox and a failed fetch look identical if this lies, and
        // the difference matters: one means nothing has happened, the other
        // means something may have and we cannot show it.
        body="This is a connection problem on our side. You may well have notifications waiting — nothing has been lost."
        action={{ label: "Try again", onClick: () => void refetch() }}
      />
    )
  }

  if (data.notifications.length === 0) {
    return (
      <EmptyState
        heading="Nothing yet"
        body="When a paper is marked, a teacher posts an announcement, or your streak is about to break, it will appear here."
      />
    )
  }

  const unreadCount = data.notifications.filter((n) => n.readAt === null).length

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Eyebrow>Inbox</Eyebrow>
          <h1 className="text-title text-t1">Notifications</h1>
        </div>
        <div className="flex items-center gap-3">
          {/* The inbox is where a reader notices they are getting too much or
              too little, so it is where the settings for that belong. Until the
              portal navs grow an entry (P5.9 chunk D), this is also the only
              route to G-12 for a student. */}
          <Link
            to="/settings/notifications"
            className="text-body-sm text-accent hover:underline"
          >
            Notification settings
          </Link>
          {unreadCount > 0 ? (
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
  )
}
