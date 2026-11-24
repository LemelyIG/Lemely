/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 */
import type { ReactNode } from "react"

/**
 * Places the hub's areas. Phone and tablet: one column in mock order. Desktop
 * (`lg`): Binny leads from the start edge, tiles across, then two
 * columns (`.pcols`, gap 40). The screen passes Binny into exactly one of the
 * two slots, so it mounts once at every width.
 */
export function HubLayout({
  binnyTop,
  binnyAfterTiles,
  tiles,
  middle,
  win,
  recent,
}: {
  binnyTop: ReactNode
  binnyAfterTiles: ReactNode
  tiles: ReactNode
  middle: ReactNode
  win: ReactNode
  recent: ReactNode
}) {
  return (
    <div className="flex flex-col gap-6 lg:gap-5">
      {binnyTop}
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
