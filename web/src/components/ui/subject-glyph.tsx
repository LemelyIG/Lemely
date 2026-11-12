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

/*
 * A subject's shape. Subjects are not colour-coded in v5 (DESIGN.md), so the
 * glyph is the one thing besides the label that tells them apart, and every
 * subject shares the same fill: `primary-container` with `on-primary-container`.
 *
 * Keyed by lowercase subject name or bare CAIE syllabus code. Which glyph means
 * Physics is a design decision and lives here; what "0625" is called is product
 * data, with its home in `lemely/db/seed.py::DEMO_SUBJECTS`, so names are not
 * duplicated for the codes. Additional Mathematics (0606) shares Mathematics'
 * glyph, and neither is rendered without its own label beside it.
 */

/** The one fill every subject uses. */
export const SUBJECT_FILL = "bg-primary-container text-on-primary-container"

const SUBJECT_GLYPHS: Record<string, Icon> = {
  mathematics: MathOperations,
  "0580": MathOperations,
  "0606": MathOperations,
  physics: Atom,
  "0625": Atom,
  chemistry: Flask,
  biology: Leaf,
  english: BookOpen,
}

/** Glyph for a subject name or syllabus code; `GraduationCap` for any other. */
export function subjectGlyphFor(subject: string): Icon {
  return SUBJECT_GLYPHS[subject.trim().toLowerCase()] ?? GraduationCap
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
  /** Subject name or bare syllabus code, resolved to a glyph by `subjectGlyphFor`. */
  subject: string
  size?: "sm" | "md"
  className?: string
}

/**
 * A tile carrying one subject's glyph on the shared subject fill — the tile-shaped
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
  const Glyph = subjectGlyphFor(subject)

  return (
    <span
      role="img"
      aria-label={subject}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-md",
        SUBJECT_FILL,
        SIZE_CLASSES[size],
        className,
      )}
    >
      <Glyph size={GLYPH_PX[size]} weight="bold" aria-hidden="true" />
    </span>
  )
}
