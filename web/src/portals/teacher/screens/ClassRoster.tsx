/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { Minus, TrendDown, TrendUp } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { GradeBadge } from "@/components/ui/grade-badge"
import { EmptyState } from "@/components/ui/state-views"
import { cn, relativeTime } from "@/lib/utils"
import { Avatar } from "@/components/ui/avatar"
import { useEnrollStudent, useRemoveStudent } from "@/lib/hooks/useTeacherApi"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import { teacherMutationFailureMessage } from "@/lib/teacherOutcome"
import type { StudentRow } from "@/lib/teacherTypes"
import { useClassDetailContext } from "./ClassDetail"
import { SortArrow } from "@/components/ui/inline-arrow"

/*
 * Class detail — roster (T-03). Reads `classDetail.students` from
 * `ClassDetailLayout`'s outlet context (`useClassDetailContext()` — one
 * `GET /classes/{classId}` fetch shared with the header, no second roster
 * query). Roster mutations are real: `useEnrollStudent`/`useRemoveStudent`
 * (`POST .../enroll`, `DELETE .../students/{id}`), both invalidating this
 * class's detail query on success.
 *
 * Columns per spec (name, papers submitted, average mark, predicted grade,
 * trend, at-risk flag with reason, last active) — every column sortable,
 * real `aria-sort` + keyboard-operable `<button>` headers, same pattern as
 * `Classes.tsx` (T-02).
 *
 * Two deliberate label corrections vs. the spec's literal wording, both
 * because the DTO the spec asks for doesn't carry what the words imply
 * (same judgment call D3.12 already made for "average predicted grade" on
 * T-01/T-02):
 *  - "average mark" -> **"Latest mark"**. `StudentRowDTO.mark` is
 *    `awarded/max marks of the student's latest paper only` (see the field's
 *    docstring) — not an average across their history. Labelling it
 *    "Average mark" would invent precision (principle §1.4/§1.6).
 *  - "predicted grade" -> `grade` IS treated as this app's working notion of
 *    "predicted grade" everywhere else (T-05's `SubjectPredictionDTO`
 *    docstring says so explicitly: "the same domain notion... already
 *    uses for its below-target rule"), so the column keeps the spec's
 *    wording and renders with `GradeBadge basis="predicted"` (outlined,
 *    provisional) rather than `"achieved"`.
 *
 * `gradeAtRisk` (grade currently in D/E/U) and `flags` (the D3.3 trend/
 * inactivity/below-target engine) are two different signals (D3.3) and are
 * rendered in two different places: `gradeAtRisk` as a small chip beside the
 * grade badge itself ("this grade is low right now"), `flags` in its own
 * "At risk" column with the real reason sentence per flag (spec: "reasons
 * must be shown, not just a red dot") and the acknowledged tag, never
 * hidden (D3.5) — T-03 has no acknowledge *action* (that's T-06, chunk d);
 * this table only ever displays acknowledgement state.
 *
 * "Trend" renders the row's single `delta` (the only trend datum this DTO
 * carries — a scalar, not a series) as a directional read, not a fabricated
 * `TrendSparkline` (which needs a real multi-point series; two points
 * conjured from one delta would draw a shape this data doesn't support).
 *
 * Bulk actions ("assign a quiz", "post an announcement") are visibly
 * disabled with a "Coming soon" tag — T-09/T-10 quiz builder and T-12
 * announcement composer don't exist until P3.8 — following `Overview.tsx`'s
 * precedent, never a button that silently does nothing.
 */

type SortColumn = "name" | "paperCount" | "mark" | "grade" | "delta" | "atRisk" | "lastActiveAt"

const GRADE_ORDER = ["A*", "A", "B", "C", "D", "E", "U"]

function markPercent(mark: string): number | null {
  const [awarded, max] = mark.split("/").map(Number)
  if (!mark || Number.isNaN(awarded) || !max) return null
  return (awarded / max) * 100
}

function valueFor(s: StudentRow, column: SortColumn): string | number | null {
  switch (column) {
    case "name":
      return s.name
    case "paperCount":
      return s.paperCount
    case "mark":
      return markPercent(s.mark)
    case "grade": {
      const idx = GRADE_ORDER.indexOf(s.grade)
      return idx === -1 ? null : idx
    }
    case "delta":
      return s.delta
    case "atRisk":
      return s.flags.length
    case "lastActiveAt":
      return s.lastActiveAt
  }
}

function compareStudents(a: StudentRow, b: StudentRow, column: SortColumn, dir: 1 | -1): number {
  const av = valueFor(a, column)
  const bv = valueFor(b, column)
  if (av == null && bv == null) return 0
  if (av == null) return 1
  if (bv == null) return -1
  // Grade sorts by ladder *position* — lower index (A*) is the best grade,
  // so "ascending" on the column means best-first, matching how a teacher
  // reads a grade column left-to-right (unlike a plain number column, where
  // ascending means smallest-first).
  if (column === "grade") return ((av as number) - (bv as number)) * dir
  if (typeof av === "string" && typeof bv === "string") return av.localeCompare(bv) * dir
  return ((av as number) - (bv as number)) * dir
}

