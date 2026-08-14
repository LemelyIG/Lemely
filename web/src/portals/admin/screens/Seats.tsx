/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useState } from "react"
import { Card, CardBody } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Eyebrow, Meter } from "@/components/ui/primitives"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import {
  adminLoadFailureMessage,
  adminMutationFailureMessage,
  seatInviteFailureMessage,
} from "@/lib/adminOutcome"
import { useInviteStudent, useRevokeSeat, useSeatUsage } from "@/lib/hooks/useSchoolApi"
import type { SeatRow, SeatUsage } from "@/lib/schoolTypes"
import { formatAdminDate } from "../data"

/**
 * K-02 · Seats and student accounts.
 *
 * Reads `GET /api/school/seats`; writes through `POST /school/seats/invite` and
 * `POST /school/seats/{id}/revoke`. Nothing on this screen is fabricated: every
 * column is a field the route returns.
 *
 * ── What the spec asks for, and what the wire actually carries ─────────────
 *
 * K-02 wants "name, class, teacher, status, last active". Four of those are
 * real; the fifth is not, and the difference is on screen rather than papered
 * over:
 *
 * * **Last active** does not exist. No table records a session or a login —
 *   `users` has no `last_seen`, and `devices` records registration rather than
 *   use. The only activity signal in the schema is the most recent attempt, so
 *   the column is headed **"Last marked"** and the API field is named
 *   `lastAttemptAt`. Labelling it "last active" would be a claim about
 *   something nobody measures.
 * * **Class** is a list, not a value. Nothing makes a student's enrolment
 *   within one school exclusive, so a student in two classes gets both, stacked
 *   one per line, rather than an arbitrary winner.
 *
 * ── Bulk invite ────────────────────────────────────────────────────────────
 *
 * The spec asks for "individually or in bulk (paste a list)". The backend has
 * one single-student route, so bulk here is a real client-side loop over that
 * route, reported per address: some succeed, some fail, and the screen says
 * which. It is deliberately **not** a progress bar over a batch endpoint that
 * does not exist, and a partial failure does not roll back the successes,
 * because the route cannot.
 */
export function Seats() {
  const { data, isPending, isError, error } = useSeatUsage()

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1.5">
        <Eyebrow>School admin</Eyebrow>
        <h1 className="text-display-lg text-ink">Seats and students</h1>
        <p className="max-w-prose text-body-md text-ink-muted">
          Every seat your school holds, who is on it, and how to invite someone new.
        </p>
      </header>

      {isPending ? (
        <>
          <PageHeaderSkeleton />
          <ListSkeleton rows={5} avatar />
        </>
      ) : isError ? (
        <ErrorState
          heading="We couldn't load your seats"
          body={adminLoadFailureMessage(error)}
          action={{ label: "Try again", onClick: () => window.location.reload() }}
        />
      ) : data.schools.length === 0 ? (
        <EmptyState
          heading="No school is assigned to you"
          body="This account holds no school membership, so there are no seats to manage."
        />
      ) : (
        data.schools.map((school) => <SchoolSeats key={school.schoolId} school={school} />)
      )}
    </div>
  )
}

function SchoolSeats({ school }: { school: SeatUsage }) {
  const atQuota = school.quota > 0 && school.available === 0
  const seatPct = school.quota > 0 ? Math.min(100, (school.used / school.quota) * 100) : 0

  return (
    <section className="flex flex-col gap-4" aria-label={school.schoolName}>
      <h2 className="text-display-sm text-ink">{school.schoolName}</h2>

      <Card>
        <CardBody className="flex flex-col gap-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <Eyebrow>Seat quota</Eyebrow>
            <div className="flex items-baseline gap-2">
              {/* The alarm is labelled, and the label and the bar are the same
                  register. Before the inspection round the bar alone carried
                  it, in the accent this product uses for links. */}
              {atQuota ? <Badge tone="warn">At capacity</Badge> : null}
              <span className="text-body-sm text-ink-muted">
                <span className="tabular-nums">{school.used}</span> of{" "}
                <span className="tabular-nums">{school.quota}</span> used
              </span>
            </div>
          </div>
          <Meter
            value={seatPct}
            label={`Seats used: ${school.used} of ${school.quota}`}
            fillClassName={atQuota ? "bg-warn" : "bg-ink-faint"}
          />
          {atQuota ? (
            // K-02's stated state: "Quota reached: explain and give a route to
            // request more." The explanation is real. The *route* is a
            // sentence, not a button, because no endpoint requests a quota
            // increase and no contact address is recorded anywhere in this
            // repo. A button that did nothing would be worse than saying who
            // to ask.
            <p className="max-w-prose text-body-sm text-ink-muted">
              Every seat is taken, so new invites will be refused. Revoking a seat frees it
              straight away and leaves that student's account and work intact. To buy more seats,
              speak to whoever arranged your school's account.
            </p>
          ) : (
            <p className="text-body-sm text-ink-muted">
              <span className="tabular-nums">{school.available}</span>{" "}
              {school.available === 1 ? "seat" : "seats"} free.
            </p>
          )}
        </CardBody>
      </Card>

      {/* The roll before the invite form, which is the reverse of the first
          draft. This screen is called "Seats and students": who is here is the
          answer it exists to give, and the invite panel is tall enough that it
          pushed the table below the fold on a laptop. Adding someone is the
          second thing you do, after looking. */}
      <SeatTable school={school} />
      <InvitePanel school={school} />
    </section>
  )
}

