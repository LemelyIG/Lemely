/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 — the T-05 page the teacher already knows, with the consent line as a quiet strip under the name and nothing the tutor cannot act on; the ended state is one sentence and one way out. */
import { Link, useLocation, useParams } from "react-router-dom"
import { CaretLeft, LockSimple } from "@phosphor-icons/react"
import { buttonVariants } from "@/components/ui/button"
import { PanelSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { EmptyState } from "@/components/ui/state-views"
import { useTutorStudent } from "@/lib/hooks/useTutoringApi"
import { isAccessEnded } from "@/lib/tutoring/apiErrors"
import {
  TUTOR_STUDENTS_PATH,
  accessEndedHeading,
  isStudentNotFound,
  sharedLine,
  studentLoadFailureMessage,
  studentNameFromState,
  tutorStudentDates,
} from "@/lib/tutoring/tutorStudentView"
import { StudentDetailView } from "../StudentDetail"

/*
 * T-20 · Student detail, tutor view (`/teacher/tutoring/students/:studentId`,
 * SPEC §d). The T-05 composition (`StudentDetailView`) fed by the tutor
 * projection of the same DTO: every date is a calendar day, there are no
 * question ids, and the teacher-only controls do not exist here. The page passes
 * the composition no attempt action (so the attempt table has no drill-down and
 * no actions column), no footer (no Assign practice), `showAcknowledged={false}`
 * (no acknowledge tag) and no integrity panel (T-05 has none). The consent line
 * from the SPEC sits under the name.
 *
 * Opening this page is an audited read: the API records the visit before it
 * sends data, and the student can see it. So the page never asks twice. A 4xx is
 * the server's answer and is not retried (`useTutorStudent`), and there is no
 * "Try again" on the ended or not-found states.
 *
 * States:
 *   - loading: a skeleton, under a heading for screen readers;
 *   - loaded: the composition;
 *   - ended (403 `access_ended`): ONE state, the C-11 sentence from the SPEC,
 *     with no data and no reason. Revoked, expired, blocked and suspended all
 *     read the same, because the server never tells the tutor which it was. The
 *     cached detail is cleared by the guard `useTutorStudent` installs
 *     (`installAccessEndedGuard`); this screen does not touch the cache, because
 *     removing the query would rebuild it on the next render and read it again;
 *   - not found (404): no grant ever existed for this pair, or the id is not a
 *     student: "We couldn't find that student", with the way back;
 *   - failure: the C-11 error (or offline) state with a retry, for a 5xx or a
 *     dropped connection.
 *
 * The student's name for the ended sentence comes from the link on T-19 (router
 * state); opened by address it reads "This student's progress...".
 */

function BackToStudents() {
  return (
    <Link
      to={TUTOR_STUDENTS_PATH}
      className="inline-flex w-fit items-center gap-1 py-1 text-body-sm text-ink-muted transition-colors hover:text-ink"
    >
      <CaretLeft size={14} aria-hidden />
      My students
    </Link>
  )
}

function BackToStudentsAction() {
  return (
    <Link to={TUTOR_STUDENTS_PATH} className={buttonVariants({ variant: "secondary", size: "md" })}>
      Back to my students
    </Link>
  )
}

export function TutorStudentDetail() {
  const { studentId = "" } = useParams<{ studentId: string }>()
  const knownName = studentNameFromState(useLocation().state)
  const query = useTutorStudent(studentId)

  if (query.status === "error" && isAccessEnded(query.error)) {
    return (
      <div className="flex min-w-0 flex-col gap-8">
        <h1 className="sr-only">Student detail</h1>
        <EmptyState
          icon={<LockSimple size={28} aria-hidden />}
          heading={accessEndedHeading(knownName)}
          kicker={null}
        >
          <BackToStudentsAction />
        </EmptyState>
      </div>
    )
  }

  if (query.status === "error" && isStudentNotFound(query.error)) {
    return (
      <div className="flex min-w-0 flex-col gap-8">
        <h1 className="sr-only">Student detail</h1>
        <EmptyState
          heading="We couldn't find that student"
          body="Only students who are sharing their progress with you can be opened from My students."
        >
          <BackToStudentsAction />
        </EmptyState>
      </div>
    )
  }

  return (
    <div className="flex min-w-0 flex-col gap-8">
      <QueryState
        query={query}
        srHeading="Student detail"
        skeleton={
          <>
            <PanelSkeleton />
            <PanelSkeleton />
          </>
        }
        error={{ heading: "We couldn't load this student", body: studentLoadFailureMessage }}
      >
        {({ detail, grantedAt }) => (
          <StudentDetailView
            student={detail}
            dates={tutorStudentDates}
            showAcknowledged={false}
            back={<BackToStudents />}
            intro={
              <p className="m-0 max-w-prose rounded-lg border border-rule bg-paper-sunk px-4 py-3 text-body-md text-ink-muted">
                {sharedLine(detail.displayName, grantedAt)}
              </p>
            }
          />
        )}
      </QueryState>
    </div>
  )
}
