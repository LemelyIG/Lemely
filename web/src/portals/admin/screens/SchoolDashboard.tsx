/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Link } from "react-router-dom"
import { Card, CardBody } from "@/components/ui/card"
import { Eyebrow, Meter } from "@/components/ui/primitives"
import { Badge } from "@/components/ui/badge"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { CardGridSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { adminLoadFailureMessage } from "@/lib/adminOutcome"
import { useSchoolOverview } from "@/lib/hooks/useSchoolApi"
import type { SchoolOverview } from "@/lib/schoolTypes"
import { cn } from "@/lib/utils"

/**
 * K-01 · School dashboard.
 *
 * Reads `GET /api/school/overview` and nothing else. Every figure on this
 * screen is a row count or the school's average, both computed server-side; the
 * screen does no arithmetic of its own beyond turning seats used into a
 * percentage for the meter.
 *
 * ── The two honesty decisions on this screen ───────────────────────────────
 *
 * **1. The average carries its denominator.** `averageLatestPercentage` is the
 * mean of each student's latest grade-bearing paper, and it is meaningless
 * without knowing how many students that was. "78% across the school" reads
 * very differently at 3 of 40 than at 40 of 40, and an administrator is exactly
 * the reader who would quote the first as if it were the second. So the count
 * is rendered as the figure's own subtitle, not as a footnote elsewhere.
 * When it is zero the average is null and the panel says so rather than
 * showing 0%, which would read as "everyone failed".
 *
 * **2. There is no subscription panel, and the screen says why.** UI spec K-01
 * lists "subscription status" among its contents. `subscriptions` is a
 * per-*user* table (`lemely/db/models/billing.py`); no school-level
 * subscription, plan, or billing state exists anywhere in the schema, and no
 * endpoint could return one. Rather than render a panel reading "Active" from
 * nothing, or quietly drop the requirement, the seats panel states the one
 * commercial fact that is real: the quota this school holds.
 */
export function SchoolDashboard() {
  const { data, isPending, isError, error } = useSchoolOverview()

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1.5">
        <Eyebrow>School admin</Eyebrow>
        <h1 className="text-display-lg text-ink">Your school</h1>
        <p className="max-w-prose text-body-md text-ink-muted">
          Seats, staff and how the school is doing, from the papers students have had marked.
        </p>
      </header>

      {isPending ? (
        <>
          <PageHeaderSkeleton />
          <CardGridSkeleton count={4} />
        </>
      ) : isError ? (
        <ErrorState
          heading="We couldn't load your school"
          body={adminLoadFailureMessage(error)}
          action={{ label: "Try again", onClick: () => window.location.reload() }}
        />
      ) : data.schools.length === 0 ? (
        <EmptyState
          marginalia="nothing to administer yet"
          heading="No school is assigned to you"
          body="This account holds no school membership, so there is nothing to show. Ask whoever set the account up to add you to your school."
        />
      ) : (
        data.schools.map((school) => <SchoolPanel key={school.schoolId} school={school} />)
      )}
    </div>
  )
}

/**
 * One school. Rendered in a loop because an administrator may hold a membership
 * of more than one, and `GET /api/school/overview` returns all of them.
 *
 * The school's name is always rendered, including in the ordinary single-school
 * case. An earlier draft of this comment claimed the heading was suppressed
 * there; it never was, and the claim was wrong on the design as well as on the
 * code. "Your school" names the page and the `<h2>` names the school, which are
 * different facts, and an administrator of two schools needs the second one to
 * appear identically in both panels.
 */
