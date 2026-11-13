import { useState, type ReactNode } from "react"
import { useNativeFrame } from "@/lib/useNativeFrame"

/** Native frame: dense teacher tables read as list rows on phones, with
 * "View table" for when the grid itself is the point (brief decision 4). */
export function TableOrList({
  label,
  table,
  list,
  storageKey,
  tableHeader,
  onViewChange,
}: {
  label: string
  table: ReactNode
  list: ReactNode
  storageKey: string
  /** Controls that act on the table's rows (bulk bars). Shown with the table
   * on every platform, never in the native list view, which has no row state. */
  tableHeader?: ReactNode
  /** Called when the native toggle switches views. */
  onViewChange?: (view: "list" | "table") => void
}) {
  const { native } = useNativeFrame()
  const [asTable, setAsTable] = useState(() => {
    try {
      return typeof sessionStorage !== "undefined" && sessionStorage.getItem(storageKey) === "table"
    } catch {
      return false
    }
  })
  if (!native) return <>{tableHeader}{table}</>
  const toggle = () => {
    const next = !asTable
    setAsTable(next)
    onViewChange?.(next ? "table" : "list")
    try {
      sessionStorage.setItem(storageKey, next ? "table" : "list")
    } catch {
      /* private mode: the choice lasts until reload */
    }
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex justify-end px-4">
        <button type="button" onClick={toggle} className="lm-press text-label text-primary">
          {asTable ? "View list" : "View table"}
        </button>
      </div>
      {asTable ? tableHeader : null}
      {asTable ? (
        <div role="region" aria-label={label} tabIndex={0} className="-mx-4 overflow-x-auto px-4 lm-scroll">
          {table}
        </div>
      ) : (
        list
      )}
    </div>
  )
}
