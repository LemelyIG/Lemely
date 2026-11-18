/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V4 */
import { useMemo, useState } from "react"
import { PageHeading } from "@/components/ui/page-heading"
import type { StudentHome } from "@/lib/studentHomeTypes"
import { readDismissed, safeLocalStorage, writeDismissed } from "./dismiss"
import { GradeFloor } from "./GradeFloor"
import { HomeBand } from "./HomeBand"
import { HomeFirstRun } from "./HomeFirstRun"
import { HomeStage } from "./HomeStage"
import { HomeTopRow } from "./HomeTopRow"
import { LastPaperRow } from "./LastPaperRow"
import { MomentRows } from "./MomentRows"
import { homeView } from "./model"
import { TodayBlock } from "./TodayBlock"
import { WinBack } from "./WinBack"

export function HomeScreen({ home }: { home: StudentHome }) {
  const [dismissed, setDismissed] = useState(() => readDismissed(safeLocalStorage(), home.localDate))
  const vm = useMemo(() => homeView(home, dismissed), [home, dismissed])

  function notNow() {
    const next = new Set(dismissed).add(vm.stage.key)
    writeDismissed(safeLocalStorage(), home.localDate, next)
    setDismissed(next)
  }

  return (
    <div className="flex flex-col gap-[22px] pb-24 max-md:not-in-data-[platform=ios]:-mx-3.5 max-md:in-data-[platform=ios]:-mx-4 max-md:px-5 max-md:pt-3.5 max-md:bg-[linear-gradient(180deg,color-mix(in_oklch,var(--md-primary-container)_45%,var(--md-surface))_0%,var(--md-surface)_46%)] md:pb-8">
      <header className="flex items-center gap-5 @[1040px]/home:pt-2">
        <PageHeading
          repeatsTitle={false}
          className="sr-only @[1040px]/home:not-sr-only @[1040px]/home:flex-1 @[1040px]/home:font-display @[1040px]/home:text-[32px] @[1040px]/home:font-extrabold @[1040px]/home:leading-[1.1] @[1040px]/home:tracking-[-0.03em] @[1040px]/home:text-primary"
        >
          {vm.heading}
        </PageHeading>
        <HomeTopRow pill={vm.streakPill} exam={vm.exam} examTo={vm.today.planTo} localDate={home.localDate} />
      </header>

      <div className="flex flex-col gap-[22px] md:grid md:grid-cols-2 md:items-start md:gap-x-9 md:gap-y-6 @[1040px]/home:grid-cols-[minmax(0,.95fr)_minmax(0,1.1fr)_minmax(364px,.95fr)]">
        <section aria-label="Binny" className="flex flex-col gap-[18px] md:pt-2">
          <HomeStage stage={vm.stage} onNotNow={notNow} />
          {vm.also.desktop.length > 0 ? (
            <MomentRows rows={vm.also.desktop} className="hidden border-t border-outline-variant pt-1 md:grid" />
          ) : null}
        </section>

        <section aria-label="Today and grades" className="flex flex-col gap-[22px] md:gap-6 md:pt-4">
          <TodayBlock today={vm.today} week={vm.week} />
          {vm.firstRun ? <HomeFirstRun /> : <GradeFloor floor={vm.floor} />}
          {vm.last ? <LastPaperRow last={vm.last} allPapersTo={vm.allPapersTo} className="md:hidden" /> : null}
          {vm.firstRun ? null : <WinBack rows={vm.win} />}
        </section>

        <HomeBand
          band={vm.band}
          week={vm.week}
          planTo={vm.today.planTo}
          allPapersTo={vm.allPapersTo}
          className="hidden md:col-span-2 md:grid md:grid-cols-2 md:gap-x-10 md:gap-y-6 md:border-t md:border-outline-variant md:pt-6 @[1040px]/home:col-span-1 @[1040px]/home:grid-cols-1 @[1040px]/home:gap-6 @[1040px]/home:border-s @[1040px]/home:border-t-0 @[1040px]/home:ps-8 @[1040px]/home:pt-4"
        />
        {/* Mock H6: on the phone the also rows close the page, after the win-back list. */}
        <MomentRows rows={vm.also.phone} className="md:hidden" />
      </div>
    </div>
  )
}
