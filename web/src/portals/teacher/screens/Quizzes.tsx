import { useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Chip, type ChipProps } from "@/components/ui/chip"
import { GradeBadge } from "@/components/ui/grade-badge"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { useCreateQuiz, useTeacherQuizzes } from "@/lib/hooks/useTeacherApi"
import type { QuizSummary } from "@/lib/teacherTypes"

/*
 * Quiz list (T-09's entry screen). Wired to `GET /teacher/quizzes`
 * (`useTeacherQuizzes()`) — replaces the old `Quizzes.tsx`, which rendered a
 * single hardcoded "Y11 Thermal physics catch-up" draft with no backend
 * behind any control (title/topics/difficulty/pool were all local `useState`
 * that reset on refresh). This screen is what makes "draft saving
 * throughout" (a named T-09 state) real: every quiz here, however
 * incomplete, is a real `quizzes` row a teacher can resume.
 *
 * "New quiz" collects exactly step 1's two required fields
 * (`CreateQuizRequest`: title + subjectCode) and creates the draft
 * immediately — there is no client-side "unsaved new quiz" state, matching
 * the rest of this builder's "every navigation is a real write" discipline
 * (see `QuizBuilder.tsx`'s module doc). On success the teacher lands
 * straight in the builder at step 1.
 *
 * Columns: title, subject, status, question count, target grade, and — for
 * a draft only — which step it's parked at, so "come back to this later"
 * has a visible answer instead of forcing the teacher to reopen it to find
 * out. A non-draft quiz's builder step is meaningless (the builder no
 * longer accepts edits once it's not a draft — see `QuizSummary`'s doc) so
 * that cell reads "—" rather than a stale number.
 *
 * Uses `text-t2` for muted labels, not the `text-t3` pattern
 * `Classes.tsx`/`ReviewItem.tsx` use for identical eyebrow/caption text —
 * see `QuizBuilder.tsx`'s module doc for why (a real, pre-existing
 * `--t3`-contrast defect found by axe, not a copy-paste inconsistency).
 */

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  assigned: "Assigned",
  closed: "Closed",
  archived: "Archived",
}

const STATUS_TONE: Record<string, NonNullable<ChipProps["tone"]>> = {
  draft: "neutral",
  assigned: "accent",
  closed: "ok",
  archived: "neutral",
}

/** Shared with `QuizBuilder.tsx` (its header chip + read-only banner) so the
 * two screens never drift on what a status word means. */
export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status
}

export function statusTone(status: string): NonNullable<ChipProps["tone"]> {
  return STATUS_TONE[status] ?? "neutral"
}

type SortColumn = "title" | "subjectCode" | "status" | "questionCount" | "targetGrade"

const GRADE_ORDER = ["A*", "A", "B", "C", "D", "E", "U"]

function valueFor(q: QuizSummary, column: SortColumn): string | number | null {
  switch (column) {
    case "title":
      return q.title
    case "subjectCode":
      return q.subjectCode
    case "status":
      return q.status
    case "questionCount":
      return q.questionCount
    case "targetGrade": {
      const idx = q.targetGrade ? GRADE_ORDER.indexOf(q.targetGrade) : -1
      return idx === -1 ? null : idx
    }
  }
}

function compareQuizzes(a: QuizSummary, b: QuizSummary, column: SortColumn, dir: 1 | -1): number {
  const av = valueFor(a, column)
  const bv = valueFor(b, column)
  if (av == null && bv == null) return 0
  if (av == null) return 1
  if (bv == null) return -1
  if (typeof av === "string" && typeof bv === "string") return av.localeCompare(bv) * dir
  return ((av as number) - (bv as number)) * dir
}

const COLUMNS: { key: SortColumn; label: string }[] = [
  { key: "title", label: "Title" },
  { key: "subjectCode", label: "Subject" },
  { key: "status", label: "Status" },
  { key: "questionCount", label: "Questions" },
  { key: "targetGrade", label: "Target grade" },
]

