import { useState } from "react"
import { Card } from "@/components/ui/card"
import {
  boardHeader,
  boards,
  scopes,
  streakCells,
  subjectRanks,
  type LeaderboardScope,
} from "../data"
import { vizText } from "../components/colors"

/*
 * Standings (isBoard). A scope-switching leaderboard (friends / school /
 * global) with the current student highlighted, a 28-cell streak heatmap, and
 * a per-subject ranking list.
 */
export function Standings() {
  const [scope, setScope] = useState<LeaderboardScope>("friends")
  const board = boards[scope]

  return (
    <div className="lm-screen flex flex-col gap-[22px]">
      <div className="flex items-end gap-5 flex-wrap">
        <div>
          <div className="font-serif text-[36px] leading-[1.1]">
            {boardHeader.title}
          </div>
          <div className="text-[14px] text-t2 mt-[7px]">{boardHeader.intro}</div>
        </div>
        <div className="flex-1" />
        <div className="flex gap-1.5 bg-surface-2 p-1 rounded-[11px]">
          {scopes.map((sc) => {
            const active = sc.id === scope
            return (
              <button
                key={sc.id}
                onClick={() => setScope(sc.id)}
                className={`border-0 cursor-pointer font-sans text-[12.5px] px-[15px] py-2 rounded-lg ${
                  active
                    ? "bg-surface text-t1 font-medium"
                    : "bg-transparent text-t2"
                }`}
              >
                {sc.label}
              </button>
            )
          })}
        </div>
      </div>

      <div className="lm-cols grid grid-cols-[1.4fr_1fr] gap-5 items-start max-[1180px]:grid-cols-1">
        <Card className="overflow-hidden">
          {board.map((b) => {
            const me = b.name === "Maya Rahman"
            return (
              <div
                key={b.rank + b.name}
                className={`grid grid-cols-[40px_34px_1fr_120px_88px] gap-[14px] items-center px-5 py-[13px] border-b border-border ${me ? "bg-accent-subtle" : "bg-transparent"}`}
              >
                <span
                  className={`font-mono text-[13px] ${me ? "text-accent" : "text-t2"}`}
                >
                  {b.rank}
                </span>
                <span
                  className={`w-[30px] h-[30px] rounded-full flex items-center justify-center text-[11.5px] font-semibold ${me ? "bg-accent text-accent-on" : "bg-surface-2 text-t2"}`}
                >
                  {b.initials}
                </span>
                <span className={`text-[13.5px] ${me ? "font-semibold" : ""}`}>
                  {b.name}
                </span>
                <span className="text-[11.5px] text-t2">{b.detail}</span>
                <span className="font-mono text-[13.5px] text-right">
                  {b.pts}
                </span>
              </div>
            )
          })}
        </Card>

        <div className="flex flex-col gap-5">
          <Card className="p-5">
            <div className="text-[15px] font-semibold mb-1">
              {boardHeader.streakTitle}
            </div>
            <div className="text-[12.5px] text-t2 mb-4">
              {boardHeader.streakSub}
            </div>
            <div className="grid grid-cols-[repeat(14,1fr)] gap-[5px]">
              {streakCells.map((c, i) => (
                <div
                  key={i}
                  className="aspect-square rounded-[4px]"
                  style={{
                    background:
                      c.kind === "empty"
                        ? "oklch(0.92 0.008 40)"
                        : c.kind === "rest"
                          ? "oklch(0.90 0.02 40)"
                          : `oklch(${c.intensity.toFixed(3)} 0.09 35)`,
                  }}
                />
              ))}
            </div>
          </Card>

          <Card className="p-5">
            <div className="text-[15px] font-semibold mb-[14px]">
              Subject standings
            </div>
            <div className="flex flex-col gap-[11px]">
              {subjectRanks.map((s) => (
                <div key={s.code} className="flex items-center gap-3">
                  <span className="font-mono text-[11.5px] text-t2 w-[38px]">
                    {s.code}
                  </span>
                  <span className="text-[12.5px] flex-1">{s.name}</span>
                  <span className={`font-mono text-[12.5px] ${vizText(s.color)}`}>
                    {s.rank}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
