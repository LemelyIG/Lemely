/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
/*
 * All papers (S-09): every attempt in one subject, filterable by paper, variant, session and date, sortable, with a
 * compare mode for two attempts. Wired to the subject endpoint through `useSubject(code)`, the same query the Subject
 * screen holds, so arriving from it shows the papers at once. Each row opens that attempt's result (S-15).
 *
 * Loading and failure go through the shared query wrapper. Two things it cannot say are decided here and handed to
 * it as a derived query: the endpoint's explicit "no papers yet" 404 is the empty state, not a failure; and
 * react-query v5 reports `error` for a failed refetch yet keeps the last good rows, so those rows stay on screen
 * with a quiet notice (the Subject screen's) instead of an error panel.
 */
import { Camera, ChartBar, Sparkle } from "@phosphor-icons/react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"
import { Walkthrough } from "@/components/redesign"
import { PageHeading } from "@/components/ui/page-heading"
import { QueryState, type QueryStateQuery } from "@/components/ui/query-state"
import { useSubjectName } from "@/lib/hooks/useReferenceApi"
import { useSubject } from "@/lib/hooks/useStudentApi"
import type { PaperHistoryRow } from "@/lib/studentTypes"
import { PapersBody } from "./papers/PapersBody"
import { PapersLoading } from "./papers/PapersLoading"
import { emptyTip, filtersToParams, isAbsentSubject, papersHeading, papersLinks, parseFilters } from "./papers/papersModel"
import { SubjectRefreshNotice } from "./subject/SubjectRefreshNotice"
import { TipSection } from "./subject/TipSection"
import { FIRST_RUN_STEPS } from "./subject/subjectModel"
import "./subject/subject.css"
import "./papers/papers.css"

const ICONS = [Camera, Sparkle, ChartBar]

export function AllPapers() {
  const { code = "" } = useParams<{ code: string }>()
  const query = useSubject(code)
  const fallbackName = useSubjectName(code)
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const now = new Date()
  const name = query.data?.header.name ?? fallbackName
  const absent = isAbsentSubject(query.error, code)
  const stale = query.status === "error" && !absent && query.data !== undefined
  const history = query.data?.paperHistory
  const derived: QueryStateQuery<PaperHistoryRow[]> =
    absent || stale
      ? { status: "success", data: absent ? [] : history, error: null, refetch: query.refetch }
      : { status: query.status, data: history, error: query.error, refetch: query.refetch, fetchStatus: query.fetchStatus }
  const filters = parseFilters(params)
  const subtitle = history && history.length > 0 && !absent ? papersHeading(name, history.length) : name
  return (
    <div className="ap-page">
      <div className="sj-head">
        <div className="sj-head-t">
          <PageHeading repeatsTitle={true} className="sj-title">
            All papers
          </PageHeading>
          {subtitle ? <span className="sj-sub">{subtitle}</span> : null}
        </div>
      </div>
      {stale ? <SubjectRefreshNotice name={name} pending={query.isFetching} onRetry={() => void query.refetch()} /> : null}
      <QueryState
        query={derived}
        skeleton={<PapersLoading name={name} />}
        error={{
          heading: `We couldn’t load ${name} papers`,
          body: "Check your connection, then try again. Your papers are safe.",
          secondaryAction: { label: `Back to ${name}`, onClick: () => navigate(papersLinks.subject(code)) },
        }}
        isEmpty={(rows) => rows.length === 0}
        empty={
          <div className="ap-main">
            <TipSection tip={emptyTip(code, name)} size={72} />
            <Walkthrough steps={FIRST_RUN_STEPS(name).map((s, i) => ({ icon: ICONS[i], title: s.title, body: s.body }))} />
          </div>
        }
      >
        {(rows) => (
          <PapersBody
            history={rows}
            filters={filters}
            onFilters={(next) => setParams(filtersToParams(next), { replace: true })}
            now={now}
          />
        )}
      </QueryState>
    </div>
  )
}
