/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — five sections in the SPEC's order, each with its own loading, empty and error, sections separated by hairlines with plain lists inside; long, so structure does the work and expression stays low. Seen in a mock-API browser harness at 320 to 1440 px, light and dark, axe clean. */
import { useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import {
  CaretDown,
  Hourglass,
  ProhibitInset,
  ShareNetwork,
  StopCircle,
  UserMinus,
  type Icon,
} from "@phosphor-icons/react"
import { StopSharingSheet } from "@/components/tutoring/stop-sharing-sheet"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Chip } from "@/components/ui/chip"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { Modal } from "@/components/ui/modal"
import { QueryState } from "@/components/ui/query-state"
import { EmptyState } from "@/components/ui/state-views"
import {
  useLeaveClass,
  useRemoveTutoringBlock,
  useRevokeTutorGrant,
  useStudentTutorAccessClasses,
  useStudentTutorAccessLog,
  useStudentTutorGrants,
  useStudentTutoringSettings,
  useTutoringBlocks,
  useUpdateStudentTutoringSettings,
} from "@/lib/hooks/useTutoringApi"
import { tutoringErrorOf } from "@/lib/tutoring/apiErrors"
import {
  ASK_SCHOOL_LINE,
  COUNTING_EXPLAINER,
  COUNTING_LABEL,
  EMPTY_BLOCKS_LINE,
  EMPTY_GRANTS_LINE,
  EMPTY_LOG_LINE,
  SHARING_EXPLAINER,
  SHARING_PARENTS_LINE,
  UNBLOCK_NOTE,
  accessLogView,
  blockRowView,
  classAccessView,
  countingChecked,
  countingUpdate,
  grantRowView,
  leaveClassCopy,
  splitGrants,
  type GrantStatusIcon,
  type GrantRowView,
} from "@/lib/tutoring/accessView"
import { usePagedItems } from "@/lib/tutoring/sessionView"
import { safetyActionError } from "@/lib/tutoring/safetyNoticeCopy"
import type { AccessLogEntry, AccessLogPage, ClassAccessItem, Grant } from "@/lib/tutoringTypes"

/*
 * S-38 · Tutors & your data (`/student/tutor-access`, SPEC §d). The student's
 * control room for everything the tutoring feature does with their data, in the
 * SPEC's order:
 *
 *   1. Sharing: each grant, with Stop sharing (S10) behind a confirm sheet.
 *   2. Who looked: the audit log of tutor reads (S11), paged.
 *   3. Teachers who see progress through a class (S16), with Leave for a
 *      school-less class (S17) and "ask your school" for the rest. Hidden when
 *      there are none.
 *   4. Results counting (S12, S13): one box, saved as soon as it changes.
 *   5. Blocked tutors (B1) with Unblock (B3).
 *
 * Each section loads, fails and empties on its own, so one slow route never
 * blanks the page. Nothing here tells a student that a tutor blocked, suspended
 * or closed anything: an ended grant reads the same whatever ended it (SPEC
 * §i.8), and the blocks listed are the student's own.
 *
 * Names (tutor, class, teacher, school) come from the API and are drawn as text.
 */

const GRANT_ICONS: Record<GrantStatusIcon, Icon> = {
  ShareNetwork,
  StopCircle,
  Hourglass,
  ProhibitInset,
  UserMinus,
}

function SectionHeading({ id, children }: { id: string; children: string }) {
  return (
    <h2 id={id} className="m-0 text-display-sm text-ink">
      {children}
    </h2>
  )
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-4 border-t border-rule pt-6">
      <SectionHeading id={id}>{title}</SectionHeading>
      {children}
    </section>
  )
}

function List({ children }: { children: ReactNode }) {
  return (
    <ul className="m-0 flex list-none flex-col overflow-hidden rounded-lg border border-rule bg-paper-raised p-0">
      {children}
    </ul>
  )
}

const ROW = "flex flex-col gap-2 border-b border-rule px-4 py-3.5 last:border-b-0"

// ── 1 · Sharing ────────────────────────────────────────────────────────────

