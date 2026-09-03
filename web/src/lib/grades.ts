/*
 * Rank a grade within a served vocabulary. Lower is better.
 *
 * Replaces six copies of a hardcoded grade-ladder constant that had drifted
 * apart — four sort keys (`Quizzes`, `ClassRoster`, `AtRiskList`, `QuizBuilder`
 * grade radios), the `Grade` union in `lib/types.ts`, and a seventh, wider
 * set in `grade-badge.tsx`.
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
 * Merge two grade sequences into their union, preserving relative order.
 *
 * Both arguments are assumed to be subsequences of the same underlying
 * ladder (true of every vocabulary `/api/reference` serves — Cambridge never
 * reorders grades per subject or tier, it only omits some), so a grade
 * present in both always occupies the same relative position in each. That
 * lets a two-pointer walk decide, at each mismatch, which side's head grade
 * is genuinely missing from the other sequence (and can be emitted now) —
 * the same idea as merging two sorted lists, except the "comparator" is
 * "does the other list contain this element", not a value comparison.
 *
 * This is the piece `widestVocabularyFor`/`widestVocabulary` were missing:
 * picking the single *longest* served array assumes the longest is a
 * superset of every shorter one, which real data disproves — 0580 Core
 * (`C,D,E,F,G,U`) and 0580 Extended (`A*,A,B,C,D,E,U`) are both length-6/7
 * and neither contains the other (Core has F/G that Extended lacks;
 * Extended has A*, A and B that Core lacks). Only a union recovers the full
 * `A*,A,B,C,D,E,F,G,U` ladder for that subject.
 */
function mergeLadders(a: readonly string[], b: readonly string[]): string[] {
  const result: string[] = []
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      result.push(a[i])
      i++
      j++
    } else if (!b.includes(a[i])) {
      result.push(a[i])
      i++
    } else if (!a.includes(b[j])) {
      result.push(b[j])
      j++
    } else {
      // Both heads appear later in the other sequence — a genuine ordering
      // conflict between two served vocabularies, which real Cambridge data
      // should never produce. Emit `a`'s head first rather than stall.
      result.push(a[i])
      i++
    }
  }
  while (i < a.length) result.push(a[i++])
  while (j < b.length) result.push(b[j++])
  return result
}

/** The union of every grade in `vocabularies`, in ladder order, with no
 * duplicates — derived entirely from the served arrays themselves, never a
 * hardcoded grade sequence (Task 16's gate forbids exactly that). */
function unionOfVocabularies(vocabularies: readonly (readonly string[])[]): string[] {
  return vocabularies.reduce<string[]>((acc, grades) => mergeLadders(acc, grades), [])
}

/**
 * Every grade served for one subject, across whichever tiers the catalogue
 * publishes for it, unioned in ladder order.
 *
 * `Quizzes.tsx`, `ClassRoster.tsx` and `QuizBuilder.tsx` need to rank or
 * offer a grade for a subject without knowing which tier it was awarded on
 * (a `QuizSummary`/`StudentRow` carries no tier field), and a tier's own
 * vocabulary can be missing grades another tier of the *same* subject
 * awards — 0580 Core (`C,D,E,F,G,U`) and 0580 Extended (`A*,A,B,C,D,E,U`)
 * are both partial views of one ladder, neither a superset of the other.
 * Unioning every served vocabulary for the subject is what recovers the
 * full `A*,A,B,C,D,E,F,G,U` ladder without inventing it.
 */
export function widestVocabularyFor(
  vocabularies: readonly { subjectCode: string; grades: readonly string[] }[],
  subjectCode: string,
): string[] {
  return unionOfVocabularies(
    vocabularies.filter((v) => v.subjectCode === subjectCode).map((v) => v.grades),
  )
}

/**
 * The union of every grade in any served list of vocabularies, regardless of
 * subject, in ladder order.
 *
 * `AtRiskList.tsx` spans every class a teacher owns, and its DTO carries no
 * subject or tier per row, so there is no `subjectCode` to key
 * `widestVocabularyFor` on. This must be a union for the same reason as
 * above — picking the single longest served array is only accidentally
 * complete (today, 0625 happens to serve the full 9-grade ladder; that is a
 * fact about the current catalogue, not a guarantee) — so it is unioned
 * across every vocabulary the catalogue serves, correct by construction
 * rather than by which subject currently has the most grades.
 */
export function widestVocabulary(
  vocabularies: readonly { grades: readonly string[] }[],
): string[] {
  return unionOfVocabularies(vocabularies.map((v) => v.grades))
}
