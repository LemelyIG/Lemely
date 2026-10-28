/* Hallmark · pre-emit critique: P4 H3 E4 S4 R5 V3 — one chip, eight distinct icon and word pairs; the chip is the whole job, so hierarchy has little to do. */
import {
  CalendarCheck,
  CalendarX,
  CheckCircle,
  ClipboardText,
  HourglassMedium,
  Prohibit,
  UserMinus,
  XCircle,
  type Icon,
} from "@phosphor-icons/react"
import { Chip } from "@/components/ui/chip"
import { cn } from "@/lib/utils"
import { BOOKING_STATUS, type BookingStatusIcon } from "@/lib/tutoring/bookingStatus"
import type { EffectiveState } from "@/lib/tutoringTypes"

/*
 * C-20 Booking status (SPEC §a.3, §d). The effective state of a session as an
 * icon and a word, never colour alone: the eight states each have their own
 * label and their own shape (`lib/tutoring/bookingStatus.ts`), so the chip is
 * readable in greyscale and by a screen reader.
 *
 * It renders the state the API computed (`Booking.effectiveState`), which
 * already folds in the clock: a request whose start has passed is "Expired", an
 * accepted session that has ended with no outcome is "Awaiting outcome". This
 * component never works out a state from times itself.
 *
 * Built on the status `Chip`, whose tones are the shared semantic tokens.
 */

const ICONS: Record<BookingStatusIcon, Icon> = {
  HourglassMedium: HourglassMedium,
  CalendarCheck: CalendarCheck,
  ClipboardText: ClipboardText,
  CheckCircle: CheckCircle,
  XCircle: XCircle,
  Prohibit: Prohibit,
  UserMinus: UserMinus,
  CalendarX: CalendarX,
}

export interface BookingStatusProps {
  state: EffectiveState
  className?: string
}

export function BookingStatus({ state, className }: BookingStatusProps) {
  const status = BOOKING_STATUS[state]
  const Glyph = ICONS[status.icon]
  return (
    <Chip tone={status.tone} className={cn("gap-1.5", className)}>
      <Glyph size={14} weight="bold" aria-hidden />
      {status.label}
    </Chip>
  )
}
