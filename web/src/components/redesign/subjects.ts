/*
 * Subject dot colours (mock pa.js / sp.js / fc.js `SUBC`: Maths green, Physics blue,
 * Add Maths violet), mapped onto existing tokens only. The dot is decorative; the
 * subject's name always sits beside it (DESIGN.md: subjects are told apart by label).
 * Every token here holds >= 3:1 against the surface in both themes (see rows.test.ts):
 * --md-tertiary (1.8:1 light) and --grade-u (3.0:1 dark, 2.85:1 on container-low) are excluded.
 */
export const SUBJECT_DOT_TOKENS = ["--grade-a", "--md-primary", "--grade-d", "--grade-e", "--grade-b", "--grade-c", "--grade-g", "--md-secondary"] as const

const NAMED: [RegExp, string][] = [
  [/^(additional\s+math(s|ematics)?|add\s+maths|0606)$/, "--grade-d"],
  [/^(math(s|ematics)?|0580|0980)$/, "--grade-a"],
  [/^(physics|0625|0972)$/, "--md-primary"],
  [/^(chemistry|0620|0971)$/, "--grade-e"],
  [/^(biology|0610|0970)$/, "--grade-b"],
]

/** `var(--token)` for a subject name or syllabus code; unknown subjects hash to a stable palette slot. */
export function subjectDotColor(subject: string): string {
  const key = subject.trim().toLowerCase()
  const named = NAMED.find(([pattern]) => pattern.test(key))
  if (named) return `var(${named[1]})`
  let hash = 0
  for (const ch of key) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return `var(${SUBJECT_DOT_TOKENS[hash % SUBJECT_DOT_TOKENS.length]})`
}
