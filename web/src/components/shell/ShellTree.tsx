/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useEffect, useId, useState, type ReactNode } from "react"
import type { NavShellItem } from "@/components/ui/nav-shells"
import { cn } from "@/lib/utils"
import { ShellIcon } from "./icons"
import { ShellNavList } from "./ShellNavList"
import { currentRowId, initialOpenIds, openOnNavigate, toggleOpen } from "./shellTree"
import { SHELL_FOCUS_RING } from "./shellStyles"

export interface ShellTreeRow {
  id: string
  label: string
  /** Native tooltip, e.g. "Additional Mathematics · 0606". */
  title?: string
  /** Short mono text after the label (the CAIE code). */
  trailing?: string
  /** Right-most adornment (the grade ring). */
  adornment?: ReactNode
  children: NavShellItem[]
}

export interface ShellTreeProps {
  labelledBy: string
  rows: readonly ShellTreeRow[]
  /** The row the current route belongs to; it starts open. */
  currentId: string | null
  /** Opened when no row matches the route (Overview plan: today's session subject). */
  fallbackId?: string | null
  /** Shown instead of rows when there are none; null renders nothing. */
  empty?: ReactNode
}

/** Design A `.as-subjects`: one disclosure button per row (`aria-expanded`,
 * `aria-controls`), its sub-links in a list that is `hidden` when closed.
 * Enter and Space toggle (native button). */
export function ShellTree({ labelledBy, rows, currentId, fallbackId = null, empty }: ShellTreeProps) {
  const baseId = useId()
  const rowIds = rows.map((r) => r.id)
  const [open, setOpen] = useState(() => initialOpenIds(rowIds, currentId, fallbackId))
  const tinted = currentRowId(rowIds, currentId, fallbackId)
  useEffect(() => {
    setOpen((prev) => openOnNavigate(prev, currentId && rowIds.includes(currentId) ? currentId : null))
    // rowIds is derived from rows; re-run when the route or the row set changes.
  }, [currentId, rowIds.join("|")]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ul aria-labelledby={labelledBy} className="m-0 flex list-none flex-col gap-px p-0">
      {rows.length === 0 && empty ? (
        <li className="px-2.5 py-1.5 text-body-sm text-on-surface-variant">{empty}</li>
      ) : null}
      {rows.map((row) => {
        const expanded = open.has(row.id)
        const subId = `${baseId}-${row.id}`
        return (
          <li key={row.id} data-current={row.id === tinted || undefined}>
            <button
              type="button"
              aria-expanded={expanded}
              aria-controls={subId}
              title={row.title}
              onClick={() => setOpen((prev) => toggleOpen(prev, row.id))}
              className={cn(
                "group flex w-full cursor-pointer items-center gap-2.5 rounded-chip px-2.5 py-1.5 text-start text-label transition-colors duration-150 pointer-coarse:min-h-11",
                // Design A tints the current row (`li[data-current] > .as-subj`), hover included.
                row.id === tinted
                  ? "bg-primary-container text-on-primary-container"
                  : "text-on-surface hover:bg-surface-container",
                SHELL_FOCUS_RING,
              )}
            >
              <ShellIcon
                name="chev"
                className="text-on-surface-variant transition-transform duration-200 group-aria-expanded:rotate-90 rtl:-scale-x-100 rtl:group-aria-expanded:rotate-90"
              />
              <span className="min-w-0 flex-1 truncate [text-box:trim-both_cap_alphabetic]">{row.label}</span>
              {row.trailing ? (
                <small className="ms-auto font-mono text-2xs font-medium tabular-nums text-on-surface-variant">
                  {row.trailing}
                </small>
              ) : null}
              {row.adornment}
            </button>
            <ShellNavList id={subId} hidden={!expanded} items={row.children} className="py-px [&_a]:ps-[38px]" />
          </li>
        )
      })}
    </ul>
  )
}
