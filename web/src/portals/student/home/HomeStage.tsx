import { Link } from "react-router-dom"
import { Binny } from "@/components/redesign"
import { cn } from "@/lib/utils"
import { FOCUS, PRESS } from "./gradeClass"
import type { StageVm } from "./model"

const STAGE_IN = "@keyframes home-stage-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}"

export function HomeStage({ stage, onNotNow }: { stage: StageVm; onNotNow: () => void }) {
  return (
    <div
      key={stage.key}
      aria-live="polite"
      className="relative grid justify-items-center gap-3.5 pb-1 pt-1.5 text-center motion-safe:animate-[home-stage-in_var(--dur-base)_var(--ease-out)]"
    >
      <style>{STAGE_IN}</style>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-[118px] mx-auto h-[30px] w-[210px] rounded-[50%] bg-[radial-gradient(closest-side,color-mix(in_oklch,var(--md-primary-container)_80%,transparent),transparent)] @[1040px]/home:top-[150px] @[1040px]/home:w-[260px]"
      />
      {/* The kit's .rd-binny sets its own display, so the size swap hides wrappers, not the svg. */}
      <div className="relative z-[1] @[1040px]/home:hidden">
        <Binny mood={stage.mood} motion={stage.motion} size={150} aria-hidden />
      </div>
      <div className="relative z-[1] hidden @[1040px]/home:block">
        <Binny mood={stage.mood} motion={stage.motion} size={200} aria-hidden />
      </div>
      <p className="max-w-[26ch] text-balance text-[20px] font-bold leading-[1.38] tracking-[-0.01em] text-on-surface @[1040px]/home:max-w-[22ch] @[1040px]/home:text-[22px]">
        {stage.greeting ? <span className="@[1040px]/home:hidden">{stage.greeting} </span> : null}
        {stage.line}
      </p>
      <div className="grid w-full justify-items-center gap-0.5">
        <Link
          to={stage.action.to}
          data-testid="home-stage-action"
          className={cn(
            "inline-flex min-h-[54px] w-full max-w-[300px] items-center justify-center rounded-inner bg-primary px-7 text-[16px] font-bold text-on-primary",
            "shadow-[0_14px_24px_-16px_color-mix(in_oklch,var(--md-shadow)_70%,transparent)]",
            PRESS,
            FOCUS,
          )}
        >
          {stage.action.label}
        </Link>
        {stage.dismissible ? (
          <button
            type="button"
            onClick={onNotNow}
            title="Binny will suggest something else later"
            className={cn("min-h-11 px-3.5 text-[14px] font-semibold text-on-surface-variant", FOCUS)}
          >
            Not now
          </button>
        ) : null}
      </div>
    </div>
  )
}
