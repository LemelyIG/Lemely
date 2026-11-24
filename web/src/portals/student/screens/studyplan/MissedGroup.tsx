/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { COPY } from "./planCopy"
import type { SessionVM } from "./planModel"

const focus = "focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"
const bar =
  "flex min-h-12 items-center justify-between gap-2.5 rounded-[14px] bg-error-container ps-3 pe-1 font-sans text-[13.5px] font-medium text-on-error-container"
const action = `inline-flex min-h-11 flex-none items-center whitespace-nowrap rounded-[14px] px-2 font-bold text-primary disabled:opacity-60 ${focus}`

/*
 * Missed sessions (`.missr`): one soft-error bar per session (never gold, which
 * is for earned things), the text opens it, the
 * action moves it to today. More than two collapse into one bar with a single
 * move-all, so a bad week never stacks a wall of warnings above today.
 * While any move is in flight every action waits, and the moving one says so.
 */
export function MissedGroup({
  missed,
  movingId,
  onOpen,
  onMoveToday,
  onMoveAllToday,
}: {
  missed: SessionVM[]
  movingId: string | null
  onOpen: (id: string) => void
  onMoveToday: (id: string) => void
  onMoveAllToday: (ids: string[]) => void
}) {
  if (missed.length === 0) return null
  if (missed.length > 2) {
    return (
      <div id="plan-missed" className={bar}>
        <span>Missed {missed.length} sessions</span>
        <button type="button" className={action} disabled={movingId !== null} onClick={() => onMoveAllToday(missed.map((s) => s.id))}>
          {movingId !== null ? COPY.moving : COPY.moveAllToday}
        </button>
      </div>
    )
  }
  return (
    <div id="plan-missed" className="grid gap-2">
      {missed.map((s) => (
        <div key={s.id} className={bar}>
          <button type="button" onClick={() => onOpen(s.id)} className={`min-h-11 min-w-0 flex-1 rounded-[10px] text-start ${focus}`}>
            Missed {s.dayShort} · {s.title}
          </button>
          <button type="button" className={action} disabled={movingId !== null} onClick={() => onMoveToday(s.id)}>
            {movingId === s.id ? COPY.moving : COPY.moveToday}
          </button>
        </div>
      ))}
    </div>
  )
}
