/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Link } from "react-router-dom"
import { Card, CardBody } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Eyebrow } from "@/components/ui/primitives"
import { CardGridSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { adminLoadFailureMessage } from "@/lib/adminOutcome"
import { useAdminOverview } from "@/lib/hooks/useAdminApi"
import type { PlatformCounts, Signup, SystemHealth } from "@/lib/adminTypes"
import { formatAdminDate } from "../data"

/**
 * X-01 · Platform admin console.
 *
 * Reads `GET /api/admin/overview`. Utilitarian by instruction (UI spec 4.10:
 * "function over polish, but consistent with the system"), which is why this
 * screen is a grid of counted figures and not a dashboard of charts.
 *
 * ── The rule this screen is built around ───────────────────────────────────
 *
 * **A blank console must never read as a calm one.** This is the screen whose
 * whole job is noticing trouble, and every one of its reassuring states —
 * nothing in the review queue, no failed uploads — looks exactly like a failed
 * fetch rendered as zeroes. So `useAdminApi.ts` passes no `fallback` anywhere,
 * and this screen renders an error state rather than an empty grid when the
 * read fails. There is no partial render: a console showing four real numbers
 * and three invented zeroes is worse than one that admits it is blind.
 *
 * Carries no spend panel (DS3): the web process keeps no cost ledger, and the
 * guard on Gemini spend is a Google Cloud billing budget on the deployed
 * service, not this console.
 */
export function PlatformConsole() {
  const query = useAdminOverview()

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1.5">
        <Eyebrow>Platform admin</Eyebrow>
        <h1 className="text-display-lg text-ink">Console</h1>
        <p className="max-w-prose text-body-md text-ink-muted">
          What the platform is carrying right now, counted from the database on every load.
        </p>
      </header>

      <QueryState
        query={query}
        skeleton={
          <>
            <PageHeaderSkeleton />
            <CardGridSkeleton count={6} />
          </>
        }
        error={{ heading: "We couldn't read the platform's figures", body: adminLoadFailureMessage }}
      >
        {(data) => (
          <>
            <WorkPanel counts={data.counts} />
            <PeoplePanel counts={data.counts} />
            <HealthPanel health={data.health} />
            <SignupsPanel signups={data.recentSignups} />
          </>
        )}
      </QueryState>
    </div>
  )
}

/** Throughput and the two queues, which is what "is anything stuck?" means. */
function WorkPanel({ counts }: { counts: PlatformCounts }) {
  const failed = counts.uploadsByStatus.failed ?? 0
  /*
   * `processing` alone. This used to add `pending`, and until P6.2 nothing in
   * the product ever wrote `processing` — so the figure under "Uploads in
   * flight" was entirely `pending`, which is the status of every scan a student
   * ever uploaded and then abandoned. Nothing clears it, so the number could
   * only grow, and the one question this panel exists to answer ("is anything
   * stuck?") was answered by a counter that went up and never came down.
   *
   * `processing` is now written for the duration of a run and cleared by every
   * exit from it, so this is a live queue depth: it returns to zero when the
   * marking stops, which is exactly what makes a non-zero reading mean
   * something. `pending` gets its own figure below rather than being folded in,
   * because "stored but never marked" is a real thing to know and a different
   * thing to know.
   */
  const inFlight = counts.uploadsByStatus.processing ?? 0
  const neverMarked = counts.uploadsByStatus.pending ?? 0

  return (
    <section className="flex flex-col gap-3" aria-label="Marking and queues">
      <h2 className="text-display-sm text-ink">Marking and queues</h2>
      <div className="grid items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Figure
          eyebrow="Marked, last 24h"
          value={counts.papersMarkedLast24Hours}
          note="Past papers only. Quizzes are not marking-pipeline work."
        />
        <Figure
          eyebrow="Marked, last 7 days"
          value={counts.papersMarkedLast7Days}
          note={`${counts.papersMarkedTotal} since the platform started.`}
        />
        <Figure
          eyebrow="Review queue"
          value={counts.openReviewItems}
          note="Marks the system was not confident enough to apply alone."
        />
        <Figure
          eyebrow="Being marked now"
          value={inFlight}
          // Two facts, and the failed one leads because it is the one that
          // needs somebody. `neverMarked` is stated rather than folded into the
          // figure: a stored scan nobody marked is not work in progress, and
          // reading it as though it were is what this panel used to do.
          note={
            failed > 0
              ? `${failed} failed and are waiting for someone to look. ${neverMarked} more were uploaded and never marked.`
              : `Nothing has failed. ${neverMarked} uploads were stored and never marked.`
          }
          // A labelled chip carries the alarm; the note stays readable and the
          // link stays the accent. The first draft coloured the whole sentence
          // accent, which made the alert and the link one indistinguishable
          // colour and hid that "Pipeline health" was clickable at all.
          badge={failed > 0 ? `${failed} failed` : null}
          to="/platform/pipeline"
          linkLabel="Pipeline health"
        />
      </div>
    </section>
  )
}

