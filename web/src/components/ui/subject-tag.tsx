import type { BadgeProps, BadgeTone } from "@/components/ui/badge"
import { Badge } from "@/components/ui/badge"

/*
 * DESIGN.md §3.8: "Semantic, not decorative: a student scanning a dashboard
 * should find Physics by colour before reading. Assign from the pastel set,
 * fixed... New subjects extend this table here first. Never pick a subject
 * colour at a call site." This is that single lookup table. A screen that
 * wants a subject-coloured tag renders `<SubjectTag subject="Physics" />`,
 * never `<Badge tone="lilac">Physics</Badge>` — the second form is exactly
 * the "picked a colour at the call site" pattern the rule forbids, because it
 * gives the next physics tag in the codebase no reason to also be lilac.
 */

const SUBJECT_TONES: Record<string, BadgeTone> = {
  mathematics: "sky",
  physics: "lilac",
  chemistry: "sage",
  biology: "clay",
  english: "amber",
}

/** Fixed per DESIGN.md §3.8. Falls back to `rose` ("Unassigned / other") for
 * any subject not yet in the table above — extend `SUBJECT_TONES`, in this
 * file only, when a new subject needs its own colour. */
export function subjectTone(subject: string): BadgeTone {
  return SUBJECT_TONES[subject.trim().toLowerCase()] ?? "rose"
}

export interface SubjectTagProps extends Omit<BadgeProps, "tone" | "children"> {
  /** Subject name, e.g. "Mathematics", "Physics". Case-insensitive; rendered
   * verbatim as the label so a caller's exact casing/spelling ("Additional
   * Mathematics") still displays correctly even if it doesn't match a table
   * entry and falls back to the "other" colour. */
  subject: string
}

export function SubjectTag({ subject, ...props }: SubjectTagProps) {
  return (
    <Badge tone={subjectTone(subject)} {...props}>
      {subject}
    </Badge>
  )
}
