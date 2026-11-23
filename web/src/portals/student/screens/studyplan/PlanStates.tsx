/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 */
import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { ArrowsClockwise, Check, Target, Timer } from "@phosphor-icons/react"
import { Binny, Walkthrough, type BinnyMood, type BinnyMotion } from "@/components/redesign"
import { Button, buttonVariants } from "@/components/ui/button"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { COPY, type RefusalCopy } from "./planCopy"
import type { WeekDoneStat } from "./planModel"

const go = "min-h-[50px] w-full max-w-[360px] rounded-[18px] text-[15.5px] font-bold shadow-[0_14px_24px_-16px_oklch(0.3_0.07_242/0.7)]"
/** Once next week is built the button is an answer, not an action: keep it legible, not greyed. */
const settled = "disabled:bg-surface-container-high disabled:text-on-surface-variant disabled:opacity-100 disabled:shadow-none"
const quiet = "inline-flex min-h-11 items-center px-3.5 font-sans text-sm font-semibold text-on-surface-variant"

/** `.err2`: centred Binny, display heading, one line, one action. */
function StateStack({
  mood,
  motion = "idle",
  size = 96,
  title,
  body,
  children,
  className,
}: {
  mood: BinnyMood
  motion?: BinnyMotion
  size?: number
  title: string
  body?: string
  children?: ReactNode
  className?: string
}) {
  return (
    <section className={cn("grid flex-1 content-center justify-items-center gap-3 px-2 py-6 text-center", className)}>
      <Binny mood={mood} size={size} motion={motion} aria-hidden />
      <h2 className="mt-1.5 mb-0 font-display text-[28px] leading-[1.15] font-extrabold tracking-[-0.02em] text-balance text-primary">{title}</h2>
      {body ? <p className="m-0 mb-1.5 max-w-[30ch] font-sans text-[15px] leading-[1.4] font-medium text-on-surface-variant">{body}</p> : null}
      {children}
    </section>
  )
}

/** PL: geometry copied from the mock's skeleton (`sk2c`). */
export function PlanLoading() {
  // One announcement for the whole skeleton, so the blocks stay quiet.
  const block = "bg-surface-container-high"
  return (
    <div role="status" aria-busy="true" aria-label="Loading your week" className="grid gap-3.5">
      <SkeletonBlock announce={false} className={cn(block, "h-10 rounded-xl")} />
      <SkeletonBlock announce={false} className={cn(block, "h-6 w-[180px]")} />
      <SkeletonBlock announce={false} className={cn(block, "h-16 rounded-[14px]")} />
      <SkeletonBlock announce={false} className={cn(block, "h-16 rounded-[14px]")} />
      <SkeletonBlock announce={false} className={cn(block, "h-14 rounded-[14px]")} />
      <SkeletonBlock announce={false} className={cn(block, "h-[52px] rounded-[14px]")} />
      <SkeletonBlock announce={false} className={cn(block, "h-[52px] rounded-[14px]")} />
      <SkeletonBlock announce={false} className={cn(block, "h-[52px] rounded-[14px]")} />
    </div>
  )
}

/** PE. */
export function PlanLoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <StateStack mood="sad" title={COPY.loadErrorTitle} body={COPY.loadErrorBody}>
      <Button variant="primary" className={go} onClick={onRetry}>{COPY.tryAgain}</Button>
      <Link to="/student" className={quiet}>{COPY.backHome}</Link>
    </StateStack>
  )
}

/** Z0 · first run: one action, then the three tips. */
export function FirstRun({ building, error, onBuild }: { building: boolean; error: string | null; onBuild: () => void }) {
  return (
    <>
      <StateStack mood="open" title={COPY.firstRunTitle} body={COPY.firstRunBody} className="pt-5">
        <Button variant="primary" className={go} loading={building} onClick={onBuild}>
          {building ? COPY.building : COPY.firstRunCta}
        </Button>
        {error ? <ActionError message={error} /> : null}
      </StateStack>
      <Walkthrough
        steps={[
          { icon: Timer, title: COPY.walk[0].title, body: COPY.walk[0].body },
          { icon: Target, title: COPY.walk[1].title, body: COPY.walk[1].body },
          { icon: ArrowsClockwise, title: COPY.walk[2].title, body: COPY.walk[2].body },
        ]}
      />
    </>
  )
}

