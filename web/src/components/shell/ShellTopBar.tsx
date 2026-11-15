/* Hallmark · pre-emit critique: P4 H4 E4 S4 R3 V3 */
import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { Gear } from "@phosphor-icons/react"
import { Breadcrumbs, type Crumb } from "@/components/ui/breadcrumbs"
import { useNativeFrame } from "@/lib/useNativeFrame"
import { useNotificationCounts } from "@/lib/hooks/useNotificationApi"
import { useOverlayState } from "@/lib/nav/useOverlayState"
import { unreadBadgeLabel } from "@/lib/staffInbox"
import { cn } from "@/lib/utils"
import type { AccountPanelProps } from "./AccountPanel"
import type { NotificationsPanelProps } from "./NotificationsPanel"
import { ShellAvatarPlaceholder } from "./ShellAvatar"
import { ShellIcon } from "./icons"
import { NativeBack } from "./NativeBack"
import { titleLevelFor } from "./largeTitle"
import { useLargeTitleCollapse } from "./useLargeTitleCollapse"
import { SHELL_ICON_BUTTON } from "./shellStyles"

// Lazy so Radix's menu stays out of the entry chunk's budget (check:bundle).
const NotificationsPanel = lazy(() =>
  import("./NotificationsPanel").then((m) => ({ default: m.NotificationsPanel })),
)
const AccountPanel = lazy(() => import("./AccountPanel").then((m) => ({ default: m.AccountPanel })))

export interface ShellTopBarProps {
  title: string
  /** Breadcrumb trail; rendered only when it has more than one crumb. */
  trail: readonly Crumb[]
  onOpenNav: () => void
  /** aria-label of the menu button, e.g. "Open teacher navigation". */
  navLabel: string
  /** The portal's own bar buttons (Create, Upload), already styled with SHELL_BUTTON_*. */
  actions?: ReactNode
  notifications: Omit<NotificationsPanelProps, "unread" | "triggerClassName">
  settingsTo: string
  /** Overrides the trail-derived level (native frame D2). */
  titleLevel?: "root" | "detail"
  /** iOS only: a root page's own action (teacher Create), trailing in the large-title row; it collapses away with the title. */
  largeTitleAction?: ReactNode
  /** Where the native back chevron goes when there is no history (portal root). */
  backFallback: string
  account: Omit<AccountPanelProps, "triggerClassName">
}

/** `.as-bar.is-stuck`: the bar lifts once the page scrolls under it. */
function useScrolled(): boolean {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const sync = () => setScrolled(window.scrollY > 0)
    sync()
    window.addEventListener("scroll", sync, { passive: true })
    return () => window.removeEventListener("scroll", sync)
  }, [])
  return scrolled
}

const BAR = cn(
  "lm-nav-chrome lm-shell-bar-inset lm-shell-bar-glass sticky top-2 z-nav mx-7 mt-2 mb-6 flex h-14 items-center gap-2 rounded-inner border border-outline-variant bg-surface-container-lowest ps-[17px] pe-[11px] transition-shadow duration-200",
  "data-[stuck=true]:shadow-[var(--shadow-hover)] dark:border-transparent dark:bg-surface-container-high dark:data-[stuck=true]:shadow-none",
  "max-shell-lg:mx-2.5 max-shell-lg:ps-3 max-shell-lg:pe-2.5",
  "max-shell-sm:relative max-shell-sm:top-auto max-shell-sm:m-0 max-shell-sm:h-11 max-shell-sm:rounded-none max-shell-sm:border-0 max-shell-sm:bg-transparent max-shell-sm:ps-3.5 max-shell-sm:pe-2 max-shell-sm:shadow-none",
  // Design A's dark bar rule (`[data-theme=dark] .as-bar`: the card surface)
  // outranks its phone rule's transparent ground, so the dark phone bar is filled.
  "dark:max-shell-sm:bg-surface-container-high",
)

/**
 * The floating top bar (design A `.as-bar`): menu button (drawer range only),
 * the page title, the portal's actions, bell, gear and avatar. The breadcrumb
 * trail renders under it only when the reader has drilled in.
 * Semi-translucent over a backdrop blur (`.lm-shell-bar-glass`), like the landing page header.
 */
export function ShellTopBar({
  title,
  trail,
  onOpenNav,
  navLabel,
  actions,
  notifications,
  settingsTo,
  titleLevel,
  largeTitleAction,
  backFallback,
  account,
}: ShellTopBarProps) {
  const overlayState = useOverlayState()
  const { data: counts } = useNotificationCounts()
  const unread = unreadBadgeLabel(counts)
  const stuck = useScrolled()
  const { native, platform } = useNativeFrame()
  const level = titleLevel ?? titleLevelFor(trail)
  const largeRef = useRef<HTMLParagraphElement>(null)
  const collapsed = useLargeTitleCollapse(largeRef, native && level === "root")
  /** iOS shows the parent page's title beside the chevron (preview `.as-back-l`). */
  const backLabel = trail.at(-2)?.label ?? title
  return (
    <>
      <header
        data-stuck={stuck}
        data-title-level={level}
        data-collapsed={collapsed}
        className={cn(BAR, "lm-native-bar")}
      >
        {level === "detail" ? (
          <NativeBack fallback={backFallback} label={backLabel} />
        ) : null}
        <button
          type="button"
          onClick={onOpenNav}
          aria-label={navLabel}
          aria-haspopup="dialog"
          // Same variant as the sidebar rail's `shell-lg:flex` (1248px), so exactly
          // one of {sidebar column, menu button} shows. The bar's drawer margins
          // (`max-shell-lg:`) follow the same breakpoint.
          className={cn(SHELL_ICON_BUTTON, "shell-lg:hidden max-shell-sm:hidden")}
        >
          <ShellIcon name="menu" />
        </button>
        {/* aria-hidden: the page's h1 carries the name, so a screen reader would hear it twice. */}
        <p data-shell-title aria-hidden="true" className="me-auto min-w-0 truncate text-title-bar text-on-surface lm-native-inline-title">
          {title}
        </p>
        {actions}
        <Suspense
          fallback={
            <Link to={notifications.inboxTo} aria-label="Notifications" className={SHELL_ICON_BUTTON}>
              <ShellIcon name="bell" />
            </Link>
          }
        >
          <NotificationsPanel {...notifications} unread={unread} triggerClassName={SHELL_ICON_BUTTON} />
        </Suspense>
        <span data-shell-action="settings" className="contents">
          <Link
            to={settingsTo}
            state={overlayState}
            aria-label="Settings"
            aria-haspopup="dialog"
            className={SHELL_ICON_BUTTON}
          >
            <Gear size={20} aria-hidden="true" />
          </Link>
        </span>
        <span data-shell-action="account" className="contents">
          <Suspense fallback={<ShellAvatarPlaceholder />}>
            <AccountPanel {...account} />
          </Suspense>
        </span>
      </header>
      <p ref={largeRef} aria-hidden="true" data-shell-large-title className="lm-native-large-title hidden">
        {title}
      </p>
      {native && platform === "ios" && level === "root" && largeTitleAction ? (
        <div className="lm-native-large-action">{largeTitleAction}</div>
      ) : null}
      {trail.length > 1 ? (
        <div className="-mt-3 mb-4 px-[72px] max-shell-lg:px-3.5 native:hidden">
          <Breadcrumbs items={[...trail]} />
        </div>
      ) : null}
    </>
  )
}