const COLUMNS: { key: SortColumn; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "paperCount", label: "Papers" },
  { key: "mark", label: "Latest mark" },
  { key: "grade", label: "Predicted grade" },
  { key: "delta", label: "Trend" },
  { key: "atRisk", label: "At risk" },
  { key: "lastActiveAt", label: "Last active" },
]

function TrendCell({ delta }: { delta: number | null }) {
  if (delta == null) {
    return <span className="text-body-sm text-ink-faint">No prior paper</span>
  }
  const Icon = delta > 0 ? TrendUp : delta < 0 ? TrendDown : Minus
  const tone = delta > 0 ? "text-ok" : delta < 0 ? "text-err" : "text-ink-muted"
  return (
    <span className={cn("inline-flex items-center gap-1 text-data-sm", tone)}>
      <Icon weight="bold" className="w-3 h-3" aria-hidden />
      {delta > 0 ? "+" : ""}
      {Math.round(delta)}pts
    </span>
  )
}

function AtRiskCell({ flags }: { flags: StudentRow["flags"] }) {
  if (flags.length === 0) {
    return <span className="text-body-sm text-ink-faint">—</span>
  }
  return (
    <div className="flex flex-col gap-[7px] max-w-[280px]">
      {flags.map((f) => (
        <div key={f.reason} className="flex items-start gap-1.5 text-body-sm text-ink-muted leading-[1.4]">
          <span
            aria-hidden="true"
            className="text-err mt-[5px] w-[5px] h-[5px] rounded-full bg-err flex-none"
          />
          <span className="flex-1 text-pretty">{f.summary}</span>
          {f.acknowledged ? (
            <Chip tone="neutral" className="flex-none">
              Acknowledged
            </Chip>
          ) : null}
        </div>
      ))}
    </div>
  )
}

function AddStudentsPanel({ classId, hasSchool }: { classId: string; hasSchool: boolean }) {
  const enroll = useEnrollStudent(classId)
  const [studentId, setStudentId] = useState("")

  function handleEnroll(e: FormEvent) {
    e.preventDefault()
    const trimmed = studentId.trim()
    if (!trimmed) return
    enroll.mutate(trimmed, { onSuccess: () => setStudentId("") })
  }

  return (
    <div className="bg-paper-raised border border-rule rounded-lg p-[18px] flex flex-col gap-3">
      <div className="text-display-sm text-ink">Add students</div>
      <p className="text-body-md text-ink-muted text-pretty m-0">
        Share the invite code above, and students join themselves from the student portal. That
        works for every class, with or without a linked school.
      </p>
      {hasSchool ? (
        <form onSubmit={handleEnroll} className="flex flex-wrap items-end gap-3 pt-2 border-t border-rule">
          <label className="flex flex-col gap-1.5 text-body-sm text-ink-muted flex-1 min-w-[220px]">
            Or add a student already seated in this school, by id
            <input
              required
              value={studentId}
              onChange={(e) => setStudentId(e.target.value)}
              placeholder="Student id (uuid)"
              className="border border-rule bg-paper-raised rounded-lg px-3 py-2 text-data-md text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
            />
          </label>
          <Button type="submit" variant="secondary" disabled={enroll.isPending}>
            {enroll.isPending ? "Adding…" : "Add"}
          </Button>
        </form>
      ) : (
        <p className="text-body-sm text-ink-faint pt-2 border-t border-rule m-0">
          This class has no linked school, so there's no seat pool to add a student by id
          from. The invite code above is the only way in.
        </p>
      )}
      {enroll.isError ? (
        <div className="text-body-sm text-err">Couldn't add that student: {teacherMutationFailureMessage(enroll.error)}</div>
      ) : null}
    </div>
  )
}

