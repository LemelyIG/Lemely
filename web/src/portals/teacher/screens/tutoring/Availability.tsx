/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 — seven plain day cards, quarter-hour selects instead of free time fields, the midnight split said in words before it is saved; not yet seen in a browser. */
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { CalendarBlank, CaretLeft, Info, Plus, WarningCircle } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Select } from "@/components/ui/select"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/state-views"
import { useReplaceTutorAvailability, useOwnTutorProfile } from "@/lib/hooks/useTutoringApi"
import { useOnlineStatus } from "@/lib/online"
import { isTutoringError } from "@/lib/tutoring/apiErrors"
import {
  DST_NOTE_FOR,
  NO_RULES_LINE,
  SPLIT_NOTE_LINE,
  WEEKDAYS,
  addRange,
  endOptions,
  formatMinute,
  removeRange,
  rulesFromWeek,
  splitNotice,
  startOptions,
  updateRange,
  validateWeek,
  weekFromRules,
  weekIsDirty,
  type DayRange,
  type IsoWeekday,
  type RangeProblem,
  type WeekDraft,
} from "@/lib/tutoring/availabilityEditor"
import { profileMode } from "@/lib/tutoring/profileSteps"
import { tutorActionFailureMessage, tutorLoadFailureMessage } from "@/lib/tutoring/tutorSessionActions"
import type { AvailabilityRule, TutorOwnProfile } from "@/lib/tutoringTypes"

/*
 * T-17 · Weekly availability (`/teacher/tutoring/availability`, SPEC §d).
 *
 * Seven day cards, each with any number of windows. A window is a start and an
 * end picked from a quarter-hour list (a Select, not a free time field, so the
 * 15-minute grid cannot be broken by typing). An end earlier than the start
 * goes past midnight and the card says, in words and before saving, that it is
 * stored as two windows (`splitNotice`). All of that logic, and the checks that
 * mirror the table's CHECKs and exclusion, live in `lib/tutoring/availabilityEditor.ts`.
 *
 * Saving replaces every rule at once (T5). The editor keeps the rules the
 * server last gave it as its baseline, so "unsaved changes" is judged against
 * what is stored, and a save resets it from the server's answer.
 *
 * States: loading (a skeleton of the seven cards), error and offline (through
 * `QueryState`), no profile (a way to the profile editor), no rules (the SPEC's
 * line), a suspended or closed profile (read-only, because T5 refuses it), and
 * a connection lost while editing (Save is disabled and says why).
 *
 * Focus: adding a window moves focus to its first field; removing one moves
 * focus to the day's "Add a time" button; a failed save moves focus to the first
 * window that needs a change.
 */

const DAY_ID = (iso: number) => `day-${iso}`

function RangeRow({
  weekday,
  dayLabel,
  index,
  range,
  problem,
  readOnly,
  onChange,
  onRemove,
}: {
  weekday: IsoWeekday
  dayLabel: string
  index: number
  range: DayRange
  problem: RangeProblem | undefined
  readOnly: boolean
  onChange: (patch: Partial<Pick<DayRange, "startMinute" | "endMinute">>) => void
  onRemove: () => void
}) {
  const notice = splitNotice(weekday, range)
  return (
    <li className="flex flex-col gap-2">
      <div
        role="group"
        aria-label={`${dayLabel}, time ${index + 1}`}
        className="flex flex-wrap items-end gap-3"
      >
        <Select
          id={`${range.id}-start`}
          label="From"
          value={String(range.startMinute)}
          disabled={readOnly}
          onChange={(event) => onChange({ startMinute: Number(event.target.value) })}
          wrapperClassName="w-32"
        >
          {startOptions().map((minute) => (
            <option key={minute} value={minute}>
              {formatMinute(minute)}
            </option>
          ))}
        </Select>
        <Select
          id={`${range.id}-end`}
          label="To"
          value={String(range.endMinute)}
          disabled={readOnly}
          onChange={(event) => onChange({ endMinute: Number(event.target.value) })}
          state={problem ? "error" : undefined}
          aria-describedby={problem ? `${range.id}-problem` : undefined}
          wrapperClassName="w-40"
        >
          {endOptions().map((minute) => (
            <option key={minute} value={minute}>
              {minute === 1440 ? "24:00 (midnight)" : formatMinute(minute)}
            </option>
          ))}
        </Select>
        {readOnly ? null : (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label={`Remove ${dayLabel} time ${index + 1}`}
            onClick={onRemove}
          >
            Remove
          </Button>
        )}
      </div>
      {problem ? (
        <p id={`${range.id}-problem`} className="m-0 flex items-start gap-1.5 text-body-sm text-err">
          <WarningCircle size={16} className="mt-0.5 shrink-0" aria-hidden />
          {problem.message}
        </p>
      ) : null}
      {notice && !problem ? (
        <p className="m-0 flex items-start gap-1.5 text-body-sm text-ink-muted">
          <Info size={16} className="mt-0.5 shrink-0 text-info" aria-hidden />
          {notice}
        </p>
      ) : null}
    </li>
  )
}

