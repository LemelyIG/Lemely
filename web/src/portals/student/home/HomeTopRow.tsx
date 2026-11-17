import { Link } from "react-router-dom"
import { CaretRight, Fire } from "@phosphor-icons/react"
import { CountdownPill } from "@/components/redesign"
import { cn } from "@/lib/utils"
import { FOCUS, HIT, PRESS } from "./gradeClass"
import { parseDay, type HomeVm } from "./model"

const PILL = "inline-flex min-h-8 items-center gap-1.5 rounded-chip px-[11px] py-1.5 text-[13px] font-semibold"

export function HomeTopRow({
  pill,
  exam,
  examTo,
  localDate,
}: {
  pill: HomeVm["streakPill"]
  exam: HomeVm["exam"]
  examTo: string
  localDate: string
}) {
  return (
    <div className="flex flex-1 items-center gap-2 @[1040px]/home:flex-none @[1040px]/home:gap-2.5">
      <Link
        to={pill.to}
        aria-label={`Streak: ${pill.label}. Open Me`}
        className={cn(
          PILL,
          HIT,
          PRESS,
          FOCUS,
          pill.lit ? "bg-tertiary-container text-on-tertiary-container" : "bg-surface-container-lowest/70 text-on-surface-variant",
        )}
      >
        <Fire size={14} weight={pill.lit ? "fill" : "regular"} aria-hidden="true" />
        {pill.label}
        <CaretRight size={14} className="-ms-0.5 opacity-55" aria-hidden="true" />
      </Link>
      {exam ? (
        <Link
          to={examTo}
          aria-label="Exam countdown. Open your study plan"
          className={cn("inline-flex items-center gap-1 rounded-chip", HIT, PRESS, FOCUS)}
        >
          <CountdownPill examDate={exam.date} now={parseDay(localDate)} />
          <CaretRight size={14} className="-ms-0.5 text-on-surface-variant opacity-55" aria-hidden="true" />
        </Link>
      ) : null}
    </div>
  )
}
