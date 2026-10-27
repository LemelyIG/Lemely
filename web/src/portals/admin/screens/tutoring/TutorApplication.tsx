/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 — read the profile, open every document, then decide; sections divided by hairlines, no boxes inside boxes; not yet seen in a browser. */
import { useEffect, useRef, useState, type ReactNode } from "react"
import { Link, useParams } from "react-router-dom"
import { CheckCircle, FileText, Warning } from "@phosphor-icons/react"
import { Badge, type BadgeTone } from "@/components/ui/badge"
import { BackControl } from "@/components/ui/back-control"
import { Button, buttonVariants } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { Modal } from "@/components/ui/modal"
import { Eyebrow } from "@/components/ui/primitives"
import { QueryState } from "@/components/ui/query-state"
import { SubjectTag } from "@/components/ui/subject-tag"
import { Textarea } from "@/components/ui/textarea"
import {
  useAdminTutor,
  useApproveTutor,
  useCloseTutor,
  useRejectTutor,
  useSuspendTutor,
} from "@/lib/hooks/useTutoringApi"
import { useOnlineStatus } from "@/lib/online"
import {
  DECISION_COPY,
  DECISION_NOTE_MAX,
  EVIDENCE_LINK_TTL_SECONDS,
  adminFailureMessage,
  approveBody,
  approveDoneLine,
  approveGate,
  availableDecisions,
  decisionBody,
  decisionLabel,
  decisionNoteError,
  decisionNoteRule,
  evidenceLinkSecondsLeft,
  evidenceLinksExpired,
  formatAdminDay,
  formatFileSize,
  listingStateLabel,
  noteLength,
  type TutorDecision,
} from "@/lib/tutoring/adminTutoring"
import { MODE_OPTIONS, availabilityRows } from "@/lib/tutoring/discovery"
import type { ListingState } from "@/lib/tutoring/profileSteps"
import type { AdminEvidence, AdminTutorDetail } from "@/lib/tutoringTypes"

/*
 * X-05 · Tutor application (`/platform/tutors/:tutorId`, SPEC §d, rows A2-A5, A12).
 *
 * Read the profile, open each document, then decide. The page is one column of
 * sections divided by hairlines: the facts first, the documents next, the
 * history, and the decision last, so the order of reading is the order of work.
 *
 * Approve is a claim that the admin looked at the documents. It stays shut until
 * the "I looked at the documents" box is ticked and every file was opened from
 * this page (`approveGate`). Reject and suspend need a note, which the tutor
 * reads. Close and suspend say what they cost before they run.
 *
 * Evidence links are 300 second downloads issued, and logged, by A2. They are
 * dead when the time is up, and the section says so and offers new ones rather
 * than leaving a link that fails.
 *
 * States: loading, error and offline (through `QueryState`; a bad id is the
 * 404 sentence with a way back), each listing state's own decisions, no
 * documents uploaded, links expired, a decision in flight, a decision refused,
 * and offline (decision buttons disabled with the reason).
 */

const STATE_TONE: Record<ListingState, BadgeTone> = {
  draft: "info",
  pending_review: "warn",
  listed: "ok",
  rejected: "err",
  suspended: "err",
  closed: "info",
}

const TEXT = "max-w-prose whitespace-pre-wrap break-words text-body-md text-ink"

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

// ── Documents ───────────────────────────────────────────────────────────────

function EvidenceRow({
  file,
  opened,
  expired,
  onOpen,
}: {
  file: AdminEvidence
  opened: boolean
  expired: boolean
  onOpen: () => void
}) {
  const usable = file.signedUrl !== null && !expired
  return (
    <li className="flex flex-col gap-2 border-b border-rule py-3 last:border-b-0 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="flex items-start gap-2 break-all text-body-md text-ink">
          <FileText size={18} className="mt-0.5 flex-none text-ink-faint" aria-hidden="true" />
          {file.filename}
        </span>
        <span className="text-body-sm text-ink-muted">
          {file.contentType}, {formatFileSize(file.sizeBytes)}, uploaded{" "}
          <time dateTime={file.uploadedAt}>{formatAdminDay(file.uploadedAt)}</time>
        </span>
        {file.description ? <span className="whitespace-pre-wrap break-words text-body-sm text-ink-muted">{file.description}</span> : null}
      </div>
      <div className="flex flex-none flex-wrap items-center gap-2">
        {opened ? (
          <Badge tone="ok" icon={<CheckCircle weight="fill" />}>
            Opened
          </Badge>
        ) : (
          <Badge tone="warn">Not opened</Badge>
        )}
        {usable ? (
          <a
            href={file.signedUrl ?? undefined}
            target="_blank"
            rel="noopener noreferrer"
            onClick={onOpen}
            className={`${buttonVariants({ variant: "secondary", size: "sm" })} min-h-11`}
          >
            Open file
          </a>
        ) : (
          <span className="text-body-sm text-ink-muted">{expired ? "Link expired" : "No link"}</span>
        )}
      </div>
    </li>
  )
}

