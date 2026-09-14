import type { BadgeProps, BadgeTone } from "@/components/ui/badge"
import { Badge } from "@/components/ui/badge"
import { subjectGlyphFor } from "@/components/ui/subject-glyph"

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

/**
 * CAIE syllabus code to the same tones, for the surfaces whose data carries a
 * code rather than a name.
 *
 * The student Overview is the case that forced this: `SubjectRowDTO.name`
 * echoes the code ("0625"), because a `PaperRecord` carries no human subject
 * name, so `subjectTone(row.name)` fell through to `rose` for *every* subject
 * and §3.8's whole premise — "a student scanning a dashboard should find
 * Physics by colour before reading" — quietly produced one colour for
 * everything.
 *
 * Deliberately a code-to-*tone* table and not a code-to-*name* one. Which
 * pastel means Physics is a design decision and belongs in this file; what
 * "0625" is called is product data, and it already has an authoritative home
 * in `lemely/db/seed.py::DEMO_SUBJECTS`. Duplicating the names here would
 * create a second source of truth for them that nothing keeps in step.
 *
 * The three codes are the ones the corpus, the accuracy harness and
 * `lemely.io.det.profiles.SUBJECT_PROFILES` all agree the build supports. A
 * fourth would be a claim of support nothing else backs.
 */
const SUBJECT_CODE_TONES: Record<string, BadgeTone> = {
  "0580": "sky", // Mathematics
  // Additional Mathematics. Shares Mathematics' tone; see the note below.
  "0606": "sky",
  "0625": "lilac", // Physics
}

/*
 * 0580 and 0606 share `sky` on purpose, and it is the one judgement call in
 * the table. DESIGN.md §3.8 allocates all six pastels — sky, lilac, sage,
 * clay, amber, and rose as "Unassigned / other" — so a seventh subject has
 * nowhere to go without either spending the "other" slot on a supported
 * subject or taking a colour that already means Chemistry or Biology to
 * someone. Additional Mathematics reading as the same family as Mathematics
 * is a much smaller cost than Additional Mathematics reading as Chemistry,
 * and neither code is ever rendered without its own label beside it. If a
 * student ever sits both and the collision bites, the fix is to extend
 * DESIGN.md §3.8's table first, then this one.
 */

/** Fixed per DESIGN.md §3.8. Falls back to `rose` ("Unassigned / other") for
 * any subject not yet in the table above — extend `SUBJECT_TONES`, in this
 * file only, when a new subject needs its own colour. */
export function subjectTone(subject: string): BadgeTone {
  const key = subject.trim().toLowerCase()
  return SUBJECT_TONES[key] ?? SUBJECT_CODE_TONES[key] ?? "rose"
}

/** Tone for a bare syllabus code ("0625"). Same table, same fallback. */
export function subjectToneForCode(code: string): BadgeTone {
  return SUBJECT_CODE_TONES[code.trim()] ?? "rose"
}

export interface SubjectTagProps extends Omit<BadgeProps, "tone" | "children" | "icon"> {
  /** Subject name, e.g. "Mathematics", "Physics". Case-insensitive; rendered
   * verbatim as the label so a caller's exact casing/spelling ("Additional
   * Mathematics") still displays correctly even if it doesn't match a table
   * entry and falls back to the "other" colour. */
  subject: string
  /** Renders the subject's glyph (`subjectGlyphFor`, `subject-glyph.tsx`)
   * before the label — the same second, faster-scanning signal `Badge.icon`
   * documents for its semantic tones, here fixed to the subject's own tone
   * rather than left for the caller to pick. Off by default: most subject
   * tags sit in dense lists (a table cell, a filter row) where a tag's own
   * pastel fill is already the identifying signal, and a glyph on every row
   * would be one more shape to scan past rather than a second signal. */
  icon?: boolean
}

export function SubjectTag({ subject, icon, ...props }: SubjectTagProps) {
  const tone = subjectTone(subject)
  const Glyph = icon ? subjectGlyphFor(tone) : null
  return (
    <Badge tone={tone} icon={Glyph ? <Glyph size={12} /> : undefined} {...props}>
      {subject}
    </Badge>
  )
}
