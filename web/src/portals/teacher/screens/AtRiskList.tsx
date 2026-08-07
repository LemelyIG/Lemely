import { useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { GradeBadge } from "@/components/ui/grade-badge"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { cn, initialsOf, relativeTime } from "@/lib/utils"
import { Avatar } from "../components/Avatar"
import {
  useAcknowledgeAtRisk,
  useAtRiskList,
  useUnacknowledgeAtRisk,
} from "@/lib/hooks/useTeacherApi"
import type { AtRiskFlag, AtRiskListEntry } from "@/lib/teacherTypes"

/*
 * At-risk list (T-06). `GET /teacher/at-risk?reason=&acknowledged=`
 * (`useAtRiskList()`) — every flagged student across the caller's classes,
 * each row a direct `AtRiskListEntryDTO`. `reason` is a real server-side
 * filter (native `<select>`, no client-side re-filtering of an unfiltered
 * fetch); `acknowledged` is D3.5's own caller-side filter, defaulting to
 * "all" so acknowledged flags are never hidden unless the teacher asks.
 *
 * **`below_target` is deliberately not offered in the reason filter.** D3.3:
 * rule 2 cannot fire in production until P4's onboarding questionnaire
 * supplies a target grade — the engine reports it *not evaluable*, never a
 * pass. Offering a filter option that can never match a real flag today
 * would imply data this build doesn't have.
 *
 * **Severity is a UI convention, mirrored exactly from the backend's own
 * definition, not a client-invented score.** The list already arrives
 * severity-sorted — `_at_risk_severity_key` in
 * `lemely/web/routers/teacher.py`: flag count descending, then worst
 * (furthest-down-`GRADE_ORDER`) grade first. `compareEntries` below
 * reproduces that identical two-key ordering only so the "Severity" column
 * stays re-sortable after a teacher sorts by Student/Class/Grade and clicks
 * back — see its comment. This is presented to the teacher only as a sort
 * order, never as a computed "severity score" the engine emitted.
 *
 * **Acknowledge-with-a-note is the screen's core interaction (D3.5).**
 * `AcknowledgeControl` renders each flag individually:
 *  - Unacknowledged -> an "Acknowledge" button (never "Dismiss"/"Mute") that
 *    expands an inline optional-note form, worded to say plainly that this
 *    stays visible and reappears if the evidence moves on — the opposite of
 *    a permanent mute.
 *  - Acknowledged -> tagged, with an "Undo" control (`DELETE .../acknowledge/
 *    {reason}`) rather than removed from view, and the note shown if one was
 *    left. `AtRiskAcknowledgementDTO.acknowledgedBy` (a user id, per D3.5) is
 *    deliberately never rendered: every ack visible to this caller was made
 *    by this same caller (`_acknowledgement_index` scopes
 *    `load_for_teacher(auth.user_id, ...)` — teacher.py — so it can only
 *    ever be "you"), and there is no display-name source to resolve it
 *    against honestly, so showing "acknowledged" with no attributed name
 *    avoids presenting a raw id as if it were a person.
 *  - A 422 (the named reason isn't currently firing — a real race if the
 *    underlying evidence changed between this list loading and the click)
 *    renders as a real inline mutation error, not swallowed.
 */

const GRADE_ORDER = ["A*", "A", "B", "C", "D", "E", "U"]

const REASON_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All reasons" },
  { value: "declining_trend", label: "Declining trend" },
  { value: "inactive", label: "Inactive" },
]

const ACK_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All flags" },
  { value: "false", label: "Unacknowledged only" },
  { value: "true", label: "Acknowledged only" },
]

type SortColumn = "name" | "className" | "grade" | "severity"

/** Mirrors the backend's own `_grade_severity_rank` (teacher.py) exactly: an
 * unrecognised or empty grade (a student with only quiz activity) ranks as
 * the mildest possible rather than sorting as "worse than a real U". */
function gradeSeverityRank(grade: string): number {
  const idx = GRADE_ORDER.indexOf(grade)
  return idx === -1 ? -1 : idx
}

function compareEntries(
  a: AtRiskListEntry,
  b: AtRiskListEntry,
  column: SortColumn,
  dir: 1 | -1,
): number {
  if (column === "severity") {
    // Reproduces `_at_risk_severity_key` exactly: flag count first, worst
    // grade second. `dir = 1` reproduces the backend's own default (most
    // flags, worst grade, first) — unlike the other columns, "ascending"
    // here means "most severe first" by definition, not "smallest value
    // first"; same judgment call `ClassRoster.tsx`'s grade column already
    // documents for the same reason (a ladder position isn't a plain number).
    if (a.flags.length !== b.flags.length) return (b.flags.length - a.flags.length) * dir
    return (gradeSeverityRank(b.grade) - gradeSeverityRank(a.grade)) * dir
  }
  if (column === "grade") {
    return (gradeSeverityRank(a.grade) - gradeSeverityRank(b.grade)) * dir
  }
  const av = column === "name" ? a.displayName : a.className
  const bv = column === "name" ? b.displayName : b.className
  return av.localeCompare(bv) * dir
}