function Documents({
  detail,
  loadedAt,
  opened,
  onOpen,
  onRefresh,
  refreshing,
}: {
  detail: AdminTutorDetail
  loadedAt: number
  opened: ReadonlySet<string>
  onOpen: (evidenceId: string) => void
  onRefresh: () => void
  refreshing: boolean
}) {
  // The links die at a known moment, so the page wakes once then, not every second.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const left = evidenceLinkSecondsLeft(loadedAt, Date.now())
    if (left === 0) return
    const timer = setTimeout(() => setNow(Date.now()), left * 1000 + 50)
    return () => clearTimeout(timer)
  }, [loadedAt])
  const expired = evidenceLinksExpired(loadedAt, now)

  return (
    <Section title="Documents">
      {detail.evidence.length === 0 ? (
        <p className="m-0 text-body-md text-ink-muted">This tutor has not uploaded any files.</p>
      ) : (
        <>
          <p className="m-0 max-w-prose text-body-sm text-ink-muted">
            Each file downloads from a link that works for {EVIDENCE_LINK_TTL_SECONDS / 60} minutes from
            when this page loaded. Every link issued is logged.
          </p>
          {expired ? (
            <div
              role="alert"
              className="flex flex-wrap items-center gap-3 rounded-lg border border-rule bg-warn-wash px-4 py-3"
            >
              <p className="m-0 text-body-md text-ink">The links have expired.</p>
              <Button className="min-h-11" size="sm" loading={refreshing} onClick={onRefresh}>
                Get new links
              </Button>
            </div>
          ) : null}
          <ul className="m-0 list-none p-0">
            {detail.evidence.map((file) => (
              <EvidenceRow
                key={file.evidenceId}
                file={file}
                opened={opened.has(file.evidenceId)}
                expired={expired}
                onOpen={() => onOpen(file.evidenceId)}
              />
            ))}
          </ul>
        </>
      )}
    </Section>
  )
}

// ── Decisions ───────────────────────────────────────────────────────────────

export function DecisionDialog({
  decision,
  tutorName,
  pending,
  error,
  onConfirm,
  onClose,
}: {
  decision: Exclude<TutorDecision, "approve">
  tutorName: string
  pending: boolean
  error: unknown
  onConfirm: (note: string) => void
  onClose: () => void
}) {
  const copy = DECISION_COPY[decision]
  const [note, setNote] = useState("")
  const rule = decisionNoteRule(decision)
  const problem = decisionNoteError(decision, note)
  const blank = note.trim() === ""

  return (
    <Modal
      open
      onClose={onClose}
      dismissible={false}
      hideCloseButton
      title={copy.title}
      description={tutorName}
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          <Button className="min-h-11" variant="primary" onClick={onClose} disabled={pending}>
            Go back
          </Button>
          <Button className="min-h-11" loading={pending} disabled={problem !== null} onClick={() => onConfirm(note)}>
            {copy.confirmLabel}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="m-0 text-body-md text-ink">{copy.consequence}</p>
        <Textarea
          label={copy.noteLabel}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          rows={4}
          hint={`${copy.noteHint} ${noteLength(note.trim())} of ${DECISION_NOTE_MAX} characters.`}
          error={!blank && problem !== null ? problem : undefined}
        />
        {rule.required && blank ? (
          <p className="m-0 text-body-sm text-ink-muted">A note is needed before this can go through.</p>
        ) : null}
        {error ? (
          <p role="alert" className="m-0 text-body-sm text-err">
            {adminFailureMessage(error, "That didn't go through. Try again.")}
          </p>
        ) : null}
      </div>
    </Modal>
  )
}

