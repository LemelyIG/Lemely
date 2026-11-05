/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Link, useNavigate } from "react-router-dom"
import { Bell, Megaphone, Warning, type Icon } from "@phosphor-icons/react"
import { DropdownMenu } from "radix-ui"
import { useMarkAllNotificationsRead, useMarkNotificationRead, useNotifications } from "@/lib/hooks/useNotificationApi"
import type { Notification } from "@/lib/notificationTypes"
import { STAFF_INBOX_ERROR, TEACHER_INBOX_EMPTY, showMarkAllRead, staffDestinationFor } from "@/lib/staffInbox"
import { formatAge } from "@/portals/student/screens/Notifications"
import { cn } from "@/lib/utils"
import { FOCUS_RING, IconTile } from "./TopBarSheets"
import { ANNOUNCEMENTS_TO, INBOX_TO, NOTIFICATION_PREVIEW_LIMIT } from "./topBarActions"

/** Same panel surface as the profile menu, a little wider for a title plus a line of detail. */
const PANEL_SURFACE =
  "z-dropdown w-[22rem] max-w-[calc(100vw-20px)] rounded-card bg-surface-container-lowest p-2 text-on-surface shadow-[var(--shadow-float)] dark:bg-surface-container-high motion-safe:animate-[lm-in_var(--dur-base)_var(--ease-out-soft)_both]"

const ROW =
  "flex w-full cursor-pointer items-start gap-3 rounded-lg p-2.5 text-start text-on-surface transition-colors duration-150 data-[highlighted]:bg-surface-container-low dark:data-[highlighted]:bg-surface-container-highest focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary"

const TYPE_ICON: Record<string, Icon> = { at_risk_alert: Warning, announcement: Megaphone }

function Row({ notification }: { notification: Notification }) {
  const navigate = useNavigate()
  const markRead = useMarkNotificationRead()
  const unread = notification.readAt === null
  const destination = staffDestinationFor("teacher", notification)
  const Glyph = TYPE_ICON[notification.type] ?? Bell
  return (
    <DropdownMenu.Item
      className={ROW}
      onSelect={() => {
        if (unread) markRead.mutate(notification.notificationId)
        void navigate(destination ?? INBOX_TO)
      }}
    >
      <IconTile><Glyph size={20} aria-hidden="true" /></IconTile>
      <span className="min-w-0 flex-1">
        <span className={cn("line-clamp-2 text-label", unread ? "font-bold" : "font-medium")}>{notification.title}</span>
        {notification.body ? (
          <span className="block truncate text-body-sm text-on-surface-variant">{notification.body}</span>
        ) : null}
      </span>
      <span className="flex flex-none flex-col items-end gap-1.5 pt-0.5">
        <time dateTime={notification.createdAt} className="text-data-sm text-on-surface-variant">
          {formatAge(notification.createdAt)}
        </time>
        {unread ? (
          <>
            <span aria-hidden className="h-2 w-2 rounded-pill bg-primary" />
            <span className="sr-only">Unread</span>
          </>
        ) : null}
      </span>
    </DropdownMenu.Item>
  )
}

/** Mounts only while the panel is open, so the inbox is fetched on first open, not on every page load. */
function Panel() {
  const query = useNotifications()
  const markAll = useMarkAllNotificationsRead()
  const page = query.data
  return (
    <>
      <div className="flex items-center justify-between px-2.5 pb-2 pt-1.5">
        <p className="text-label">Notifications</p>
        {page && showMarkAllRead(page) ? (
          <button
            type="button"
            onClick={() => markAll.mutate()}
            disabled={markAll.isPending}
            className={cn("rounded-md text-body-sm font-bold text-primary hover:underline disabled:opacity-60", FOCUS_RING)}
          >
            Mark all read
          </button>
        ) : null}
      </div>
      {query.isPending ? (
        <p role="status" className="px-2.5 py-6 text-center text-body-sm text-on-surface-variant">Loading</p>
      ) : query.isError ? (
        <div role="alert" className="px-2.5 py-4 text-body-sm">
          <p className="font-bold">{STAFF_INBOX_ERROR.heading}</p>
          <button type="button" onClick={() => void query.refetch()} className={cn("mt-1 rounded-md font-bold text-primary hover:underline", FOCUS_RING)}>
            Try again
          </button>
        </div>
      ) : page && page.notifications.length === 0 ? (
        <div className="px-2.5 py-5 text-center">
          <p className="text-label">{TEACHER_INBOX_EMPTY.heading}</p>
          <p className="mt-1 text-body-sm text-on-surface-variant">{TEACHER_INBOX_EMPTY.body}</p>
        </div>
      ) : (
        page?.notifications.slice(0, NOTIFICATION_PREVIEW_LIMIT).map((n) => (
          <Row key={n.notificationId} notification={n} />
        ))
      )}
      <div className="mt-1 flex items-center justify-around border-t border-outline-variant pt-1">
        {[
          { to: INBOX_TO, label: "All notifications" },
          { to: ANNOUNCEMENTS_TO, label: "Announcements" },
        ].map((link) => (
          <DropdownMenu.Item key={link.to} asChild>
            <Link to={link.to} className="cursor-pointer rounded-lg px-3 py-2.5 text-label text-primary data-[highlighted]:bg-surface-container-low dark:data-[highlighted]:bg-surface-container-highest focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary">
              {link.label}
            </Link>
          </DropdownMenu.Item>
        ))}
      </div>
    </>
  )
}

/**
 * The bell in the top bar and the panel it drops, the same shape as the
 * profile menu: Radix DropdownMenu, anchored to the trigger, no scroll lock.
 * `unread` is the badge text from the counts endpoint, which the shell already
 * reads, so the badge shows before the panel is ever opened.
 */
export function NotificationsMenu({ unread, triggerClassName }: { unread: string | null; triggerClassName: string }) {
  return (
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        className={triggerClassName}
      >
        <Bell size={20} aria-hidden="true" />
        {unread ? (
          <span className="absolute -end-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-pill bg-primary px-1 text-data-sm text-on-primary">
            {unread}
          </span>
        ) : null}
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={8} collisionPadding={10} className={PANEL_SURFACE}>
          <Panel />
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