function DayCard({
  weekday,
  dayLabel,
  ranges,
  problems,
  readOnly,
  onAdd,
  onChange,
  onRemove,
}: {
  weekday: IsoWeekday
  dayLabel: string
  ranges: DayRange[]
  problems: Map<string, RangeProblem>
  readOnly: boolean
  onAdd: () => void
  onChange: (id: string, patch: Partial<Pick<DayRange, "startMinute" | "endMinute">>) => void
  onRemove: (id: string) => void
}) {
  return (
    <section
      aria-labelledby={DAY_ID(weekday)}
      className="flex flex-col gap-3 rounded-lg border border-rule bg-paper-raised p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={DAY_ID(weekday)} className="m-0 text-display-sm text-ink">
          {dayLabel}
        </h2>
        {readOnly ? null : (
          <Button
            id={`add-${weekday}`}
            type="button"
            variant="secondary"
            size="sm"
            icon={<Plus size={14} />}
            aria-label={`Add a time on ${dayLabel}`}
            onClick={onAdd}
          >
            Add a time
          </Button>
        )}
      </div>
      {ranges.length === 0 ? (
        <p className="m-0 text-body-sm text-ink-muted">Not available</p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {ranges.map((range, index) => (
            <RangeRow
              key={range.id}
              weekday={weekday}
              dayLabel={dayLabel}
              index={index}
              range={range}
              problem={problems.get(range.id)}
              readOnly={readOnly}
              onChange={(patch) => onChange(range.id, patch)}
              onRemove={() => onRemove(range.id)}
            />
          ))}
        </ul>
      )}
    </section>
  )
}

