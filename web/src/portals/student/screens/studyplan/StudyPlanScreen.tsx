/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V3 */
import { useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate, useParams } from "react-router-dom"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import { QueryState } from "@/components/ui/query-state"
import { useToast } from "@/components/ui/toast"
import { useExamCalendar } from "@/lib/hooks/useAnnouncementApi"
import { useStudentProfile } from "@/lib/hooks/useMeApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import {
  useCompleteStudyPlanSession,
  useMoveStudyPlanSession,
  useRebuildStudyPlans,
  useStudyPlanWeek,
} from "@/lib/hooks/useStudyPlanApi"
import { useXpProfile } from "@/lib/hooks/useXpApi"
import { subjectNameFor } from "@/lib/reference"
import type { StudyPlanOverviewDTO } from "@/lib/studyPlanTypes"
import { BasedOn } from "./BasedOn"
import { COPY, nextExamForSubject } from "./planCopy"
import {
  confirmRebuild,
  dayScrollTarget,
  gateWeek,
  moveBusy,
  moveCallbacks,
  nextWeekCallbacks,
  openSessionNav,
  planListUrl,
  planRoute,
  rebuildFailure,
  retryWeek,
  runMoveAll,
  screenNotices,
  shouldResetRebuild,
} from "./planFlow"
import { planScreen, resolveFilter, type SessionVM } from "./planModel"
import { PlanHeader } from "./PlanHeader"
import { PlanList } from "./PlanList"
import {
  ActionError,
  FirstRun,
  NeedPaper,
  NoSubjects,
  NotInWeekNote,
  NothingScheduled,
  PlanLoadError,
  PlanLoading,
  RebuildingBanner,
  WeekDone,
} from "./PlanStates"
import { SessionPanel, SessionSheet } from "./SessionDetail"
import { useWide } from "./useWide"

/*
 * L9 · the study plan: one week across subjects (mock WA/WM/SS/SD and the
 * states). The screen fetches, routes and runs mutations. `planModel`
 * decides everything shown.
 *
 * URL is state: the filter lives in `:subjectCode` and an open session in
 * `:sessionId`, so a push or inbox link lands on the right sheet (K44) and
 * the back gesture closes the sheet.
 */
export function StudyPlanScreen() {
  // A refetch that fails keeps the week it already has; only a week that never loaded is an error.
  const week = gateWeek(useStudyPlanWeek())
  return (
    // The bottom clearance is the mock's `.sjpad` 100px: the shell's own pad stops short of the tab bar, so the "Built from" line would sit under it.
    <div className="flex flex-col gap-6 max-sidebar:pb-12 md:mx-auto md:w-full md:max-w-[640px] xl:max-w-none">
      {week.status === "error" ? (
        // The load failure is Binny's (PE), so it is drawn here; `QueryState` keeps pending, the loaded week and the empty response.
        <>
          <h1 className="sr-only">{COPY.title}</h1>
          <PlanLoadError onRetry={retryWeek(week)} />
        </>
      ) : (
        <QueryState
          query={week}
          skeleton={<PlanLoading />}
          srHeading={COPY.title}
          error={{ heading: COPY.loadErrorTitle, body: COPY.loadErrorBody }}
        >
          {(overview) => <PlanContent overview={overview} />}
        </QueryState>
      )}
    </div>
  )
}

