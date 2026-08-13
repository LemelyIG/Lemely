/* Hallmark · pre-emit critique: P4 H4 E4 S5 R5 V3 */
import type { HTMLAttributes } from "react"
import { Fire, Snowflake, Lightning } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { Eyebrow } from "@/components/ui/primitives"
import { CountUp } from "@/components/ui/celebration"

/*
 * C-9 · XP / streak indicator — effort-only motivation display. HARD RULE
 * (MISSION / PRODUCT.md): leaderboards and XP rank effort, never grades —
 * this component has no prop for a mark, grade, or percentage, and callers
 * must never smuggle one in via `sources`/labels.
 *
 * `frozen` swaps the flame glyph for a snowflake (a SHAPE change, not just a
 * color change, per "no meaning by color alone") and mutes the tone, so
 * "streak paused" reads even in greyscale. Numbers render in the mono/
 * metadata face rather than the display face used for marks and grades —
 * deliberately, so this never visually reads as a mark. See S-31 design note:
 * "make it feel like a training log."
 *
 * ── P4.4 ────────────────────────────────────────────────────────────────
 *
 * **This component had no call site anywhere in the product.** It was built in
 * Phase 2 for the gamification surface and the gamification surface, when it
 * arrived, hand-rolled its own cards instead. Same shape as the §8 texture
 * classes surface 3 found unused, and the same resolution: give it the call
 * site it was written for rather than leave a kit component that nothing
 * proves works. `compact` now sits in the student header — see the note there
 * on why that pill was once removed and is honest to restore.
 *
 * Two corrections came with the migration:
 *
 * - **The figures are on the `data-*` rungs now.** They were `font-mono` plus
 *   a size utility, which is audit finding N2: the tabular alignment depended
 *   on JetBrains Mono happening to be fixed-width rather than on
 *   `font-variant-numeric`, and would have broken silently the day the face
 *   changed. Every `text-data-*` rung carries `tabular-nums` by construction.
 * - **`frozen` is a prop with no wire field behind it.** `Streak` carries
 *   `freezesAvailable` (how many the student holds) but nothing that says a
 *   freeze is being spent today, so no caller can currently pass `frozen`
 *   truthfully. The prop stays because the state is real and modelled; it is
 *   noted here so nobody wires it to `freezesAvailable > 0`, which would tell
 *   a student their streak is frozen whenever it is not.
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
  /** Streak-freeze is active today — a distinct frost state, not a broken
   * streak. Nothing on the wire reports this yet; see this file's header. */
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
        className={cn("rounded-lg border border-rule bg-paper-raised p-5", className)}
        {...props}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <StreakGlyph frozen={frozen} size={26} />
            <div>
              <div className="text-data-lg text-ink">{streakDays}</div>
              <Eyebrow className="mt-0.5">Day streak</Eyebrow>
            </div>
          </div>
          {typeof level === "number" ? (
            <div className="text-end">
              <Eyebrow>Level</Eyebrow>
              <div className="text-data-lg text-ink">{level}</div>
            </div>
          ) : null}
        </div>

        {frozen ? (
          <div className="mt-3 flex items-center gap-1.5 rounded-md bg-paper-sunk px-2.5 py-1.5 text-body-sm text-ink-muted">
            <Snowflake size={12} className="text-ink-muted" />
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
          <div className="mt-5 flex items-center gap-2 border-t border-rule pt-4">
            <Lightning size={16} weight="fill" className="text-accent" />
            <span className="text-data-md text-ink">
              {xpTotal.toLocaleString()}
            </span>
            <span className="text-body-md text-ink-muted">XP</span>
            {typeof weeklyXp === "number" ? (
              <span className="text-body-sm text-ink-faint">
                +{weeklyXp} this week
              </span>
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
                <span className="text-ink-muted">{s.label}</span>
                <span className="text-data-sm text-ink">{s.xp} XP</span>
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
        "inline-flex items-center gap-7px rounded-md border border-rule bg-paper-raised px-11px py-7px",
        className,
      )}
      {...props}
    >
      <StreakGlyph frozen={frozen} size={14} />
      {/* Counts up when it grows, which on this pill means the moment a study
          session or a marked paper lands while the student is on another
          screen (§9.3, "XP gained"). No flourish: the header is chrome, and
          confetti in the chrome would fire over whatever the student is
          actually reading. */}
      <span className="text-data-sm text-ink">
        <CountUp value={streakDays} />
      </span>
      <span className="text-body-sm text-ink-muted">
        {frozen ? "streak frozen" : "day streak"}
      </span>
      {typeof xpTotal === "number" ? (
        <>
          <span className="h-3 w-px bg-rule" />
          <Lightning size={12} weight="fill" className="text-accent" />
          <span className="text-data-sm text-ink">
            <CountUp value={xpTotal} />
          </span>
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
        className="text-ink-muted"
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
        className="h-2.5 w-2.5 rounded-full border-2 border-ink-faint bg-paper-sunk"
        role="img"
        aria-label="Frozen"
      />
    )
  }
  if (status === "missed") {
    return (
      <span
        className="h-2.5 w-2.5 rounded-full border border-rule"
        role="img"
        aria-label="Missed"
      />
    )
  }
  return (
    <span
      className="h-2.5 w-2.5 rounded-full border border-dashed border-rule"
      role="img"
      aria-label="Upcoming"
    />
  )
}