const COLUMNS: { key: SortColumn; label: string }[] = [
  { key: "name", label: "Student" },
  { key: "className", label: "Class" },
  { key: "grade", label: "Latest grade" },
  { key: "severity", label: "Severity" },
]

function AcknowledgeControl({
  studentId,
  flag,
}: {
  studentId: string
  flag: AtRiskFlag
}) {
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState("")
  const acknowledge = useAcknowledgeAtRisk(studentId)
  const unacknowledge = useUnacknowledgeAtRisk(studentId)

  if (flag.acknowledged) {
    return (
      <div className="flex flex-col gap-1 mt-1">
        <div className="flex items-center gap-2 flex-wrap">
          <Chip tone="neutral">
            Acknowledged {relativeTime(flag.acknowledged.acknowledgedAt)}
          </Chip>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => unacknowledge.mutate(flag.reason)}
            disabled={unacknowledge.isPending}
            title="Not a re-flag — just removes your acknowledgement so this reads as unseen again"
          >
            {unacknowledge.isPending ? "Undoing…" : "Undo"}
          </Button>
        </div>
        {flag.acknowledged.note ? (
          <div className="text-xs text-t2 italic text-pretty">“{flag.acknowledged.note}”</div>
        ) : null}
        {unacknowledge.isError ? (
          <div className="text-xs text-err">Couldn't undo: {unacknowledge.error.message}</div>
        ) : null}
      </div>
    )
  }

  if (!open) {
    return (
      <Button type="button" size="sm" variant="secondary" className="mt-1" onClick={() => setOpen(true)}>
        Acknowledge
      </Button>
    )
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        acknowledge.mutate(
          { reason: flag.reason, note: note.trim() || undefined },
          {
            onSuccess: () => {
              setOpen(false)
              setNote("")
            },
          },
        )
      }}
      className="flex flex-col gap-2 max-w-[320px] bg-surface-2 border border-border rounded-lg p-3 mt-1"
    >
      <label className="flex flex-col gap-1 text-xs text-t2">
        Note (optional — visible only to you)
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          className="border border-border bg-surface rounded-md px-2 py-1.5 text-dense-sm text-t1 resize-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        />
      </label>
      <p className="text-xs text-t3 m-0">
        This notes that you've seen it — the flag stays visible and reappears as new if the
        student's situation changes. It's never a permanent mute.
      </p>
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" variant="ink" disabled={acknowledge.isPending}>
          {acknowledge.isPending ? "Saving…" : "Confirm acknowledge"}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      {acknowledge.isError ? (
        <div className="text-xs text-err">Couldn't acknowledge: {acknowledge.error.message}</div>
      ) : null}
    </form>
  )
}

function FlagsCell({ studentId, flags }: { studentId: string; flags: AtRiskFlag[] }) {
  if (flags.length === 0) return <span className="text-xs text-t3">—</span>
  return (
    <div className="flex flex-col gap-3 max-w-[360px]">
      {flags.map((f) => (
        <div key={f.reason} className="flex flex-col">
          <div className="flex items-start gap-1.5 text-dense-sm text-t2 leading-[1.4]">
            <span
              aria-hidden="true"
              className="text-err mt-[5px] w-[5px] h-[5px] rounded-full bg-err flex-none"
            />
            <span className="flex-1 text-pretty">{f.summary}</span>
          </div>
          <AcknowledgeControl studentId={studentId} flag={f} />
        </div>
      ))}
    </div>
  )
}

