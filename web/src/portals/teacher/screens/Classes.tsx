/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { EmptyState } from "@/components/ui/state-views"
import { QueryState } from "@/components/ui/query-state"
import { cn, relativeTime } from "@/lib/utils"
import {
  useTeacherClasses,
  useCreateClass,
  useUpdateClass,
  useDeleteClass,
} from "@/lib/hooks/useTeacherApi"
import { CardGridSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import {
  teacherLoadFailureMessage,
  teacherMutationFailureMessage,
} from "@/lib/teacherOutcome"
import type { ClassSummary } from "@/lib/teacherTypes"
import { SortArrow } from "@/components/ui/inline-arrow"

/*
 * Classes (T-02). Wired to `GET /teacher/classes` (`useTeacherClasses()`);
 * create/rename/delete via `useCreateClass`/`useUpdateClass`/`useDeleteClass`
 * (`POST /classes`, `PATCH`/`DELETE /classes/{id}`).
 *
 * This replaces a Classes.tsx that actually rendered T-03/T-04 mock content
 * (one class's roster + topic-mastery heatmap + grade-distribution chart —
 * `classStats`/`mastery`/`distribution`/`bubble`/`students` in `../data.ts`),
 * not a classes *list*. That content belongs to T-03/T-04 (chunk c) once
 * built against `ClassDetailDTO`/`ClassAnalyticsDTO`; it is deleted here
 * along with the mock arrays it alone consumed, not carried forward as dead
 * code for a screen this chunk doesn't own.
 *
 * Table columns per spec: name, subject, student count, average, last
 * activity, at-risk count — `ClassSummaryDTO` (chunk a, D3.12). "Average
 * predicted grade" (the spec's literal wording) is deliberately NOT
 * computed — averaging letter grades invents precision the ladder doesn't
 * support (D3.12) — `average` (mean latest percentage) is rendered and
 * labelled "Average mark" instead.
 *
 * Row -> T-03 (`/teacher/classes/:classId`) is wired (the `Link` below) even
 * though that route has no child screen until chunk c lands — the spec asks
 * for the exit and the wiring should already be in place; until then the
 * link 404s at the router level. Documented in the phase report, not
 * silently "fixed" by inventing a placeholder screen here.
 */

type SortColumn = "label" | "subjectCode" | "studentCount" | "average" | "lastActivityAt" | "atRiskCount"

function valueFor(c: ClassSummary, column: SortColumn): string | number | null {
  switch (column) {
    case "label":
      return c.label
    case "subjectCode":
      return c.subjectCode
    case "studentCount":
      return c.studentCount
    case "average":
      return c.average
    case "lastActivityAt":
      return c.lastActivityAt
    case "atRiskCount":
      return c.atRiskCount
  }
}

function compareClasses(a: ClassSummary, b: ClassSummary, column: SortColumn, dir: 1 | -1): number {
  const av = valueFor(a, column)
  const bv = valueFor(b, column)
  if (av == null && bv == null) return 0
  if (av == null) return 1
  if (bv == null) return -1
  if (typeof av === "string" && typeof bv === "string") return av.localeCompare(bv) * dir
  return ((av as number) - (bv as number)) * dir
}

const COLUMNS: { key: SortColumn; label: string }[] = [
  { key: "label", label: "Name" },
  { key: "subjectCode", label: "Subject" },
  { key: "studentCount", label: "Students" },
  { key: "average", label: "Average mark" },
  { key: "lastActivityAt", label: "Last activity" },
  { key: "atRiskCount", label: "At risk" },
]

export function Classes() {
  const classesQuery = useTeacherClasses()
  const createClass = useCreateClass()
  const updateClass = useUpdateClass()
  const deleteClass = useDeleteClass()
  const queryClient = useQueryClient()
  const [pendingDelete, setPendingDelete] = useState<ClassSummary | null>(null)

  const [search, setSearch] = useState("")
  const [sortColumn, setSortColumn] = useState<SortColumn>("label")
  const [sortDir, setSortDir] = useState<1 | -1>(1)
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState("")
  const [subjectCode, setSubjectCode] = useState("")
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState("")

  function toggleSort(column: SortColumn) {
    if (column === sortColumn) {
      setSortDir((d) => (d === 1 ? -1 : 1))
    } else {
      setSortColumn(column)
      setSortDir(1)
    }
  }

  function handleCreate(e: FormEvent) {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    createClass.mutate(
      { name: trimmed, subjectCode: subjectCode.trim() || null },
      {
        onSuccess: () => {
          setShowCreate(false)
          setName("")
          setSubjectCode("")
        },
      },
    )
  }

  function startRename(c: ClassSummary) {
    setEditingId(c.id)
    setEditName(c.label)
  }

  function saveRename(classId: string) {
    const trimmed = editName.trim()
    if (!trimmed) return
    updateClass.mutate(
      { classId, body: { name: trimmed } },
      { onSuccess: () => setEditingId(null) },
    )
  }

  /*
   * The most destructive action in the teacher portal, and until P4.5 the one
   * asking for consent through a browser dialog whose buttons said "OK" and
   * "Cancel". Deleting a class removes it for every enrolled student, so this
   * is the case C-24 `ConfirmModal`'s default consequence line was written
   * for, and the confirm button names the act rather than agreeing with a
   * question.
   */
  function handleDelete(c: ClassSummary) {
    deleteClass.mutate(c.id, {
      onSuccess: () => {
        setPendingDelete(null)
        queryClient.invalidateQueries({ queryKey: ["teacher", "overview"] })
      },
    })
  }

  return (
    <div className="lm-screen flex flex-col gap-5 min-w-0">
      <QueryState
        query={classesQuery}
        srHeading="Classes"
        skeleton={
          <>
            <PageHeaderSkeleton />
            <CardGridSkeleton count={6} />
          </>
        }
        error={{ heading: "Couldn't load your classes", body: teacherLoadFailureMessage }}
      >
        {(classList) => {
          const classes = classList.classes
          const term = search.trim().toLowerCase()
          const filtered = term
            ? classes.filter(
                (c) =>
                  c.label.toLowerCase().includes(term) ||
                  (c.subjectCode ?? "").toLowerCase().includes(term),
              )
            : classes
          const sorted = [...filtered].sort((a, b) => compareClasses(a, b, sortColumn, sortDir))

          return (
            <>
              <div className="flex items-end gap-[18px] pb-[18px] border-b border-rule flex-wrap gap-y-3">
              <div>
                <div className="text-eyebrow text-ink-faint">
                  {classes.length} class{classes.length === 1 ? "" : "es"}
                </div>
                <h1 className="text-display-md mt-1.5">Classes</h1>
              </div>
              <div className="flex-1" />
              <label className="flex flex-col gap-1">
                <span className="sr-only">Search classes</span>
                <input
                  type="search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search classes or subjects…"
                  className="border border-rule bg-paper-raised rounded-lg px-3.5 py-2 text-body-md w-[240px] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                />
              </label>
              <Button variant="ink" onClick={() => setShowCreate((v) => !v)}>
                {showCreate ? "Cancel" : "+ New class"}
              </Button>
            </div>

            {showCreate ? (
              <form
                onSubmit={handleCreate}
                className="bg-paper-raised border border-rule rounded-lg p-[18px] flex flex-wrap items-end gap-3"
              >
                <label className="flex flex-col gap-1.5 text-body-sm text-ink-muted flex-1 min-w-[200px]">
                  Class name
                  <input
                    required
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g. Y11 Physics"
                    className="border border-rule bg-paper-raised rounded-lg px-3 py-2 text-body-md text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                  />
                </label>
                <label className="flex flex-col gap-1.5 text-body-sm text-ink-muted w-[180px]">
                  Subject code (optional)
                  <input
                    value={subjectCode}
                    onChange={(e) => setSubjectCode(e.target.value)}
                    placeholder="e.g. 0625"
                    className="border border-rule bg-paper-raised rounded-lg px-3 py-2 text-body-md text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                  />
                </label>
                <Button type="submit" variant="ink" disabled={createClass.isPending}>
                  {createClass.isPending ? "Creating…" : "Create class"}
                </Button>
                {createClass.isError ? (
                  <div className="text-body-sm text-err w-full">
                    Couldn't create the class: {teacherMutationFailureMessage(createClass.error)}
                  </div>
                ) : null}
              </form>
            ) : null}

            {classes.length === 0 ? (
              <EmptyState
                heading="No classes yet"
                body="Create a class to start enrolling students and tracking their marks."
                action={{ label: "Create a class", onClick: () => setShowCreate(true) }}
              />
            ) : (
              <div
                className="bg-paper-raised border border-rule rounded-lg overflow-hidden overflow-x-auto min-w-0"
                // `tabIndex`/`role`/`aria-label` are required, not decorative: a
                // horizontally scrollable container no keyboard user can reach or
                // scroll is axe's serious `scrollable-region-focusable`. Chunk c hit
                // exactly this on the roster/heatmap/paper tables; this table has the
                // same shape and only escapes the finding today because it happens
                // not to overflow at the tested viewport and data size — latent, not
                // safe. Do not strip these as "unnecessary ARIA".
                tabIndex={0}
                role="region"
                aria-label="Your classes, scrollable horizontally"
              >
                <table className="w-full text-body-md border-collapse">
                  <caption className="sr-only">Your classes, sortable by every column</caption>
                  <thead>
                    <tr className="bg-paper-sunk border-b border-rule">
                      {COLUMNS.map((col) => {
                        const active = col.key === sortColumn
                        return (
                          <th
                            key={col.key}
                            scope="col"
                            aria-sort={active ? (sortDir === 1 ? "ascending" : "descending") : "none"}
                            className="text-start px-[18px] py-[10px]"
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
                      <th scope="col" className="px-[18px] py-[10px]">
                        <span className="sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.length === 0 ? (
                      <tr>
                        <td colSpan={COLUMNS.length + 1} className="px-[18px] py-6 text-ink-muted text-body-md">
                          No classes match "{search}".
                        </td>
                      </tr>
                    ) : (
                      sorted.map((c) => (
                        <tr key={c.id} className="border-b border-rule last:border-b-0">
                          <td className="px-[18px] py-[13px]">
                            {editingId === c.id ? (
                              <div className="flex items-center gap-2">
                                {/* P3.3: this had no accessible name at all — no
                                    label, no aria-label, not even a placeholder. It
                                    appears in place of the class name when a teacher
                                    clicks rename, so a screen reader announced an
                                    anonymous textbox already containing text, with
                                    nothing to say what editing it would do. There is
                                    no room for a visible label inside a table cell
                                    that is standing in for one line of text, so the
                                    name is carried by `aria-label`. */}
                                <input
                                  autoFocus
                                  aria-label={`Rename class ${c.label}`}
                                  value={editName}
                                  onChange={(e) => setEditName(e.target.value)}
                                  className="border border-rule bg-paper-raised rounded-lg px-2.5 py-1.5 text-body-md text-ink w-[160px] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                                />
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  disabled={updateClass.isPending}
                                  onClick={() => saveRename(c.id)}
                                >
                                  Save
                                </Button>
                                <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                                  Cancel
                                </Button>
                              </div>
                            ) : (
                              <Link to={`/teacher/classes/${c.id}`} className="text-ink hover:underline">
                                {c.label}
                              </Link>
                            )}
                          </td>
                          <td className="px-[18px] py-[13px] text-data-sm text-ink-faint">
                            {c.subjectCode ? (
                              <div className="flex flex-col gap-0.5">
                                <span className="text-body-sm text-ink">{c.subjectName ?? c.subjectCode}</span>
                                {/* Omitted when the name has resolved to the code
                                    itself — a class's `subjectCode` is free text a
                                    teacher typed, so most classes hit the det
                                    registry's default profile (name === code, see
                                    `subjectIdentifier`'s docstring) and this element
                                    would otherwise print the same code twice. */}
                                {(c.subjectName ?? c.subjectCode) !== c.subjectCode ? (
                                  <span className="text-data-sm text-ink-faint">{c.subjectCode}</span>
                                ) : null}
                              </div>
                            ) : (
                              <span className="text-body-sm text-ink-faint">Not set</span>
                            )}
                          </td>
                          <td className="px-[18px] py-[13px] text-data-sm">{c.studentCount}</td>
                          <td className="px-[18px] py-[13px] text-data-sm">
                            {c.average != null ? `${Math.round(c.average)}%` : "—"}
                          </td>
                          <td className="px-[18px] py-[13px] text-body-sm text-ink-muted">
                            {c.lastActivityAt ? relativeTime(c.lastActivityAt) : "No activity yet"}
                          </td>
                          <td className="px-[18px] py-[13px]">
                            {c.atRiskCount ? (
                              <Chip tone="err">{c.atRiskCount}</Chip>
                            ) : (
                              <span className="text-data-sm text-ink-faint">0</span>
                            )}
                          </td>
                          <td className="px-[18px] py-[13px] text-end whitespace-nowrap">
                            {editingId === c.id ? null : (
                              <>
                                <Button size="sm" variant="ghost" onClick={() => startRename(c)}>
                                  Rename
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className={cn("text-err", deleteClass.isPending && "opacity-50")}
                                  disabled={deleteClass.isPending}
                                  onClick={() => setPendingDelete(c)}
                                >
                                  Delete
                                </Button>
                              </>
                            )}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}

              <ConfirmModal
              open={pendingDelete !== null}
              title="Delete this class?"
              description={pendingDelete ? `"${pendingDelete.label}"` : undefined}
              consequence="This removes the class for every enrolled student, along with its roster. It cannot be undone."
              confirmLabel="Delete class"
              pendingLabel="Deleting…"
              pending={deleteClass.isPending}
              error={deleteClass.isError ? teacherMutationFailureMessage(deleteClass.error) : null}
              onCancel={() => setPendingDelete(null)}
              onConfirm={() => {
                if (pendingDelete) handleDelete(pendingDelete)
              }}
            />
            {deleteClass.isError ? (
              <div className="text-body-sm text-err">
                Couldn't delete the class: {teacherMutationFailureMessage(deleteClass.error)}
              </div>
            ) : null}
            {updateClass.isError ? (
              <div className="text-body-sm text-err">
                Couldn't rename the class: {teacherMutationFailureMessage(updateClass.error)}
              </div>
            ) : null}
            </>
          )
        }}
      </QueryState>
    </div>
  )
}
