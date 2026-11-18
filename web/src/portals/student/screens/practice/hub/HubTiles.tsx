/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useNavigate } from "react-router-dom"
import { Tile } from "@/components/redesign"
import { CardsIcon, PaperIcon, SetIcon, TestIcon } from "../practiceIcons"
import type { TileView } from "./hubModel"

const ICONS = { set: SetIcon, cards: CardsIcon, paper: PaperIcon, test: TestIcon } as const

/**
 * `.pgrid.tint` (2 up) and `.pgrid.tint.four` (4 up from md). Tiles that open a
 * page are links. The set tile opens the builder sheet over the hub, so it is a
 * button that pushes the builder route with `fromHub`, letting Close pop back
 * instead of stacking a second hub entry.
 */
export function HubTiles({ tiles }: { tiles: readonly TileView[] }) {
  const navigate = useNavigate()
  return (
    <ul aria-label="Ways to practise" className="grid grid-cols-2 gap-2.5 md:grid-cols-4 md:gap-3">
      {tiles.map((t) => {
        const to = t.to
        const opensSheet = t.key === "set"
        return (
          <li key={t.key} className="contents">
            <Tile
              icon={ICONS[t.key]}
              title={t.title}
              status={
                t.count !== null ? (
                  <>
                    <b className="font-mono text-[15px] font-extrabold text-primary">{t.count}</b> due today
                  </>
                ) : (
                  t.status
                )
              }
              tone={t.tone}
              disabled={t.disabled}
              to={to && !opensSheet ? to : undefined}
              onClick={to && opensSheet ? () => navigate(to, { state: { fromHub: true } }) : undefined}
            />
          </li>
        )
      })}
    </ul>
  )
}
