# Student Self-Review of Flagged Questions — Design Spec

Date: 2026-09-17 · Status: draft for review · Spec 2 of 2. **Depends on
`2026-09-17-per-question-marking-detail-design.md`**, which creates every table
and column this spec writes to. Storage is implemented first; this spec adds no
migration.

## Context

A student who has had a paper marked can see their per-question results on
`web/src/portals/student/screens/PaperResult.tsx`, which already carries
All / Lost / **Flagged** tabs with
per-question `feedback`, `reviewReason` and a confidence tier. What they cannot
do is engage with a mark — the screen is read-only, and "flagged" today means
"a teacher should look at this," routed to `ReviewQueueItem`
(`lemely/db/models/ops.py:26`).

This spec makes flagged questions something the student works through: they mark
their own answer against the mark scheme first, then the marker's verdict is
revealed and disagreements are surfaced.

## Decisions

**D1 — Self-mark, then reveal.** The student commits to a verdict per mark point
before seeing the marker's. Considered and rejected: a read-only breakdown
(nothing to disagree with), a dispute button (invites gaming and adds a teacher
step), and re-attempting the question (needs an answer-entry surface and a
single-question marking path — a much larger build).

**D2 — On a low-confidence flagged point, the student is right.** Low confidence
is the marker stating it is unsure. Deferring to the student there is the whole
premise of the feature. Evidence is optional in this case.

**D3 — Elsewhere, evidence unlocks the mark, judged leniently.** On a point the
marker was confident about, a self-mark alone changes nothing. The student may
still push back, but must write something, and a lenient judge decides.

**D4 — The review-queue row auto-resolves.** The point of deferring to the
student is that a teacher no longer has to look. The row closes rather than
staying open, using the columns `ReviewQueueItem` already has: `resolved_by` set
to the student's own `users.id`, `resolved_at` stamped, `resolution_note`
recording that it was a self-mark. No new column. Whether a resolution came from
a teacher or a student is read from the `question_result_revisions` row's
`source`, which is the one place that provenance lives.

**D5 — One accessor, one number. Self-marks reach every surface.** Recorded as
an explicit, accepted trade-off, not an oversight. See "Blast radius" below.

**D6 — Self-marking downward is honoured.** A student who says they did *not*
earn a point the marker awarded has that applied on the same terms. A rule that
only ever moves marks up is a grade-inflation mechanism wearing a pedagogy
costume.

## Flow

States per question: `not_started` → `self_marking` → `revealed` → `settled`.

**The reveal is server-enforced, not client-hidden.**
`GET /api/student/attempts/{attemptId}/questions/{questionResultId}/self-review`
returns `mark_point_id`, `ordinal`, `mark_type`, `tariff` and `point_text` per
point, and **omits `awarded` entirely** while the state is `not_started` or
`self_marking`. If the verdict were in the payload and merely hidden in the UI,
the entire exercise is defeated by opening devtools. The verdict arrives only in
the response to the submission.

**Submission.** `POST` to the same path, carrying a verdict for **every** point
in the question plus an optional `evidence` string per point. Partial
submissions are rejected: self-marking three of five points, revealing, then
marking the rest would let a student calibrate against the answer.

**One pass per question.** Once revealed, the self-mark is recorded and cannot
be redone — otherwise a student iterates until they find the awarding
combination. `student_selfmarked_at` records that the pass happened.

## Authority

Per point, where the student says earned and the marker said missed:

| Question's flag state | Mark changes? | Evidence |
| --- | --- | --- |
| `ReviewReason.low_confidence` | yes, student wins (D2) | optional |
| not flagged low-confidence | only if the judge accepts (D3) | required |

"Low confidence" means `confidence_score < REVIEW_CONFIDENCE_THRESHOLD` (0.90,
`lemely/core/schemas.py:47`) or the marking-side structural signal — exactly the
condition `_persist` already uses to open a `low_confidence` queue row.

**Integrity flags grant no authority.** A question flagged only
`plagiarism_flag` or `ai_detection_flag` is not low-confidence. Those are a
separate `ReviewReason`, and QUALITY-BAR.md is explicit that integrity flags are
teacher-only and must never read as an accusation on a student-facing screen. So
such a question behaves as "not flagged" for authority purposes and the student
is never told why. The `marking_flagged` computation already in `_persist`
(`lemely/db/attempt_repo.py:308`) draws exactly this line; the self-review path
reuses it rather than re-deriving it.

**Agreement does nothing** beyond confirming it to the student.

## The lenient judge

One bounded call per challenged point. Input: `point_text`, `mark_type`,
`tariff`, the student's transcribed answer, the marker's rationale for missing
the point, and the student's evidence. Output: accept or reject plus a short
reason, stored in `evidence_verdict` and shown to the student.

"Lenient" is operational, not a vibe: **accept unless the student's evidence is
contradicted by their own recorded answer.** The burden sits on rejection.
Plausible-but-unproven clears the bar; only a direct contradiction with what
they actually wrote does not.

**Judge failure is not a silent decision.** On timeout or error there is no mark
change, `evidence_verdict` stays null, and a queue row opens under a new
`ReviewReason.student_evidence_unjudged`. The student is told a teacher will
look. Defaulting to accept turns an outage into automatic grade inflation;
defaulting to reject punishes a student for an infrastructure fault.

