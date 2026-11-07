import type { ReactNode } from "react"
import { Link, useNavigate } from "react-router-dom"
import { DropdownMenu } from "radix-ui"
import { useMarkAllNotificationsRead, useMarkNotificationRead, useNotifications } from "@/lib/hooks/useNotificationApi"
import type { Notification } from "@/lib/notificationTypes"
import { unreadCountOf } from "@/lib/staffInbox"
import { cn } from "@/lib/utils"
import { ShellIcon } from "./icons"
import { notificationsTriggerLabel, panelTimeLabel } from "./shellModel"
import { SHELL_FOCUS_RING, SHELL_PANEL } from "./shellStyles"

export interface NotificationsPanelProps {
  /** Badge text from the counts query (`unreadBadgeLabel`), null for none. */
  unread: string | null
  triggerClassName: string
  /** Where a row goes; null sends the reader to `inboxTo`. */
  destinationFor: (notification: Notification) => string | null
  /** The glyph for a row's notification type. */
  iconFor: (type: string) => ReactNode
  inboxTo: string
  footerLinks: readonly { to: string; label: string }[]
  emptyMessage: string
  errorHeading: string
  /** Rows shown; default 4. */
  previewLimit?: number
}

type PanelProps = Omit<NotificationsPanelProps, "unread" | "triggerClassName">

const ITEM =
  "grid w-full cursor-pointer grid-cols-[32px_minmax(0,1fr)_auto] items-start gap-2.5 rounded-chip p-2 text-start text-(length:--fs-body-sm) leading-normal text-on-surface transition-colors duration-150 data-[highlighted]:bg-surface-container-low focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary"

const FOOT_LINK =
  "flex-1 cursor-pointer rounded-chip p-2 text-center text-2xs font-semibold leading-[1.3] text-primary transition-colors duration-150 data-[highlighted]:bg-surface-container-low pointer-coarse:min-h-11 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary"

function Row({
  notification,
  destinationFor,
  iconFor,
  inboxTo,
}: { notification: Notification } & Pick<PanelProps, "destinationFor" | "iconFor" | "inboxTo">) {
  const navigate = useNavigate()
  const markRead = useMarkNotificationRead()
  const unread = notification.readAt === null
  return (
    <DropdownMenu.Item
      className={ITEM}
      onSelect={() => {
        if (unread) markRead.mutate(notification.notificationId)
        void navigate(destinationFor(notification) ?? inboxTo)
      }}
    >
      <span className="grid size-8 place-items-center rounded-row bg-primary-container text-primary">
        {iconFor(notification.type)}
      </span>
      <span className="flex min-w-0 flex-col">
        {unread ? <span className="sr-only">Unread: </span> : null}
        <b className="line-clamp-2 font-bold text-on-surface [text-wrap:pretty]">{notification.title}</b>
        {notification.body ? (
          <small className="text-2xs leading-normal text-on-surface-variant">{notification.body}</small>
        ) : null}
      </span>
      <time
        dateTime={notification.createdAt}
        className="flex flex-col items-end gap-2 font-mono text-2xs font-medium leading-[1.3] text-on-surface-variant"
      >
        {panelTimeLabel(notification.createdAt)}
        {unread ? <span aria-hidden="true" className="size-2 rounded-pill bg-primary" /> : null}
      </time>
    </DropdownMenu.Item>
  )
}

/** Mounts only while the panel is open, so the inbox is fetched on first open. */
function Panel({ destinationFor, iconFor, inboxTo, footerLinks, emptyMessage, errorHeading, previewLimit }: PanelProps) {
  const query = useNotifications()
  const markAll = useMarkAllNotificationsRead()
  const page = query.data
  const hasRows = Boolean(page && page.notifications.length > 0)
  const unreadRows = page ? unreadCountOf(page) : 0
  return (
    <>
      <div className="mx-2 my-1.5 flex items-baseline justify-between gap-3">
        {/* Not `text-body-sm`: that unlayered `font:` shorthand would undo the weight and leading. */}
        <p className="text-(length:--fs-body-sm) font-extrabold leading-[1.2] tracking-[-0.01em]">Notifications</p>
        {hasRows ? (
          <button
            type="button"
            onClick={() => markAll.mutate()}
            disabled={unreadRows === 0 || markAll.isPending}
            className={cn(
              "-mx-2 -my-1 cursor-pointer rounded-chip px-2 py-1 text-2xs font-semibold leading-[1.3] text-primary transition-colors duration-150 hover:bg-surface-container-low disabled:cursor-default disabled:bg-transparent disabled:text-on-surface-variant pointer-coarse:min-h-11",
              SHELL_FOCUS_RING,
            )}
          >
            Mark all read
          </button>
        ) : null}
      </div>
      {query.isPending ? (
        <p role="status" className="px-2 pt-2 pb-3 text-body-sm text-on-surface-variant">
          Loading
        </p>
      ) : query.isError ? (
        <div role="alert" className="px-2 pt-2 pb-3 text-body-sm">
          <p className="font-bold">{errorHeading}</p>
          <button
            type="button"
            onClick={() => void query.refetch()}
            className={cn("mt-1 rounded-chip font-bold text-primary hover:underline", SHELL_FOCUS_RING)}
          >
            Try again
          </button>
        </div>
      ) : !hasRows ? (
        <p className="px-2 pt-2 pb-3 text-(length:--fs-body-sm) leading-normal text-on-surface-variant">{emptyMessage}</p>
      ) : (
        <div className="flex flex-col">
          {page!.notifications.slice(0, previewLimit ?? 4).map((n) => (
            <Row key={n.notificationId} notification={n} destinationFor={destinationFor} iconFor={iconFor} inboxTo={inboxTo} />
          ))}
        </div>
      )}
      <div className="mt-1 flex gap-1 border-t border-outline-variant pt-1">
        {footerLinks.map((link) => (
          <DropdownMenu.Item key={link.to} asChild>
            <Link to={link.to} className={FOOT_LINK}>
              {link.label}
            </Link>
          </DropdownMenu.Item>
        ))}
      </div>
    </>
  )
}

/**
 * The bell and the panel it drops (Radix DropdownMenu: anchored, no scroll
 * lock, arrow keys, Escape and outside click close it and focus returns to
 * the bell). `unread` comes from the counts query the top bar already reads,
 * so the dot shows before the panel is ever opened.
 */
export function NotificationsPanel({ unread, triggerClassName, ...panel }: NotificationsPanelProps) {
  return (
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger aria-label={notificationsTriggerLabel(unread)} className={triggerClassName}>
        <ShellIcon name="bell" />
        {unread ? (
          <i
            aria-hidden="true"
            className="absolute end-[7px] top-1.5 size-2 rounded-pill bg-primary shadow-[0_0_0_2px_var(--color-surface-container-lowest)]"
          />
        ) : null}
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={8} collisionPadding={10} className={SHELL_PANEL}>
          <Panel {...panel} />
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
