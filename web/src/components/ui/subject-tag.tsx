import type { BadgeProps } from "@/components/ui/badge"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { SUBJECT_FILL, subjectGlyphFor } from "@/components/ui/subject-glyph"

/*
 * Subjects are not colour-coded in v5 (DESIGN.md): every subject uses the one
 * `primary-container` / `on-primary-container` pairing, `SUBJECT_FILL`, and is
 * told apart by its label and its glyph (`subjectGlyphFor`), never by a hue.
 * The retired Study Notebook table gave each subject a pastel tone. A screen
 * that wants a subject tag renders `<SubjectTag subject="Physics" />`; it does
 * not pick a fill or a colour at the call site.
 */

export interface SubjectTagProps extends Omit<BadgeProps, "tone" | "children" | "icon"> {
  /** Subject name ("Mathematics") or bare syllabus code ("0625"), rendered
   * verbatim as the label so a caller's exact casing and spelling ("Additional
   * Mathematics") still displays correctly. */
  subject: string
  /** Renders the subject's glyph (`subjectGlyphFor`) before the label: a shape
   * to scan by, since colour no longer tells subjects apart. Off by default:
   * most subject tags sit in dense lists where a glyph on every row would be
   * one more shape to scan past. */
  icon?: boolean
}

export function SubjectTag({ subject, icon, className, ...props }: SubjectTagProps) {
  const Glyph = icon ? subjectGlyphFor(subject) : null
  return (
    <Badge tone="info" icon={Glyph ? <Glyph size={12} /> : undefined} {...props} className={cn(SUBJECT_FILL, className)}>
      {subject}
    </Badge>
  )
}
