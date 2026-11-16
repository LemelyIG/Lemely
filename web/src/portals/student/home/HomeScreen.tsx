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
    <div className="flex flex-col gap-[22px] pb-24 max-md:-mx-4 max-md:px-5 max-md:pt-3.5 max-md:bg-[linear-gradient(180deg,color-mix(in_oklch,var(--md-primary-container)_45%,var(--md-surface))_0%,var(--md-surface)_46%)] md:pb-8">
      <header className="flex items-center gap-5 xl:pt-2">
        <PageHeading
          repeatsTitle={false}
          className="sr-only xl:not-sr-only xl:flex-1 xl:font-display xl:text-[32px] xl:font-extrabold xl:leading-[1.1] xl:tracking-[-0.03em] xl:text-primary"
        >
          {vm.heading}
        </PageHeading>
        <HomeTopRow pill={vm.streakPill} exam={vm.exam} examTo={vm.today.planTo} localDate={home.localDate} />
      </header>

      <div className="flex flex-col gap-[22px] md:grid md:grid-cols-2 md:items-start md:gap-x-9 md:gap-y-6 xl:grid-cols-[minmax(0,.95fr)_minmax(0,1.1fr)_minmax(0,.95fr)]">
        <section aria-label="Binny" className="flex flex-col gap-[18px] md:pt-2">
          <HomeStage stage={vm.stage} onNotNow={notNow} />
          <MomentRows rows={vm.also.phone} className="md:hidden" />
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
          className="hidden md:col-span-2 md:grid md:grid-cols-3 md:gap-10 md:border-t md:border-outline-variant md:pt-6 xl:col-span-1 xl:grid-cols-1 xl:gap-6 xl:border-s xl:border-t-0 xl:ps-8 xl:pt-4"
        />
      </div>
    </div>
  )
}
