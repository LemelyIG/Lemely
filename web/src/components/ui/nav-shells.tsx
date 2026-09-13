import type { HTMLAttributes, ReactNode } from "react"
import { NavLink } from "react-router-dom"
import { cn } from "@/lib/utils"

/*
 * C-13 · Navigation shells — `BottomNav` (student/teacher, mobile, icon+label
 * tab bar) and `SidebarNav` (student/teacher/admin, desktop, icon+label
 * vertical list).
 *
 * Packet B3 (Task 4) is the retrofit `nav-drawer.tsx`'s own comment used to
 * name as future work: `NavShellItem` now wires through react-router's
 * `NavLink` when it carries a `to` (route-wired, `viewTransition`, active
 * state from the router itself), and every portal actually mounts these
 * rather than a bespoke copy of the same markup — `BottomNav` as the
 * student/teacher tab bar below the `sidebar` breakpoint, `SidebarNav` as
 * part of all three desktop sidebars above it. `href`/`onClick` stay for the
 * one entry that is not a route (BottomNav's "More", which opens the
 * existing `NavDrawer`) — `to` wins when both could apply.
 *
 * Both variants expose the current location via `aria-current="page"` (not
 * color alone) and inherit the house focus-visible ring used by Button.
 */

/** The retrofit's three shared dimensions, read back by `index.css`'s
 * `--sidebar-width`/`--breakpoint-sidebar`/`--bottom-nav-height` tokens
 * (`design-tokens.test.ts` pins the two sides agree) and by
 * `vite/preMountShell.ts`'s `%LEMELY_SIDEBAR_WIDTH%`/
 * `%LEMELY_SIDEBAR_BREAKPOINT%` placeholders for the pre-mount shell. */
export const SIDEBAR_WIDTH = 252
export const SIDEBAR_BREAKPOINT = 820
export const BOTTOM_NAV_HEIGHT = 56

export interface NavShellItem {
  id: string
  label: string
  icon: ReactNode
  /** A route destination — renders as a router-wired `NavLink`, active state
   * from the router itself. Wins over `href`/`onClick` when present. */
  to?: string
  /** Passed straight to `NavLink`'s own `end` prop; only meaningful with `to`. */
  end?: boolean
  href?: string
  onClick?: () => void
  /** Only consulted for an `href`/`onClick` item (a `to` item's active state
   * comes from the router) — ORed with the router's own match so a caller
   * can still force a `to` item active for a case the router's own
   * prefix-match cannot express (e.g. the teacher sidebar's "Classes" row,
   * active for an out-of-cap class page but not for one of its own visible
   * rows — see `classesItemActive` in `portals/teacher/data.ts`). */
  active?: boolean
  /** Small trailing marker — unread count, review-queue depth, etc. */
  badge?: string | number
  /** Wired by Task 11 (B6): prefetch the destination's chunk on hover/focus. */
  prefetch?: () => void
}

interface NavShellLinkOwnProps {
  item: NavShellItem
  className: (isActive: boolean) => string
  children: (isActive: boolean) => ReactNode
}

function NavShellLink({ item, className, children }: NavShellLinkOwnProps) {
  if (item.to) {
    return (
      <NavLink
        to={item.to}
        end={item.end}
        viewTransition
        onMouseEnter={item.prefetch}
        onFocus={item.prefetch}
        className={({ isActive }) => className(isActive || !!item.active)}
      >
        {({ isActive }) => children(isActive || !!item.active)}
      </NavLink>
    )
  }

  const isActive = !!item.active
  const current = isActive ? ("page" as const) : undefined

  if (item.href) {
    return (
      <a href={item.href} onClick={item.onClick} aria-current={current} className={className(isActive)}>
        {children(isActive)}
      </a>
    )
  }

  return (
    <button type="button" onClick={item.onClick} aria-current={current} className={className(isActive)}>
      {children(isActive)}
    </button>
  )
}

export interface BottomNavProps extends HTMLAttributes<HTMLElement> {
  items: NavShellItem[]
  /** The `item.id` to render as a raised accent-circle emphasis tab (the
   * student portal's "Correct a paper" tab) rather than an ordinary flat
   * icon+label cell. */
  emphasisId?: string
  className?: string
}

