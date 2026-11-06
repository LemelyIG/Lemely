/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { createContext, useContext, useId, type ReactNode } from "react"
import { cn } from "@/lib/utils"

/*
 * The building blocks every settings section is made of, so all of them read
 * the same way: a section heading with one line of helper text, then a card
 * of rows, each row with its label and description on the left and its
 * control on the right. Status (saving, saved, a failure) sits under the row
 * that produced it, never at the bottom of the section.
 *
 * The heading level is contextual. On the page-based lane the page's own
 * `<h1>` sits above, so sections are `<h2>`; inside the Settings dialog the
 * dialog title is the `<h2>` and the tab heading the `<h3>`, so sections step
 * down to `<h4>`. `SettingsHeadingLevel` carries that without every section
 * taking a prop.
 *
 * No section or card is coloured crimson, destructive ones included: red is
 * for lost marks and genuine errors, never a heading (DESIGN.md, "The Red
 * Means Lost Rule"). A destructive action's danger is carried by the
 * confirmation dialog it opens.
 */

type HeadingLevel = 2 | 3 | 4

const HeadingLevelContext = createContext<HeadingLevel>(2)

const HEADING_TAG = { 2: "h2", 3: "h3", 4: "h4" } as const

export function SettingsHeadingLevel({ level, children }: { level: HeadingLevel; children: ReactNode }) {
  return <HeadingLevelContext.Provider value={level}>{children}</HeadingLevelContext.Provider>
}

export interface SettingsSectionProps {
  title: string
  /** One short sentence under the heading. */
  description?: ReactNode
  children: ReactNode
  className?: string
}

export function SettingsSection({
  title,
  description,
  children,
  className,
}: SettingsSectionProps) {
  const level = useContext(HeadingLevelContext)
  const headingId = useId()
  const Heading = HEADING_TAG[level]
  return (
    <section aria-labelledby={headingId} className={cn("flex flex-col gap-3", className)}>
      <div className="flex flex-col gap-1">
        <Heading id={headingId} className="text-display-xs text-on-surface">
          {title}
        </Heading>
        {description ? (
          <p className="max-w-[65ch] text-body-sm text-on-surface-variant">{description}</p>
        ) : null}
      </div>
      {children}
    </section>
  )
}

/** The card a section's rows sit in. Rows are divided by hairlines rather
 * than each being its own card, so a group reads as one group. */
export function SettingsCard({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "flex flex-col divide-y divide-outline-variant rounded-tile border border-outline-variant bg-surface-container-lowest",
        className,
      )}
    >
      {children}
    </div>
  )
}

export interface SettingsRowProps {
  label: ReactNode
  description?: ReactNode
  /** The control: a button, select, switch group, or a read-only value. */
  control?: ReactNode
  /** A line under the row: save state, a failure, a confirmation. */
  status?: ReactNode
  /** Stack the control under the text at every width (wide controls). */
  stacked?: boolean
  className?: string
}

/** One setting: label and description on the left, control on the right,
 * wrapping to a stack on narrow screens. */
export function SettingsRow({
  label,
  description,
  control,
  status,
  stacked = false,
  className,
}: SettingsRowProps) {
  return (
    <div className={cn("flex flex-col gap-3 px-4 py-4 sm:px-5", className)}>
      <div
        className={cn(
          "flex flex-col gap-3",
          stacked ? null : "sm:flex-row sm:items-center sm:justify-between sm:gap-6",
        )}
      >
        <div className="flex min-w-0 flex-col gap-1">
          <div className="text-label text-on-surface">{label}</div>
          {description ? (
            <div className="max-w-[60ch] text-body-sm text-on-surface-variant">{description}</div>
          ) : null}
        </div>
        {control ? <div className="flex shrink-0 flex-wrap items-center gap-2">{control}</div> : null}
      </div>
      {status}
    </div>
  )
}

/** A row-level status line. `error` is for a save that failed; everything
 * else (saving, saved, a no-op) is neutral. Announced politely. */
export function SettingsStatus({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "error"
  children: ReactNode
}) {
  return (
    <p
      role="status"
      className={cn("text-body-sm", tone === "error" ? "text-error" : "text-on-surface-variant")}
    >
      {children}
    </p>
  )
}