**The judge needs its own metric.** A judge that accepts everything is
indistinguishable from having no guard at all. Accept rate per subject is logged
from day one, or nobody will be able to tell which one was built.

## Effects

**Precedence.** `QuestionResult.effective_marks` becomes
teacher > student > AI. `awarded_marks` is still never mutated — the existing
P3.4 rule holds, which is what keeps `lemely/eval` measurement honest (the
harness reads `awarded_marks`, not `effective_marks`).

**Totals.** `ReviewService._recompute_attempt_totals`
(`lemely/db/review_repo.py:716`) is reused, not reimplemented. A self-marked
attempt and a teacher-overridden attempt with identical marks then cannot round
differently — the invariant that function already exists to protect.

**Blast radius (D5).** `effective_marks` is read well beyond the student's own
screen: `lemely/db/quiz_results_repo.py` (teacher class analytics, per-question
class performance) and `lemely/db/placement_repo.py:359` (placement). Adding a
student tier means self-reported marks reach teacher class averages, placement
decisions, and the student's own `grade` and `predicted_grade`.

**Standings are unaffected**, contrary to the concern first raised when this was
decided. `student_standings` (`lemely/web/routers/student.py:1192`) reads no
marks at all: `rank` is structurally empty because cross-student ranking needs a
cohort the single-student store cannot provide, leaderboards are omitted
entirely, and the only figures returned are paper counts and streak days. There
is no ranking surface for a self-mark to inflate.

The trade-off was raised and accepted deliberately, in favour of one accessor
and one number. The alternative considered was a second accessor
(`assessed_marks`, teacher > AI) for teacher-facing surfaces. It was rejected as
two numbers for the same question, which is the drift `effective_marks`'
"single accessor" docstring exists to prevent. The consequence to hold in mind:
a teacher's class average can contain self-reported marks, with nothing on
screen saying so.

**Weakness signal.** A misconception is not lost marks, so it does not enter
`WeaknessRecord`'s accuracy arithmetic — that would corrupt a number which
currently means one thing. It is derivable from the points table directly: rows
where `student_selfmark = true`, `awarded = false`, and no mark change was
granted. The study plan reads misconception counts by topic alongside existing
weak areas.

**On a mark change**, in one transaction: `student_selfmark` and
`student_selfmark_at` set on the point row, `student_selfmark_marks` set on
`question_results`, a `student_selfmark` revision appended,
`_recompute_attempt_totals` called, and the open `low_confidence` queue row
resolved per D4 (`resolved_by` = the student's `users.id`, `resolved_at`
stamped, `resolution_note` recording the self-mark).

## API

```
GET  /api/student/attempts/{attemptId}/questions/{questionResultId}/self-review
POST /api/student/attempts/{attemptId}/questions/{questionResultId}/self-review
```

Both are student-scoped and reach only the caller's own attempt.

## Error handling

- **Double submission.** The unique constraint on
  `(question_result_id, mark_point_id)` plus a non-null `student_selfmarked_at`
  makes the second POST a 409, not a second self-mark.
- **Teacher override races the student.** Precedence settles marks regardless of
  arrival order — the teacher wins either way. But if a teacher resolves the
  queue row while the student is mid-pass, the submission still *records* the
  self-mark and its misconception signal; it just does not move marks. The
  learning data is not discarded because of a timing accident.
- **No point rows** (a quiz, or any attempt corrected before spec 1 shipped —
  there is no backfill, spec 1 D7) — the self-review action is absent. Derived
  from the absence of rows, not a separate flag that can drift.
- **Ownership.** Cross-student access is a 404, not a 403, matching the existing
  student routes.
- **Atomicity.** Self-mark rows, the revision, the queue resolve and the totals
  recompute all run in one transaction. A failed recompute rolls the whole thing
  back rather than leaving marks and revisions disagreeing.

## Testing

The two that carry the most risk:

- **Reveal withholding.** A literal assertion that the pre-submission `GET`
  payload contains no `awarded` key anywhere, at any nesting depth. This is the
  one bug that would silently void the entire feature while every other test
  still passed.
- **Authority matrix**, as an exhaustive table test: low-confidence ×
  high-confidence × integrity-flagged-only, against evidence present / absent,
  against judge accept / reject / fail. That grid is the feature; anything less
  than full coverage means a cell nobody checked.

The rest:

- Precedence across all three tiers, in both directions, including self-marking
  downward (D6).
- One-pass enforcement: the second POST is a 409.
- Totals consistency: a self-marked attempt and a teacher-overridden attempt
  with identical marks produce an identical percentage.
- An accuracy guard asserting `awarded_marks` is unchanged after a self-mark
  that moved `effective_marks`.
- Authz matrix entry for both new routes.
- Frontend unit tests for the self-review state machine; Playwright for the
  end-to-end flow.

## Open items

- **Quizzes are out of scope at launch**, inherited from spec 1: a quiz has no
  mark scheme, so it has no point rows to self-mark against.
- **Papers corrected before spec 1 shipped are out of scope too**, inherited
  from spec 1 D7 (no backfill). The surface appears only on papers marked from
  that point on, so uptake is gradual rather than retroactive. Worth saying in
  the UI copy rather than leaving a student to wonder why one paper offers
  self-review and an older one does not.
- **Judge model and cost** are unspecified here. One call per challenged point
  is the budget; which model serves it is an implementation decision to make
  against the accept-rate metric above.