export function AtRiskList() {
  const [reason, setReason] = useState("")
  const [acknowledged, setAcknowledged] = useState("")
  const [sortColumn, setSortColumn] = useState<SortColumn>("severity")
  const [sortDir, setSortDir] = useState<1 | -1>(1)

  const listQuery = useAtRiskList({
    reason: reason || undefined,
    acknowledged: acknowledged === "" ? undefined : acknowledged === "true",
  })

  function toggleSort(column: SortColumn) {
    if (column === sortColumn) {
      setSortDir((d) => (d === 1 ? -1 : 1))
    } else {
      setSortColumn(column)
      setSortDir(1)
    }
  }

  if (listQuery.isPending) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">At-risk students</h1>
        <div role="status" className="text-dense-lg text-t2">
          Loading at-risk students…
        </div>
      </div>
    )
  }

  if (listQuery.isError) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">At-risk students</h1>
        <ErrorState
          heading="Couldn't load the at-risk list"
          body={listQuery.error.message}
          action={{ label: "Retry", onClick: () => listQuery.refetch() }}
        />
      </div>
    )
  }

  const students = [...listQuery.data.students].sort((a, b) =>
    compareEntries(a, b, sortColumn, sortDir),
  )
  const filtersActive = reason !== "" || acknowledged !== ""

  return (
    <div className="lm-screen flex flex-col gap-6 min-w-0">
      <div className="flex flex-col gap-1">
        <div className="font-mono text-2xs tracking-[0.11em] uppercase text-t3">
          Flagged by trajectory, not by one bad day
        </div>
        <h1 className="text-display-md mt-1">At-risk students</h1>
      </div>

      <div className="flex items-end gap-4 flex-wrap">
        <label className="flex flex-col gap-1.5 text-dense-sm text-t2">
          Reason
          <select
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="border border-border bg-surface rounded-lg px-3 py-2 text-dense text-t1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            {REASON_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1.5 text-dense-sm text-t2">
          Acknowledged
          <select
            value={acknowledged}
            onChange={(e) => setAcknowledged(e.target.value)}
            className="border border-border bg-surface rounded-lg px-3 py-2 text-dense text-t1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            {ACK_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {students.length === 0 ? (
        <EmptyState
          heading={filtersActive ? "No matches for these filters" : "Nothing flagged right now"}
          body={
            filtersActive
              ? "No flagged student matches the current reason/acknowledged filters."
              : "No students across your classes are currently flagged as at risk — good news."
          }
          action={
            filtersActive
              ? {
                  label: "Clear filters",
                  onClick: () => {
                    setReason("")
                    setAcknowledged("")
                  },
                }
              : undefined
          }
        />
      ) : (
        <div
          className="bg-surface border border-border rounded-lg overflow-hidden overflow-x-auto min-w-0"
          tabIndex={0}
          role="region"
          aria-label="At-risk students, scrollable horizontally"
        >
          <table className="w-full text-dense border-collapse">
            <caption className="sr-only">
              Flagged students across your classes, sortable by every column. Severity mirrors
              the order this list already arrives in from the server: most flags, then worst
              grade, first.
            </caption>
            <thead>
              <tr className="bg-surface-2 border-b border-border">
                {COLUMNS.map((col) => {
                  const active = col.key === sortColumn
                  return (
                    <th
                      key={col.key}
                      scope="col"
                      aria-sort={active ? (sortDir === 1 ? "ascending" : "descending") : "none"}
                      className="text-left px-[16px] py-[10px] align-bottom"
                    >
                      <button
                        type="button"
                        onClick={() => toggleSort(col.key)}
                        className="inline-flex items-center gap-1 font-mono text-3xs tracking-[0.09em] uppercase text-t3 hover:text-t1 cursor-pointer bg-transparent border-0 p-0"
                      >
                        {col.label}
                        {active ? <span aria-hidden="true">{sortDir === 1 ? "↑" : "↓"}</span> : null}
                      </button>
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {students.map((s) => (
                <tr key={s.studentId} className="border-b border-border last:border-b-0 align-top">
                  <td className="px-[16px] py-[13px]">
                    <div className="flex items-center gap-2.5">
                      <Avatar initials={initialsOf(s.displayName)} className="w-7 h-7 text-3xs flex-none" />
                      <Link to={`/teacher/students/${s.studentId}`} className="text-t1 hover:underline">
                        {s.displayName}
                      </Link>
                    </div>
                  </td>
                  <td className="px-[16px] py-[13px]">
                    <Link
                      to={`/teacher/classes/${s.classId}`}
                      className="text-t2 hover:text-t1 hover:underline"
                    >
                      {s.className}
                    </Link>
                  </td>
                  <td className="px-[16px] py-[13px]">
                    {s.grade ? (
                      // `AtRiskListEntryDTO.grade` is the student's latest
                      // recorded grade — the same underlying value as
                      // `StudentRowDTO.grade` (T-03) and
                      // `SubjectPredictionDTO.predictedGrade` (T-05), both of
                      // which render `basis="predicted"` for exactly this
                      // reason (their own docstrings: "the same domain
                      // notion... already uses for its below-target rule").
                      // Matching that here, not `"achieved"` — the same
                      // value must never read differently on two screens.
                      <GradeBadge grade={s.grade} size="inline" basis="predicted" />
                    ) : (
                      <span className="text-xs text-t3">No paper grade yet</span>
                    )}
                  </td>
                  <td className="px-[16px] py-[13px]">
                    <div className={cn("font-mono text-xs", s.flags.length >= 2 ? "text-err" : "text-t2")}>
                      {s.flags.length} flag{s.flags.length === 1 ? "" : "s"}
                    </div>
                  </td>
                  <td className="px-[16px] py-[13px]">
                    <FlagsCell studentId={s.studentId} flags={s.flags} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
