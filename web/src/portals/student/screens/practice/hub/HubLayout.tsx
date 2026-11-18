/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 */
import type { ReactNode } from "react"

/**
 * Places the hub's areas. Phone and tablet: one column in mock order. Desktop
 * (`lg`): homework and Binny share a row (`.phr`; Binny alone when there is no
 * homework), tiles across, then two
 * columns (`.pcols`, gap 40). The screen passes Binny into exactly one of the
 * two slots, so it mounts once at every width.
 */
export function HubLayout({
  homework,
  binnyTop,
  binnyAfterTiles,
  tiles,
  middle,
  win,
  recent,
}: {
  homework: ReactNode
  binnyTop: ReactNode
  binnyAfterTiles: ReactNode
  tiles: ReactNode
  middle: ReactNode
  win: ReactNode
  recent: ReactNode
}) {
  return (
    <div className="flex flex-col gap-6 lg:gap-5">
      {homework ? (
        <div className="flex flex-col gap-6 lg:grid lg:grid-cols-[minmax(0,560px)_minmax(0,1fr)] lg:items-center lg:gap-6">
          <div>{homework}</div>
          {binnyTop}
        </div>
      ) : (
        // No homework: Binny leads the page from the start edge rather than floating in an empty column.
        binnyTop
      )}
      {tiles}
      {binnyAfterTiles}
      {middle}
      {win || recent ? (
        <div className="flex flex-col gap-6 lg:grid lg:grid-cols-2 lg:items-start lg:gap-x-10">
          {win ? <div className="flex flex-col gap-6">{win}</div> : null}
          {recent ? <div>{recent}</div> : null}
        </div>
      ) : null}
    </div>
  )
}
