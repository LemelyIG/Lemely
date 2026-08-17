import { qualificationLevelLabel } from "./qualificationLevels"

/**
 * Compose a subject's primary/secondary display text: the name leads,
 * the qualification level (when known) and the code follow as secondary,
 * muted detail. Every screen that shows a subject renders through this
 * rather than inventing its own primary/secondary split — see the design
 * spec (`docs/superpowers/specs/2026-08-17-subject-name-primary-identifier-design.md`).
 */
export function subjectIdentifier(
  name: string,
  code: string,
  level?: string | null,
): { primary: string; secondary: string } {
  const levelLabel = qualificationLevelLabel(level)
  return {
    primary: name,
    secondary: levelLabel ? `${levelLabel} · ${code}` : code,
  }
}
