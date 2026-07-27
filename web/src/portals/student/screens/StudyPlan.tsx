import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { days, planCards, planHeader, planRows, type PlanCell } from "../data"

/*
 * Study plan (isPlan) - "Your week". A 7-day timetable grid with focus / light /
 * live / empty blocks, plus three explainer cards below.
 */

function cellClasses(kind: PlanCell["kind"]): string {
  switch (kind) {
    case "focus":
      return "border-[oklch(0.88_0.05_35)] bg-accent-subtle"
    case "live":
      return "border-ink bg-ink"
    case "light":
      return "border-border bg-surface-2"
    case "empty":
      return "border-transparent bg-transparent"
  }
}

function Cell({ cell }: { cell: PlanCell }) {
  if (cell.kind === "empty") {
    return (
      <div className="min-h-[62px] rounded-[10px] border border-transparent" />
    )
  }
  const dark = cell.kind === "live"
  const focus = cell.kind === "focus"
  return (
    <div
      className={`min-h-[62px] rounded-[10px] border px-2.5 py-[9px] flex flex-col gap-[3px] ${cellClasses(cell.kind)}`}
    >
      <div
        className={`text-[12px] font-medium leading-[1.25] ${dark ? "text-bg" : focus ? "text-[oklch(0.34_0.07_35)]" : "text-t1"}`}
      >
        {cell.title}
      </div>
      <div
        className={`text-[10.5px] leading-[1.3] ${dark ? "text-[oklch(0.75_0.01_40)]" : focus ? "text-[oklch(0.46_0.05_35)]" : "text-t2"}`}
      >
        {cell.detail}
      </div>
    </div>
  )
}

export function StudyPlan() {
  return (
    <div className="lm-screen flex flex-col gap-[22px]">
      <div className="flex items-end gap-5 flex-wrap">
        <div>
          <div className="font-serif text-[36px] leading-[1.1]">
            {planHeader.title}
          </div>
          <div className="text-[14px] text-t2 mt-[7px] max-w-[64ch] text-pretty">
            {planHeader.intro}
          </div>
        </div>
        <div className="flex-1" />
        <div className="flex gap-2.5 items-center">
          <div className="text-[12px] text-t2 font-mono">
            {planHeader.weekOf}
          </div>
          <Button variant="secondary" size="sm">
            Adjust hours
          </Button>
        </div>
      </div>

      <Card className="p-5 overflow-auto lm-scroll">
        <div className="grid grid-cols-[56px_repeat(7,minmax(118px,1fr))] gap-2 min-w-[900px]">
          <div />
          {days.map((d) => (
            <div
              key={d.label}
              className="text-[12px] font-medium pb-2 border-b border-border"
            >
              {d.label}{" "}
              <span className="text-t3 font-mono text-[11px]">{d.date}</span>
            </div>
          ))}
          {planRows.map((row) => (
            <div key={row.time} className="contents">
              <div className="font-mono text-[11px] text-t3 pt-1.5">
                {row.time}
              </div>
              {row.cells.map((c, i) => (
                <Cell key={`${row.time}-${i}`} cell={c} />
              ))}
            </div>
          ))}
        </div>
      </Card>

      <div className="lm-cols grid grid-cols-3 gap-5 max-[1180px]:grid-cols-1">
        {planCards.map((p) => (
          <Card key={p.title} className="p-5">
            <div className="text-[11px] tracking-[0.09em] uppercase text-t3">
              {p.kicker}
            </div>
            <div className="text-[15px] font-semibold mt-[7px]">{p.title}</div>
            <div className="text-[12.5px] text-t2 leading-[1.5] mt-[7px] text-pretty">
              {p.body}
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