function ApproveForm({
  detail,
  opened,
  online,
  onDone,
}: {
  detail: AdminTutorDetail
  opened: ReadonlySet<string>
  online: boolean
  onDone: (line: string) => void
}) {
  const approve = useApproveTutor()
  const [documentsSeen, setDocumentsSeen] = useState(false)
  const [note, setNote] = useState("")
  const input = { documentsSeen, evidence: detail.evidence, opened }
  const gate = approveGate(input)
  const noteProblem = decisionNoteError("approve", note)
  const label = decisionLabel("approve", detail.listingState)
  const canSend = gate.enabled && noteProblem === null && online
  const reasonId = "approve-reason"
  const shown = !online ? "You're offline. Reconnect to decide." : (gate.reason ?? noteProblem)

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault()
        const body = approveBody(input, note)
        if (body === null || !canSend) return
        approve.mutate(
          { tutorId: detail.tutorId, body },
          { onSuccess: (result) => onDone(approveDoneLine(detail.listingState, result.listingState)) },
        )
      }}
    >
      <div className="flex items-center [&_label]:min-h-11">
        <Checkbox
          label="I looked at the documents"
          checked={documentsSeen}
          onChange={(event) => setDocumentsSeen(event.target.checked)}
          aria-describedby={shown ? reasonId : undefined}
        />
      </div>
      <Textarea
        label="Note (optional)"
        value={note}
        onChange={(event) => setNote(event.target.value)}
        rows={3}
        hint="Kept in the approval history."
        error={noteProblem ?? undefined}
      />
      <div className="flex flex-col items-start gap-2">
        <Button className="min-h-11" type="submit" variant="primary" loading={approve.isPending} disabled={!canSend}>
          {label}
        </Button>
        {shown ? (
          <p id={reasonId} className="m-0 text-body-sm text-ink-muted">
            {shown}
          </p>
        ) : null}
        {approve.isError ? (
          <p role="alert" className="m-0 text-body-sm text-err">
            {adminFailureMessage(approve.error, "That didn't go through. Try again.")}
          </p>
        ) : null}
      </div>
    </form>
  )
}

