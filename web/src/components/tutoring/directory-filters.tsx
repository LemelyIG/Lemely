/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — plain native controls in one calm row; the filter bar folds behind a button on a phone so the tutors stay above the fold. */
import { useId, useState } from "react"
import { Funnel } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Select } from "@/components/ui/select"
import { cn } from "@/lib/utils"
import {
  MODE_OPTIONS,
  RATING_OPTIONS,
  TIME_OF_DAY_OPTIONS,
  WEEKDAYS,
  activeFilterCount,
  type Audience,
  type DirectoryFilterState,
} from "@/lib/tutoring/discovery"
import type { TimeOfDay } from "@/lib/tutoring/queryKeys"
import type { AreaRef, SubjectRef, TutoringMode } from "@/lib/tutoringTypes"

/*
 * Directory filters (SPEC §d, G-16 and S-33): subject, way of meeting, area,
 * minimum rating, and on the logged-in directory "Usually available" (days and
 * time of day). The component is controlled; the screen keeps the state in the
 * address (`lib/tutoring/discovery.ts`) so a filtered list is a link.
 *
 * Native controls throughout (`Select`, `Checkbox`): arrow keys, typeahead and
 * the phone's own pickers come for free. The groups are real `<fieldset>`s
 * with legends. Below `md` the bar folds behind a "Filters" button that says
 * how many are set and reports `aria-expanded`; from `md` it is always open.
 * The options for subject and area come from the API (the first page's facets
 * and P3), never from this file. A value in the address that is not among them
 * is still shown, so the select never claims "All" while a filter is applied.
 *
 * The rating filter leaves out "New" tutors (P1: three students or more), and
 * its hint says so, so an empty result is explained and not mysterious.
 */

export interface DirectoryFiltersProps {
  audience: Audience
  value: DirectoryFilterState
  onChange: (next: DirectoryFilterState) => void
  onClear: () => void
  subjects: readonly SubjectRef[]
  areas: readonly AreaRef[]
  className?: string
}

function toggle<T>(list: readonly T[], item: T): T[] {
  return list.includes(item) ? list.filter((x) => x !== item) : [...list, item]
}

/** Options plus the current value when the list does not hold it (a stale link). */
function withCurrent<T extends { code: string; name: string }>(options: readonly T[], current: string) {
  if (current === "" || options.some((o) => o.code === current)) return options
  return [...options, { code: current, name: current }]
}

export function DirectoryFilters({
  audience,
  value,
  onChange,
  onClear,
  subjects,
  areas,
  className,
}: DirectoryFiltersProps) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const count = activeFilterCount(value, audience)
  const subjectOptions = withCurrent(subjects, value.subject)
  const areaOptions = withCurrent(areas, value.area)

  return (
    <section aria-label="Filters" className={cn("flex flex-col gap-4", className)}>
      <div className="flex items-center justify-between gap-3 md:hidden">
        <Button
          variant="secondary"
          size="md"
          icon={<Funnel size={16} />}
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((v) => !v)}
        >
          {count > 0 ? `Filters (${count})` : "Filters"}
        </Button>
        {count > 0 ? (
          <Button variant="ghost" size="md" onClick={onClear}>
            Clear filters
          </Button>
        ) : null}
      </div>

      <div id={panelId} className={cn("flex-col gap-5", open ? "flex" : "hidden", "md:flex")}>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Select
            label="Subject"
            value={value.subject}
            onChange={(e) => onChange({ ...value, subject: e.target.value })}
          >
            <option value="">All subjects</option>
            {subjectOptions.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name}
              </option>
            ))}
          </Select>
          <Select
            label="Area"
            value={value.area}
            onChange={(e) => onChange({ ...value, area: e.target.value })}
          >
            <option value="">Anywhere</option>
            {areaOptions.map((a) => (
              <option key={a.code} value={a.code}>
                {a.name}
              </option>
            ))}
          </Select>
          <Select
            label="Minimum rating"
            hint="Tutors with fewer than 3 student ratings show as New and are left out."
            value={value.minRating === null ? "" : String(value.minRating)}
            onChange={(e) =>
              onChange({ ...value, minRating: e.target.value === "" ? null : Number(e.target.value) })
            }
          >
            <option value="">Any rating</option>
            {RATING_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {r.toFixed(1)} and up
              </option>
            ))}
            {value.minRating !== null && !RATING_OPTIONS.includes(value.minRating) ? (
              <option value={value.minRating}>{value.minRating.toFixed(1)} and up</option>
            ) : null}
          </Select>
        </div>

        <fieldset className="m-0 flex min-w-0 flex-col gap-1 border-0 p-0">
          <legend className="mb-1 p-0 text-label text-ink">Way of meeting</legend>
          <div className="flex flex-wrap gap-x-5">
            {MODE_OPTIONS.map((mode) => (
              <Checkbox
                key={mode.value}
                label={mode.label}
                className="min-h-11"
                checked={value.modes.includes(mode.value as TutoringMode)}
                onChange={() => onChange({ ...value, modes: toggle(value.modes, mode.value) })}
              />
            ))}
          </div>
        </fieldset>

        {audience === "member" ? (
          <fieldset className="m-0 flex min-w-0 flex-col gap-3 border-0 p-0">
            <legend className="mb-1 p-0 text-label text-ink">Usually available</legend>
            <div className="flex flex-wrap gap-x-5">
              {WEEKDAYS.map((day) => (
                <Checkbox
                  key={day.value}
                  label={day.short}
                  aria-label={day.long}
                  className="min-h-11"
                  checked={value.days.includes(day.value)}
                  onChange={() => onChange({ ...value, days: toggle(value.days, day.value) })}
                />
              ))}
            </div>
            <div className="flex flex-wrap gap-x-5">
              {TIME_OF_DAY_OPTIONS.map((time) => (
                <Checkbox
                  key={time.value}
                  label={`${time.label} ${time.hours}`}
                  className="min-h-11"
                  checked={value.timesOfDay.includes(time.value as TimeOfDay)}
                  onChange={() =>
                    onChange({ ...value, timesOfDay: toggle(value.timesOfDay, time.value) })
                  }
                />
              ))}
            </div>
            <p className="m-0 text-body-sm text-ink-muted">
              Times are on the tutor's own clock. A tutor shows if one of their weekly times falls on a day and in a
              time of day you picked.
            </p>
          </fieldset>
        ) : null}

        {count > 0 ? (
          <div className="hidden md:block">
            <Button variant="ghost" size="sm" onClick={onClear}>
              Clear filters
            </Button>
          </div>
        ) : null}
      </div>
    </section>
  )
}
