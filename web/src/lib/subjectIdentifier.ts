import { qualificationLevelLabel } from "./qualificationLevels"
import type { LabelledValue } from "@/lib/referenceTypes"

/**
 * Compose a subject's primary/secondary display text: the name leads,
 * the qualification level (when known) and the code follow as secondary,
 * muted detail. Every screen that shows a subject renders through this
 * rather than inventing its own primary/secondary split — see the design
 * spec (`docs/superpowers/specs/2026-08-17-subject-name-primary-identifier-design.md`).
 *
 * When `name === code`, the code is dropped from `secondary` rather than
 * printed a second time. This is the common case, not an edge one: the
 * backend resolves a subject's name as `get_profile(code).name or code`
 * (`lemely/io/det/profiles.py`), and `_REGISTRY` only names three codes
 * (0625, 0580, 0606) — every other code, including every free-text
 * `SchoolClass.subject_code` a teacher can type, falls back to
 * `_DEFAULT_PROFILE`, whose `name` is `""`, collapsing `name` to `code`.
 * Callers must treat an empty `secondary` as renderable-nothing, never a
 * stray separator around it.
 */
export function subjectIdentifier(
  levels: LabelledValue[] | undefined,
  name: string,
  code: string,
  level?: string | null,
): { primary: string; secondary: string } {
  const levelLabel = qualificationLevelLabel(levels, level)
  const parts = [levelLabel, name === code ? null : code].filter(Boolean)
  return {
    primary: name,
    secondary: parts.join(" · "),
  }
}
