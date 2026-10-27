/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — two plain lists under one sentence that says who decides; nothing here can be pressed except Report, because a parent can read this and cannot change it. */
import { useState, type ReactNode } from "react"
import { Link, useParams } from "react-router-dom"
import { CaretDown, Hourglass, ProhibitInset, ShareNetwork, StopCircle, UserMinus, type Icon } from "@phosphor-icons/react"
import { ReportSheet } from "@/components/tutoring/report-sheet"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { EmptyState } from "@/components/ui/state-views"
import {
  useCreateTutoringReport,
  useParentChildTutorAccessLog,
  useParentChildTutorGrants,
} from "@/lib/hooks/useTutoringApi"
import { accessLogView, type GrantStatusIcon } from "@/lib/tutoring/accessView"
import {
  noGrantsLine,
  noLogLine,
  PARENT_TUTORS_PATH,
  parentGrantRowView,
  parentSharingLine,
  type ParentGrantRowView,
} from "@/lib/tutoring/parentTutoring"
import { usePagedItems } from "@/lib/tutoring/sessionView"
import type { AccessLogEntry, AccessLogPage } from "@/lib/tutoringTypes"
import { ChildScope } from "./ChildTutoring"

/*
 * P-08 · Who {child} shares progress with (`/parent/children/:childId/tutor-access`,
 * SPEC §d, row 16 i). Read-only, in two parts:
 *
 *   1. The child's grants (PA6): the tutor, since when, and the status. One line
 *      says who decides: "{Child} decides who can see their progress. Only
 *      {child} can stop sharing. If something worries you, report it."
 *   2. Who looked (PA7): the tutor, "viewed {child}'s progress" or "saw {child}
 *      in their student list", and when. Paged with "Show more".
 *
 * There is no revoke control, by design: sharing is the child's decision, and
 * this file imports no revoke, unblock or settings hook (a test reads the
 * source). The one thing a parent can do is Report a tutor, from a grant or a
 * log entry that names one. Everything is in the third person, and a grant a
 * tutor ended reads the same whatever ended it (SPEC §i.8).
 *
 * No back link of its own: the shell's trail (Overview, Tutoring, Who they share
 * with) leads back to P-05; see `ParentTrail` in `../../index.tsx`.
 *
 * Each part loads, fails and empties on its own. A parent's reads here write no
 * audit row (O22): that log records tutor reads only.
 */

const GRANT_ICONS: Record<GrantStatusIcon, Icon> = {
  ShareNetwork,
  StopCircle,
  Hourglass,
  ProhibitInset,
  UserMinus,
}

const ROW = "flex flex-col gap-2 border-b border-rule px-4 py-3.5 last:border-b-0"

function List({ children }: { children: ReactNode }) {
  return (
    <ul className="m-0 flex list-none flex-col overflow-hidden rounded-lg border border-rule bg-paper-raised p-0">
      {children}
    </ul>
  )
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-4 border-t border-rule pt-6">
      <h2 id={id} className="m-0 text-display-sm text-ink">
        {title}
      </h2>
      {children}
    </section>
  )
}

interface ReportTarget {
  tutorId: string
  tutorName: string
}

function ReportButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <Button variant="ghost" size="sm" aria-label={label} onClick={onClick}>
      Report
    </Button>
  )
}

// ── 1 · Sharing ────────────────────────────────────────────────────────────

function GrantRow({ row, onReport }: { row: ParentGrantRowView; onReport: () => void }) {
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
      <div className="-ms-3">
        <ReportButton label={row.reportLabel} onClick={onReport} />
      </div>
    </li>
  )
}

