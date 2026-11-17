/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useMemo } from "react"
import { Snowflake } from "@phosphor-icons/react"
import { Celebrate, CountUp, MilestoneSticker } from "@/components/ui/celebration"
import { Chip } from "@/components/ui/chip"
import { BarChart } from "@/components/ui/lazy-chart"
import { Meter } from "@/components/ui/primitives"
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet"
import type { XpProfile } from "@/lib/xpTypes"
import { fillCalendar, sourceLabel } from "./meModel"

function formatDay(day: string): string {
  return new Date(`${day}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" })
}

export function ProgressSheet({ open, onOpenChange, xp }: { open: boolean; onOpenChange: (open: boolean) => void; xp: XpProfile | undefined }) {
  const days = useMemo(() => (xp ? fillCalendar(xp) : []), [xp])
  const data = useMemo(() => days.map((d) => ({ label: formatDay(d.day), value: d.xp })), [days])
  if (!xp) return null
  const { current, longest, freezesAvailable, lastActiveOn } = xp.streak
  const peak = Math.max(1, ...xp.week.bySource.map((s) => s.xp))
  const total = days.reduce((sum, d) => sum + d.xp, 0)

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="adaptive"
        className="flex flex-col gap-6 p-6"
      >
        <SheetTitle className="text-display-md">Your progress</SheetTitle>
        <SheetDescription>Everything here measures work done, never how well you did it.</SheetDescription>

        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div role="group" aria-label="Total XP">
            <span className="text-[13px] text-on-surface-variant">Total XP</span>
            <Celebrate value={xp.totalXp} className="block font-mono text-[30px] font-extrabold text-on-surface">
              <CountUp value={xp.totalXp} />
            </Celebrate>
          </div>
          <MilestoneSticker streakDays={current} className="text-[12px]" />
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone="neutral" className="text-[12px]">Longest {longest}</Chip>
            {freezesAvailable > 0 ? (
              <Chip tone="accent" className="text-[12px]">
                <Snowflake size={12} weight="bold" aria-hidden="true" />
                {freezesAvailable} freeze{freezesAvailable === 1 ? "" : "s"} saved
              </Chip>
            ) : null}
          </div>
          <p className="text-body-sm text-on-surface-variant">
            {lastActiveOn === null ? "Your streak starts the first day you earn XP." : `Last earned XP on ${formatDay(lastActiveOn)}.`}
            {freezesAvailable > 0 ? " A freeze covers a day you miss, automatically." : ""}
          </p>
        </div>

        <section aria-labelledby="progress-week" className="flex flex-col gap-2.5">
          <h3 id="progress-week" className="text-[18px] font-extrabold">This week</h3>
          {xp.week.bySource.map((s) => (
            <div key={s.source} className="flex items-center gap-3">
              <span className="w-32 flex-none text-[15px] text-on-surface-variant">{sourceLabel(s.source)}</span>
              <span className="min-w-0 flex-1">
                <Meter value={(s.xp / peak) * 100} label={`${sourceLabel(s.source)}: ${s.xp} XP this week`} />
              </span>
              <span className="w-16 flex-none text-end font-mono text-[15px] text-on-surface">
                {s.xp}
                <span className="ms-1 font-sans text-[13px] text-on-surface-variant">XP</span>
              </span>
            </div>
          ))}
        </section>

        <section aria-labelledby="progress-calendar" className="flex flex-col gap-2">
          <h3 id="progress-calendar" className="text-[18px] font-extrabold">Last four weeks</h3>
          <BarChart
            data={data}
            height={180}
            tickEvery={9}
            tickFontSize={12}
            axisLeftLegend="XP"
            formatValue={(v) => String(Math.round(v))}
            tooltipDetail={(point) => (point.value === 0 ? "No XP earned" : null)}
            ariaLabel="XP earned per day over the last four weeks"
          />
          <p className="text-body-sm text-on-surface-variant">
            {total === 0 ? "The first day you earn XP is the first bar here." : `${formatDay(xp.calendarStart)} to ${formatDay(xp.calendarEnd)}.`}
          </p>
        </section>
      </SheetContent>
    </Sheet>
  )
}