/** Z1 · not enough to plan from (or an unknown refusal, with its own copy). */
export function NeedPaper({ copy, placementCode }: { copy: RefusalCopy; placementCode: string }) {
  return (
    <StateStack mood="thinking" title={copy.heading} body={copy.body} className="pt-5">
      <Link to="/student/correct" className={cn(buttonVariants({ variant: "primary" }), go)}>{COPY.needPaperCta}</Link>
      <Link to={`/student/placement/${placementCode}`} className={quiet}>{COPY.placementCta}</Link>
    </StateStack>
  )
}

/** A real plan with nothing in it (K5). No mock frame. */
export function NothingScheduled({ practiceCode }: { practiceCode: string }) {
  return (
    <StateStack mood="happy" title={COPY.nothingTitle} body={COPY.nothingBody}>
      <Link to={`/student/practice/${practiceCode}`} className={cn(buttonVariants({ variant: "primary" }), go)}>{COPY.nothingCta}</Link>
    </StateStack>
  )
}

/** No enrolments. No mock frame. */
export function NoSubjects() {
  return (
    <StateStack mood="thinking" title={COPY.noSubjectsTitle} body={COPY.noSubjectsBody}>
      <Link to="/student/onboard" className={cn(buttonVariants({ variant: "primary" }), go)}>{COPY.noSubjectsCta}</Link>
    </StateStack>
  )
}

/** PD · week done. */
export function WeekDone({
  body,
  stats,
  practiceCode,
  planning,
  nextWeekReady,
  onPlanNextWeek,
}: {
  body: string
  stats: WeekDoneStat[]
  practiceCode: string
  planning: boolean
  nextWeekReady: boolean
  onPlanNextWeek: () => void
}) {
  return (
    <StateStack mood="happy" motion="hop" size={110} title={COPY.weekDoneTitle} body={body} className="pt-3">
      <div className="grid w-full text-center" style={{ gridTemplateColumns: `repeat(${stats.length}, minmax(0, 1fr))` }}>
        {stats.map((s) => (
          <span key={s.label} className="grid justify-items-center gap-0.5">
            <b className={cn("font-mono text-2xl font-extrabold", s.tone === "ok" ? "text-success-text" : "text-primary")}>{s.value}</b>
            <small className="font-sans text-[12.5px] font-medium text-on-surface-variant">{s.label}</small>
          </span>
        ))}
      </div>
      <Button variant="primary" className={cn(go, settled)} loading={planning} disabled={nextWeekReady} onClick={onPlanNextWeek}>
        {nextWeekReady ? <Check weight="bold" size={18} aria-hidden /> : null}
        {nextWeekReady ? COPY.nextWeekReady : COPY.planNextWeek}
      </Button>
      <Link to={`/student/practice/${practiceCode}`} className={quiet}>{COPY.bonusPractice}</Link>
    </StateStack>
  )
}

/** PR · `.rebuild`. Carries the screen's one Binny while it shows. */
export function RebuildingBanner() {
  return (
    <div role="status" className="flex items-center gap-3 rounded-2xl bg-surface-container-lowest px-3.5 py-3 shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)]">
      <Binny mood="thinking" size={52} motion="idle" aria-hidden />
      <p className="m-0 font-sans text-[14.5px] leading-[1.4] font-medium text-on-surface">
        <b>{COPY.rebuildingTitle}</b>
        <br />
        <span className="text-on-surface-variant">{COPY.rebuildingBody}</span>
      </p>
    </div>
  )
}

/** K25: a deep link to a session this week's plan no longer has. Not a 404. */
export function NotInWeekNote() {
  return (
    <p role="status" className="m-0 rounded-xl bg-surface-container-high px-3 py-2.5 font-sans text-[13.5px] leading-[1.35] font-semibold text-on-surface">
      {COPY.notInWeek}
    </p>
  )
}

/** `.errl`: an action failure under the header (K7). */
export function ActionError({ message }: { message: string }) {
  return (
    <div role="alert" className="w-full rounded-xl bg-error-container px-3 py-2.5 text-start font-sans text-[13.5px] leading-[1.35] font-semibold text-on-error-container">
      {message}
    </div>
  )
}