function AvailabilityEditor({ profile }: { profile: TutorOwnProfile }) {
  const readOnly = profileMode(profile.listingState) === "readonly"
  const online = useOnlineStatus()
  const save = useReplaceTutorAvailability()
  const [baseline, setBaseline] = useState<readonly AvailabilityRule[]>(profile.availability)
  const [week, setWeek] = useState<WeekDraft>(() => weekFromRules(profile.availability))
  const [attempted, setAttempted] = useState(false)
  const [savedNotice, setSavedNotice] = useState(false)
  const focusAfter = useRef<string | null>(null)

  const validation = useMemo(() => validateWeek(week), [week])
  const dirty = weekIsDirty(week, baseline)
  const problems = useMemo(() => {
    const byRange = new Map<string, RangeProblem>()
    for (const problem of validation.problems) {
      if (!byRange.has(problem.rangeId)) byRange.set(problem.rangeId, problem)
    }
    return byRange
  }, [validation.problems])
  const empty = rulesFromWeek(week).length === 0

  useEffect(() => {
    if (focusAfter.current === null) return
    document.getElementById(focusAfter.current)?.focus()
    focusAfter.current = null
  }, [week])

  function edit(next: WeekDraft) {
    setWeek(next)
    setSavedNotice(false)
    if (save.isError) save.reset()
  }

  function onAdd(weekday: IsoWeekday) {
    const next = addRange(week, weekday)
    const added = next[weekday].find((range) => !week[weekday].some((old) => old.id === range.id))
    if (added) focusAfter.current = `${added.id}-start`
    edit(next)
  }

  function onRemove(weekday: IsoWeekday, id: string) {
    focusAfter.current = `add-${weekday}`
    edit(removeRange(week, weekday, id))
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (readOnly || !dirty) return
    if (validation.problems.length > 0 || validation.tooMany) {
      setAttempted(true)
      const first = validation.problems[0]
      if (first) document.getElementById(`${first.rangeId}-end`)?.focus()
      return
    }
    setAttempted(false)
    try {
      const stored = await save.mutateAsync({ rules: rulesFromWeek(week) })
      setBaseline(stored)
      setWeek(weekFromRules(stored))
      setSavedNotice(true)
    } catch {
      // The hook keeps the error; it is shown under the buttons.
    }
  }

  const saveError = tutorActionFailureMessage(save.error, "We couldn't save your times. Try again.")
  const blocked = attempted && (validation.problems.length > 0 || validation.tooMany)

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5 min-w-0" noValidate>
      <div className="flex flex-col gap-2 border-b border-rule pb-5">
        <Link
          to="/teacher/tutoring/profile?step=availability"
          className="inline-flex w-fit items-center gap-1 py-1 text-body-sm text-ink-muted transition-colors hover:text-ink"
        >
          <CaretLeft size={14} aria-hidden />
          Back to your profile
        </Link>
        <h1 className="m-0 text-display-md text-ink">Weekly availability</h1>
        <p className="m-0 max-w-prose text-body-md text-ink-muted">{DST_NOTE_FOR(profile.zoneLabel)}</p>
      </div>

      {readOnly ? (
        <p className="m-0 flex items-start gap-2 rounded-md border border-rule bg-paper-sunk px-3 py-2.5 text-body-sm text-ink">
          <WarningCircle size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden />
          {profile.listingState === "suspended"
            ? "Your profile is suspended, so your times can't be changed."
            : "Your profile is closed, so your times can't be changed."}
        </p>
      ) : null}

      {empty ? (
        <p className="m-0 flex items-start gap-2 rounded-md border border-rule bg-info-wash px-3 py-2.5 text-body-md text-ink">
          <CalendarBlank size={18} className="mt-0.5 shrink-0 text-info" aria-hidden />
          {NO_RULES_LINE}
        </p>
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {WEEKDAYS.map((day) => (
          <DayCard
            key={day.iso}
            weekday={day.iso}
            dayLabel={day.label}
            ranges={week[day.iso]}
            problems={problems}
            readOnly={readOnly}
            onAdd={() => onAdd(day.iso)}
            onChange={(id, patch) => edit(updateRange(week, day.iso, id, patch))}
            onRemove={(id) => onRemove(day.iso, id)}
          />
        ))}
      </div>

      <p className="m-0 max-w-prose text-body-sm text-ink-muted">{SPLIT_NOTE_LINE}</p>

      {readOnly ? null : (
        <div className="flex flex-col gap-3 border-t border-rule pt-5">
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" variant="primary" loading={save.isPending} disabled={!dirty || !online}>
              Save weekly times
            </Button>
            {dirty ? (
              <Button
                type="button"
                variant="ghost"
                disabled={save.isPending}
                onClick={() => {
                  setWeek(weekFromRules(baseline))
                  setAttempted(false)
                  if (save.isError) save.reset()
                }}
              >
                Discard changes
              </Button>
            ) : null}
            <Link
              to="/teacher/tutoring"
              className="py-2 text-body-sm text-ink-muted transition-colors hover:text-ink"
            >
              Tutoring home
            </Link>
          </div>
          <div aria-live="polite" className="flex flex-col gap-1">
            {!online ? (
              <p className="m-0 text-body-sm text-ink-muted">You're offline. Reconnect to save your times.</p>
            ) : null}
            {dirty && !save.isPending && !savedNotice ? (
              <p className="m-0 text-body-sm text-ink-muted">You have changes that aren't saved yet.</p>
            ) : null}
            {blocked ? (
              <p role="alert" className="m-0 text-body-sm text-err">
                {validation.tooMany
                  ? "There are too many times. Remove some so there are 42 or fewer once windows past midnight are split."
                  : "Fix the times marked above, then save."}
              </p>
            ) : null}
            {savedNotice && !dirty ? <p className="m-0 text-body-sm text-ok">Weekly times saved.</p> : null}
          </div>
          {saveError ? (
            <p role="alert" className="m-0 text-body-sm text-err">
              {saveError}
            </p>
          ) : null}
        </div>
      )}
    </form>
  )
}

function AvailabilitySkeleton() {
  return (
    <div className="flex flex-col gap-5">
      <PageHeaderSkeleton />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {Array.from({ length: 6 }, (_, index) => (
          <SkeletonBlock key={index} announce={false} className="h-28" />
        ))}
      </div>
    </div>
  )
}

export function Availability() {
  const profileQuery = useOwnTutorProfile()
  const navigate = useNavigate()

  if (isTutoringError(profileQuery.error, "no_tutor_profile")) {
    return (
      <div className="flex flex-col gap-5 min-w-0">
        <h1 className="sr-only">Weekly availability</h1>
        <EmptyState
          heading="Set up your tutor profile first"
          body="Your weekly times belong to your profile. Create it, then come back to choose when you teach."
          action={{ label: "Set up your profile", onClick: () => void navigate("/teacher/tutoring/profile") }}
        />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-5 min-w-0">
      <QueryState
        query={profileQuery}
        srHeading="Weekly availability"
        skeleton={<AvailabilitySkeleton />}
        error={{ heading: "Couldn't load your weekly times", body: tutorLoadFailureMessage }}
      >
        {(profile) => <AvailabilityEditor profile={profile} />}
      </QueryState>
    </div>
  )
}
