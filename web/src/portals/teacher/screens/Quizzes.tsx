import { useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Chip, type ChipProps } from "@/components/ui/chip"
import { GradeBadge } from "@/components/ui/grade-badge"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { Input } from "@/components/ui/input"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import {
  teacherLoadFailureMessage,
  teacherMutationFailureMessage,
} from "@/lib/teacherOutcome"
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
 * **P4.5 retires this screen's contrast workaround.** It used to use the
 * `--t2` step for muted labels where `Classes.tsx`/`ReviewItem.tsx` used
 * `--t3` for identical eyebrow and caption text, because `--t3` failed
 * contrast under the build-era palette and axe caught it. The Study Notebook
 * palette fixes that by construction: DESIGN.md §3.2 sets `--ink-faint` at
 * L 0.529 specifically so it clears AA on all three paper surfaces (4.94:1 on
 * `--paper`, 4.60:1 on the darkest, `--paper-sunk`), and there is deliberately
 * no lighter step to reach for. So the divergence has no reason to exist any
 * more and this screen uses `--ink-faint` like its neighbours.
 */

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  assigned: "Assigned",
  closed: "Closed",
  archived: "Archived",
}

/*
 * P4.5: `assigned` was `accent`. On the Study Notebook palette the accent is a
 * warm coral-red, so the healthy live state rendered in the product's alert
 * register while `closed` sat beside it in `ok` teal — a teacher scanning the
 * list read alarm on the working rows and success on the finished ones.
 * `info` is §3.6's neutral-notice pair and is what "currently live" should
 * look like.
 */
