/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
/*
 * Subject (redesign L2, mock `.impeccable/mocks/student-r2/final.html`).
 * Wired to `GET /student/subject/{code}` via `useSubject(code)`. Thin on
 * purpose: `subject/subjectModel.ts` makes every decision (state, copy, Binny,
 * links, bar heights) and the `subject/*` files draw it. The endpoint's
 * explicit no-history and no-papers responses render the first run (K2).
 *
 * react-query v5 reports `status: "error"` for a failed refetch yet keeps the
 * last good `data`. `hasData` tells the model which of the two failures this is:
 * a failed first load is the error screen with a real retry; a failed refetch
 * over a subject already on screen keeps that body and adds a quiet notice.
 *
 * This screen does not use the shared per-status query wrapper (see its entry
 * on the queryStateGate allowlist): that wrapper renders one treatment per
 * query status, which would replace a readable body with an error panel on a
 * failed refresh and cannot turn a 404 into the first-run screen.
 */
import { useParams, useSearchParams } from "react-router-dom"
import { ApiError } from "@/lib/api"
import { useExamCalendar } from "@/lib/hooks/useAnnouncementApi"
import { useFlashcardDecks } from "@/lib/hooks/useFlashcardApi"
import { useReference, useSubjectName } from "@/lib/hooks/useReferenceApi"
import { useSubject } from "@/lib/hooks/useStudentApi"
import { subjectIdentifier } from "@/lib/subjectIdentifier"
import { SubjectBody } from "./subject/SubjectBody"
import { SubjectError } from "./subject/SubjectError"
import { SubjectFirstRun } from "./subject/SubjectFirstRun"
import { SubjectHeader } from "./subject/SubjectHeader"
import { SubjectLoading } from "./subject/SubjectLoading"
import { SubjectRefreshNotice } from "./subject/SubjectRefreshNotice"
import {
  buildSubjectView,
  links,
  nextExamDate,
  refreshFailed,
  selectScreenState,
  subtitleFor,
  tierLabel,
  type QueryFacts,
} from "./subject/subjectModel"
import { useMinWidth } from "./subject/useMinWidth"
import "./subject/subject.css"

export function Subject() {
  // The only route here is `subject/:code`, which cannot match without a code,
  // so `useSubject`'s `enabled: !!code` never parks this screen at idle.
  const { code = "" } = useParams<{ code: string }>()
  const query = useSubject(code)
  const fallbackName = useSubjectName(code)
  const { data: reference } = useReference()
  const { data: calendar } = useExamCalendar()
  const { data: decks = [] } = useFlashcardDecks(code)
  const [params, setParams] = useSearchParams()
  const wide = useMinWidth(1280)
  const twoCol = useMinWidth(768)
  const now = new Date()

  const catalogue = reference?.subjects.find((s) => s.code === code)
  const name = query.data?.header.name ?? fallbackName
  // Only the subject endpoint's two explicit absence responses supersede cached data.
  const absent = query.error instanceof ApiError && query.error.status === 404 &&
    (query.error.detail === `No history for subject ${code}` || query.error.detail === `No papers for subject ${code}`)
  const facts: QueryFacts = {
    status: query.status,
    errorStatus: absent ? 404 : null,
    paperCount: query.data?.paperHistory.length ?? 0,
    hasData: !absent && query.data !== undefined,
  }
  const state = selectScreenState(facts)
  const examDate = nextExamDate(calendar, code, now)
  const view =
    (state === "full" || state === "sparse") && query.data
      ? buildSubjectView({
          data: query.data,
          catalogue,
          decks,
          examDate,
          now,
          requestedPaper: params.get("paper"),
          mode: state,
        })
      : null

  const { primary, secondary } = subjectIdentifier(
    reference?.qualificationLevels,
    name,
    code,
    query.data?.header.qualificationLevel ?? catalogue?.qualificationLevel,
  )

  const selectPaper = (paperNumber: number) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set("paper", String(paperNumber))
        return next
      },
      { replace: true },
    )

  return (
    <div className="flex flex-col gap-4">
      <SubjectHeader
        title={primary}
        subtitle={subtitleFor(secondary, tierLabel(catalogue, view?.path.selected ?? null))}
        examDate={examDate}
        planTo={links.plan(code)}
        now={now}
      />
      {refreshFailed(facts) ? (
        <SubjectRefreshNotice name={name} pending={query.isFetching} onRetry={() => void query.refetch()} />
      ) : null}
      {state === "loading" ? <SubjectLoading name={name} /> : null}
      {state === "error" ? <SubjectError name={name} onRetry={() => void query.refetch()} /> : null}
      {state === "first-run" ? <SubjectFirstRun code={code} name={name} wide={wide} twoCol={twoCol} /> : null}
      {view ? <SubjectBody view={view} code={code} wide={wide} twoCol={twoCol} onSelectPaper={selectPaper} /> : null}
    </div>
  )
}
