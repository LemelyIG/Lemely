/*
 * Rank a grade within a served vocabulary. Lower is better.
 *
 * Replaces six copies of a hardcoded grade-ladder constant that had drifted
 * apart — four sort keys (`Quizzes`, `ClassRoster`, `AtRiskList`,
 * `onboardingData`), the grade array in `QuizBuilder`, and the `Grade` union
 * in `lib/types.ts`, with a seventh, wider set in `grade-badge.tsx`.
 *
 * The behavioural fix is the fallback. Every one of those call sites used
 * that ladder's own `.indexOf(grade)`, which returns `-1` for anything it does not
 * know — so a Core-tier F sorted *ahead of* an A*. Core papers genuinely award
 * F and G (234 of 350 boundary records carry them), so that was reachable.
 * Returning `vocabulary.length` puts an unknown grade last, which is the only
 * honest place for a grade the vocabulary cannot rank.
 */
export function gradeRank(
  grade: string | null | undefined,
  vocabulary: readonly string[],
): number {
  if (!grade) return vocabulary.length
  const index = vocabulary.indexOf(grade)
  return index === -1 ? vocabulary.length : index
}

/**
 * The widest vocabulary served for one subject, across whichever tiers the
 * catalogue publishes for it.
 *
 * `Quizzes.tsx`, `ClassRoster.tsx` and `QuizBuilder.tsx` need to rank a
 * grade against a subject without knowing which tier it was awarded on (a
 * `QuizSummary`/`StudentRow` carries no tier field). Every tier of one
 * subject's vocabulary is a subsequence of the same underlying ladder
 * (A*, A, B, C, D, E, F, G, U — Cambridge never reorders it per tier), so
 * picking the longest one served for that subject is a safe superset to rank
 * against, not an invented list — it is one of the arrays `/api/reference`
 * actually returned, just the most inclusive one for this subject.
 */
export function widestVocabularyFor(
  vocabularies: readonly { subjectCode: string; grades: readonly string[] }[],
  subjectCode: string,
): string[] {
  return widestVocabulary(vocabularies.filter((v) => v.subjectCode === subjectCode))
}

/**
 * The longest vocabulary among any served list of them, regardless of
 * subject.
 *
 * `AtRiskList.tsx` spans every class a teacher owns, and its DTO carries no
 * subject or tier per row, so there is no `subjectCode` to key
 * `widestVocabularyFor` on. Every subject's vocabulary is a subsequence of
 * the same Cambridge ladder (A*, A, B, C, D, E, F, G, U — the order never
 * changes per subject, only which rungs are awarded), so the longest served
 * array is a safe cross-subject ranking: it is guaranteed to place every
 * grade any subject can award in its correct relative position, because it
 * is a real vocabulary `/api/reference` returned, not one assembled here.
 */
export function widestVocabulary(
  vocabularies: readonly { grades: readonly string[] }[],
): string[] {
  return vocabularies.reduce<string[]>(
    (widest, v) => (v.grades.length > widest.length ? [...v.grades] : widest),
    [],
  )
}
