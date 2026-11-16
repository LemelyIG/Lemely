import { Fragment } from "react"
import { GhostRows, HairRow, HairRows } from "@/components/redesign"
import { cn } from "@/lib/utils"
import { gradeText } from "./gradeClass"
import type { HomeVm } from "./model"
import { MomentRows } from "./MomentRows"
import { homeRoutes } from "./routes"
import { SectionLink } from "./SectionLink"
import { WeekStrip } from "./WeekStrip"

export function HomeBand({
  band,
  week,
  planTo,
  allPapersTo,
  className,
}: {
  band: HomeVm["band"]
  week: HomeVm["week"]
  planTo: string
  allPapersTo: string | null
  className?: string
}) {
  return (
    <section aria-label="This week and your class" className={className}>
      <div className="grid content-start gap-1.5">
        <SectionLink id="home-week" title="This week" to={planTo} />
        <WeekStrip days={week} />
        {band.weekNext.length > 0 ? (
          <p className="mt-1.5 text-[13px] text-on-surface-variant">
            {band.weekNext.map((w, i) => (
              <Fragment key={w.when}>
                {i > 0 ? " · " : null}
                {w.when}: <b className="font-semibold text-on-surface">{w.what}</b>
              </Fragment>
            ))}
          </p>
        ) : null}
      </div>

      <div className="grid content-start gap-1.5">
        <SectionLink id="home-recent" title="Recent papers" to={allPapersTo ?? homeRoutes.scan} />
        {band.recent.length > 0 ? (
          <HairRows aria-label="Recent papers">
            {band.recent.map((p) => (
              <HairRow
                key={p.to}
                to={p.to}
                leading={<b className={cn("w-9 text-center font-display text-[28px] font-extrabold leading-none", gradeText(p.grade))}>{p.grade}</b>}
                title={p.title}
                sub={p.sub}
              />
            ))}
          </HairRows>
        ) : (
          <>
            <GhostRows rows={2} withLeading />
            <p className="text-[13px] text-on-surface-variant">Your marked papers land here.</p>
          </>
        )}
      </div>

      <div className="grid content-start gap-1.5">
        <SectionLink id="home-class" title="From your class" to={homeRoutes.classes} />
        {band.classRows.length > 0 ? (
          <MomentRows rows={band.classRows} />
        ) : (
          <p className="py-2 text-[13px] text-on-surface-variant">Nothing from your class yet.</p>
        )}
      </div>
    </section>
  )
}
