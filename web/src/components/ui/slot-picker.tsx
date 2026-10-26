/* Hallmark · pre-emit critique: P4 H4 E4 S4 R3 V3 */
import { useId, useState } from "react"
import { Check } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { dayChipSummary, groupSlotsByDay, windowDays } from "@/lib/tutoring/slotGroups"
import type { Slot, Slots } from "@/lib/tutoringTypes"

/*
 * C-19 Slot picker (SPEC §d). Day chips, then the times of the chosen day, all
 * in the TUTOR's zone with its label (SPEC §0 "Times"), so a student in another
 * city sees the hour the session actually happens.
 *
 * Two native radio groups, not a custom widget: one for the day, one for the
 * time. A native radio group gives arrow-key movement inside the group, Tab to
 * leave it, and the right announcements for free; the visible chip is only the
 * face of the real input, which stays in the accessibility tree.
 *
 * Choosing does not hide the others. A day with no times is still a chip, says
 * "No times", and shows "No times on this day." when chosen, so a gap in the
 * tutor's week is visible rather than silently skipped. Whatever is selected is
 * marked with a check as well as colour, and repeated in words under the picker.
 *
 * Grouping, ordering, the repeated hour when the clocks go back, and every
 * label come from `lib/tutoring/slotGroups.ts`; this file does no date
 * arithmetic. "Show later dates" is the screen's: it asks for a longer window
 * and passes the new `slots` in.
 *
 * `loading` is a skeleton. `disabled` (offline, or a request in flight) greys
 * the group and, with `disabledReason`, says why in text. An error fetching the
 * slots belongs to the screen (`QueryState`, C-11).
 */

export interface SlotPickerProps {
  /** SP5's answer: the window, the tutor's zone and the bookable slots. */
  slots: Slots | undefined
  /** `startsAt` of the chosen slot, or null. */
  value: string | null
  onChange: (slot: Slot) => void
  loading?: boolean
  disabled?: boolean
  /** Why the picker is disabled, in words ("You're offline."). */
  disabledReason?: string
  className?: string
}

const face =
  "flex min-h-11 min-w-11 flex-col items-center justify-center rounded-md border border-rule bg-paper-raised px-3 py-2 text-center " +
  "transition-colors duration-[var(--dur-instant)] ease-out-soft " +
  "peer-hover:border-rule-strong peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-focus-ring " +
  "peer-checked:border-accent peer-checked:bg-accent-wash peer-checked:text-accent-ink " +
  "peer-disabled:cursor-not-allowed peer-disabled:opacity-50"

export function SlotPicker({
  slots,
  value,
  onChange,
  loading = false,
  disabled = false,
  disabledReason,
  className,
}: SlotPickerProps) {
  const id = useId()
  const [chosenDay, setChosenDay] = useState<string | null>(null)

  if (loading || !slots) {
    return (
      <div className={cn("flex flex-col gap-4", className)} role="status" aria-label="Loading times">
        <div className="flex flex-wrap gap-2">
          {[0, 1, 2, 3].map((i) => (
            <SkeletonBlock key={i} announce={false} className="h-14 w-24" />
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <SkeletonBlock key={i} announce={false} className="h-11" />
          ))}
        </div>
      </div>
    )
  }

  const withTimes = groupSlotsByDay(slots.slots, slots.zone, slots.zoneLabel)
  const byKey = new Map(withTimes.map((day) => [day.dayKey, day]))
  const days = windowDays(slots.windowStart, slots.windowEnd, slots.zone).map((day) => ({
    ...day,
    slots: byKey.get(day.dayKey)?.slots ?? [],
  }))
  // A slot outside the window the API reported is still shown rather than lost.
  for (const day of withTimes) {
    if (!days.some((d) => d.dayKey === day.dayKey)) days.push(day)
  }
  days.sort((a, b) => (a.dayKey < b.dayKey ? -1 : a.dayKey > b.dayKey ? 1 : 0))

  const selected = value ? withTimes.flatMap((d) => d.slots).find((s) => s.startsAt === value) : undefined
  const dayOfValue = selected ? withTimes.find((d) => d.slots.includes(selected))?.dayKey : undefined
  const firstWithTimes = days.find((d) => d.slots.length > 0)?.dayKey
  const activeKey = chosenDay ?? dayOfValue ?? firstWithTimes ?? days[0]?.dayKey
  const active = days.find((d) => d.dayKey === activeKey)

  if (slots.slots.length === 0) {
    return (
      <p className={cn("m-0 text-body-md text-ink-muted", className)}>
        No times are free in this window. Try later dates.
      </p>
    )
  }

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      <fieldset className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0" disabled={disabled}>
        <legend className="mb-1 p-0 text-label text-ink">Day</legend>
        <div className="flex flex-wrap gap-2">
          {days.map((day) => (
            <label key={day.dayKey} className="relative cursor-pointer has-disabled:cursor-not-allowed">
              <input
                type="radio"
                name={`${id}-day`}
                value={day.dayKey}
                checked={day.dayKey === activeKey}
                onChange={() => setChosenDay(day.dayKey)}
                className="peer sr-only"
              />
              <span className={face}>
                <span className="text-label">{day.chipLabel}</span>
                <span className="text-body-sm text-ink-muted">{dayChipSummary(day.slots.length)}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {active ? (
        <fieldset className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0" disabled={disabled}>
          <legend className="mb-1 p-0 text-label text-ink">
            Times on {active.chipLabel} ({slots.zoneLabel})
          </legend>
          {active.slots.length === 0 ? (
            <p className="m-0 text-body-md text-ink-muted">No times on this day.</p>
          ) : (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {active.slots.map((slot) => (
                <label key={slot.startsAt} className="relative cursor-pointer has-disabled:cursor-not-allowed">
                  <input
                    type="radio"
                    name={`${id}-time`}
                    value={slot.startsAt}
                    checked={slot.startsAt === value}
                    onChange={() => onChange({ startsAt: slot.startsAt, endsAt: slot.endsAt })}
                    className="peer sr-only"
                  />
                  <span className={face}>
                    <span className="text-data-md">{slot.label}</span>
                  </span>
                  <Check
                    size={14}
                    weight="bold"
                    aria-hidden
                    className="absolute end-1.5 top-1.5 hidden text-accent-ink peer-checked:block"
                  />
                </label>
              ))}
            </div>
          )}
        </fieldset>
      ) : null}

      {disabled && disabledReason ? (
        <p className="m-0 text-body-sm text-ink-muted">{disabledReason}</p>
      ) : null}

      <p className="m-0 text-body-sm text-ink-muted" aria-live="polite">
        {selected ? `Selected: ${selected.fullLabel}` : `Times are in ${slots.zoneLabel}.`}
      </p>
    </div>
  )
}