function PeoplePanel({ counts }: { counts: PlatformCounts }) {
  return (
    <section className="flex flex-col gap-3" aria-label="Accounts">
      <h2 className="text-display-sm text-ink">Accounts</h2>
      <div className="grid items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Figure eyebrow="Students" value={counts.students} note="With an account, on any plan." />
        <Figure eyebrow="Parents" value={counts.parents} note="Linked to at least one account." />
        <Figure
          eyebrow="Teachers"
          value={counts.teachers}
          note={`${counts.schoolAdmins} school ${
            counts.schoolAdmins === 1 ? "admin" : "admins"
          } alongside them.`}
        />
        <Figure
          eyebrow="Schools"
          value={counts.schools}
          note={`Running ${counts.classes} ${counts.classes === 1 ? "class" : "classes"}.`}
        />
      </div>
    </section>
  )
}

/**
 * The three checks this process can honestly make from inside a request.
 *
 * `databaseReachable` is true because the counts above it were produced by a
 * query in the same request, which is stated rather than dressed up as a
 * separate probe. There is no uptime figure and no dependency ping, because
 * nothing records them: a green light with no check behind it is worse than no
 * light at all.
 */
function HealthPanel({ health }: { health: SystemHealth }) {
  return (
    <Card>
      <CardBody className="flex flex-col gap-3">
        <Eyebrow>System</Eyebrow>
        <dl className="grid gap-3 sm:grid-cols-3">
          <div className="flex flex-col gap-1">
            <dt className="text-body-sm text-ink-muted">Database</dt>
            <dd className="text-body-sm text-ink">
              {health.databaseReachable ? "Answered this request" : "Did not answer"}
            </dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="text-body-sm text-ink-muted">Gemini key</dt>
            <dd className="text-body-sm text-ink">
              {health.geminiKeyConfigured ? "Configured" : "Missing, so marking cannot run"}
            </dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="text-body-sm text-ink-muted">Version</dt>
            <dd className="text-body-sm tabular-nums text-ink">{health.version}</dd>
          </div>
        </dl>
        <p className="max-w-prose text-body-sm text-ink-faint">
          These are the only checks this page can make from inside a request. There is no uptime
          or worker heartbeat here because nothing records one.
        </p>
      </CardBody>
    </Card>
  )
}

function SignupsPanel({ signups }: { signups: Signup[] }) {
  return (
    <Card>
      <CardBody className="flex flex-col gap-3">
        <Eyebrow>Recent signups</Eyebrow>
        {signups.length === 0 ? (
          <p className="text-body-sm text-ink-muted">Nobody has signed up yet.</p>
        ) : (
          <ul className="flex flex-col divide-y divide-rule">
            {signups.map((signup) => (
              <li
                key={signup.userId}
                className="flex flex-wrap items-baseline justify-between gap-2 py-2 first:pt-0 last:pb-0"
              >
                <span className="text-body-sm text-ink">
                  {signup.displayName ?? signup.email}{" "}
                  <span className="text-ink-faint">{signup.role.replace(/_/g, " ")}</span>
                </span>
                <time
                  dateTime={signup.createdAt}
                  className="text-body-sm tabular-nums text-ink-muted"
                >
                  {formatAdminDate(signup.createdAt)}
                </time>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  )
}

/** A counted figure with one sentence of context under it. */
function Figure({
  eyebrow,
  value,
  note,
  badge = null,
  to,
  linkLabel,
}: {
  eyebrow: string
  value: number
  note: string
  /** A labelled alarm chip, or null when there is nothing wrong. */
  badge?: string | null
  to?: string
  linkLabel?: string
}) {
  return (
    <Card>
      {/* `h-full` plus `mt-auto` on the link: the notes are different lengths,
          and §4 asks for CTAs aligned across siblings rather than landing
          wherever the copy above them happens to stop. */}
      <CardBody className="flex h-full flex-col gap-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <Eyebrow>{eyebrow}</Eyebrow>
          {badge ? <Badge tone="warn">{badge}</Badge> : null}
        </div>
        <span className="text-data-lg tabular-nums text-ink">{value}</span>
        <p className="text-body-sm text-ink-muted">{note}</p>
        {to && linkLabel ? (
          <Link to={to} className="mt-auto pointer-coarse:flex pointer-coarse:items-center pointer-coarse:min-h-11 text-body-sm text-accent-ink hover:underline">
            {linkLabel}
          </Link>
        ) : null}
      </CardBody>
    </Card>
  )
}
