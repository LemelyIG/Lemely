import type { HTMLAttributes } from "react"
import { Fire, Snowflake, Lightning } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { Eyebrow } from "@/components/ui/primitives"

/*
 * C-9 · XP / streak indicator — effort-only motivation display. HARD RULE
 * (MISSION / PRODUCT.md): leaderboards and XP rank effort, never grades —
 * this component has no prop for a mark, grade, or percentage, and callers
 * must never smuggle one in via `sources`/labels.
 *
 * `frozen` swaps the flame glyph for a snowflake (a SHAPE change, not just a
 * color change, per "no meaning by color alone") and mutes the tone, so
 * "streak paused" reads even in greyscale. Numbers render in the mono/
 * metadata face (JetBrains Mono, "reserved for... technical logs" per
 * DESIGN.md) rather than the Instrument Serif hero treatment used for marks/
 * grades — deliberately, so this never visually reads as a mark. See S-31
 * design note: "make it feel like a training log."
 */

export interface XPStreakDaily {
  /** ISO date or any unique label, oldest first. */
  date: string
  status: "active" | "missed" | "frozen" | "future"
}

export interface XPStreakSource {
  label: string
  xp: number
}

export interface XPStreakProps extends HTMLAttributes<HTMLDivElement> {
  variant?: "compact" | "expanded"
  streakDays: number
  /** Streak-freeze is active today — a distinct frost state, not a broken streak. */
  frozen?: boolean
  xpTotal?: number
  level?: number
  weeklyXp?: number
  /** Expanded only: a short calendar strip, oldest → newest. */
  days?: XPStreakDaily[]
  /** Expanded only: "papers corrected", "quizzes", "flashcards", etc. */
  sources?: XPStreakSource[]
  className?: string
}

export function XPStreak({
  variant = "compact",
  streakDays,
  frozen = false,
  xpTotal,
  level,
  weeklyXp,
  days,
  sources,
  className,
  ...props
}: XPStreakProps) {
  if (variant === "expanded") {
    return (
      <div
        className={cn("rounded-lg border border-border bg-surface p-5", className)}
        {...props}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <StreakGlyph frozen={frozen} size={26} />
            <div>
              <div className="font-mono text-3xl font-semibold text-t1">
                {streakDays}
              </div>
              <Eyebrow className="mt-0.5">Day streak</Eyebrow>
            </div>
          </div>
          {typeof level === "number" ? (
            <div className="text-right">
              <Eyebrow>Level</Eyebrow>
              <div className="font-mono text-3xl font-semibold text-t1">{level}</div>
            </div>
          ) : null}
        </div>

        {frozen ? (
          <div className="mt-3 flex items-center gap-1.5 rounded-md bg-surface-2 px-2.5 py-1.5 text-xs text-t2">
            <Snowflake size={12} className="text-t2" />
            Streak freeze active. Today is protected.
          </div>
        ) : null}

        {days && days.length > 0 ? (
          <div className="mt-5 flex items-center gap-2">
            {days.map((d) => (
              <DayDot key={d.date} status={d.status} />
            ))}
          </div>
        ) : null}

        {typeof xpTotal === "number" ? (
          <div className="mt-5 flex items-center gap-2 border-t border-border pt-4">
            <Lightning size={16} weight="fill" className="text-accent" />
            <span className="text-body-lg font-medium text-t1">
              {xpTotal.toLocaleString()} XP
            </span>
            {typeof weeklyXp === "number" ? (
              <span className="text-metadata text-t3">+{weeklyXp} this week</span>
            ) : null}
          </div>
        ) : null}

        {sources && sources.length > 0 ? (
          <div className="mt-4 flex flex-col gap-2">
            {sources.map((s) => (
              <div
                key={s.label}
                className="flex items-center justify-between text-body-md"
              >
                <span className="text-t2">{s.label}</span>
                <span className="text-metadata text-t1">{s.xp} XP</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    )
  }

  // compact — sized for a nav bar / header pill.
  return (
    <div
      className={cn(
        "inline-flex items-center gap-7px rounded-md border border-border bg-surface px-11px py-7px",
        className,
      )}
      {...props}
    >
      <StreakGlyph frozen={frozen} size={14} />
      <span className="text-metadata font-semibold text-t1">{streakDays}</span>
      <span className="text-xs text-t2">{frozen ? "streak frozen" : "day streak"}</span>
      {typeof xpTotal === "number" ? (
        <>
          <span className="h-3 w-px bg-border" />
          <Lightning size={12} weight="fill" className="text-accent" />
          <span className="text-metadata text-t1">{xpTotal.toLocaleString()}</span>
        </>
      ) : null}
    </div>
  )
}

function StreakGlyph({ frozen, size }: { frozen: boolean; size: number }) {
  if (frozen) {
    return (
      <Snowflake
        size={size}
        weight="bold"
        className="text-t2"
        aria-label="Streak frozen"
      />
    )
  }
  return (
    <Fire
      size={size}
      weight="fill"
      className="text-accent"
      aria-label="Streak active"
    />
  )
}

function DayDot({ status }: { status: XPStreakDaily["status"] }) {
  if (status === "active") {
    return (
      <span
        className="h-2.5 w-2.5 rounded-full bg-accent"
        role="img"
        aria-label="Active"
      />
    )
  }
  if (status === "frozen") {
    return (
      <span
        className="h-2.5 w-2.5 rounded-full border-2 border-t3 bg-surface-2"
        role="img"
        aria-label="Frozen"
      />
    )
  }
  if (status === "missed") {
    return (
      <span
        className="h-2.5 w-2.5 rounded-full border border-border"
        role="img"
        aria-label="Missed"
      />
    )
  }
  return (
    <span
      className="h-2.5 w-2.5 rounded-full border border-dashed border-border"
      role="img"
      aria-label="Upcoming"
    />
  )
}
