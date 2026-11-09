/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useEffect, useMemo, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ArrowDown,
  ArrowUp,
  CaretLeft,
  CaretRight,
  DownloadSimple,
  MagnifyingGlass,
  WarningCircle,
  X,
} from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { Input } from "@/components/ui/input"
import { Kbd } from "@/components/ui/kbd"
import { Select } from "@/components/ui/select"
import { EmptyState } from "@/components/ui/state-views"
import { QueryState } from "@/components/ui/query-state"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { adminLoadFailureMessage } from "@/lib/adminOutcome"
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import {
  WAITLIST_BOARDS,
  WAITLIST_BOARD_LABELS,
  WAITLIST_LEVELS,
  WAITLIST_LEVEL_LABELS,
  WAITLIST_LIMITS,
  WAITLIST_ROLES,
  WAITLIST_ROLE_LABELS,
  WAITLIST_STATUSES,
  ALL_SUBJECTS,
  examSessionOptions,
  exportWaitlistCsv,
  listWaitlist,
  updateWaitlistApplicant,
  waitlistSubjectLabel,
  type WaitlistApplicant,
  type WaitlistPage,
  type WaitlistQuery,
  type WaitlistSort,
  type WaitlistStatus,
  type WaitlistStatusFilter,
  type WaitlistUpdate,
} from "@/lib/waitlist-api"

/*
 * Platform admin: the waitlist applicant queue.
 *
 * Split into a container (`Waitlist`: server state, mutations, CSV) and a pure view
 * (`WaitlistQueueView`: everything drawn) so the dev preview and the tests can render
 * every state without a backend.
 *
 * Rows are one line each. The table shares the screen with a 380px side panel, so the
 * subject, board and session cells truncate or abbreviate and carry the full text in a
 * `title`; the side panel always has the whole value.
 */

/** Below `lg` the applicant panel is a full-screen overlay; from `lg` it sits beside the table. */
function useWide(): boolean {
  const query = "(min-width: 1024px)"
  const [wide, setWide] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const mq = window.matchMedia(query)
    const on = () => setWide(mq.matches)
    mq.addEventListener("change", on)
    return () => mq.removeEventListener("change", on)
  }, [])
  return wide
}

function PanelHost({ wide, children }: { wide: boolean; children: ReactNode }) {
  // A portal, not `position: fixed` in place: an ancestor with a transform (the screen
  // entrance animation) would otherwise become the overlay's containing block.
  return wide ? children : createPortal(children, document.body)
}

const SHORT_ROLE: Record<WaitlistApplicant["role"], string> = {
  student: "Student",
  teacher: "Teacher",
  parent: "Parent",
  centre_admin: "Centre",
}
const STATUS_TONE = {
  new: "info",
  contacted: "warn",
  invited: "ok",
  declined: "neutral",
} as const

const RANGES = [
  { value: "", label: "Any time", days: 0 },
  { value: "1", label: "Last 24 hours", days: 1 },
  { value: "7", label: "Last 7 days", days: 7 },
  { value: "30", label: "Last 30 days", days: 30 },
] as const

const SESSION_NAMES: Record<string, string> = { mj: "May/June", on: "Oct/Nov" }

/** `2027-mj` to "May/June 2027". Unknown shapes pass through. */
export function sessionLabel(value: string | null): string {
  const m = value?.match(/^(\d{4})-(mj|on)$/)
  return m ? `${SESSION_NAMES[m[2]]} ${m[1]}` : (value ?? "")
}
/** `2027-mj` to "MJ 27", short enough for a narrow column. */
export function sessionShort(value: string | null): string {
  const m = value?.match(/^(\d{4})-(mj|on)$/)
  return m ? `${m[2] === "mj" ? "MJ" : "ON"} ${m[1].slice(2)}` : "-"
}
const BOARD_SHORT: Record<string, string> = { oxford_aqa: "Oxford" }
const boardShort = (b: WaitlistApplicant["examBoards"][number]) => BOARD_SHORT[b] ?? WAITLIST_BOARD_LABELS[b]
const boardsShort = (boards: WaitlistApplicant["examBoards"]) =>
  boards.length === 0
    ? "-"
    : boards.length === 1
      ? boardShort(boards[0])
      : `${boardShort(boards[0])} +${boards.length - 1}`

function subjectsText(a: WaitlistApplicant): string {
  return [...a.subjects.map(waitlistSubjectLabel), ...a.otherSubjects].join(", ")
}
const isoDay = (offsetDays: number) =>
  new Date(Date.now() - offsetDays * 864e5).toISOString().slice(0, 10)
