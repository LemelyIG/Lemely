/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 — one hairline list, the whole row a link, three facts per row and nothing that scores a student; the page is the consent sentence plus the list, so it stays quiet. */
import { Link } from "react-router-dom"
import { CaretLeft, CaretRight } from "@phosphor-icons/react"
import { Button, buttonVariants } from "@/components/ui/button"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { EmptyState } from "@/components/ui/state-views"
import { useTutorStudents } from "@/lib/hooks/useTutoringApi"
import { usePagedItems } from "@/lib/tutoring/sessionView"
import {
  MY_STUDENTS_INTRO,
  NO_STUDENTS_LINE,
  NO_TUTOR_PROFILE_ACTION,
  NO_TUTOR_PROFILE_BODY,
  NO_TUTOR_PROFILE_HEADING,
  TUTORING_HOME_PATH,
  TUTOR_PROFILE_PATH,
  isNoTutorProfile,
  studentLoadFailureMessage,
  studentRowView,
  type StudentRowView,
} from "@/lib/tutoring/tutorStudentView"
import type { TutorStudentItem, TutorStudentPage } from "@/lib/tutoringTypes"

/*
 * T-19 · My students (`/teacher/tutoring/students`, SPEC §d).
 *
 * The students whose grant to this tutor is live: the label, since when, and how
 * many sessions are coming. Nothing about how a student is doing is on this
 * page; that is T-20, one visit at a time. Each row is the whole link to T-20.
 *
 * Every page of this list is an audited read (T19 writes one `list` row per
 * student shown), so the hook never serves it from cache and never refetches it
 * on its own (no focus or reconnect refetch). A 4xx is not retried; a network
 * drop or a 5xx is retried once (`retryUnlessRefused`), so a page whose answer
 * was lost can be logged twice. "Show more students" asks for the next keyset
 * page.
 *
 * States: skeleton rows while loading; for a teacher with no tutor profile yet
 * (404 `no_tutor_profile`), one honest sentence and the way to T-16, not an error; the C-11 error and offline states from
 * `QueryState` with a retry; the SPEC's empty line; a line under the list when
 * a later page fails. The intro is shown in every one of them but loading and
 * failure, because it is the promise the students were given, not a decoration.
 */

const studentKey = (student: TutorStudentItem) => student.grantId

function useStudentsPage(_scope: null, cursor: string | null) {
  return useTutorStudents({ cursor })
}

function StudentRow({ row }: { row: StudentRowView }) {
  return (
    <li className="relative flex items-center gap-3 border-b border-rule px-4 py-4 transition-colors duration-[var(--dur-instant)] ease-out-soft last:border-b-0 hover:bg-paper-sunk focus-within:bg-paper-sunk active:bg-paper-sunk">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <Link
          to={row.href}
          state={{ studentName: row.name }}
          aria-label={row.ariaLabel}
          className="min-w-0 break-words text-body-lg font-medium text-ink after:absolute after:inset-0"
        >
          {row.name}
        </Link>
        <p className="m-0 text-body-sm text-ink-muted">{row.sinceLine}</p>
        <p className="m-0 text-body-sm text-ink-muted">{row.upcomingLine}</p>
      </div>
      <CaretRight size={16} className="shrink-0 text-ink-faint" aria-hidden />
    </li>
  )
}

export function MyStudents() {
  const paged = usePagedItems<null, TutorStudentItem, TutorStudentPage>(useStudentsPage, null, studentKey)

  return (
    <div className="flex w-full max-w-160 flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Link
          to={TUTORING_HOME_PATH}
          className="inline-flex w-fit items-center gap-1 py-1 text-body-sm text-ink-muted transition-colors hover:text-ink"
        >
          <CaretLeft size={14} aria-hidden />
          Back to tutoring
        </Link>
        <h1 className="m-0 text-display-md text-ink">My students</h1>
      </div>

      {isNoTutorProfile(paged.state.error) ? (
        <EmptyState heading={NO_TUTOR_PROFILE_HEADING} body={NO_TUTOR_PROFILE_BODY}>
          <Link to={TUTOR_PROFILE_PATH} className={buttonVariants({ variant: "secondary", size: "md" })}>
            {NO_TUTOR_PROFILE_ACTION}
          </Link>
        </EmptyState>
      ) : (
        <QueryState
          query={paged.state}
          skeleton={<ListSkeleton rows={3} />}
          error={{ heading: "We couldn't load your students", body: studentLoadFailureMessage }}
          isEmpty={(items) => items.length === 0}
          empty={
            <>
              <p className="m-0 max-w-prose text-body-md text-ink-muted">{MY_STUDENTS_INTRO}</p>
              <EmptyState heading={NO_STUDENTS_LINE} />
            </>
          }
        >
          {(items) => (
            <>
              <p className="m-0 max-w-prose text-body-md text-ink-muted">{MY_STUDENTS_INTRO}</p>
              <div className="flex flex-col gap-4">
                <ul className="m-0 flex list-none flex-col overflow-hidden rounded-lg border border-rule bg-paper-raised p-0">
                  {items.map((student) => (
                    <StudentRow key={student.grantId} row={studentRowView(student)} />
                  ))}
                </ul>
                {paged.moreFailed ? (
                  <p role="alert" className="m-0 text-body-sm text-err">
                    We couldn't load more students. Press Show more students to try again.
                  </p>
                ) : null}
                {paged.hasMore ? (
                  <div>
                    <Button
                      variant="secondary"
                      size="md"
                      loading={paged.loadingMore}
                      onClick={paged.moreFailed ? paged.retryMore : paged.loadMore}
                    >
                      Show more students
                    </Button>
                  </div>
                ) : null}
              </div>
            </>
          )}
        </QueryState>
      )}
    </div>
  )
}
