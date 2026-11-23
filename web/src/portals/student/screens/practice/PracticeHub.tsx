/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 */
/* L4 · Practice tab root (mock C, practice-hub-final.html). Thin: every decision is in hubModel. */
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { BinnyLine } from "@/components/redesign"
import { PageHeading } from "@/components/ui/page-heading"
import { SetBuilderSheet } from "./builder/SetBuilderSheet"
import { HomeworkRow } from "./hub/HomeworkRow"
import { practiceHubView } from "./hub/hubModel"
import { HubLayout } from "./hub/HubLayout"
import { FirstRun, HubError, HubNotice, HubSkeleton } from "./hub/HubStates"
import { HubTiles } from "./hub/HubTiles"
import { RecentRuns } from "./hub/RecentRuns"
import { usePracticeHubData } from "./hub/usePracticeHubData"
import { useWide } from "./hub/useWide"
import { ScanTip, WinBackList } from "./hub/WinBackList"

export function PracticeHub() {
  const wide = useWide()
  const hub = usePracticeHubData()
  const view = practiceHubView(hub.input)
  const order = hub.builderSubjects.map((s) => s.code)
  // One notice at a time keeps one live region: a failed profile is the more specific news.
  const notice = view.notice ?? (hub.refreshError ? "refresh" : null)

  const { subjectCode } = useParams<{ subjectCode?: string }>()
  const [search] = useSearchParams()
  const navigate = useNavigate()
  const location = useLocation()
  // Opened from the hub, Close pops back to it; a deep link has nothing to pop to, so it replaces.
  const closeBuilder = () => {
    if ((location.state as { fromHub?: boolean } | null)?.fromHub) navigate(-1)
    else navigate("/student/practice", { replace: true })
  }

  // Binny mounts once: the top slot on desktop, after the tiles below it. The first run renders its own.
  const binny =
    view.binny && view.state !== "firstTime" ? (
      <BinnyLine mood={view.binny.mood} line={view.binny.line} size={48} motion="idle" />
    ) : null

  return (
    <div className="flex flex-col gap-4 pb-6">
      <header className="grid gap-0.5">
        <PageHeading
          repeatsTitle
          className="font-display text-[28px] font-extrabold leading-[1.1] tracking-[-0.03em] text-primary lg:text-[32px]"
        >
          Practice
        </PageHeading>
        {view.subtitle ? <p className="text-[13px] font-medium text-on-surface-variant">{view.subtitle}</p> : null}
      </header>

      {view.state === "loading" ? (
        <HubSkeleton />
      ) : (
        <HubLayout
          homework={view.homework ? <HomeworkRow homework={view.homework} /> : null}
          binnyTop={wide ? binny : null}
          binnyAfterTiles={wide ? null : binny}
          tiles={<HubTiles tiles={view.tiles} />}
          middle={
            view.state === "error" && view.errorKind ? (
              <HubError
                kind={view.errorKind}
                tilesWork={view.tiles.some((t) => t.key === "set" && !t.disabled)}
                onRetry={hub.refetchAll}
                retrying={hub.refetching}
              />
            ) : (
              <>
                {notice ? <HubNotice kind={notice} onRetry={hub.refetchAll} retrying={hub.refetching} /> : null}
                {view.state === "firstTime" && view.binny ? <FirstRun line={view.binny.line} /> : null}
              </>
            )
          }
          win={
            view.winBack.length > 0 || view.showScanTip ? (
              <>
                <WinBackList rows={view.winBack} more={view.winBackMore} subjectOrder={order} />
                {view.showScanTip ? <ScanTip /> : null}
              </>
            ) : null
          }
          recent={view.recent.length > 0 ? <RecentRuns rows={view.recent} more={view.recentMore} subjectOrder={order} /> : null}
        />
      )}

      {subjectCode ? (
        <SetBuilderSheet
          key={subjectCode}
          subjects={hub.builderSubjects}
          initialSubject={subjectCode}
          focusTopic={search.get("topic")}
          onClose={closeBuilder}
        />
      ) : null}
    </div>
  )
}
