/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 — what was reported, the evidence in order, then one choice and a note; sections divided by hairlines; not yet seen in a browser. */
import { useEffect, useRef, useState, type ReactNode } from "react"
import { Link, useParams } from "react-router-dom"
import { Info, Warning } from "@phosphor-icons/react"
import { BackControl } from "@/components/ui/back-control"
import { Badge } from "@/components/ui/badge"
import { BookingStatus } from "@/components/ui/booking-status"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { Modal } from "@/components/ui/modal"
import { Eyebrow } from "@/components/ui/primitives"
import { QueryState } from "@/components/ui/query-state"
import { Radio, RadioGroup } from "@/components/ui/radio"
import { Textarea } from "@/components/ui/textarea"
import { useAdminTutoringReport, useResolveTutoringReport } from "@/lib/hooks/useTutoringApi"
import { useOnlineStatus } from "@/lib/online"
import {
  RESOLUTION_NOTE_MAX,
  THREAD_VIEW_NOTICE,
  adminFailureMessage,
  adminNoteRows,
  formatAdminDay,
  formatAdminInstant,
  formatAdminRange,
  isSafetyConcern,
  noteLength,
  reportReasonLabel,
  reportStateLabel,
  reportTargetLabel,
  reporterLabel,
  resolutionConfirm,
  resolutionLabel,
  resolutionNoteError,
  resolutionOptions,
  resolutionUnavailable,
  resolveBody,
  snapshotRows,
} from "@/lib/tutoring/adminTutoring"
import { MODE_OPTIONS } from "@/lib/tutoring/discovery"
import type { ReportDetail as ReportDetailData, ReportResolution } from "@/lib/tutoringTypes"

/*
 * X-07 · Report detail (`/platform/reports/:reportId`, SPEC §d, rows A10, A11).
 *
 * What was reported and by whom (a party, never a name), a snapshot of the
 * reported content as it was when the report was filed, for a booking or note
 * report the booking and its notes thread, and then the resolution.
 *
 * Opening the page is itself logged by A10 because it can show the notes thread
 * (SC-23), and the page says so. The thread names each author by party, never by
 * name, and shows hidden notes marked as hidden.
 *
 * A resolution is one of the choices A11 can apply to this report right now
 * (`resolutionOptions`), with a note of at most 1000 characters. When the
 * booking has started, the missing "Cancel the booking" is explained instead of
 * silently absent. Choices that cannot be taken back ask first, and say what
 * they do. A refusal from the server (somebody resolved it first, the booking
 * moved on) is shown in its own words.
 *
 * States: loading, error and offline (through `QueryState`; a bad id is the
 * 404 sentence with a way back), a report with no thread, a frozen thread, hidden
 * notes, a resolved report (the outcome in place of the form), resolving, a
 * refused resolution, and offline (the submit waits, with the reason).
 */

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 border-t border-rule pt-6">
      <h2 className="text-display-sm text-ink">{title}</h2>
      {children}
    </section>
  )
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="text-body-sm text-ink-muted">{label}</dt>
      <dd className="m-0 break-words text-body-md text-ink">{children}</dd>
    </div>
  )
}

const TEXT = "m-0 max-w-prose whitespace-pre-wrap break-words text-body-md text-ink"

function BookingSummary({ report }: { report: ReportDetailData }) {
  const booking = report.bookingSummary
  if (booking === null) return null
  const mode = MODE_OPTIONS.find((option) => option.value === booking.mode)?.label ?? booking.mode
  return (
    <Section title="Booking">
      <dl className="m-0 grid gap-4 sm:grid-cols-2">
        <Fact label="Subject">{booking.subject.name}</Fact>
        <Fact label="Way of meeting">{mode}</Fact>
        <Fact label="When">{formatAdminRange(booking.startsAt, booking.endsAt)}</Fact>
        <Fact label="State">
          <BookingStatus state={booking.effectiveState} />
        </Fact>
        {booking.completedBy ? <Fact label="Marked completed by">{booking.completedBy.replace("_", " ")}</Fact> : null}
      </dl>
    </Section>
  )
}