function PlanContent({ overview }: { overview: StudyPlanOverviewDTO }) {
  const { subjectCode, sessionId } = useParams<{ subjectCode?: string; sessionId?: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const wide = useWide()
  const { toast } = useToast()
  const reference = useReference()
  const profile = useStudentProfile()
  const calendar = useExamCalendar()
  const xp = useXpProfile()
  const complete = useCompleteStudyPlanSession()
  const move = useMoveStudyPlanSession()
  const rebuild = useRebuildStudyPlans()
  const { reset: resetComplete } = complete
  const [confirmCodes, setConfirmCodes] = useState<string[] | null>(null)
  const [nextWeekReady, setNextWeekReady] = useState(false)
  const [missingNote, setMissingNote] = useState(false)
  const [movingAll, setMovingAll] = useState(false)

  const filter = resolveFilter(overview, subjectCode)
  const listUrl = planListUrl(filter)
  const now = useMemo(() => new Date(`${overview.today}T12:00:00`), [overview.today])

  const screen = useMemo(
    () =>
      planScreen({
        overview,
        filter,
        subjectName: (code) => subjectNameFor(reference.data, code),
        targetGrade: (code) => profile.data?.enrolments.find((e) => e.subjectCode === code)?.targetGrade ?? null,
        nextExam: (code) => nextExamForSubject(calendar.data, code, now),
        now,
        xp: xp.data ? { weekXp: xp.data.week.total, streak: xp.data.streak.current } : null,
      }),
    [overview, filter, reference.data, profile.data, calendar.data, xp.data, now],
  )

  const all: SessionVM[] = screen.kind === "plan" || screen.kind === "weekDone" ? screen.all : []
  const fromParam = sessionId ? (all.find((s) => s.id === sessionId) ?? null) : null
  const firstOpenId = screen.kind === "plan" ? screen.body.firstOpenId : null
  // The url names the open session on every width; with none named, the wide panel follows the first open one.
  const selected = wide ? (fromParam ?? all.find((s) => s.id === firstOpenId) ?? null) : null
  const sheetSession = wide ? null : fromParam

  // The url may name a subject or a session this week does not hold: correct it (K18, K24/K25).
  const sessionKnown = fromParam !== null
  useEffect(() => {
    const step = planRoute({ subjectCode, sessionId, filter, sessionKnown })
    if (step.missingNote !== null) setMissingNote(step.missingNote)
    if (step.redirectTo) navigate(step.redirectTo, { replace: true })
  }, [subjectCode, sessionId, filter, sessionKnown, navigate])

  // A fresh session starts with a clean error.
  const activeId = (sheetSession ?? selected)?.id ?? null
  useEffect(() => {
    resetComplete()
  }, [activeId, resetComplete])

  const openSession = (id: string) => {
    const { to, options } = openSessionNav(wide, filter, id)
    navigate(to, options)
  }
  const closeSheet = () => {
    if ((location.state as { fromList?: boolean } | null)?.fromList) navigate(-1)
    else navigate(listUrl, { replace: true })
  }
  const onFilter = (code: string | null) => navigate(planListUrl(code), { replace: true })

  // A rebuild failure belongs to the list it happened on: another subject's list starts clean.
  const { reset: resetRebuild, isError: rebuildFailed } = rebuild
  const previousFilter = useRef(filter)
  useEffect(() => {
    const previous = previousFilter.current
    previousFilter.current = filter
    if (shouldResetRebuild({ previous, current: filter, failed: rebuildFailed })) resetRebuild()
  }, [filter, rebuildFailed, resetRebuild])

  const runMove = (s: SessionVM, date: string) =>
    move.mutate(
      { sessionId: s.id, subjectCode: s.subjectCode, date },
      moveCallbacks({ date, today: overview.today, toast, closeSheet: !wide && sheetSession ? closeSheet : null }),
    )
  const moveToday = (id: string) => {
    const s = all.find((x) => x.id === id)
    if (s) runMove(s, overview.today)
  }
  const moveAllToday = (ids: string[]) =>
    runMoveAll({
      ids,
      moveOne: async (id) => {
        const s = all.find((x) => x.id === id)
        if (s) await move.mutateAsync({ sessionId: s.id, subjectCode: s.subjectCode, date: overview.today })
      },
      setBusy: setMovingAll,
      toast,
    })

  const runRebuild = (codes: string[]) => rebuild.mutate({ subjectCodes: codes })
  const askRebuild = (codes: string[]) => {
    const scope = all.filter((s) => codes.includes(s.subjectCode))
    if (scope.some((s) => s.status === "done")) setConfirmCodes(codes)
    else runRebuild(codes)
  }
  const planNextWeek = (codes: string[]) =>
    rebuild.mutate({ subjectCodes: codes, week: "next" }, nextWeekCallbacks({ setReady: setNextWeekReady, toast }))

  const onDay = (date: string) => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    const { id, opensDone } = dayScrollTarget(all, date)
    if (opensDone) {
      const fold = document.getElementById("plan-done")
      if (fold instanceof HTMLDetailsElement) fold.open = true
    }
    document.getElementById(id)?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" })
  }

  const completeErrorFor = (s: SessionVM | null) =>
    s && complete.isError && complete.variables?.sessionId === s.id ? COPY.completeError : null
  const actionsFor = (s: SessionVM | null) => ({
    completing: !!s && complete.isPending && complete.variables?.sessionId === s.id,
    completeError: completeErrorFor(s),
    movingTo: s && move.isPending && move.variables?.sessionId === s.id ? move.variables.date : null,
    moveBusy: moveBusy(move.isPending, movingAll),
    onStart: (path: string) => navigate(path),
    onComplete: () => s && complete.mutate({ sessionId: s.id, subjectCode: s.subjectCode }),
    onMove: (date: string) => s && runMove(s, date),
  })

  if (screen.kind === "noSubjects") {
    return (
      <>
        <h1 className="sr-only">{COPY.title}</h1>
        <NoSubjects />
      </>
    )
  }

  const rebuilding = rebuild.isPending && rebuild.variables?.week !== "next"
  const rebuildError = rebuildFailure(rebuild)
  const notices = screenNotices({ kind: screen.kind, missingNote, rebuilding, rebuildError })

  return (
    <>
      <PlanHeader header={screen.header} wide={wide} now={now} onFilter={onFilter} />
      {notices.missing ? <NotInWeekNote rebuilt={notices.missingRebuilt} /> : null}
      {notices.rebuilding ? <RebuildingBanner /> : null}
      {notices.actionError ? <ActionError message={notices.actionError} /> : null}

      {screen.kind === "firstRun" ? (
        <FirstRun building={rebuild.isPending} error={rebuildError} onBuild={() => runRebuild(screen.codesToBuild)} />
      ) : null}
      {screen.kind === "needPaper" ? <NeedPaper copy={screen.copy} placementCode={screen.placementCode} /> : null}
      {screen.kind === "nothingScheduled" ? (
        <>
          <NothingScheduled practiceCode={screen.practiceCode} />
          <BasedOn line={screen.basedOn} rebuilding={rebuilding} onRebuild={() => askRebuild(screen.scopeCodes)} />
        </>
      ) : null}
      {screen.kind === "weekDone" ? (
        <WeekDone
          body={screen.body}
          stats={screen.stats}
          practiceCode={screen.practiceCode}
          planning={rebuild.isPending && rebuild.variables?.week === "next"}
          nextWeekReady={nextWeekReady}
          onPlanNextWeek={() => planNextWeek(screen.scopeCodes)}
        />
      ) : null}
      {screen.kind === "plan" ? (
        <div className="xl:grid xl:grid-cols-[minmax(0,1fr)_340px] xl:gap-10">
          <PlanList
            body={screen.body}
            wide={wide}
            selectedId={selected?.id ?? null}
            movingId={movingAll ? "all" : move.isPending ? (move.variables?.sessionId ?? null) : null}
            rebuilding={rebuilding}
            onOpen={openSession}
            onMoveToday={moveToday}
            onMoveAllToday={(ids) => void moveAllToday(ids)}
            onDay={onDay}
            onRebuild={() => askRebuild(screen.scopeCodes)}
            onBuild={(code) => runRebuild([code])}
          />
          {wide ? <SessionPanel session={selected} binnyLine={rebuilding ? null : screen.body.binnyLine} {...actionsFor(selected)} /> : null}
        </div>
      ) : null}
      {screen.kind === "plan" && wide ? (
        <BasedOn line={screen.body.basedOn} rebuilding={rebuilding} onRebuild={() => askRebuild(screen.scopeCodes)} className="pb-5" />
      ) : null}

      <SessionSheet session={sheetSession} onClose={closeSheet} {...actionsFor(sheetSession)} />
      <ConfirmModal
        open={confirmCodes !== null}
        title={COPY.rebuildConfirmTitle}
        consequence={COPY.rebuildConfirmBody}
        destructive={false}
        confirmLabel={COPY.rebuildConfirmCta}
        pendingLabel={COPY.rebuilding}
        cancelLabel={COPY.rebuildKeep}
        pending={rebuild.isPending}
        onConfirm={() => confirmRebuild(confirmCodes, { run: runRebuild, close: () => setConfirmCodes(null) })}
        onCancel={() => setConfirmCodes(null)}
      />
    </>
  )
}
