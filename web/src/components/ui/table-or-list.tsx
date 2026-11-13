import { useState, type ReactNode } from "react"
import { useNativeFrame } from "@/lib/useNativeFrame"

/** Native frame: dense teacher tables read as list rows on phones, with
 * "View table" for when the grid itself is the point (brief decision 4). */
export function TableOrList({ label, table, list, storageKey }: { label: string; table: ReactNode; list: ReactNode; storageKey: string }) {
  const { native } = useNativeFrame()
  const [asTable, setAsTable] = useState(() => {
    try {
      return typeof sessionStorage !== "undefined" && sessionStorage.getItem(storageKey) === "table"
    } catch {
      return false
    }
  })
  if (!native) return <>{table}</>
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
