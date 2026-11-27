/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
import { HairRow, SubjectDot } from "@/components/redesign"
import { cn } from "@/lib/utils"
import { ActivityGlyph, TickGlyph } from "./icons"
import { ACTIVITY_TILE, DONE_TILE } from "./planStyles"
import type { SessionVM } from "./planModel"

/** The tinted activity tile (`.sic`). A done session swaps its icon for the tick. */
export function ActivityTile({ session }: { session: SessionVM }) {
  const done = session.status === "done"
  return (
    <span className={cn("grid size-10 shrink-0 place-items-center rounded-[13px]", done ? DONE_TILE : (ACTIVITY_TILE[session.activity] ?? ACTIVITY_TILE.review))}>
      {done ? <TickGlyph /> : <ActivityGlyph activity={session.activity} />}
    </span>
  )
}

/*
 * One session as a kit hairline row (`.srow2`). The kit owns the row geometry,
 * the hover tint, the title's hover colour and the chevron; this file only fills
 * the slots. `big` is today's row: taller, with its reason line.
 */
export function SessionRow({
  session,
  big = false,
  selected = false,
  onOpen,
}: {
  session: SessionVM
  big?: boolean
  selected?: boolean
  onOpen: (id: string) => void
}) {
  const done = session.status === "done"
  return (
    <HairRow
      leading={<ActivityTile session={session} />}
      title={
        done ? (
          <span className="text-on-surface-variant line-through decoration-outline">
            <span className="sr-only">Done: </span>
            {session.title}
          </span>
        ) : (
          session.title
        )
      }
      sub={
        <span className={cn("flex flex-col", big && "py-1")}>
          <span>
            <SubjectDot subject={session.subjectCode} />
            {session.subjectName} · {session.activityLabel} · {session.minutesLabel}
          </span>
          {big && session.why ? <span className="font-semibold text-primary">{session.why}</span> : null}
        </span>
      }
      onClick={() => onOpen(session.id)}
      selected={selected}
    />
  )
}
