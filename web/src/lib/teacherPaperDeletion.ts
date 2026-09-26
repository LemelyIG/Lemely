import { deleteCountdown, formatDay } from "@/lib/paperDeletion"

/*
 * Pure state for teacher-console paper deletion and per-class unshare (R2,
 * D9), kept out of the screens for the reason `paperDeletion.ts`'s own
 * header gives: `web/vitest.config.ts` is Node-only, so nothing in this
 * file may reach `document` or `window`.
 *
 * The retention-window arithmetic is identical to the student flow's own
 * (`RETENTION_DAYS` is one constant behind both), so it is re-exported
 * here rather than reimplemented — a second copy of the same "days
 * remaining, floored, never negative" logic is exactly the drift risk the
 * whole feature's pure-helper split exists to avoid.
 */
export { deleteCountdown, formatDay }

/**
 * The recently-deleted row's countdown line. Same wording the student
 * screen renders locally (`RecentlyDeleted.tsx`'s own `countdownLabel`) —
 * kept as a named, exported, tested function here rather than a second
 * inline copy, since the teacher screen has no reason to say this
 * differently from the student one.
 */
export function teacherPaperCountdownLabel(days: number): string {
  if (days <= 0) return "Restore window closed"
  if (days === 1) return "1 day left to restore"
  return `${days} days left to restore`
}

/**
 * The unshare confirmation's consequence line (controller addition, Task
 * 13's review: "Copy must not imply the student loses anything — unshare
 * hides the paper from this class only (D9)"). A pure function so the exact
 * wording is pinned by a test, not just eyeballed once in the component.
 */
export function unshareConsequence(paperLabel: string): string {
  return `${paperLabel} will no longer count in this class's results, averages or review queue. Its place on the roster is untouched, and the student's own copy is unchanged, so you can reshare it here at any time.`
}

/**
 * A class-papers row's own label — "0625 Paper 4 Variant 2, May/June 2024" —
 * carrying the session and year so two sittings of the same paper number
 * (a resit, a specimen re-run) read as distinguishable rows rather than
 * identical-looking duplicates. `sessionYear` is nullable
 * (`ExamMetadata.session_year`), so it is dropped rather than rendered as
 * "undefined" when absent.
 */
export function classPaperLabel(paper: {
  subjectCode: string
  paperNumber: number
  paperVariant: number
  sessionMonth: string
  sessionYear: number | null
}): string {
  const session =
    paper.sessionYear !== null ? `${paper.sessionMonth} ${paper.sessionYear}` : paper.sessionMonth
  return `${paper.subjectCode} Paper ${paper.paperNumber} Variant ${paper.paperVariant}, ${session}`
}

/** The reshare control's own, much smaller, consequence line. */
export function reshareConsequence(paperLabel: string): string {
  return `${paperLabel} will count in this class again.`
}