/**
 * Invite one student, or paste a list.
 *
 * One address per line, which is the shape a school's own spreadsheet exports
 * and the only one that needs no parser to explain. A display name is offered
 * for the single case only: pairing names to addresses in a textarea needs a
 * format an administrator would have to be taught, and a wrong pairing is
 * silent.
 */
function InvitePanel({ school }: { school: SeatUsage }) {
  const [email, setEmail] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [bulk, setBulk] = useState("")
  const [results, setResults] = useState<InviteOutcome[]>([])
  const [running, setRunning] = useState(false)
  const invite = useInviteStudent()

  const atQuota = school.quota > 0 && school.available === 0

  async function inviteMany(addresses: string[], name: string | null) {
    setRunning(true)
    const collected: InviteOutcome[] = []
    for (const address of addresses) {
      try {
        const created = await invite.mutateAsync({
          schoolId: school.schoolId,
          email: address,
          displayName: name,
        })
        collected.push({
          email: address,
          ok: true,
          temporaryPassword: created.temporaryPassword,
        })
      } catch (err) {
        collected.push({ email: address, ok: false, message: seatInviteFailureMessage(err) })
      }
      // Reported as it goes rather than at the end: a paste of forty addresses
      // that fails on the ninth should say so while the rest are still running.
      setResults([...collected])
    }
    setRunning(false)
  }

  return (
    <Card>
      <CardBody className="flex flex-col gap-5">
        <Eyebrow>Invite students</Eyebrow>

        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            if (!email.trim()) return
            setResults([])
            void inviteMany([email.trim()], displayName.trim() || null)
            setEmail("")
            setDisplayName("")
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              label="Email address"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="off"
            />
            <Input
              label="Name (optional)"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              hint="Shown to their teachers. They can change it later."
              autoComplete="off"
            />
          </div>
          <div>
            <Button type="submit" variant="primary" loading={running} disabled={atQuota}>
              Invite this student
            </Button>
          </div>
        </form>

        <div className="border-t border-rule pt-5">
          <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault()
              const addresses = bulk
                .split("\n")
                .map((line) => line.trim())
                .filter((line) => line !== "")
              if (addresses.length === 0) return
              setResults([])
              void inviteMany(addresses, null)
              setBulk("")
            }}
          >
            <Textarea
              label="Or paste a list"
              value={bulk}
              onChange={(event) => setBulk(event.target.value)}
              rows={4}
              // A genuine format hint, not a label substitute: the visible
              // label is above it, and DESIGN.md §12 permits a placeholder
              // only for this.
              placeholder={"one@school.example\ntwo@school.example"}
              hint="One email address per line. Each is invited on its own, so if one fails the rest still go through."
            />
            <div>
              <Button type="submit" loading={running} disabled={atQuota}>
                Invite everyone on the list
              </Button>
            </div>
          </form>
        </div>

        {atQuota ? (
          <p className="text-body-sm text-ink-muted">
            Inviting is off while every seat is taken.
          </p>
        ) : null}

        {results.length > 0 ? <InviteResults results={results} /> : null}
      </CardBody>
    </Card>
  )
}

interface InviteOutcome {
  email: string
  ok: boolean
  temporaryPassword?: string | null
  message?: string
}

/**
 * What happened to each address.
 *
 * The temporary password is shown here and nowhere else, once, because that is
 * the only time it exists: the backend generates it, returns it, and stores
 * only its hash. There is no email provider in v1, so an administrator who
 * navigates away without copying it has to reset the account instead. The copy
 * says so plainly rather than letting them find out.
 */
