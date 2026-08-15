import type { HTMLAttributes, ReactNode } from "react"
import { cn } from "@/lib/utils"

/*
 * C-13 · Navigation shells — `BottomNav` (student, mobile, icon+label tab
 * bar) and `SidebarNav` (teacher/admin, desktop, icon+label vertical list).
 *
 * These are layout shells only: they take a list of items (label, icon,
 * href/onClick, active) rather than hardcoding Lemely's real routes — actual
 * route wiring is the P2.5.3 retrofit task. `item.href` renders a plain
 * `<a>`; if the retrofit wires these to react-router, swap in `NavLink`
 * there (or pass `onClick` + no `href` and let the caller navigate).
 *
 * Both variants expose the current location via `aria-current="page"` (not
 * color alone) and inherit the house focus-visible ring used by Button.
 */

export interface NavShellItem {
  id: string
  label: string
  icon: ReactNode
  href?: string
  onClick?: () => void
  active: boolean
  /** Small trailing marker — unread count, review-queue depth, etc. */
  badge?: string | number
}

interface NavShellLinkOwnProps {
  item: NavShellItem
  className: string
  children: ReactNode
}

function NavShellLink({ item, className, children }: NavShellLinkOwnProps) {
  const current = item.active ? ("page" as const) : undefined

  if (item.href) {
    return (
      <a
        href={item.href}
        onClick={item.onClick}
        aria-current={current}
        className={className}
      >
        {children}
      </a>
    )
  }

  return (
    <button
      type="button"
      onClick={item.onClick}
      aria-current={current}
      className={className}
    >
      {children}
    </button>
  )
}

export interface BottomNavProps extends HTMLAttributes<HTMLElement> {
  items: NavShellItem[]
  className?: string
}

/** Mobile student tab bar — fixed to the viewport bottom. */
export function BottomNav({ items, className, ...props }: BottomNavProps) {
  return (
    <nav
      aria-label="Primary"
      className={cn(
        // P6.3: `z-nav`. The raw `z-30` put a *navigation* bar in the dropdown
        // band, above every menu and popover that would ever need to open over
        // it — the exact inversion the §7 scale exists to prevent.
        "fixed inset-x-0 bottom-0 z-nav flex items-stretch border-t border-border bg-surface",
        className,
      )}
      {...props}
    >
      {items.map((item) => (
        <NavShellLink
          key={item.id}
          item={item}
          className={cn(
            "flex min-h-14 flex-1 flex-col items-center justify-center gap-1 py-2.5 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
            item.active ? "text-accent" : "text-t3 hover:text-t2",
          )}
        >
          <span className="relative flex items-center justify-center">
            {item.icon}
            {item.badge ? (
              <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-err px-0.5 text-metadata leading-none text-white">
                {item.badge}
              </span>
            ) : null}
          </span>
          <span className={cn("text-xs", item.active && "font-medium")}>{item.label}</span>
        </NavShellLink>
      ))}
    </nav>
  )
}

export interface SidebarNavProps extends HTMLAttributes<HTMLElement> {
  items: NavShellItem[]
  className?: string
}

/** Desktop teacher/admin vertical nav list — a current-section indicator, not a full sidebar shell. */
export function SidebarNav({ items, className, ...props }: SidebarNavProps) {
  return (
    <nav aria-label="Primary" className={cn("flex flex-col gap-0.5", className)} {...props}>
      {items.map((item) => (
        <NavShellLink
          key={item.id}
          item={item}
          className={cn(
            // `pointer-coarse:min-h-11` is §6.1's touch floor: measured at 32px
            // tall on every mobile width, and this is the control a student on
            // a phone touches most. Safe as a min because the row already
            // centres its content.
            "flex w-full items-center gap-2.5 rounded-md px-9px py-2 pointer-coarse:min-h-11 text-left text-body-md transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
            item.active
              ? "bg-surface-2 font-medium text-t1"
              : "font-normal text-t2 hover:bg-surface-2",
          )}
        >
          <span className="flex-none">{item.icon}</span>
          <span className="flex-1">{item.label}</span>
          {item.badge ? <span className="text-metadata text-t3">{item.badge}</span> : null}
        </NavShellLink>
      ))}
    </nav>
  )
}