const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" })
const fullDate = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }) + " UTC"

export interface WaitlistQueueViewProps {
  page: WaitlistPage
  query: WaitlistQuery
  /** Merge a change into the query. Anything but `page` resets to page 1. */
  onQueryChange: (patch: Partial<WaitlistQuery>) => void
  selectedId: string | null
  onSelect: (id: string | null) => void
  onUpdate: (id: string, update: WaitlistUpdate) => void
  onExport: () => void
  exporting?: boolean
  /** A failed status/note save or export, shown above the table until dismissed. */
  actionError?: string | null
  onDismissError?: () => void
}

function NoteField({
  applicant,
  onCommit,
}: {
  applicant: WaitlistApplicant
  onCommit: (note: string | null) => void
}) {
  const [draft, setDraft] = useState(applicant.adminNote ?? "")
  // Resync only when a different applicant is shown; typing must never be overwritten.
  useEffect(() => setDraft(applicant.adminNote ?? ""), [applicant.id]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Textarea
      label="Note"
      value={draft}
      rows={3}
      maxLength={WAITLIST_LIMITS.adminNote}
      hint="Saved when you leave the field. Only platform admins see notes."
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        if (draft !== (applicant.adminNote ?? "")) onCommit(draft.trim() ? draft : null)
      }}
    />
  )
}