export function ClassRoster() {
  const { classDetail, classId } = useClassDetailContext()
  const removeStudent = useRemoveStudent(classId)

  const [sortColumn, setSortColumn] = useState<SortColumn>("name")
  const [sortDir, setSortDir] = useState<1 | -1>(1)
  const [showAdd, setShowAdd] = useState(false)

  const sorted = [...classDetail.students].sort((a, b) =>
    compareStudents(a, b, sortColumn, sortDir),
  )

  function toggleSort(column: SortColumn) {
    if (column === sortColumn) {
      setSortDir((d) => (d === 1 ? -1 : 1))
    } else {
      setSortColumn(column)
      setSortDir(1)
    }
  }

  const [pendingRemove, setPendingRemove] = useState<StudentRow | null>(null)

  return (
    <div className="flex flex-col gap-5 min-w-0">
      <h2 className="sr-only">Roster</h2>

      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex-1" />
        <Button variant="secondary" size="sm" onClick={() => setShowAdd((v) => !v)}>
          {showAdd ? "Hide add students" : "+ Add students"}
        </Button>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" disabled aria-disabled="true" title="Coming in a later release">
            Assign a quiz
          </Button>
          <Chip tone="neutral">Coming soon</Chip>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" disabled aria-disabled="true" title="Coming in a later release">
            Post an announcement
          </Button>
          <Chip tone="neutral">Coming soon</Chip>
        </div>
      </div>

      {showAdd ? <AddStudentsPanel classId={classId} hasSchool={classDetail.schoolId != null} /> : null}

      {classDetail.students.length === 0 ? (
        <EmptyState
          heading="No students yet"
          body={
            classDetail.joinCode
              ? `Share the code "${classDetail.joinCode}" with your students. They enter it from the student portal to join.`
              : "Add students to start tracking their marks."
          }
          action={{ label: "Add students", onClick: () => setShowAdd(true) }}
        />
      ) : (
        <div
          className="bg-paper-raised border border-rule rounded-lg overflow-hidden overflow-x-auto min-w-0"
          tabIndex={0}
          role="region"
          aria-label="Class roster, scrollable horizontally"
        >
          <table className="w-full text-body-md border-collapse">
            <caption className="sr-only">Class roster, sortable by every column</caption>
            <thead>
              <tr className="bg-paper-sunk border-b border-rule">
                {COLUMNS.map((col) => {
                  const active = col.key === sortColumn
                  return (
                    <th
                      key={col.key}
                      scope="col"
                      aria-sort={active ? (sortDir === 1 ? "ascending" : "descending") : "none"}
                      className="text-start px-[16px] py-[10px] align-bottom"
                    >
                      <button
                        type="button"
                        onClick={() => toggleSort(col.key)}
                        className="inline-flex items-center gap-1 text-eyebrow text-ink-faint transition-colors hover:text-ink cursor-pointer bg-transparent border-0 p-0"
                      >
                        {col.label}
                        {active ? <SortArrow direction={sortDir === 1 ? "asc" : "desc"} /> : null}
                      </button>
                    </th>
                  )
                })}
                <th scope="col" className="px-[16px] py-[10px]">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((s) => (
                <tr key={s.studentId} className="border-b border-rule last:border-b-0 align-top">
                  <td className="px-[16px] py-[13px]">
                    <div className="flex items-center gap-2.5">
                      <Avatar name={s.name} size="sm" />
                      <Link
                        to={`/teacher/students/${s.studentId}`}
                        className="text-ink hover:underline"
                      >
                        {s.name}
                      </Link>
                    </div>
                  </td>
                  <td className="px-[16px] py-[13px] text-data-sm">
                    {s.paperCount ?? 0}
                  </td>
                  <td className="px-[16px] py-[13px] text-data-sm">
                    {s.mark || "—"}
                  </td>
                  <td className="px-[16px] py-[13px]">
                    <div className="flex items-center gap-1.5">
                      {s.grade ? (
                        <GradeBadge grade={s.grade} size="inline" basis="predicted" />
                      ) : (
                        <span className="text-body-sm text-ink-faint">No grade yet</span>
                      )}
                      {s.gradeAtRisk ? <Chip tone="warn">Low</Chip> : null}
                    </div>
                  </td>
                  <td className="px-[16px] py-[13px]">
                    <TrendCell delta={s.delta} />
                  </td>
                  <td className="px-[16px] py-[13px]">
                    <AtRiskCell flags={s.flags} />
                  </td>
                  <td className="px-[16px] py-[13px] text-body-sm text-ink-muted whitespace-nowrap">
                    {s.lastActiveAt ? relativeTime(s.lastActiveAt) : "Never"}
                  </td>
                  <td className="px-[16px] py-[13px] text-end whitespace-nowrap">
                    <Button
                      size="sm"
                      variant="ghost"
                      className={cn("text-err", removeStudent.isPending && "opacity-50")}
                      disabled={removeStudent.isPending}
                      onClick={() => setPendingRemove(s)}
                    >
                      Remove
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Reversible: the student can be enrolled again from the form above,
          and removing them from a class does not delete their marked work. The
          consequence line says so rather than borrowing the component's
          default claim that this cannot be undone. */}
      <ConfirmModal
        open={pendingRemove !== null}
        title="Remove this student from the class?"
        description={pendingRemove ? pendingRemove.name : undefined}
        consequence="You can add them back at any time. Their marked papers are not deleted."
        confirmLabel="Remove"
        pendingLabel="Removing…"
        pending={removeStudent.isPending}
        error={removeStudent.isError ? teacherMutationFailureMessage(removeStudent.error) : null}
        onCancel={() => setPendingRemove(null)}
        onConfirm={() => {
          if (!pendingRemove) return
          removeStudent.mutate(pendingRemove.studentId, {
            onSuccess: () => setPendingRemove(null),
          })
        }}
      />
      {removeStudent.isError ? (
        <div className="text-body-sm text-err">
          Couldn't remove that student: {teacherMutationFailureMessage(removeStudent.error)}
        </div>
      ) : null}
    </div>
  )
}