/** Mobile student/teacher tab bar — fixed to the viewport bottom. */
export function BottomNav({ items, emphasisId, className, ...props }: BottomNavProps) {
  return (
    <nav
      aria-label="Primary"
      className={cn(
        // P6.3: `z-nav`. The raw `z-30` put a *navigation* bar in the dropdown
        // band, above every menu and popover that would ever need to open over
        // it — the exact inversion the §7 scale exists to prevent.
        "lm-nav-chrome lm-safe-bottom fixed inset-x-0 bottom-0 z-nav flex items-stretch border-t border-border bg-surface",
        className,
      )}
      {...props}
    >
      {items.map((item) => {
        const emphasis = item.id === emphasisId
        return (
          <NavShellLink
            key={item.id}
            item={item}
            className={(isActive) =>
              cn(
                "flex min-h-14 flex-1 flex-col items-center justify-center gap-1 py-2.5 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent active:scale-[0.98]",
                isActive && !emphasis ? "text-accent" : "text-t3 hover:text-t2",
              )
            }
          >
            {(isActive) => (
              <>
                <span
                  className={cn(
                    "relative flex items-center justify-center",
                    emphasis &&
                      "-mt-5 h-11 w-11 rounded-full bg-accent text-accent-on shadow-[var(--shadow-float)]",
                  )}
                >
                  {item.icon}
                  {item.badge ? (
                    <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-err px-0.5 text-metadata leading-none text-accent-on">
                      {item.badge}
                    </span>
                  ) : null}
                </span>
                <span className={cn("text-xs", isActive && "font-medium")}>{item.label}</span>
              </>
            )}
          </NavShellLink>
        )
      })}
    </nav>
  )
}

export interface SidebarNavGroup {
  /** Omitted for a group that renders no eyebrow heading of its own. */
  label?: string
  items: NavShellItem[]
}

export interface SidebarNavProps extends HTMLAttributes<HTMLElement> {
  /** A single flat list — the common case (teacher/admin). */
  items?: NavShellItem[]
  /** Labelled sections — the student sidebar's "Student"/"Marking" split. */
  groups?: SidebarNavGroup[]
  className?: string
}

/** Desktop student/teacher/admin vertical nav list — a current-section
 * indicator, not a full sidebar shell (identity block, "Your classes", the
 * subject accordion all stay in each portal's own `Sidebar`). */
export function SidebarNav({ items, groups, className, ...props }: SidebarNavProps) {
  const sections: SidebarNavGroup[] = groups ?? [{ items: items ?? [] }]

  return (
    <nav
      aria-label="Primary"
      className={cn("flex flex-col", groups ? "gap-[22px]" : "gap-0.5", className)}
      {...props}
    >
      {sections.map((section, index) => (
        // eslint-disable-next-line react/no-array-index-key -- a group has no
        // stable id of its own besides its (optional) label, which two
        // sections could share; index is stable across this array's own
        // re-renders since the caller passes a fixed literal, not a
        // reordering list.
        <div key={section.label ?? index} className="flex flex-col gap-0.5">
          {section.label ? (
            <div className="text-eyebrow text-ink-faint px-2 pb-[7px]">{section.label}</div>
          ) : null}
          {section.items.map((item) => (
            <NavShellLink
              key={item.id}
              item={item}
              className={(isActive) =>
                cn(
                  // `pointer-coarse:min-h-11` is §6.1's touch floor: measured at 32px
                  // tall on every mobile width, and this is the control a student on
                  // a phone touches most. Safe as a min because the row already
                  // centres its content.
                  "flex w-full items-center gap-2.5 rounded-md px-9px py-2 pointer-coarse:min-h-11 text-start text-body-md transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent active:scale-[0.98]",
                  isActive
                    ? "bg-surface-2 font-medium text-t1"
                    : "font-normal text-t2 hover:bg-surface-2",
                )
              }
            >
              {() => (
                <>
                  <span className="flex-none">{item.icon}</span>
                  <span className="flex-1">{item.label}</span>
                  {item.badge ? <span className="text-metadata text-t3">{item.badge}</span> : null}
                </>
              )}
            </NavShellLink>
          ))}
        </div>
      ))}
    </nav>
  )
}
