/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useNavigate } from "react-router-dom"
import { GoldRing, H2Row, HairRows, TopicChips, topicState } from "@/components/redesign"
import { cn } from "@/lib/utils"
import { BasedOn } from "./BasedOn"
import { TickGlyph } from "./icons"
import { MissedGroup } from "./MissedGroup"
import { COPY } from "./planCopy"
import type { PlanBody, SessionVM } from "./planModel"
import { SessionRow } from "./SessionRow"
import { WeekStrip } from "./WeekStrip"

export interface PlanListProps {
  body: PlanBody
  /** >= 1280px: the side panel is showing, so the selected row is marked and the provenance line moves to it. */
  wide: boolean
  selectedId: string | null
  movingId: string | null
  rebuilding: boolean
  onOpen: (id: string) => void
  onMoveToday: (id: string) => void
  onMoveAllToday: (ids: string[]) => void
  onDay: (date: string) => void
  onRebuild: () => void
  onBuild: (code: string) => void
}

const TODAY_HEADING_ID = "plan-today-heading"
const PENDING_COPY = { notGenerated: "no plan yet", refused: "needs a paper first", build: "Build" } as const

/**
 * The subject a filtered week belongs to. The model only fills `whyTopics` for one subject,
 * and every session in that view is that subject's, so the first one found names it.
 */
function focusSubjectCode(body: PlanBody): string | null {
  const first =
    body.today.sessions[0] ??
    body.missed[0] ??
    body.week.anyDay[0] ??
    body.later[0]?.sessions[0] ??
    body.done.sessions[0]
  return first?.subjectCode ?? null
}

/*
 * The plan body: today first, then what was missed, the any-day week, later days,
 * the done fold, why these topics, and the provenance line. It renders what
 * `planModel` decided and decides nothing; every action goes up through a prop.
 * While the week rebuilds the whole list dims and is marked busy.
 */
export function PlanList(p: PlanListProps) {
  const { body } = p
  const navigate = useNavigate()
  const subjectCode = focusSubjectCode(body)
  const rows = (list: SessionVM[], big: boolean, label: string) => (
    <HairRows aria-label={label}>
      {list.map((s) => (
        <SessionRow key={s.id} session={s} big={big} selected={p.wide && p.selectedId === s.id} onOpen={p.onOpen} />
      ))}
    </HairRows>
  )

  return (
    <div id="plan-list" aria-busy={p.rebuilding || undefined} className={cn("flex flex-col gap-6 xl:gap-[22px]", p.rebuilding && "opacity-50")}>
      {body.subjectTop ? (
        <p className="m-0 flex flex-wrap gap-x-3.5 font-sans text-[13.5px] font-medium text-on-surface-variant [&>span+span]:before:me-3.5 [&>span+span]:before:text-outline [&>span+span]:before:content-['·']">
          {body.subjectTop.targetGrade ? (
            <span>
              <b className="font-sans text-[15px] font-extrabold text-grade-a-star">{body.subjectTop.targetGrade}</b> target
            </span>
          ) : null}
          {body.subjectTop.exam ? <span>{body.subjectTop.exam}</span> : null}
        </p>
      ) : null}

      <section id={`plan-day-${body.today.date}`} aria-labelledby={TODAY_HEADING_ID} className="flex flex-col gap-6 xl:gap-[22px]">
        <div className="flex items-center gap-3">
          <GoldRing parts={body.ring} size={32} label={body.ringLabel} />
          <div>
            <h2 id={TODAY_HEADING_ID} className="m-0 font-sans text-lg font-extrabold tracking-[-0.01em] text-on-surface">
              {body.today.heading}
            </h2>
            <span className="font-sans text-[13px] font-medium text-on-surface-variant">{body.today.sub}</span>
          </div>
        </div>
        {body.today.sessions.length > 0 ? rows(body.today.sessions, true, "Today's sessions") : null}
      </section>

      <MissedGroup
        missed={body.missed}
        movingId={p.movingId}
        onOpen={p.onOpen}
        onMoveToday={p.onMoveToday}
        onMoveAllToday={p.onMoveAllToday}
      />

      {body.week.show ? (
        <section aria-label={COPY.anyDay} className="grid gap-2.5">
          <H2Row title={COPY.anyDay} />
          <WeekStrip days={body.week.days} onDay={p.onDay} />
          {body.week.anyDay.length > 0 ? rows(body.week.anyDay, true, COPY.anyDay) : null}
        </section>
      ) : null}

      {body.later.length > 0 ? (
        <section aria-label={COPY.later} className="mt-1 grid">
          <H2Row title={COPY.later} />
          {body.later.map((g) => (
            <div key={g.date} id={`plan-day-${g.date}`} className="grid">
              <span className="pt-2.5 pb-0.5 font-sans text-[12.5px] font-bold text-on-surface-variant">{g.label}</span>
              {rows(g.sessions, false, g.label)}
            </div>
          ))}
        </section>
      ) : null}

      {body.done.count > 0 ? (
        <details id="plan-done" open={body.done.openByDefault}>
          <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-[10px] font-sans text-sm font-bold text-success-text focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary [&::-webkit-details-marker]:hidden">
            <TickGlyph /> {body.done.title} <span className="font-medium text-on-surface-variant">{body.done.daysLabel}</span>
          </summary>
          {rows(body.done.sessions, false, body.done.title)}
        </details>
      ) : null}

      {body.whyTopics.length > 0 ? (
        <section aria-label={COPY.whyTopics} className="grid gap-2.5">
          <H2Row title={COPY.whyTopics} />
          {/* The kit chip names its state in words as well as colour. The generator prefills the weak topics, so the subject's practice page is the whole destination. */}
          <TopicChips
            topics={body.whyTopics.map((t) => ({ topic: t.topic, state: topicState(t.pct), pct: t.pct }))}
            onSelect={subjectCode ? () => navigate(`/student/practice/${subjectCode}`) : undefined}
          />
          {body.whyHint ? <p className="m-0 font-sans text-sm leading-[1.4] font-medium text-on-surface-variant">{body.whyHint}</p> : null}
        </section>
      ) : null}

      {body.pending.map((s) => (
        <p key={s.subjectCode} className="m-0 flex min-h-11 items-center gap-1.5 font-sans text-[13px] text-on-surface-variant">
          {s.subjectName}: {PENDING_COPY[s.kind === "refused" ? "refused" : "notGenerated"]} ·
          <button
            type="button"
            disabled={p.rebuilding}
            className="min-h-11 rounded-[10px] px-1 font-bold text-primary disabled:opacity-60 focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"
            onClick={() => p.onBuild(s.subjectCode)}
          >
            {s.kind === "refused" ? COPY.rebuild : PENDING_COPY.build}
          </button>
        </p>
      ))}

      {!p.wide ? <BasedOn line={body.basedOn} rebuilding={p.rebuilding} onRebuild={p.onRebuild} /> : null}
    </div>
  )
}
