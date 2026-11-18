/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useEffect, useState, type ReactElement, type ReactNode } from "react"
import { BinnyLine, SubjectDot } from "@/components/redesign"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { useNativeFrame } from "@/lib/useNativeFrame"
import { cn } from "@/lib/utils"
import { CalendarGlyph, TickGlyph } from "./icons"
import { COPY } from "./planCopy"
import type { SessionVM } from "./planModel"
import { ActivityTile } from "./SessionRow"

export interface SessionActions {
  completing: boolean
  completeError: string | null
  /** The day a move is in flight to, or null. */
  movingTo: string | null
  onStart: (path: string) => void
  onComplete: () => void
  onMove: (date: string) => void
}

/** `.sa`: the two secondary actions. */
const actionClass =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-[14px] bg-surface-container-high font-sans text-sm font-bold text-primary disabled:opacity-60 focus-visible:outline-[2.5px] focus-visible:outline-primary focus-visible:outline-offset-2"

/** The body shared by the sheet (SS, PX) and the desktop panel (SD). */
export function SessionDetail({
  session,
  titleWrap,
  footer,
  completing,
  completeError,
  movingTo,
  onStart,
  onComplete,
  onMove,
}: { session: SessionVM; titleWrap?: (heading: ReactElement) => ReactNode; footer?: ReactNode } & SessionActions) {
  const [moveOpen, setMoveOpen] = useState(false)
  // A new session starts with the move choice closed.
  useEffect(() => setMoveOpen(false), [session.id])
  const done = session.status === "done"
  const heading = <h2 className="m-0 font-sans text-[22px] font-extrabold text-on-surface">{session.title}</h2>

  return (
    <div className="flex flex-1 flex-col gap-3.5">
      <div className="flex items-center gap-3">
        <ActivityTile session={session} />
        <div className="min-w-0">
          {titleWrap ? titleWrap(heading) : heading}
          <span className="inline-flex items-center gap-1.5 font-sans text-[13px] font-medium text-on-surface-variant">
            <SubjectDot subject={session.subjectCode} />
            {session.subjectName} · {session.activityLabel} · {session.minutesLabel}
          </span>
        </div>
      </div>

      {completeError ? (
        <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 font-sans text-[13.5px] leading-[1.35] font-semibold text-on-error-container">
          {completeError}
        </div>
      ) : (
        <p className="m-0 font-sans text-[15px] leading-[1.45] font-medium text-on-surface">
          <b className="text-primary">{COPY.whyThis}</b> {session.whyBody}
        </p>
      )}

      {session.start && !done ? (
        <Button
          variant="primary"
          onClick={() => session.start && onStart(session.start.path)}
          className="min-h-[50px] w-full rounded-[18px] text-[15.5px] shadow-[0_14px_24px_-16px_oklch(0.3_0.07_242/0.7)]"
        >
          {session.start.label}
        </Button>
      ) : null}

      <div className={cn("grid gap-2.5", session.canMove ? "grid-cols-2" : "grid-cols-1")}>
        {done ? (
          <span className={cn(actionClass, "text-success-text")}>
            <TickGlyph /> {COPY.done}
          </span>
        ) : (
          <button type="button" className={actionClass} onClick={onComplete} disabled={completing}>
            <TickGlyph /> {completing ? COPY.saving : completeError ? COPY.tryAgain : COPY.markDone}
          </button>
        )}
        {session.canMove ? (
          <button
            type="button"
            className={actionClass}
            aria-expanded={moveOpen}
            aria-controls={moveOpen ? `move-${session.id}` : undefined}
            onClick={() => setMoveOpen((open) => !open)}
          >
            <CalendarGlyph /> {COPY.move}
          </button>
        ) : null}
      </div>

      {moveOpen && session.canMove ? (
        <div id={`move-${session.id}`} role="group" aria-label="Move to" className="flex flex-wrap gap-2">
          {session.moveDays.map((day) => (
            <button
              key={day.date}
              type="button"
              onClick={() => onMove(day.date)}
              disabled={movingTo !== null}
              aria-pressed={movingTo === day.date}
              className={cn(
                "min-h-11 flex-1 rounded-xl font-sans text-sm font-semibold focus-visible:outline-[2.5px] focus-visible:outline-primary focus-visible:outline-offset-2",
                movingTo === day.date
                  ? "bg-primary-container text-primary shadow-[inset_0_0_0_2px_var(--color-primary)]"
                  : "bg-surface-container-lowest text-on-surface shadow-[inset_0_0_0_1.5px_var(--color-outline)]",
              )}
            >
              {day.label}
            </button>
          ))}
        </div>
      ) : null}

      {footer}
    </div>
  )
}

/**
 * `.grab`: the 40x5 grabber for a bottom sheet that is not the native frame. The native sheet
 * draws its own, and from `sm` the sheet floats at the end edge, so neither shows this one.
 */
function PhoneGrabber() {
  const { native } = useNativeFrame()
  if (native) return null
  return (
    <div className="flex justify-center sm:hidden" aria-hidden="true">
      <span className="block h-[5px] w-10 rounded-[3px] bg-outline" />
    </div>
  )
}

/** < 1280px: the session as a sheet (SS, PX). Bottom on phones, floating from `sm`. */
export function SessionSheet({ session, onClose, ...actions }: { session: SessionVM | null; onClose: () => void } & SessionActions) {
  return (
    <Sheet open={session !== null} onOpenChange={(open) => !open && onClose()}>
      {session ? (
        <SheetContent side="adaptive" showCloseButton={false} aria-describedby={undefined} className="gap-3 pt-3">
          <PhoneGrabber />
          <SessionDetail session={session} titleWrap={(heading) => <SheetTitle asChild>{heading}</SheetTitle>} {...actions} />
        </SheetContent>
      ) : null}
    </Sheet>
  )
}

/** >= 1280px: the side panel that follows the selected row (SD). */
export function SessionPanel({ session, binnyLine, ...actions }: { session: SessionVM | null; binnyLine: string | null } & SessionActions) {
  const binny = binnyLine ? (
    <div className="mt-auto">
      <BinnyLine mood="happy" line={binnyLine} size={56} motion="idle" />
    </div>
  ) : null
  return (
    <aside
      aria-label="Session"
      className="sticky top-6 flex min-h-[420px] flex-col gap-3.5 self-start rounded-[22px] bg-surface-container-lowest p-5 shadow-[0_1px_3px_oklch(0.3_0.05_240/0.1)]"
    >
      {session ? <SessionDetail session={session} footer={binny} {...actions} /> : binny}
    </aside>
  )
}
