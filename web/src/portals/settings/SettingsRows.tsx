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
 * dialog title is the `<h2>` and the tab heading follows it, so sections step
 * down to `<h3>`. `SettingsHeadingLevel` carries that without every section
 * taking a prop.
 */

const HeadingLevelContext = createContext<2 | 3>(2)

export function SettingsHeadingLevel({ level, children }: { level: 2 | 3; children: ReactNode }) {
  return <HeadingLevelContext.Provider value={level}>{children}</HeadingLevelContext.Provider>
}

export interface SettingsSectionProps {
  title: string
  /** One short sentence under the heading. */
  description?: ReactNode
  /** `danger` sets the section apart for destructive actions only. */
  tone?: "default" | "danger"
  children: ReactNode
  className?: string
}

export function SettingsSection({
  title,
  description,
  tone = "default",
  children,
  className,
}: SettingsSectionProps) {
  const level = useContext(HeadingLevelContext)
  const headingId = useId()
  const Heading = level === 3 ? "h3" : "h2"
  return (
    <section aria-labelledby={headingId} className={cn("flex flex-col gap-3", className)}>
      <div className="flex flex-col gap-1">
        <Heading
          id={headingId}
          className={cn("text-display-xs", tone === "danger" ? "text-error" : "text-on-surface")}
        >
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
export function SettingsCard({
  children,
  tone = "default",
  className,
}: {
  children: ReactNode
  tone?: "default" | "danger"
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex flex-col divide-y rounded-tile border bg-surface-container-lowest",
        tone === "danger"
          ? "divide-outline-variant border-error/40"
          : "divide-outline-variant border-outline-variant",
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
