# Stale "needs review" flag after a settled self-review

## Shape chosen, and why

`review_reason` and `needs_teacher_review` stay untouched — they are the marker's
record and were never ours to rewrite. Instead, `SelfReviewService.list_questions`
now also asks the queue itself: whether an **open `ReviewQueueItem` exists for
that question result, right now**. That's a new field, `pending_teacher: bool`,
on `AttemptQuestion`, computed in one batch query (mirroring the existing
`group_flags` batch pattern in the same method — no N+1 reintroduced, and the
`test_list_questions_cost_does_not_grow_with_the_number_of_questions` bound of
`<=5` queries for 12 questions still holds at 4).

It rides the wire as `QuestionResultDTO.pendingTeacher: bool | None = None`,
defaulting to `None` everywhere except the self-review list route, which is the
only call site with a queue to ask. Every other producer of this DTO (the live
`/student/correct` frame, the teacher console) leaves it unset, so their
behaviour is unchanged.

On the frontend, `ConfidenceInput` gained the matching optional field.
`confidenceTierFor` checks it first: `pendingTeacher === false` forces the
`"confident"` tier outright, ahead of `reviewReason`. `undefined` (every other
source) falls through to the old logic exactly as before.  `isFlagged`
(`questionFilter.ts`) got the same short-circuit, so the Flagged tab and its
count agree too — not just the chip and the summary banner the screenshot
showed.

I mapped "settled" straight to `"confident"` rather than to a raw
confidence-score bucket (which would still have shown `"uncertain"` and still
counted in the "waiting for your teacher" banner, since `ConfidenceIndicatorSummary`
treats `uncertain` and `needs-review` as one `flagged` bucket). "Confident" here
reads as "nothing pending for a teacher", which is what the screen is actually
claiming — and matches D4's own reasoning for auto-resolving the row on every
settled pass, not only one that moved marks.

## RED transcripts

**Backend** (`tests/test_self_review_repo.py::test_list_questions_pending_teacher_drops_to_false_once_the_self_mark_settles_the_row`),
run against the pre-fix `self_review_repo.py` (temporarily set aside via a
tagged `git stash`, applied back and dropped afterward — never popped):

```
AttributeError: 'AttemptQuestion' object has no attribute 'pending_teacher'
tests/test_self_review_repo.py:1932: AttributeError
FAILED tests/test_self_review_repo.py::test_list_questions_pending_teacher_drops_to_false_once_the_self_mark_settles_the_row
```

**Frontend** (`web/tests/unit/markingConfidence.test.ts`,
`web/tests/unit/questionFilter.test.ts`), same technique against the pre-fix
`markingConfidence.ts`/`questionFilter.ts`:

```
FAIL  tests/unit/markingConfidence.test.ts > confidenceTierFor > stale-flag defect (S2 review): a settled self-review beats a frozen reviewReason
AssertionError: expected 'needs-review' to be 'confident'

FAIL  tests/unit/questionFilter.test.ts > isFlagged > stale-flag defect (S2 review): false once pendingTeacher says the queue closed
AssertionError: expected true to be false

Test Files  2 failed (2)
     Tests  2 failed | 17 passed (19)
```

Both restored (fix reapplied, stash dropped) and reran green — see below.

## Live-correction path (`/student/correct`)

Checked, not assumed: `routers/student.py:1195` builds the completion frame's
questions through `lemely.web.schemas.question_to_dto`, a different converter
from the self-review router's own `_question_dto`. `question_to_dto` never
sets `pendingTeacher`, so it stays `None` on that frame and
`confidenceTierFor`/`isFlagged` fall through to their pre-existing logic —
unchanged, and correct, since no queue exists yet at correction time. The
panel's own `invalidateQueries({ queryKey: attemptQuestionsKey(attemptId) })`
on a successful submit (`web/src/lib/hooks/useSelfReviewApi.ts:117`) is what
moves a corrected-state row from the live/no-queue path onto the
`GET /student/attempts/{id}/questions` route that *can* compute this — so the
settled state is reachable in practice, not just in theory.

## What I left alone

- `review_reason` / `needs_teacher_review` columns: untouched, as instructed.
- The `RevealedSelfReview.pending_teacher` field (self-review's own GET/POST
  response) already existed and covers a narrower case (`student_evidence_unjudged`
  only); I didn't touch it or its `_has_open_unjudged_row` helper — the new
  `list_questions` query checks *any* open reason, which is the correct scope
  for "is a teacher going to look at this question on the result screen",
  a different question from "does the reveal itself still say pending".

## Verification run (post-fix)

- `pytest tests/test_self_review_repo.py tests/test_student_self_review_web.py tests/test_web_app.py --no-cov`: 112 passed.
- `npx vitest run tests/unit/markingConfidence.test.ts tests/unit/questionFilter.test.ts tests/unit/selfReviewWiring.test.ts`: 36 passed.
- `npm run typecheck`, `npm run lint`, `npm run check:copy`: all pass (lint warnings are pre-existing `only-export-components` notices, unrelated to this change).
- `pre-commit run --all-files`: all hooks pass (ruff, ruff-format, mypy, import-linter).
- `git diff | grep '^+' | grep -c ';$'` on every touched frontend file: `0`.