function SchoolPanel({ school }: { school: SchoolOverview }) {
  const seatPct = school.quota > 0 ? Math.min(100, (school.seatsUsed / school.quota) * 100) : 0
  const atQuota = school.quota > 0 && school.seatsAvailable === 0

  return (
    <section className="flex flex-col gap-4" aria-label={school.schoolName}>
      <h2 className="text-display-sm text-ink">{school.schoolName}</h2>

      <div className="grid items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardBody className="flex h-full flex-col gap-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <Eyebrow>Seats</Eyebrow>
              {/* Labelled, never a bare colour. The inspection round found the
                  alarm being carried by the meter alone, in the same terracotta
                  the "Manage seats" link beneath it uses, so one colour meant
                  both "you are out of seats" and "this is a link". */}
              {atQuota ? <Badge tone="warn">At capacity</Badge> : null}
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-data-lg tabular-nums text-ink">{school.seatsUsed}</span>
              <span className="text-body-sm text-ink-muted">of {school.quota} used</span>
            </div>
            <Meter
              value={seatPct}
              label={`Seats used: ${school.seatsUsed} of ${school.quota}`}
              // `warn`, not `accent`. The accent is this product's link and
              // brand colour and appears on this very card; using it for the
              // alarm too made the two indistinguishable. The warn token is the
              // alert register, and it now matches the badge above.
              fillClassName={atQuota ? "bg-warn" : "bg-ink-faint"}
            />
            <p className="text-body-sm text-ink-muted">
              {atQuota
                ? "Every seat is taken. Revoke one to free it, or ask us for more."
                : `${school.seatsAvailable} free.`}
            </p>
            {/* On its own line rather than trailing the sentence above. Inside
                the paragraph it wrapped mid-link ("See" / "the roll"), which is
                a two-line clickable target and is banned outright by the mobile
                rules in §6. Same reason on every card below. */}
            <Link
              to="/school/seats"
              className="mt-auto pointer-coarse:flex pointer-coarse:items-center pointer-coarse:min-h-11 text-body-sm text-accent-ink hover:underline"
            >
              Manage seats
            </Link>
          </CardBody>
        </Card>

        <StatCard
          eyebrow="Students"
          value={school.enrolledStudentCount}
          note="Enrolled in at least one class here."
          to="/school/seats"
          linkLabel="See the roll"
        />

        <StatCard
          eyebrow="Teachers"
          value={school.teacherCount}
          note="On this school's staff."
          to="/school/teachers"
          linkLabel="Manage staff"
        />

        <StatCard
          eyebrow="Classes"
          value={school.classCount}
          note="Across every teacher here."
          to="/school/classes"
          linkLabel="See classes"
        />
      </div>

      <Card>
        <CardBody className="flex flex-col gap-3">
          <Eyebrow>How the school is doing</Eyebrow>
          {school.averageLatestPercentage === null ? (
            <>
              <p className="text-body-lg text-ink">No papers marked yet</p>
              <p className="max-w-prose text-body-sm text-ink-muted">
                This figure is the average of each student's most recent past paper. Nobody here
                has had one marked, so there is nothing to average. It will appear on its own.
              </p>
            </>
          ) : (
            <>
              <div className="flex items-baseline gap-2">
                <span className="text-data-lg tabular-nums text-ink">
                  {Math.round(school.averageLatestPercentage)}%
                </span>
                <span className="text-body-sm text-ink-muted">
                  averaged over {school.studentsWithAPaper} of {school.enrolledStudentCount}{" "}
                  {school.enrolledStudentCount === 1 ? "student" : "students"}
                </span>
              </div>
              <p className="max-w-prose text-body-sm text-ink-muted">
                Each student's most recent past paper, averaged. Quizzes are left out because a
                quiz percentage is not comparable to a paper's. Students who have not had a paper
                marked are not in the figure at all, rather than counted as zero.
              </p>
            </>
          )}
        </CardBody>
      </Card>
    </section>
  )
}

/** A counted figure with the screen it came from one link away. */
function StatCard({
  eyebrow,
  value,
  note,
  to,
  linkLabel,
  className,
}: {
  eyebrow: string
  value: number
  note: string
  to: string
  linkLabel: string
  className?: string
}) {
  return (
    <Card className={className}>
      {/* `justify-between` with `h-full` so the link pins to the bottom of every
          card in the row: the notes are different lengths, and DESIGN.md §4
          asks for CTAs aligned across siblings rather than floating wherever
          the copy above them happens to end. */}
      <CardBody className={cn("flex h-full flex-col gap-3", className)}>
        <Eyebrow>{eyebrow}</Eyebrow>
        <span className="text-data-lg tabular-nums text-ink">{value}</span>
        <p className="text-body-sm text-ink-muted">{note}</p>
        <Link to={to} className="mt-auto pointer-coarse:flex pointer-coarse:items-center pointer-coarse:min-h-11 text-body-sm text-accent-ink hover:underline">
          {linkLabel}
        </Link>
      </CardBody>
    </Card>
  )
}
