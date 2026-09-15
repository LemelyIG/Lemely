/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import {
  Atom,
  BookOpen,
  Flask,
  GraduationCap,
  Leaf,
  MathOperations,
  type Icon,
} from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { toneFill, type BadgeTone } from "@/components/ui/badge"
import { subjectTone } from "@/components/ui/subject-tag"

/*
 * The glyph half of DESIGN.md §3.8's pastel table. `subject-tag.tsx` already
 * fixes subject -> tone; this file fixes tone -> shape, so a subject reads
 * before a student parses the label even in greyscale or for a colour-blind
 * reader — colour alone is never the only signal (§3.6).
 *
 * `student/data.ts` had already grown its own version of this table
 * (`subjectIcon(code)`: Atom for 0625, Calculator for 0580/0606, Books
 * otherwise) because `SubjectRow` carries no icon field and the nav needed
 * one. Picking `Calculator` there and `MathOperations` here is exactly the
 * "the next physics tag in the codebase has no reason to also be lilac"
 * drift subject-tag.tsx's own header warns about — a second table nothing
 * keeps in step with the first. This file is the one lookup; `student/data.ts`
 * stops maintaining its own.
 */

const TONE_GLYPHS: Record<BadgeTone, Icon> = {
  sky: MathOperations,
  lilac: Atom,
  sage: Flask,
  clay: Leaf,
  amber: BookOpen,
  rose: GraduationCap,
  // The four semantic (non-subject) tones have no curriculum meaning; they
  // fall back to the same "unassigned" glyph `rose` already uses so a caller
  // that somehow reaches this table with a status tone still gets a shape,
  // not a blank tile.
  ok: GraduationCap,
  warn: GraduationCap,
  err: GraduationCap,
  info: GraduationCap,
}

/** Subject glyph for a pastel tone. Falls back to `GraduationCap` (the same
 * "unassigned / other" glyph as `rose`) for a tone with no subject affinity. */
export function subjectGlyphFor(tone: BadgeTone): Icon {
  return TONE_GLYPHS[tone] ?? GraduationCap
}

const SIZE_CLASSES = {
  sm: "h-8 w-8",
  md: "h-10 w-10",
} as const

const GLYPH_PX = {
  sm: 16,
  md: 20,
} as const

export interface SubjectGlyphProps {
  /** Subject name (or bare syllabus code — see `subjectTone`'s docstring),
   * resolved to a pastel tone the same way `SubjectTag` does. */
  subject: string
  size?: "sm" | "md"
  className?: string
}

/**
 * A pastel tile carrying one subject's tone and glyph — the tile-shaped
 * sibling to `SubjectTag`'s pill. Used wherever a subject needs to read as a
 * standalone mark (a page header, a sidebar row) rather than inline with its
 * own label text, which is what `SubjectTag` is for.
 *
 * `role="img"` + `aria-label={subject}` on the tile itself, glyph
 * `aria-hidden`: the tile is one accessible object ("Physics"), not an
 * unlabelled decorative icon next to unrelated text — the same shape
 * `ProgressRing` below uses for the same reason.
 */
export function SubjectGlyph({ subject, size = "md", className }: SubjectGlyphProps) {
  const tone = subjectTone(subject)
  const Glyph = subjectGlyphFor(tone)

  return (
    <span
      role="img"
      aria-label={subject}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-md",
        toneFill(tone),
        SIZE_CLASSES[size],
        className,
      )}
    >
      <Glyph size={GLYPH_PX[size]} weight="bold" aria-hidden="true" />
    </span>
  )
}