function Decisions({
  detail,
  opened,
  online,
  onDone,
}: {
  detail: AdminTutorDetail
  opened: ReadonlySet<string>
  online: boolean
  onDone: (line: string) => void
}) {
  const reject = useRejectTutor()
  const suspend = useSuspendTutor()
  const close = useCloseTutor()
  const [dialog, setDialog] = useState<Exclude<TutorDecision, "approve"> | null>(null)
  const decisions = availableDecisions(detail.listingState)
  const mutation = { reject, suspend, close }

  if (decisions.length === 0) {
    return <p className="m-0 text-body-md text-ink-muted">This profile is closed. No decisions are left.</p>
  }

  const others = decisions.filter((decision): decision is Exclude<TutorDecision, "approve"> => decision !== "approve")
  const active = dialog ? mutation[dialog] : null

  return (
    <div className="flex flex-col gap-6">
      {decisions.includes("approve") ? (
        <ApproveForm detail={detail} opened={opened} online={online} onDone={onDone} />
      ) : null}
      {others.length > 0 ? (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-2">
            {others.map((decision) => (
              <Button
                className="min-h-11"
                key={decision}
                disabled={!online}
                onClick={() => {
                  mutation[decision].reset()
                  setDialog(decision)
                }}
              >
                {decisionLabel(decision, detail.listingState)}
              </Button>
            ))}
          </div>
          {!online ? <p className="m-0 text-body-sm text-ink-muted">You're offline. Reconnect to decide.</p> : null}
        </div>
      ) : null}
      {dialog && active ? (
        <DecisionDialog
          decision={dialog}
          tutorName={detail.publicName}
          pending={active.isPending}
          error={active.error}
          onClose={() => setDialog(null)}
          onConfirm={(note) =>
            active.mutate(
              { tutorId: detail.tutorId, body: decisionBody(dialog, note) },
              {
                onSuccess: () => {
                  setDialog(null)
                  onDone(DECISION_COPY[dialog].doneLine)
                },
              },
            )
          }
        />
      ) : null}
    </div>
  )
}

// ── The page ────────────────────────────────────────────────────────────────

const HISTORY_LABEL = {
  approved: "Approved",
  rejected: "Rejected",
  suspended: "Suspended",
  reinstated: "Reinstated",
  closed: "Closed",
} as const

function Application({
  detail,
  loadedAt,
  refreshing,
  onRefresh,
}: {
  detail: AdminTutorDetail
  loadedAt: number
  refreshing: boolean
  onRefresh: () => void
}) {
  const online = useOnlineStatus()
  const [opened, setOpened] = useState<ReadonlySet<string>>(() => new Set())
  const [done, setDone] = useState<string | null>(null)
  const doneRef = useRef<HTMLParagraphElement>(null)
  const rows = availabilityRows(detail.availability).filter((row) => row.ranges.length > 0)

  useEffect(() => {
    if (done) doneRef.current?.focus()
  }, [done])

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <Eyebrow>Platform admin</Eyebrow>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-display-lg text-ink">{detail.publicName}</h1>
          <Badge tone={STATE_TONE[detail.listingState]}>{listingStateLabel(detail.listingState)}</Badge>
          {detail.paused ? <Badge tone="info">Paused by the tutor</Badge> : null}
        </div>
        <p className="m-0 text-body-md text-ink-muted">{detail.headline}</p>
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

      {detail.openReports > 0 ? (
        <p className="m-0 flex flex-wrap items-center gap-2 text-body-md text-ink">
          <Warning size={18} className="flex-none text-warn" aria-hidden="true" />
          {detail.openReports === 1 ? "1 open report" : `${detail.openReports} open reports`} about this tutor.
          <Link to="/platform/reports" className="inline-flex min-h-11 items-center rounded-sm text-accent-ink underline underline-offset-2 transition-colors hover:text-accent-hover">
            Go to reports
          </Link>
        </p>
      ) : null}

      <Section title="Profile">
        <dl className="m-0 grid gap-4 sm:grid-cols-2">
          <Fact label="Account email">{detail.accountEmail}</Fact>
          <Fact label="Submitted">
            {detail.submittedAt ? (
              <time dateTime={detail.submittedAt}>{formatAdminDay(detail.submittedAt)}</time>
            ) : (
              "Not submitted"
            )}
          </Fact>
          <Fact label="Area">{detail.area.name}</Fact>
          <Fact label="Ways to meet">
            {detail.modes.map((mode) => MODE_OPTIONS.find((option) => option.value === mode)?.label ?? mode).join(", ")}
          </Fact>
          <Fact label="Subjects">
            <span className="flex flex-wrap gap-1.5">
              {detail.subjects.map((subject) => (
                <SubjectTag key={subject.code} subject={subject.name} />
              ))}
            </span>
          </Fact>
          <Fact label="Documents seen at last approval">{detail.documentsSeen ? "Yes" : "No"}</Fact>
        </dl>
        <div className="flex flex-col gap-1">
          <h3 className="text-label text-ink-muted">About</h3>
          <p className={`m-0 ${TEXT}`}>{detail.bio === "" ? "Not set" : detail.bio}</p>
        </div>
        <div className="flex flex-col gap-1">
          <h3 className="text-label text-ink-muted">Qualifications</h3>
          <p className={`m-0 ${TEXT}`}>{detail.qualificationNote ?? "Not set"}</p>
        </div>
        {detail.otherModeNote ? (
          <div className="flex flex-col gap-1">
            <h3 className="text-label text-ink-muted">Another way to meet</h3>
            <p className={`m-0 ${TEXT}`}>{detail.otherModeNote}</p>
          </div>
        ) : null}
        <div className="flex flex-col gap-1">
          <h3 className="text-label text-ink-muted">Weekly availability, {detail.zoneLabel}</h3>
          {rows.length === 0 ? (
            <p className="m-0 text-body-md text-ink-muted">No times set.</p>
          ) : (
            <dl className="m-0 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
              {rows.map((row) => (
                <div key={row.isoWeekday} className="contents">
                  <dt className="text-body-md text-ink-muted">{row.dayLabel}</dt>
                  <dd className="m-0 text-body-md tabular-nums text-ink">{row.ranges.join(", ")}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </Section>

      <Documents
        detail={detail}
        loadedAt={loadedAt}
        opened={opened}
        onOpen={(evidenceId) => setOpened((previous) => new Set(previous).add(evidenceId))}
        onRefresh={onRefresh}
        refreshing={refreshing}
      />

      <Section title="History">
        {detail.history.length === 0 ? (
          <p className="m-0 text-body-md text-ink-muted">No decisions yet.</p>
        ) : (
          <ol className="m-0 flex list-none flex-col gap-3 p-0">
            {detail.history.map((event) => (
              <li key={`${event.createdAt}-${event.decision}`} className="flex flex-col gap-0.5">
                <span className="text-body-md text-ink">
                  <span className="font-medium">{HISTORY_LABEL[event.decision]}</span>
                  {", "}
                  <time dateTime={event.createdAt}>{formatAdminDay(event.createdAt)}</time>
                  {event.decision === "approved" || event.decision === "reinstated"
                    ? event.documentsSeen
                      ? ", documents seen"
                      : ", documents not seen"
                    : ""}
                </span>
                {event.note ? <span className="whitespace-pre-wrap break-words text-body-sm text-ink-muted">{event.note}</span> : null}
              </li>
            ))}
          </ol>
        )}
      </Section>

      <Section title="Decision">
        <Decisions
          detail={detail}
          opened={opened}
          online={online}
          onDone={setDone}
        />
      </Section>
    </div>
  )
}

export function TutorApplication() {
  const { tutorId = "" } = useParams()
  const query = useAdminTutor(tutorId)

  return (
    <div className="flex flex-col gap-4">
      <div>
        <BackControl fallback="/platform/tutors" label="Tutors" className="-ms-3 min-h-11" />
      </div>
      <QueryState
        query={query}
        srHeading="Tutor application"
        skeleton={
          <>
            <PageHeaderSkeleton />
            <ListSkeleton rows={4} />
          </>
        }
        error={{
          heading: "We couldn't load this tutor",
          body: (error) => adminFailureMessage(error, "Something went wrong loading this profile. Try again."),
        }}
      >
        {(detail) => (
          <Application
            detail={detail}
            loadedAt={query.dataUpdatedAt}
            refreshing={query.isFetching}
            onRefresh={() => void query.refetch()}
          />
        )}
      </QueryState>
    </div>
  )
}