export function WaitlistQueueView({
  page,
  query,
  onQueryChange,
  selectedId,
  onSelect,
  onUpdate,
  onExport,
  exporting,
  actionError,
  onDismissError,
}: WaitlistQueueViewProps) {
  const wide = useWide()
  const items = useMemo(() => page.items, [page])
  const counts = page.counts
  const [emailDraft, setEmailDraft] = useState(query.q ?? "")
  const [range, setRange] = useState("")
  const sessions = useMemo(() => examSessionOptions(), [])
  const idx = items.findIndex((r) => r.id === selectedId)
  const current = idx >= 0 ? items[idx] : undefined
  const sort: WaitlistSort = query.sort ?? "created_at"
  const order = query.order ?? "desc"
  const status = query.status ?? "all"
  const filtersActive = Boolean(
    query.status || query.q || query.role || query.level || query.subject || query.board || query.session || query.createdFrom || query.emailConfirmed !== undefined,
  )

  useEffect(() => {
    const t = setTimeout(() => {
      if ((query.q ?? "") !== emailDraft.trim()) onQueryChange({ q: emailDraft.trim() || undefined })
    }, 250)
    return () => clearTimeout(t)
  }, [emailDraft]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (/INPUT|TEXTAREA|SELECT/.test(t.tagName) || selectedId === null) return
      if (e.key === "Escape") onSelect(null)
      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault()
        onSelect(items[Math.min(items.length - 1, idx + 1)]?.id ?? null)
      }
      if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault()
        onSelect(items[Math.max(0, idx - 1)]?.id ?? null)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [selectedId, idx, items, onSelect])

  const clear = () => {
    setEmailDraft("")
    setRange("")
    onQueryChange({
      status: undefined, q: undefined, role: undefined, level: undefined, subject: undefined,
      board: undefined, session: undefined, createdFrom: undefined, emailConfirmed: undefined,
    })
  }
  const sortBtn = (key: WaitlistSort, label: string) => (
    <button
      type="button"
      className="inline-flex min-h-8 items-center gap-1 font-[inherit] uppercase tracking-[inherit] text-inherit"
      onClick={() => onQueryChange({ sort: key, order: sort === key && order === "desc" ? "asc" : "desc" })}
    >
      {label}
      {sort === key ? order === "asc" ? <ArrowUp size={12} aria-hidden /> : <ArrowDown size={12} aria-hidden /> : null}
    </button>
  )
  const ariaSort = (k: WaitlistSort) =>
    (sort === k ? (order === "asc" ? "ascending" : "descending") : "none") as "ascending" | "descending" | "none"

  const chips: [WaitlistStatusFilter | "all", string][] = [
    ["all", "All"], ["new", "New"], ["contacted", "Contacted"], ["invited", "Invited"], ["declined", "Declined"], ["partial", "Partial"],
  ]
  const total = page.total
  const pageSize = page.pageSize
  const pageNo = page.page

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1.5">
          <h1 className="text-display-lg text-on-surface">Waitlist</h1>
          <p className="max-w-prose text-body-md text-on-surface-variant">
            Applicants from the landing page, including people who stopped after step 1.
          </p>
        </div>
        <Button
          variant="secondary"
          icon={<DownloadSimple size={18} />}
          disabled={!total || exporting}
          loading={exporting}
          onClick={onExport}
          className="min-h-11"
        >
          Export CSV{filtersActive ? " (filtered)" : ""} · {total}
        </Button>
      </div>

      <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-2">
        {chips.map(([k, label]) => (
          <button
            key={k}
            type="button"
            className="lw-chipcount"
            aria-pressed={status === k}
            onClick={() => onQueryChange({ status: k === "all" ? undefined : (k as WaitlistStatusFilter) })}
            style={k === "partial" && status !== k ? { borderStyle: "dashed" } : undefined}
          >
            {label}
            <b>{counts[k]}</b>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 items-end gap-3 sm:grid-cols-4 2xl:grid-cols-8">
        <Input
          label="Email"
          type="search"
          placeholder="Search email"
          value={emailDraft}
          onChange={(e) => setEmailDraft(e.target.value)}
          leadingIcon={<MagnifyingGlass size={16} aria-hidden />}
          wrapperClassName="col-span-2 sm:col-span-1"
        />
        <Select label="Role" value={query.role ?? ""} onChange={(e) => onQueryChange({ role: (e.target.value || undefined) as WaitlistQuery["role"] })}>
          <option value="">Any</option>
          {WAITLIST_ROLES.map((r) => <option key={r} value={r}>{WAITLIST_ROLE_LABELS[r]}</option>)}
        </Select>
        <Select label="Level" value={query.level ?? ""} onChange={(e) => onQueryChange({ level: (e.target.value || undefined) as WaitlistQuery["level"] })}>
          <option value="">Any</option>
          {WAITLIST_LEVELS.map((l) => <option key={l} value={l}>{WAITLIST_LEVEL_LABELS[l]}</option>)}
        </Select>
        <Select label="Subject" value={query.subject ?? ""} onChange={(e) => onQueryChange({ subject: e.target.value || undefined })}>
          <option value="">Any</option>
          {ALL_SUBJECTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </Select>
        <Select label="Board" value={query.board ?? ""} onChange={(e) => onQueryChange({ board: (e.target.value || undefined) as WaitlistQuery["board"] })}>
          <option value="">Any</option>
          {WAITLIST_BOARDS.map((b) => <option key={b} value={b}>{WAITLIST_BOARD_LABELS[b]}</option>)}
        </Select>
        <Select label="Session" value={query.session ?? ""} onChange={(e) => onQueryChange({ session: e.target.value || undefined })}>
          <option value="">Any</option>
          {sessions.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </Select>
        <Select
          label="Confirmed"
          value={query.emailConfirmed === undefined ? "" : String(query.emailConfirmed)}
          onChange={(e) => onQueryChange({ emailConfirmed: e.target.value === "" ? undefined : e.target.value === "true" })}
        >
          <option value="">Any</option>
          <option value="true">Confirmed</option>
          <option value="false">Unconfirmed</option>
        </Select>
        <Select
          label="Applied"
          value={range}
          onChange={(e) => {
            setRange(e.target.value)
            const days = RANGES.find((r) => r.value === e.target.value)?.days ?? 0
            onQueryChange({ createdFrom: days ? isoDay(days) : undefined })
          }}
        >
          {RANGES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
        </Select>
      </div>

      {actionError ? (
        <p role="alert" className="m-0 flex items-start justify-between gap-3 rounded-xl bg-error-container px-4 py-3 text-body-sm text-on-error-container">
          <span>{actionError}</span>
          {onDismissError ? (
            <button type="button" onClick={onDismissError} className="min-h-11 shrink-0 rounded-lg px-2 font-semibold underline underline-offset-4">
              Dismiss
            </button>
          ) : null}
        </p>
      ) : null}

      <div className={current ? "grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_380px]" : ""}>
        <div className="flex min-w-0 flex-col gap-3">
          {total === 0 && !filtersActive ? (
            <EmptyState
              heading="No applicants yet"
              body="When someone joins from the landing page they appear here, including people who stopped after step 1 (marked Partial). The daily digest email goes out only when there are new ones."
            />
          ) : items.length === 0 ? (
            <div className="flex flex-col items-start gap-3 rounded-lg border border-outline-variant bg-surface-container-lowest p-8">
              <p className="m-0 text-title text-on-surface">No applicants match these filters</p>
              <p className="m-0 text-body-md text-on-surface-variant">Clear a filter to see more of the list.</p>
              <Button variant="secondary" onClick={clear} className="min-h-11">Clear filters</Button>
            </div>
          ) : (
            <>
              <Table density="operate">
                <THead>
                  <TR>
                    <TH className="px-2.5" aria-sort={ariaSort("email")} style={{ minWidth: 184 }}>{sortBtn("email", "Email")}</TH>
                    <TH className="px-2.5" aria-sort={ariaSort("role")} style={{ width: 72 }}>{sortBtn("role", "Role")}</TH>
                    <TH className="px-2.5" style={{ minWidth: 120 }}>Subjects</TH>
                    <TH className="px-2.5" style={{ width: 82 }}>Board</TH>
                    <TH className="px-2.5" aria-sort={ariaSort("exam_session")} style={{ width: 74 }}>{sortBtn("exam_session", "Session")}</TH>
                    <TH className="px-2.5" aria-sort={ariaSort("status")} style={{ width: 104 }}>{sortBtn("status", "Status")}</TH>
                    <TH className="px-2.5" aria-sort={ariaSort("created_at")} style={{ width: 64 }}>{sortBtn("created_at", "Date")}</TH>
                  </TR>
                </THead>
                <TBody>
                  {items.map((r) => (
                    <TR key={r.id} selected={r.id === selectedId} onClick={() => onSelect(r.id)} aria-label={r.email}>
                      <TD className="lw-mono whitespace-nowrap px-2.5 text-[13px]" title={r.emailConfirmed ? r.email : `${r.email} (email not confirmed)`}>
                        {r.email}
                        {r.emailConfirmed ? null : (
                          <span className="ms-1.5 inline-flex align-middle text-on-surface-variant">
                            <WarningCircle size={13} aria-hidden />
                            <span className="sr-only">Unconfirmed</span>
                          </span>
                        )}
                      </TD>
                      <TD className="whitespace-nowrap px-2.5 text-body-sm" title={WAITLIST_ROLE_LABELS[r.role]}>{SHORT_ROLE[r.role]}</TD>
                      <TD className="max-w-0 truncate px-2.5 text-body-sm" title={subjectsText(r)}>
                        {r.partial ? <span className="text-on-surface-variant">Step 1 only</span> : subjectsText(r)}
                      </TD>
                      <TD className="whitespace-nowrap px-2.5 text-body-sm" title={r.examBoards.map((b) => WAITLIST_BOARD_LABELS[b]).join(", ")}>{boardsShort(r.examBoards)}</TD>
                      <TD className="lw-mono whitespace-nowrap px-2.5 text-[13px]" title={sessionLabel(r.examSession)}>{sessionShort(r.examSession)}</TD>
                      <TD className="whitespace-nowrap px-2.5"><Chip tone={STATUS_TONE[r.status]} className={r.id === selectedId ? "ring-1 ring-primary" : undefined}>{r.status}</Chip></TD>
                      <TD className="lw-mono whitespace-nowrap px-2.5 text-[13px]" title={fullDate(r.createdAt)}>{shortDate(r.createdAt)}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
              <div className="flex flex-wrap items-center justify-between gap-2 text-body-sm text-on-surface-variant">
                <span>
                  Showing {(pageNo - 1) * pageSize + 1} to {Math.min(total, pageNo * pageSize)} of {total}. Select a row, then <Kbd>j</Kbd> <Kbd>k</Kbd> move between applicants and <Kbd>Esc</Kbd> closes the panel.
                </span>
                {total > pageSize ? (
                  <span className="flex gap-1">
                    <Button variant="secondary" size="sm" className="min-h-11" disabled={pageNo <= 1} onClick={() => onQueryChange({ page: pageNo - 1 })}>Previous</Button>
                    <Button variant="secondary" size="sm" className="min-h-11" disabled={pageNo * pageSize >= total} onClick={() => onQueryChange({ page: pageNo + 1 })}>Next</Button>
                  </span>
                ) : null}
              </div>
            </>
          )}
        </div>

        {current ? (
          <PanelHost wide={wide}>
          <aside
            aria-label={`Applicant ${current.email}`}
            className="flex flex-col border border-outline-variant bg-surface-container-lowest max-lg:fixed max-lg:inset-0 max-lg:z-modal lg:sticky lg:top-4 lg:max-h-[calc(100dvh-2rem)] lg:rounded-xl"
          >
            <div className="flex items-center justify-between gap-2 border-b border-outline-variant p-3">
              <div className="flex gap-1">
                <Button variant="ghost" aria-label="Previous applicant" className="min-h-11 min-w-11" disabled={idx === 0} onClick={() => onSelect(items[idx - 1].id)}><CaretLeft size={18} /></Button>
                <Button variant="ghost" aria-label="Next applicant" className="min-h-11 min-w-11" disabled={idx === items.length - 1} onClick={() => onSelect(items[idx + 1].id)}><CaretRight size={18} /></Button>
              </div>
              <span className="lw-mono text-[12px] text-on-surface-variant">{idx + 1} of {items.length}</span>
              <Button variant="ghost" aria-label="Close panel" className="min-h-11 min-w-11" onClick={() => onSelect(null)}><X size={18} /></Button>
            </div>
            <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-5">
              <div className="flex flex-col gap-2">
                <h2 className="lw-mono m-0 break-all text-[16px] font-semibold">{current.email}</h2>
                <div className="flex flex-wrap gap-1.5">
                  <Chip tone="accent">{WAITLIST_ROLE_LABELS[current.role]}</Chip>
                  {current.partial ? <Chip tone="neutral">Partial: stopped after step 1</Chip> : null}
                  {current.emailConfirmed ? null : <Chip tone="neutral">Unconfirmed</Chip>}
                </div>
              </div>
              <Select label="Status" value={current.status} onChange={(e) => onUpdate(current.id, { status: e.target.value as WaitlistStatus })}>
                {WAITLIST_STATUSES.map((s) => <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>)}
              </Select>
              <NoteField applicant={current} onCommit={(adminNote) => onUpdate(current.id, { adminNote })} />
              <dl className="m-0 grid grid-cols-[96px_1fr] gap-x-3 gap-y-3 text-body-sm">
                {([
                  ["Levels", current.levels.map((l) => WAITLIST_LEVEL_LABELS[l]).join(", ")],
                  ["Subjects", subjectsText(current)],
                  ["Exam board", current.examBoards.map((b) => WAITLIST_BOARD_LABELS[b]).join(", ")],
                  ["Session", sessionLabel(current.examSession)],
                  ["Centre", current.centreName ?? ""],
                  ["Phone", current.phone ? `${current.phone}${current.phoneHasWhatsapp ? " (WhatsApp)" : ""}` : ""],
                  ["Source", current.utmSource ? `utm_source=${current.utmSource}` : "Direct"],
                  ["Applied", fullDate(current.createdAt)],
                  ["Consent", `"${current.consentText}" Saved ${shortDate(current.consentAt)}.`],
                ] as const).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="lw-label self-start pt-0.5">{k}</dt>
                    <dd className={`m-0 break-words ${k === "Phone" || k === "Applied" ? "lw-mono" : ""} ${v ? "" : "text-on-surface-variant"}`}>{v || "Not provided"}</dd>
                  </div>
                ))}
              </dl>
              <p className="m-0 text-body-sm text-on-surface-variant">Phone numbers are shown to platform admins only and never go in the daily digest.</p>
            </div>
          </aside>
          </PanelHost>
        ) : null}
      </div>
    </div>
  )
}

const KEY = ["admin", "waitlist"] as const

export function Waitlist() {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState<WaitlistQuery>({ sort: "created_at", order: "desc", page: 1, pageSize: 50 })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const result = useQuery({
    queryKey: [...KEY, query],
    queryFn: () => listWaitlist(query),
    placeholderData: keepPreviousData,
  })
  const update = useMutation({
    mutationFn: ({ id, update: u }: { id: string; update: WaitlistUpdate }) => updateWaitlistApplicant(id, u),
    onSuccess: () => {
      setActionError(null)
      return queryClient.invalidateQueries({ queryKey: KEY })
    },
    onError: () => setActionError("Couldn't save that change. The applicant was not updated. Try again."),
  })

  async function exportCsv() {
    setExporting(true)
    try {
      const url = await exportWaitlistCsv(query)
      const a = document.createElement("a")
      a.href = url
      a.download = "lemely-waitlist.csv"
      a.click()
      URL.revokeObjectURL(url)
      setActionError(null)
    } catch {
      setActionError("Couldn't export the CSV. Check your connection and try again.")
    } finally {
      setExporting(false)
    }
  }

  return (
    <QueryState
      query={result}
      skeleton={<ListSkeleton rows={8} />}
      error={{ heading: "We couldn't load the waitlist", body: adminLoadFailureMessage }}
    >
      {(page) => (
        <WaitlistQueueView
          page={page}
          query={query}
          onQueryChange={(patch) => setQuery((q) => ({ ...q, page: 1, ...patch }))}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onUpdate={(id, u) => update.mutate({ id, update: u })}
          onExport={() => void exportCsv()}
          exporting={exporting}
          actionError={actionError}
          onDismissError={() => setActionError(null)}
        />
      )}
    </QueryState>
  )
}