function Thread({ report }: { report: ReportDetailData }) {
  if (report.bookingSummary === null) return null
  const rows = adminNoteRows(report.notes)
  const frozen = report.bookingSummary.notesFrozen
  return (
    <Section title="Notes">
      <p className="m-0 flex max-w-prose items-start gap-2 text-body-sm text-ink-muted">
        <Info size={16} className="mt-0.5 flex-none" aria-hidden="true" />
        {THREAD_VIEW_NOTICE}
      </p>
      {frozen ? (
        <p className="m-0 text-body-sm text-ink-muted">Notes are paused for the student and tutor while this report is open.</p>
      ) : null}
      {rows.length === 0 ? (
        <p className="m-0 text-body-md text-ink-muted">There are no notes on this booking.</p>
      ) : (
        <ol className="m-0 flex list-none flex-col p-0">
          {rows.map((row) => (
            <li key={row.noteId} className="flex flex-col gap-1 border-b border-rule py-3 first:pt-0 last:border-b-0">
              <div className="flex flex-wrap items-center gap-2 text-body-sm text-ink-muted">
                <span className="font-medium text-ink">{row.label}</span>
                <time dateTime={row.createdAt} className="tabular-nums">
                  {formatAdminInstant(row.createdAt)}
                </time>
                {row.hidden ? <Chip tone="neutral">Hidden from the student and tutor</Chip> : null}
              </div>
              {row.body === null ? (
                <p className="m-0 text-body-md text-ink-muted">The text is not available.</p>
              ) : (
                <p className={TEXT}>{row.body}</p>
              )}
            </li>
          ))}
        </ol>
      )}
    </Section>
  )
}

function Outcome({ report }: { report: ReportDetailData }) {
  return (
    <Section title="Resolution">
      <dl className="m-0 grid gap-4 sm:grid-cols-2">
        <Fact label="Outcome">{report.resolution ? resolutionLabel(report.resolution) : reportStateLabel(report.state)}</Fact>
        <Fact label="Resolved">
          {report.resolvedAt ? <time dateTime={report.resolvedAt}>{formatAdminDay(report.resolvedAt)}</time> : "Not recorded"}
        </Fact>
      </dl>
      {report.resolutionNote ? <p className={TEXT}>{report.resolutionNote}</p> : null}
    </Section>
  )
}

/**
 * The mutation is owned by the page, not the form: a resolved report swaps this
 * form for its outcome, and a callback passed to `mutate` is dropped if the
 * component that called it has unmounted by then.
 */
function ResolveForm({
  report,
  resolve,
  onDone,
}: {
  report: ReportDetailData
  resolve: ReturnType<typeof useResolveTutoringReport>
  onDone: (line: string) => void
}) {
  const online = useOnlineStatus()
  const [now] = useState(() => new Date())
  const [choice, setChoice] = useState<ReportResolution | null>(null)
  const [note, setNote] = useState("")
  const [confirming, setConfirming] = useState(false)

  const options = resolutionOptions(report, now)
  const selected = options.find((option) => option.value === choice) ?? null
  const unavailable = resolutionUnavailable(report, now)
  const noteProblem = resolutionNoteError(note)
  const blank = note.trim() === ""
  const confirm = selected ? resolutionConfirm(selected.value) : null
  const ready = selected !== null && noteProblem === null && online

  function send() {
    if (selected === null || !ready) return
    resolve.mutate(
      { reportId: report.reportId, body: resolveBody(selected.value, note) },
      {
        onSuccess: () => {
          setConfirming(false)
          onDone("Report resolved.")
        },
        onError: () => setConfirming(false),
      },
    )
  }

  return (
    <Section title="Resolve this report">
      <form
        className="flex max-w-prose flex-col gap-5"
        onSubmit={(event) => {
          event.preventDefault()
          if (!ready) return
          if (confirm) setConfirming(true)
          else send()
        }}
      >
        <RadioGroup
          label="What should happen?"
          value={selected?.value ?? ""}
          onValueChange={(value) => {
            resolve.reset()
            setChoice(value as ReportResolution)
          }}
        >
          {options.map((option) => (
            <Radio key={option.value} value={option.value} label={option.label} description={option.help} />
          ))}
        </RadioGroup>
        {unavailable ? <p className="m-0 text-body-sm text-ink-muted">{unavailable}</p> : null}
        <Textarea
          label="Note"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          rows={4}
          hint={`Kept with the report. ${noteLength(note.trim())} of ${RESOLUTION_NOTE_MAX} characters.`}
          error={!blank && noteProblem !== null ? noteProblem : undefined}
        />
        <div className="flex flex-col items-start gap-2">
          <Button className="min-h-11" type="submit" variant="primary" loading={resolve.isPending && !confirming} disabled={!ready}>
            Resolve report
          </Button>
          {!online ? (
            <p className="m-0 text-body-sm text-ink-muted">You're offline. Reconnect to resolve.</p>
          ) : selected === null ? (
            <p className="m-0 text-body-sm text-ink-muted">Choose what should happen.</p>
          ) : blank ? (
            <p className="m-0 text-body-sm text-ink-muted">A note is needed before this can be recorded.</p>
          ) : null}
          {resolve.isError && !confirming ? (
            <p role="alert" className="m-0 text-body-sm text-err">
              {adminFailureMessage(resolve.error, "That didn't go through. Try again.")}
            </p>
          ) : null}
        </div>
      </form>

      {confirming && confirm ? (
        <Modal
          open
          onClose={() => setConfirming(false)}
          dismissible={false}
          hideCloseButton
          title={confirm.title}
          description={`${reportTargetLabel(report.targetType)} about ${report.tutorName}`}
          footer={
            <div className="flex flex-wrap justify-end gap-2">
              <Button className="min-h-11" variant="primary" onClick={() => setConfirming(false)} disabled={resolve.isPending}>
                Go back
              </Button>
              <Button className="min-h-11" loading={resolve.isPending} onClick={send}>
                {confirm.confirmLabel}
              </Button>
            </div>
          }
        >
          <p className="m-0 text-body-md text-ink">{confirm.body}</p>
        </Modal>
      ) : null}
    </Section>
  )
}