const STATUS_TONE: Record<string, NonNullable<ChipProps["tone"]>> = {
  draft: "neutral",
  assigned: "info",
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
        <PageHeaderSkeleton />
        <ListSkeleton rows={5} />
      </div>
    )
  }

  if (quizzesQuery.isError) {
    return (
      <div className="lm-screen flex flex-col gap-5 min-w-0">
        <h1 className="sr-only">AI quizzes</h1>
        <ErrorState
          heading="Couldn't load your quizzes"
          body={teacherLoadFailureMessage(quizzesQuery.error)}
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
      <div className="flex items-end gap-[18px] pb-5 border-b border-rule flex-wrap gap-y-3">
        <div>
          <div className="text-eyebrow text-ink-faint">
            {quizzes.length} quiz{quizzes.length === 1 ? "" : "zes"}
          </div>
          <h1 className="text-display-lg text-ink mt-1.5">AI quizzes</h1>
        </div>
        <div className="flex-1" />
        {/* The kit's `<Input>`, which requires a label by type rather than by
            convention — §12 bans placeholder-as-label and the kit enforces it
            at the prop signature. `labelClassName="sr-only"` keeps this one
            visually hidden, which is the right call for a search field beside
            a heading that names what is being searched, and is different from
            having no label at all. */}
        <Input
          type="search"
          label="Search quizzes"
          labelClassName="sr-only"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search quizzes or subjects…"
          wrapperClassName="w-[240px]"
        />
        <Button variant="ink" onClick={() => setShowCreate((v) => !v)}>
          {showCreate ? "Cancel" : "+ New quiz"}
        </Button>
      </div>

      {showCreate ? (
        <form
          onSubmit={handleCreate}
          className="bg-paper-raised border border-rule rounded-lg p-6 flex flex-wrap items-end gap-3"
        >
          <Input
            required
            label="Quiz title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Y11 Thermal physics catch-up"
            wrapperClassName="flex-1 min-w-[220px]"
          />
          <Input
            required
            label="Subject code"
            value={subjectCode}
            onChange={(e) => setSubjectCode(e.target.value)}
            placeholder="e.g. 0625"
            wrapperClassName="w-[160px]"
          />
          <Button type="submit" variant="ink" disabled={createQuiz.isPending}>
            {createQuiz.isPending ? "Creating…" : "Create draft"}
          </Button>
          {createQuiz.isError ? (
            <div className="text-body-sm text-err w-full">
              Couldn't create the quiz: {teacherMutationFailureMessage(createQuiz.error)}
            </div>
          ) : null}
        </form>
      ) : null}

      {quizzes.length === 0 ? (
        <EmptyState
          heading="No quizzes yet"
          body="A quiz is a set of past-paper or AI-generated questions targeted at a grade, assigned to a class, and auto-marked when students submit it. Start one below. You can save it as a draft at any step and come back later."
          action={{ label: "Create a quiz", onClick: () => setShowCreate(true) }}
        />
      ) : (
        <div
          className="bg-paper-raised border border-rule rounded-lg overflow-hidden overflow-x-auto min-w-0"
          tabIndex={0}
          role="region"
          aria-label="Your quizzes, scrollable horizontally"
        >
          <table className="w-full text-body-md border-collapse">
            <caption className="sr-only">Your quizzes, sortable by every column</caption>
            <thead>
              <tr className="bg-paper-sunk border-b border-rule">
                {COLUMNS.map((col) => {
                  const active = col.key === sortColumn
                  return (
                    <th
                      key={col.key}
                      scope="col"
                      aria-sort={active ? (sortDir === 1 ? "ascending" : "descending") : "none"}
                      className="text-start px-6 py-2.5"
                    >
                      <button
                        type="button"
                        onClick={() => toggleSort(col.key)}
                        // `whitespace-nowrap` (P6.1): "Target grade" is two
                        // words in an uppercase eyebrow inside a table header
                        // cell, and it broke across two lines at every width
                        // from 320 to 768 — a two-line clickable target, and on
                        // a sort control the second line looks like a separate
                        // header. The column can be wider; the label cannot
                        // break.
                        className="inline-flex items-center gap-1 whitespace-nowrap text-eyebrow text-ink-faint transition-colors hover:text-ink cursor-pointer bg-transparent border-0 p-0 rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                      >
                        {col.label}
                        {active ? <span aria-hidden="true">{sortDir === 1 ? "↑" : "↓"}</span> : null}
                      </button>
                    </th>
                  )
                })}
                <th scope="col" className="px-6 py-2.5">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sorted.length === 0 ? (
                <tr>
                  <td colSpan={COLUMNS.length + 1} className="px-6 py-6 text-ink-muted text-body-md">
                    No quizzes match "{search}".
                  </td>
                </tr>
              ) : (
                sorted.map((q) => (
                  <tr key={q.id} className="border-b border-rule last:border-b-0">
                    <td className="px-6 py-3.5">
                      {/* Opts out of §6.1's two-line-clickable rule: a quiz
                          title is the teacher's own words, and truncating it in
                          the one column that identifies the row would be worse
                          than letting it wrap. See scripts/adapt_audit.mjs. */}
                      <Link
                        to={`/teacher/quizzes/${q.id}`}
                        data-wraps-content-title
                        className="text-ink hover:underline"
                      >
                        {q.title}
                      </Link>
                      {q.status === "draft" ? (
                        <div className="text-body-sm text-ink-faint mt-1">
                          Step {q.builderStep} of 6
                        </div>
                      ) : null}
                    </td>
                    <td className="px-6 py-3.5 text-data-sm text-ink-faint">
                      {q.subjectCode}
                    </td>
                    <td className="px-6 py-3.5">
                      <Chip tone={statusTone(q.status)}>{statusLabel(q.status)}</Chip>
                    </td>
                    <td className="px-6 py-3.5 text-data-md text-ink">{q.questionCount}</td>
                    <td className="px-6 py-3.5">
                      {q.targetGrade ? (
                        <GradeBadge grade={q.targetGrade} size="inline" basis="target" />
                      ) : (
                        <span className="text-body-sm text-ink-faint">Not set</span>
                      )}
                    </td>
                    <td className="px-6 py-3.5 text-end whitespace-nowrap">
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