function GrantRow({ row, onStop }: { row: GrantRowView; onStop?: () => void }) {
  const Glyph = GRANT_ICONS[row.status.icon]
  return (
    <li className={ROW}>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <Link to={row.tutorHref} className="min-w-0 break-words text-body-lg font-medium text-ink underline">
          {row.tutorName}
        </Link>
        <Chip tone={row.status.tone} className="gap-1.5">
          <Glyph size={14} weight="bold" aria-hidden />
          {row.status.label}
        </Chip>
      </div>
      <p className="m-0 text-body-sm text-ink-muted">{row.sinceLine}</p>
      <p className="m-0 text-body-sm text-ink-muted">{row.status.detail}</p>
      {row.canStop && onStop ? (
        <div>
          <Button variant="secondary" size="sm" aria-label={row.stopLabel} onClick={onStop}>
            Stop sharing
          </Button>
        </div>
      ) : null}
    </li>
  )
}

function SharingSection() {
  const grants = useStudentTutorGrants()
  const revoke = useRevokeTutorGrant()
  // The grant stays in state while the sheet animates out; `open` is what closes it.
  const [target, setTarget] = useState<Grant | null>(null)
  const [open, setOpen] = useState(false)
  const [showEnded, setShowEnded] = useState(false)

  async function stop() {
    if (!target) return
    try {
      await revoke.mutateAsync({ grantId: target.grantId })
      setOpen(false)
    } catch {
      // Shown inside the sheet from `revoke.error`.
    }
  }

  return (
    <Section id="tutor-access-sharing" title="Sharing">
      <div className="flex max-w-prose flex-col gap-2">
        <p className="m-0 text-body-md text-ink-muted">{SHARING_EXPLAINER}</p>
        <p className="m-0 text-body-md text-ink-muted">{SHARING_PARENTS_LINE}</p>
      </div>
      <QueryState
        query={grants}
        skeleton={<ListSkeleton rows={2} />}
        error={{ heading: "We couldn't load who you share with", compact: true }}
        isEmpty={(data) => data.items.length === 0}
        empty={<EmptyState compact heading={EMPTY_GRANTS_LINE} />}
      >
        {(data) => {
          const { live, ended } = splitGrants(data.items)
          return (
            <div className="flex flex-col gap-4">
              {live.length > 0 ? (
                <List>
                  {live.map((grant) => (
                    <GrantRow
                      key={grant.grantId}
                      row={grantRowView(grant)}
                      onStop={() => {
                        revoke.reset()
                        setTarget(grant)
                        setOpen(true)
                      }}
                    />
                  ))}
                </List>
              ) : (
                <p className="m-0 text-body-md text-ink-muted">{EMPTY_GRANTS_LINE}</p>
              )}
              {ended.length > 0 ? (
                <div className="flex flex-col gap-3">
                  <div>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-expanded={showEnded}
                      aria-controls="tutor-access-ended"
                      icon={<CaretDown size={14} className={showEnded ? "rotate-180" : undefined} />}
                      onClick={() => setShowEnded((value) => !value)}
                    >
                      {showEnded ? "Hide" : "Show"} earlier sharing ({ended.length})
                    </Button>
                  </div>
                  {showEnded ? (
                    <div id="tutor-access-ended">
                      <List>
                        {ended.map((grant) => (
                          <GrantRow key={grant.grantId} row={grantRowView(grant)} />
                        ))}
                      </List>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          )
        }}
      </QueryState>
      <StopSharingSheet
        open={open}
        grant={target}
        pending={revoke.isPending}
        error={revoke.error}
        onCancel={() => setOpen(false)}
        onConfirm={() => void stop()}
      />
    </Section>
  )
}

// ── 2 · Who looked ─────────────────────────────────────────────────────────

const logKey = (entry: AccessLogEntry) => `${entry.tutorId ?? entry.tutorName}|${entry.action}|${entry.accessedAt}`

function useAccessLogPage(_scope: "all", cursor: string | null) {
  return useStudentTutorAccessLog({ cursor })
}

function LogSection() {
  const paged = usePagedItems<"all", AccessLogEntry, AccessLogPage>(useAccessLogPage, "all", logKey)
  return (
    <Section id="tutor-access-log" title="Who looked">
      <QueryState
        query={paged.state}
        skeleton={<ListSkeleton rows={3} />}
        error={{ heading: "We couldn't load who looked", compact: true }}
        isEmpty={(items) => items.length === 0}
        empty={<EmptyState compact heading={EMPTY_LOG_LINE} />}
      >
        {(items) => (
          <div className="flex flex-col gap-4">
            <List>
              {items.map((entry) => {
                const view = accessLogView(entry)
                return (
                  <li key={logKey(entry)} className={ROW}>
                    <p className="m-0 break-words text-body-md text-ink">
                      {view.tutorHref ? (
                        <Link to={view.tutorHref} className="font-medium underline">
                          {view.tutorName}
                        </Link>
                      ) : (
                        <span className="font-medium">{view.tutorName}</span>
                      )}{" "}
                      {view.action}
                    </p>
                    <p className="m-0 text-body-sm text-ink-muted">{view.timeLabel}</p>
                  </li>
                )
              })}
            </List>
            {paged.moreFailed ? (
              <p role="alert" className="m-0 text-body-sm text-err">
                We couldn't load more. Press Show more to try again.
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
                  Show more
                </Button>
              </div>
            ) : null}
          </div>
        )}
      </QueryState>
    </Section>
  )
}

// ── 3 · Classes ────────────────────────────────────────────────────────────

function ClassesSection() {
  const classes = useStudentTutorAccessClasses()
  const leave = useLeaveClass()
  const [target, setTarget] = useState<ClassAccessItem | null>(null)
  const [open, setOpen] = useState(false)

  async function confirmLeave() {
    if (!target) return
    try {
      await leave.mutateAsync({ classId: target.classId })
      setOpen(false)
    } catch {
      // Shown inside the sheet from `leave.error`.
    }
  }

  const copy = target ? leaveClassCopy(target) : null
  const leaveError =
    leave.error === null
      ? null
      : (tutoringErrorOf(leave.error)?.message ?? "We couldn't leave this class. Try again.")

  // No classes: the section is hidden, and so is its heading (SPEC §d S-38).
  if (classes.status === "success" && classes.data.items.length === 0) return null

  return (
    <QueryState
      query={classes}
      skeleton={
        <Section id="tutor-access-classes" title="Teachers who can see your progress through a class">
          <ListSkeleton rows={2} />
        </Section>
      }
      error={{ heading: "We couldn't load your classes", compact: true }}
    >
      {(data) => (
        <Section id="tutor-access-classes" title="Teachers who can see your progress through a class">
          <List>
            {data.items.map((item) => {
              const view = classAccessView(item)
              return (
                <li key={view.classId} className={ROW}>
                  <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
                    <span className="min-w-0 break-words text-body-lg font-medium text-ink">{view.className}</span>
                    {view.alsoTutor ? <Chip tone="info">Also your tutor</Chip> : null}
                  </div>
                  <p className="m-0 text-body-sm text-ink-muted">
                    {view.teacherName}, {view.whereLine}
                  </p>
                  {view.canLeave ? (
                    <div>
                      <Button
                        variant="secondary"
                        size="sm"
                        aria-label={`Leave ${view.className}`}
                        onClick={() => {
                          leave.reset()
                          setTarget(item)
                          setOpen(true)
                        }}
                      >
                        Leave
                      </Button>
                    </div>
                  ) : null}
                  {view.askSchool ? <p className="m-0 text-body-sm text-ink-muted">{ASK_SCHOOL_LINE}</p> : null}
                </li>
              )
            })}
          </List>
          {copy ? (
            <Modal
              open={open}
              onClose={() => setOpen(false)}
              title={copy.title}
              description={copy.body}
              size="sm"
              dismissible={false}
              hideCloseButton
              footer={
                <div className="flex flex-wrap justify-end gap-2">
                  <Button variant="secondary" size="sm" disabled={leave.isPending} onClick={() => setOpen(false)}>
                    {copy.cancelLabel}
                  </Button>
                  <Button variant="accent" size="sm" loading={leave.isPending} onClick={() => void confirmLeave()}>
                    {copy.confirmLabel}
                  </Button>
                </div>
              }
            >
              {leaveError ? (
                <p role="alert" className="m-0 text-body-sm text-err">
                  {leaveError}
                </p>
              ) : null}
            </Modal>
          ) : null}
        </Section>
      )}
    </QueryState>
  )
}

// ── 4 · Results counting ───────────────────────────────────────────────────

function CountingSection() {
  const settings = useStudentTutoringSettings()
  const update = useUpdateStudentTutoringSettings()
  return (
    <Section id="tutor-access-counting" title="Results counting">
      <QueryState
        query={settings}
        skeleton={<ListSkeleton rows={1} />}
        error={{ heading: "We couldn't load this setting", compact: true }}
      >
        {(data) => {
          // While a change is saving, show the box as the student just set it.
          const checked = update.isPending && update.variables ? !update.variables.outcomeStatsOptOut : countingChecked(data)
          return (
            <div className="flex max-w-prose flex-col gap-3">
              <Checkbox
                label={COUNTING_LABEL}
                checked={checked}
                state={update.isPending ? "loading" : undefined}
                onChange={(event) => update.mutate(countingUpdate(event.target.checked))}
              />
              <p className="m-0 text-body-md text-ink-muted">{COUNTING_EXPLAINER}</p>
              <p role="status" className="m-0 min-h-5 text-body-sm text-ink-muted">
                {update.isSuccess && !update.isPending ? "Saved." : ""}
              </p>
              {update.isError ? (
                <p role="alert" className="m-0 text-body-sm text-err">
                  {safetyActionError(update.error, "We couldn't save that. Try again.")}
                </p>
              ) : null}
            </div>
          )
        }}
      </QueryState>
    </Section>
  )
}

// ── 5 · Blocked tutors ─────────────────────────────────────────────────────

function BlocksSection() {
  const blocks = useTutoringBlocks()
  const remove = useRemoveTutoringBlock()
  const [failed, setFailed] = useState<string | null>(null)

  async function unblock(counterpartId: string) {
    setFailed(null)
    try {
      await remove.mutateAsync({ counterpartId })
    } catch (error) {
      setFailed(safetyActionError(error, "We couldn't unblock them. Try again."))
    }
  }

  return (
    <Section id="tutor-access-blocks" title="Blocked tutors">
      <QueryState
        query={blocks}
        skeleton={<ListSkeleton rows={1} />}
        error={{ heading: "We couldn't load your blocked tutors", compact: true }}
        isEmpty={(data) => data.items.length === 0}
        empty={<EmptyState compact heading={EMPTY_BLOCKS_LINE} />}
      >
        {(data) => (
          <div className="flex flex-col gap-3">
            <List>
              {data.items.map((block) => {
                const row = blockRowView(block)
                return (
                  <li key={row.counterpartId} className={ROW}>
                    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
                      <span className="min-w-0 break-words text-body-lg font-medium text-ink">{row.name}</span>
                      <Button
                        variant="secondary"
                        size="sm"
                        aria-label={row.unblockLabel}
                        loading={remove.isPending && remove.variables?.counterpartId === row.counterpartId}
                        onClick={() => void unblock(row.counterpartId)}
                      >
                        Unblock
                      </Button>
                    </div>
                    <p className="m-0 text-body-sm text-ink-muted">{row.sinceLine}</p>
                  </li>
                )
              })}
            </List>
            <p className="m-0 text-body-sm text-ink-muted">{UNBLOCK_NOTE}</p>
            {failed ? (
              <p role="alert" className="m-0 text-body-sm text-err">
                {failed}
              </p>
            ) : null}
          </div>
        )}
      </QueryState>
    </Section>
  )
}

export function TutorAccess() {
  return (
    <div className="flex w-full max-w-160 flex-col gap-6">
      <h1 className="m-0 text-display-md text-ink">Tutors &amp; your data</h1>
      <SharingSection />
      <LogSection />
      <ClassesSection />
      <CountingSection />
      <BlocksSection />
    </div>
  )
}