function InviteResults({ results }: { results: InviteOutcome[] }) {
  const failed = results.filter((r) => !r.ok)
  const created = results.filter((r) => r.ok)

  return (
    <div className="flex flex-col gap-3 border-t border-rule pt-5">
      <Eyebrow>Results</Eyebrow>
      {created.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="text-body-sm text-ink">
            <span className="tabular-nums">{created.length}</span>{" "}
            {created.length === 1 ? "account" : "accounts"} created. Copy the passwords now: they
            are shown once and cannot be read again.
          </p>
          <ul className="flex flex-col gap-1.5">
            {created.map((result) => (
              <li key={result.email} className="flex flex-wrap items-center gap-2">
                <span className="text-body-sm text-ink">{result.email}</span>
                {result.temporaryPassword ? (
                  <code className="rounded-sm bg-paper-sunk px-1.5 py-0.5 text-data-sm text-ink">
                    {result.temporaryPassword}
                  </code>
                ) : (
                  <span className="text-body-sm text-ink-muted">password you set</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {failed.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          {failed.map((result) => (
            <p key={result.email} className="text-body-sm text-err">
              {result.email}: {result.message}
            </p>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function SeatTable({ school }: { school: SeatUsage }) {
  const [pendingRevoke, setPendingRevoke] = useState<SeatRow | null>(null)
  const revoke = useRevokeSeat()

  if (school.seats.length === 0) {
    return (
      <EmptyState
        marginalia="an empty register"
        heading="Nobody is on a seat yet"
        body="Invite a student above and they will appear here with the classes they join."
      />
    )
  }

  return (
    <>
      <Table>
        <THead>
          <tr>
            <TH>Student</TH>
            <TH>Classes</TH>
            {/* Was a "Status" column, and it was removed in the inspection
                round because it was a constant. `list_seats` filters revoked
                seats out and nothing in the product creates an unassigned one,
                so every row read "On a seat" — a column that took width from
                the classes beside it and told a reader nothing. `assignedAt`
                was going unrendered at the same time, so the column now carries
                the fact the spec's "status" was reaching for: since when. */}
            <TH>On a seat since</TH>
            {/* Not "Last active": no table records a session or a login. This
                column is the most recent marked paper or quiz, which is the
                only activity signal the schema carries. */}
            <TH>Last marked</TH>
            <TH>
              <span className="sr-only">Actions</span>
            </TH>
          </tr>
        </THead>
        <TBody>
          {school.seats.map((seat) => (
            <TR key={seat.seatId}>
              <TD>
                <div className="flex flex-col">
                  <span className="text-body-sm text-ink">
                    {seat.assignedDisplayName ?? seat.assignedEmail ?? "Unassigned seat"}
                  </span>
                  {seat.assignedDisplayName && seat.assignedEmail ? (
                    <span className="text-body-sm text-ink-faint">{seat.assignedEmail}</span>
                  ) : null}
                </div>
              </TD>
              <TD>
                {seat.classes.length === 0 ? (
                  <span className="text-body-sm text-ink-faint">Not in a class here</span>
                ) : (
                  // A stacked list, not a wrapped row. Side by side, "10A
                  // Physics (Hana Sabry)" and "10B Maths (Omar Reda)" ran
                  // together into one string with only a space between them,
                  // which is how two classes read as one.
                  <ul className="flex flex-col gap-0.5">
                    {seat.classes.map((seatClass) => (
                      <li key={seatClass.classId} className="text-body-sm text-ink-muted">
                        {seatClass.name}
                        {seatClass.teacherName ? (
                          <span className="text-ink-faint"> · {seatClass.teacherName}</span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                )}
              </TD>
              <TD>
                {/* K-02's spec asks for a status of "invited / active /
                    inactive". None of those three exists: the schema has
                    `available` / `assigned` / `revoked`, this route filters
                    revoked out, and there is no "invited" state at all because
                    an invite creates the account immediately rather than
                    sending anything to accept. So the column reports the date
                    the seat was taken, which is the real fact underneath. */}
                {seat.assignedAt ? (
                  <time
                    dateTime={seat.assignedAt}
                    className="text-body-sm tabular-nums text-ink-muted"
                  >
                    {formatAdminDate(seat.assignedAt)}
                  </time>
                ) : (
                  <span className="text-body-sm text-ink-faint">Not assigned</span>
                )}
              </TD>
              <TD>
                {seat.lastAttemptAt ? (
                  <time
                    dateTime={seat.lastAttemptAt}
                    className="text-body-sm tabular-nums text-ink-muted"
                  >
                    {formatAdminDate(seat.lastAttemptAt)}
                  </time>
                ) : (
                  <span className="text-body-sm text-ink-faint">Nothing yet</span>
                )}
              </TD>
              <TD>
                {seat.assignedUserId ? (
                  <Button size="sm" onClick={() => setPendingRevoke(seat)}>
                    Revoke seat
                  </Button>
                ) : null}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>

      {/* K-02 asks for "revoke a seat with an explanation of what happens to
          that student's data". This is that explanation, and it is accurate:
          `SeatService.revoke_seat` flips the seat to `revoked` and touches
          nothing else. `consequence` is overridden because this is genuinely
          reversible, and the kit's default claims it is not.

          The failure is rendered *inside* the modal rather than under the
          table, so a revoke that does not go through is reported where the
          reader is looking, instead of behind a dialog they have to close
          before they can see it. */}
      <ConfirmModal
        open={pendingRevoke !== null}
        onCancel={() => setPendingRevoke(null)}
        title="Free up this seat?"
        description={`${
          pendingRevoke?.assignedDisplayName ?? pendingRevoke?.assignedEmail ?? "This student"
        } will no longer count against your school's seat quota.`}
        confirmLabel="Revoke the seat"
        pendingLabel="Revoking…"
        consequence="Their account, their marked papers and their work all stay exactly as they are. Only the seat is released, and you can invite them back onto one later."
        pending={revoke.isPending}
        error={revoke.isError ? adminMutationFailureMessage(revoke.error) : null}
        onConfirm={() => {
          if (!pendingRevoke) return
          revoke.mutate(pendingRevoke.seatId, { onSuccess: () => setPendingRevoke(null) })
        }}
      />
    </>
  )
}