export function Quizzes() {
  const navigate = useNavigate()
  const quizzesQuery = useTeacherQuizzes()
  const createQuiz = useCreateQuiz()

  const [search, setSearch] = useState("")
  const [sortColumn, setSortColumn] = useState<SortColumn>("title")
  const [sortDir, setSortDir] = useState<1 | -1>(1)
  const [showCreate, setShowCreate] = useState(false)
  const [title, setTitle] = useState("")
  const [subjectCode, setSubjectCode] = useState("")

  if (quizzesQuery.isPending) {
    return (
      <div className="lm-screen flex flex-col gap-5 min-w-0">
        <h1 className="sr-only">AI quizzes</h1>
        <div role="status" className="text-[13.5px] text-t2">
          Loading quizzes…
        </div>
      </div>
    )
  }

  if (quizzesQuery.isError) {
    return (
      <div className="lm-screen flex flex-col gap-5 min-w-0">
        <h1 className="sr-only">AI quizzes</h1>
        <ErrorState
          heading="Couldn't load your quizzes"
          body={quizzesQuery.error.message}
          action={{ label: "Retry", onClick: () => quizzesQuery.refetch() }}
        />
      </div>
    )
  }

  const quizzes = quizzesQuery.data.quizzes
  const term = search.trim().toLowerCase()
  const filtered = term
    ? quizzes.filter(
        (q) => q.title.toLowerCase().includes(term) || q.subjectCode.toLowerCase().includes(term),
      )
    : quizzes
  const sorted = [...filtered].sort((a, b) => compareQuizzes(a, b, sortColumn, sortDir))

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
    const trimmedTitle = title.trim()
    const trimmedSubject = subjectCode.trim()
    if (!trimmedTitle || !trimmedSubject) return
    createQuiz.mutate(
      { title: trimmedTitle, subjectCode: trimmedSubject },
      {
        onSuccess: (quiz) => {
          navigate(`/teacher/quizzes/${quiz.id}?step=1`)
        },
      },
    )
  }

  return (
    <div className="lm-screen flex flex-col gap-5 min-w-0">
      <div className="flex items-end gap-[18px] pb-[18px] border-b border-border flex-wrap gap-y-3">
        <div>
          <div className="font-mono text-[11px] tracking-[0.11em] uppercase text-t2">
            {quizzes.length} quiz{quizzes.length === 1 ? "" : "zes"}
          </div>
          <h1 className="font-serif text-[34px] leading-[1.1] mt-1.5">AI quizzes</h1>
        </div>
        <div className="flex-1" />
        <label className="flex flex-col gap-1">
          <span className="sr-only">Search quizzes</span>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search quizzes or subjects…"
            className="border border-border bg-surface rounded-lg px-3.5 py-2 text-[13px] w-[240px] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          />
        </label>
        <Button variant="ink" onClick={() => setShowCreate((v) => !v)}>
          {showCreate ? "Cancel" : "+ New quiz"}
        </Button>
      </div>

      {showCreate ? (
        <form
          onSubmit={handleCreate}
          className="bg-surface border border-border rounded-[14px] p-[18px] flex flex-wrap items-end gap-3"
        >
          <label className="flex flex-col gap-1.5 text-[12.5px] text-t2 flex-1 min-w-[220px]">
            Quiz title
            <input
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Y11 Thermal physics catch-up"
              className="border border-border bg-surface rounded-lg px-3 py-2 text-[13px] text-t1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            />
          </label>
          <label className="flex flex-col gap-1.5 text-[12.5px] text-t2 w-[160px]">
            Subject code
            <input
              required
              value={subjectCode}
              onChange={(e) => setSubjectCode(e.target.value)}
              placeholder="e.g. 0625"
              className="border border-border bg-surface rounded-lg px-3 py-2 text-[13px] text-t1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            />
          </label>
          <Button type="submit" variant="ink" disabled={createQuiz.isPending}>
            {createQuiz.isPending ? "Creating…" : "Create draft"}
          </Button>
          {createQuiz.isError ? (
            <div className="text-[12.5px] text-err w-full">
              Couldn't create the quiz: {createQuiz.error.message}
            </div>
          ) : null}
        </form>
      ) : null}

      {quizzes.length === 0 ? (
        <EmptyState
          heading="No quizzes yet"
          body="A quiz is a set of past-paper or AI-generated questions targeted at a grade, assigned to a class, and auto-marked when students submit it. Start one below — you can save it as a draft at any step and come back later."
          action={{ label: "Create a quiz", onClick: () => setShowCreate(true) }}
        />
      ) : (
        <div
          className="bg-surface border border-border rounded-[14px] overflow-hidden overflow-x-auto min-w-0"
          tabIndex={0}
          role="region"
          aria-label="Your quizzes, scrollable horizontally"
        >
          <table className="w-full text-[13px] border-collapse">
            <caption className="sr-only">Your quizzes, sortable by every column</caption>
            <thead>
              <tr className="bg-surface-2 border-b border-border">
                {COLUMNS.map((col) => {
                  const active = col.key === sortColumn
                  return (
                    <th
                      key={col.key}
                      scope="col"
                      aria-sort={active ? (sortDir === 1 ? "ascending" : "descending") : "none"}
                      className="text-left px-[18px] py-[10px]"
                    >
                      <button
                        type="button"
                        onClick={() => toggleSort(col.key)}
                        className="inline-flex items-center gap-1 font-mono text-[10px] tracking-[0.09em] uppercase text-t2 hover:text-t1 cursor-pointer bg-transparent border-0 p-0"
                      >
                        {col.label}
                        {active ? <span aria-hidden="true">{sortDir === 1 ? "↑" : "↓"}</span> : null}
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
                  <td colSpan={COLUMNS.length + 1} className="px-[18px] py-6 text-t2 text-[13px]">
                    No quizzes match "{search}".
                  </td>
                </tr>
              ) : (
                sorted.map((q) => (
                  <tr key={q.id} className="border-b border-border last:border-b-0">
                    <td className="px-[18px] py-[13px]">
                      <Link to={`/teacher/quizzes/${q.id}`} className="text-t1 hover:underline">
                        {q.title}
                      </Link>
                      {q.status === "draft" ? (
                        <div className="text-[11.5px] text-t2 mt-0.5">
                          Step {q.builderStep} of 6
                        </div>
                      ) : null}
                    </td>
                    <td className="px-[18px] py-[13px] font-mono text-[12.5px] text-t2">
                      {q.subjectCode}
                    </td>
                    <td className="px-[18px] py-[13px]">
                      <Chip tone={statusTone(q.status)}>{statusLabel(q.status)}</Chip>
                    </td>
                    <td className="px-[18px] py-[13px] font-mono text-[12.5px]">{q.questionCount}</td>
                    <td className="px-[18px] py-[13px]">
                      {q.targetGrade ? (
                        <GradeBadge grade={q.targetGrade} size="inline" basis="predicted" />
                      ) : (
                        <span className="text-[12px] text-t2">Not set</span>
                      )}
                    </td>
                    <td className="px-[18px] py-[13px] text-right whitespace-nowrap">
                      <Button size="sm" variant="secondary" onClick={() => navigate(`/teacher/quizzes/${q.id}`)}>
                        {q.status === "draft" ? "Continue →" : "Open →"}
                      </Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
