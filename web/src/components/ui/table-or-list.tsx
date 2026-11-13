import { useEffect, useState, type ReactNode } from "react"
import { useNativeFrame } from "@/lib/useNativeFrame"

/** Native frame: dense teacher tables read as list rows on phones, with
 * "View table" for when the grid itself is the point (brief decision 4). */
export function TableOrList({
  label,
  table,
  list,
  storageKey,
  tableHeader,
  notices,
  onListView,
}: {
  label: string
  table: ReactNode
  list: ReactNode
  storageKey: string
  /** Controls that act on the table's rows (bulk bars). Shown with the table
   * on every platform, never in the native list view, which has no row state. */
  tableHeader?: ReactNode
  /** Outcome messages for those controls (errors, results). Shown straight
   * after `tableHeader` off native, and in both native views so a teacher who
   * switches to the list still sees and hears the outcome. */
  notices?: ReactNode
  /** Called whenever the native frame resolves to the list view: on toggle,
   * and when the frame becomes native (rotation) already showing the list. */
  onListView?: () => void
}) {
  const { native } = useNativeFrame()
  const [asTable, setAsTable] = useState(() => {
    try {
      return typeof sessionStorage !== "undefined" && sessionStorage.getItem(storageKey) === "table"
    } catch {
      return false
    }
  })
  const listActive = native && !asTable
  useEffect(() => {
    if (listActive) onListView?.()
    // onListView is a fresh closure each render; only the view resolving matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listActive])
  if (!native) return <>{tableHeader}{notices}{table}</>
  const toggle = () => {
    const next = !asTable
    setAsTable(next)
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
      {notices}
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