function Report({ report }: { report: ReportDetailData }) {
  const resolve = useResolveTutoringReport()
  const [done, setDone] = useState<string | null>(null)
  const doneRef = useRef<HTMLParagraphElement>(null)
  const rows = snapshotRows(report.snapshot)

  useEffect(() => {
    if (done) doneRef.current?.focus()
  }, [done])

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <Eyebrow>Platform admin</Eyebrow>
        <h1 className="text-display-lg text-ink">{reportTargetLabel(report.targetType)} report</h1>
        <div className="flex flex-wrap items-center gap-2">
          {isSafetyConcern(report) ? (
            <Badge tone="err" icon={<Warning weight="fill" />}>
              {reportReasonLabel(report.reason)}
            </Badge>
          ) : (
            <Badge tone="info">{reportReasonLabel(report.reason)}</Badge>
          )}
          <Badge tone={report.state === "open" ? "warn" : "ok"}>{reportStateLabel(report.state)}</Badge>
        </div>
        <p className="m-0 text-body-md text-ink-muted">
          Reported by {reporterLabel(report.reporterParty).toLowerCase()} on{" "}
          <time dateTime={report.createdAt}>{formatAdminDay(report.createdAt)}</time>. Tutor:{" "}
          <Link
            to={`/platform/tutors/${encodeURIComponent(report.tutorId)}`}
            className="rounded-sm text-accent-ink underline underline-offset-2 transition-colors hover:text-accent-hover"
          >
            {report.tutorName}
          </Link>
        </p>
      </header>

      {done ? (
        <p
          ref={doneRef}
          tabIndex={-1}
          role="status"
          className="m-0 rounded-lg border border-rule bg-ok-wash px-4 py-3 text-body-md text-ink"
        >
          {done}
        </p>
      ) : null}

      <Section title="What was reported">
        {report.details ? (
          <div className="flex flex-col gap-1">
            <h3 className="text-label text-ink-muted">Their words</h3>
            <p className={TEXT}>{report.details}</p>
          </div>
        ) : (
          <p className="m-0 text-body-md text-ink-muted">They added no words.</p>
        )}
        {rows.length > 0 ? (
          <div className="flex flex-col gap-1">
            <h3 className="text-label text-ink-muted">As it was when reported</h3>
            <dl className="m-0 grid gap-3 sm:grid-cols-2">
              {rows.map((row) => (
                <div key={row.label} className="flex min-w-0 flex-col gap-0.5">
                  <dt className="text-body-sm text-ink-muted">{row.label}</dt>
                  <dd className="m-0 whitespace-pre-wrap break-words text-body-md text-ink">{row.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        ) : null}
      </Section>

      <BookingSummary report={report} />
      <Thread report={report} />

      {report.state === "open" ? <ResolveForm report={report} resolve={resolve} onDone={setDone} /> : <Outcome report={report} />}
    </div>
  )
}

export function ReportDetail() {
  const { reportId = "" } = useParams()
  const query = useAdminTutoringReport(reportId)

  return (
    <div className="flex flex-col gap-4">
      <div>
        <BackControl fallback="/platform/reports" label="Reports" className="-ms-3 min-h-11" />
      </div>
      <QueryState
        query={query}
        srHeading="Report"
        skeleton={
          <>
            <PageHeaderSkeleton />
            <ListSkeleton rows={3} />
          </>
        }
        error={{
          heading: "We couldn't load this report",
          body: (error) => adminFailureMessage(error, "Something went wrong loading this report. Try again."),
        }}
      >
        {(report) => <Report report={report} />}
      </QueryState>
    </div>
  )
}
