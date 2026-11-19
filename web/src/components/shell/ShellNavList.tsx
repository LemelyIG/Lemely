/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { NavShellLink, type NavShellItem } from "@/components/ui/nav-shells"
import { cn } from "@/lib/utils"
import { SHELL_FOCUS_RING } from "./shellStyles"

/** `.as-list a` / `.as-sub a` */
export const SHELL_ROW =
  "flex w-full items-center gap-2.5 rounded-chip px-2.5 py-[9px] text-start text-label transition-colors duration-150 pointer-coarse:min-h-11 " +
  SHELL_FOCUS_RING

/** `.as-lb` */
export const SHELL_LABEL = "min-w-0 flex-1 [text-box:trim-both_cap_alphabetic]"

export function shellRowClass(active: boolean): string {
  return cn(
    SHELL_ROW,
    active ? "bg-primary-container text-primary" : "text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface",
  )
}

/** Design A's nav rows. Links come from nav-shells' `NavShellLink` (react-router
 * `NavLink`, `viewTransition`, `aria-current="page"`). No landmark of its own:
 * the sidebar is the one `nav`. */
export interface ShellNavListProps {
  items: readonly NavShellItem[]
  className?: string
  id?: string
  hidden?: boolean
  "aria-labelledby"?: string
}

export function ShellNavList({ items, className, id, hidden, "aria-labelledby": labelledBy }: ShellNavListProps) {
  return (
    <ul
      id={id}
      hidden={hidden}
      aria-labelledby={labelledBy}
      className={cn("m-0 flex list-none flex-col gap-px p-0", hidden && "hidden", className)}
    >
      {items.map((item) => (
        <li key={item.id}>
          <NavShellLink item={item} className={shellRowClass}>
            {(active) => (
              <>
                {item.icon}
                <span className={SHELL_LABEL}>{item.label}</span>
                {item.badge !== undefined ? (
                  <span
                    className={cn(
                      "ms-auto rounded-pill px-[7px] py-px font-mono text-2xs font-semibold tabular-nums",
                      active || item.urgent ? "bg-primary text-on-primary" : "bg-surface-container-high text-on-surface",
                    )}
                  >
                    {item.badge}
                  </span>
                ) : null}
              </>
            )}
          </NavShellLink>
        </li>
      ))}
    </ul>
  )
}