function SharingSection({ childId, childName, onReport }: { childId: string; childName: string; onReport: (target: ReportTarget) => void }) {
  const grants = useParentChildTutorGrants(childId)
  const [showEnded, setShowEnded] = useState(false)

  return (
    <Section id="child-access-sharing" title="Sharing">
      <p className="m-0 max-w-prose text-body-md text-ink-muted">{parentSharingLine(childName)}</p>
      <QueryState
        query={grants}
        skeleton={<ListSkeleton rows={2} />}
        error={{ heading: `We couldn't load who ${childName} shares with`, compact: true }}
        isEmpty={(data) => data.items.length === 0}
        empty={<EmptyState compact heading={noGrantsLine(childName)} />}
      >
        {(data) => {
          const rows = data.items.map((grant) => parentGrantRowView(grant, childName, childId))
          const live = rows.filter((row) => row.status.live)
          const ended = rows.filter((row) => !row.status.live)
          const drawRow = (row: ParentGrantRowView) => (
            <GrantRow
              key={row.grantId}
              row={row}
              onReport={() => onReport({ tutorId: row.tutorId, tutorName: row.tutorName })}
            />
          )
          return (
            <div className="flex flex-col gap-4">
              {live.length > 0 ? (
                <List>{live.map(drawRow)}</List>
              ) : (
                <p className="m-0 text-body-md text-ink-muted">{noGrantsLine(childName)}</p>
              )}
              {ended.length > 0 ? (
                <div className="flex flex-col gap-3">
                  <div>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-expanded={showEnded}
                      aria-controls="child-access-ended"
                      icon={<CaretDown size={14} className={showEnded ? "rotate-180" : undefined} />}
                      onClick={() => setShowEnded((value) => !value)}
                    >
                      {showEnded ? "Hide" : "Show"} earlier sharing ({ended.length})
                    </Button>
                  </div>
                  {showEnded ? (
                    <div id="child-access-ended">
                      <List>{ended.map(drawRow)}</List>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          )
        }}
      </QueryState>
    </Section>
  )
}

// ── 2 · Who looked ─────────────────────────────────────────────────────────

const logKey = (entry: AccessLogEntry) => `${entry.tutorId ?? entry.tutorName}|${entry.action}|${entry.accessedAt}`

function useAccessLogPage(childId: string, cursor: string | null) {
  return useParentChildTutorAccessLog(childId, { cursor })
}

function LogSection({ childId, childName, onReport }: { childId: string; childName: string; onReport: (target: ReportTarget) => void }) {
  const paged = usePagedItems<string, AccessLogEntry, AccessLogPage>(useAccessLogPage, childId, logKey)
  return (
    <Section id="child-access-log" title="Who looked">
      <QueryState
        query={paged.state}
        skeleton={<ListSkeleton rows={3} />}
        error={{ heading: `We couldn't load who looked at ${childName}'s progress`, compact: true }}
        isEmpty={(items) => items.length === 0}
        empty={<EmptyState compact heading={noLogLine(childName)} />}
      >
        {(items) => (
          <div className="flex flex-col gap-4">
            <List>
              {items.map((entry) => {
                const view = accessLogView(entry, childName, PARENT_TUTORS_PATH)
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
                    <div className="flex flex-wrap items-center justify-between gap-x-3">
                      <p className="m-0 text-body-sm text-ink-muted">{view.timeLabel}</p>
                      {entry.tutorId !== null ? (
                        <ReportButton
                          label={`Report ${entry.tutorName}`}
                          onClick={() => onReport({ tutorId: entry.tutorId as string, tutorName: entry.tutorName })}
                        />
                      ) : null}
                    </div>
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

// ── The screen ─────────────────────────────────────────────────────────────

function AccessBody({ childId, childName }: { childId: string; childName: string }) {
  const report = useCreateTutoringReport()
  const [target, setTarget] = useState<ReportTarget | null>(null)
  const [open, setOpen] = useState(false)

  function askToReport(next: ReportTarget) {
    report.reset()
    setTarget(next)
    setOpen(true)
  }

  return (
    <div className="flex w-full max-w-160 flex-col gap-6">
      <h1 className="m-0 break-words text-display-md text-ink">Who {childName} shares progress with</h1>
      <SharingSection childId={childId} childName={childName} onReport={askToReport} />
      <LogSection childId={childId} childName={childName} onReport={askToReport} />
      {target ? (
        <ReportSheet
          open={open}
          onClose={() => setOpen(false)}
          targetType="tutor_profile"
          targetLabel={target.tutorName}
          onSubmit={({ reason, details }) =>
            report.mutate({ targetType: "tutor_profile", targetId: target.tutorId, reason, details })
          }
          pending={report.isPending}
          error={report.error}
          sent={report.isSuccess}
        />
      ) : null}
    </div>
  )
}

export function ChildTutorAccess() {
  const { childId = "" } = useParams()
  return (
    <ChildScope key={childId} childId={childId} srHeading="Tutor access">
      {(child) => <AccessBody childId={child.childId} childName={child.displayName} />}
    </ChildScope>
  )
}
