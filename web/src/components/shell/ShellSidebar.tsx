/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useId, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { BrandLockup } from "@/components/ui/brand-lockup"
import type { NavShellItem } from "@/components/ui/nav-shells"
import { cn } from "@/lib/utils"
import { ShellIcon } from "./icons"
import { ShellAvatar } from "./ShellAvatar"
import { ShellNavList } from "./ShellNavList"
import { SHELL_FOCUS_RING, SHELL_ICON_BUTTON } from "./shellStyles"

export interface ShellSidebarGroup {
  id: string
  label: string
  render: (labelId: string) => ReactNode
}

export interface ShellSidebarProps {
  variant: "rail" | "drawer"
  /** aria-label of the sidebar's single nav landmark. */
  navLabel: string
  homeTo: string
  /** aria-label of the wordmark link, e.g. "Lemely, overview". */
  homeLabel: string
  items: readonly NavShellItem[]
  groups?: readonly ShellSidebarGroup[]
  /** The foot's primary action (Upload). Hidden in the phone sheet, where the bottom bar has it. */
  footerAction?: ReactNode
  /** Under the wordmark, above the nav list: the parent child switcher (mock pa.js rail2 .kid). */
  lead?: ReactNode
  user: ReactNode
  /** Drawer only: renders the close button in the head. */
  onClose?: () => void
}

export type ShellSidebarContent = Omit<ShellSidebarProps, "variant" | "onClose">

const RAIL =
  "lm-scroll sticky top-0 hidden h-dvh w-shell-sidebar flex-none overflow-y-auto overscroll-contain bg-surface-container-lowest px-3 pt-[18px] pb-3 shadow-[1px_0_0_var(--color-outline-variant)] rtl:shadow-[-1px_0_0_var(--color-outline-variant)] shell-lg:flex"

const DRAWER =
  "lm-scroll flex min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pt-[18px] pb-3 max-shell-sm:pt-3 max-shell-sm:pb-[calc(1rem+env(safe-area-inset-bottom))]"

function Group({ group }: { group: ShellSidebarGroup }) {
  const labelId = useId()
  return (
    <>
      <p id={labelId} className="mx-2.5 mt-1.5 -mb-1.5 text-eyebrow text-on-surface-variant">
        {group.label}
      </p>
      {group.render(labelId)}
    </>
  )
}

/** Design A `.as-side`: the sidebar is the portal's one `nav` landmark. The
 * rail is a sticky column from `shell-lg`; the drawer variant is the same
 * content inside `NavDrawer variant="shell"` (a floating drawer, a bottom
 * sheet on phones). */
export function ShellSidebar({ variant, navLabel, homeTo, homeLabel, items, groups, footerAction, lead, user, onClose }: ShellSidebarProps) {
  const rail = variant === "rail"
  return (
    <nav aria-label={navLabel} className={cn("flex-col gap-4 text-on-surface", rail ? RAIL : DRAWER)}>
      <div className="flex items-start justify-between">
        <Link
          to={homeTo}
          aria-label={homeLabel}
          className={cn("inline-flex self-start rounded-chip px-2 pt-0.5 pb-2", SHELL_FOCUS_RING, !rail && "max-shell-sm:invisible")}
        >
          {/* `!`: the unlayered `.wordmark-sm` (26px) beats a plain layered utility. */}
          <BrandLockup as="span" className="[--wm-size:32px]! [&_svg]:w-[0.451em]" />
        </Link>
        {onClose ? (
          <button type="button" onClick={onClose} aria-label="Close menu" className={SHELL_ICON_BUTTON}>
            <ShellIcon name="x" />
          </button>
        ) : null}
      </div>
      {lead ? <div className="flex px-0.5">{lead}</div> : null}
      <ShellNavList items={items} />
      {groups?.map((group) => <Group key={group.id} group={group} />)}
      <div className="mt-auto flex flex-col gap-3 border-t border-outline-variant pt-4">
        {footerAction ? (
          <div className={cn("flex flex-col [&>*]:justify-center", !rail && "max-shell-sm:hidden")}>{footerAction}</div>
        ) : null}
        {user}
      </div>
    </nav>
  )
}

/** `.as-user`: who is signed in, under the foot's action. */
export function ShellUserBlock({ name, avatarUrl, detail }: { name: string; avatarUrl?: string | null; detail: string | null }) {
  return (
    <div className="flex items-center gap-2.5 px-0.5">
      <ShellAvatar name={name} src={avatarUrl} />
      <span className="flex min-w-0 flex-col">
        <b className="truncate text-(length:--fs-body-sm) font-medium leading-[1.45] text-on-surface">{name}</b>
        {detail ? <small className="truncate text-body-sm text-on-surface-variant">{detail}</small> : null}
      </span>
    </div>
  )
}
