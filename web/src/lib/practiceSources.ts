/*
 * Task 8 (C3c) · `content-practice-source-filter-dead-in-ui`. Mirrors
 * `lemely/db/models/enums.py`'s `QuestionSource` — pinned verbatim by
 * `practiceSources.test.ts`, the same cross-language technique
 * `design-tokens.test.ts` uses for `index.css` — plus an "All sources"
 * `null` option, `PracticeFilterSet.source`'s own "no filter on this
 * dimension" value (`practiceTypes.ts`).
 */

export const PRACTICE_SOURCES: readonly { value: string | null; label: string }[] = [
  { value: null, label: "All sources" },
  { value: "past_paper", label: "Past papers" },
  { value: "teacher_upload", label: "Your marked papers" },
  { value: "generated", label: "Lemely's practice bank" },
]
