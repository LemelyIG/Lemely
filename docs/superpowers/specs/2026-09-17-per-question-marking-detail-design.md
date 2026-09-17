# Per-Question Marking Detail — Design Spec

Date: 2026-09-17 · Status: draft for review · Spec 1 of 2. Spec 2
(`2026-09-17-student-self-review-design.md`) depends on this one and is
meaningless without it; this one ships and proves itself alone.

## Context

The request was "after correction/marking, per-question detail should be
stored." Much of it already is. `QuestionResult`
(`lemely/db/models/attempts.py:151`) persists, per question: `question_id`,
`awarded_marks`, `maximum_marks`, `confidence_band`, `confidence_score`,
`needs_teacher_review`, `marker_source`, `topic`, `student_answer`,
`expected_answer`, `review_reason`, `feedback`, `matched_point_ids`, and the
P3.4 teacher-override columns, behind the `effective_marks` accessor.

Three things are genuinely missing.

1. **Per-mark-point outcome.** `matched_point_ids` is a flat list of ids. There
   is no per-point tariff, mark type, earned/missed state or reason.
   `teacher_breakdown`'s own docstring names this gap: "only `matched_point_ids`
   (bare point ids) is persisted here, with no join back to per-point mark
   types. There is nothing here honest to derive a breakdown from."

2. **Marker reasoning and evidence.** `feedback` is a single prose string per
   question. Worse, three fields the pipeline already computes are dropped on
   the floor: `CorrectedQuestion.extraction_confidence`, `plagiarism_flagged`
   and `ai_detection_flagged` (`lemely/core/schemas.py:117`) reach `_persist`,
   are used to decide review-queue fan-out
   (`lemely/db/attempt_repo.py:308-334`), and are then discarded rather than
   stored on the row.

3. **Re-mark history.** A teacher override mutates the single row in place.
   "What changed, when, and who changed it" is not answerable.

### The two findings that shape the design

**The mark scheme is already in hand.** `mark_schemes.parsed_payload`
(`lemely/db/models/academic.py:106`, JSONB, `unique` on `paper_id`) holds the
full parsed scheme for every paper, and more usefully, the parsed `MarkScheme`
object is live at correction time — `lemely/web/services/grading.py:105` already
passes it to `fill_correction_topics`. Per-point tariff, mark type and point
text are therefore already available. The gap is one of persistence and shape,
not of missing information.

**`attempts.paper_id` is dead weight.** The column exists
(`lemely/db/models/attempts.py:96`, nullable FK to `papers.id`) but
`AttemptRepository._persist` constructs `Attempt(...)` without it
(`lemely/db/attempt_repo.py:262-280`) and no `paper_id=` assignment exists in
that file. It is NULL on every row. Any design that derives per-point rows by
joining from an attempt to its paper is therefore building on a link that does
not exist — which rules out both the obvious derivation route and any backfill
of existing attempts.

## Decisions

**D1 — Derive the per-point ledger at write time; do not change the marker
prompt.** Considered and rejected: changing `CorrectedQuestion` to emit
`points: list[MarkPointOutcome]` with per-point reasons. That lands on the
accuracy-critical path — a prompt change means re-running baselines, the
fidelity and coherence gates and the A/A churn floor, and both
`_verify_calculated_answers` (`lemely/io/correction_ai.py:304`) and
`_check_coherence` (`:384`) key off `matched_point_ids` and would need rework. It is a real improvement and should happen, but as its own
separately-measured change. Bundling it with a UI feature makes a regression in
either unattributable.

**D2 — Per-point reasons are not invented.** The `rationale` column stays null
until a marker emits one. Deriving a plausible-sounding reason from the mark
scheme text would be exactly the manufactured precision `teacher_breakdown`'s
docstring exists to forbid.

**D3 — Snapshot, do not join live.** `point_text`, `tariff` and `mark_type` are
copied onto the row at write time. Mark schemes get re-parsed and corrected; a
student's marked paper must not change meaning underneath them months later.

**D4 — The existing row stays the current projection.** Revisions are an
append-only side table. `question_results` keeps working exactly as it does
today, so no existing read surface changes in this spec.

**D6 — Derive from the `MarkScheme` object, threaded explicitly; and start
populating `attempts.paper_id`.** The scheme is passed into
`persist_correction` from the correction call site, where it is already live.
This is not merely a workaround for the dead `paper_id` — it is more correct
than a join would have been, because it uses the exact scheme the paper was
marked against rather than whatever a later re-parse produced, which is what D3
is reaching for. Separately, `_persist` starts writing `attempts.paper_id`,
fixing the latent bug on its own merits so that anything future wanting
attempt → paper has a working link.

**D7 — No backfill.** Existing attempts have no usable link to a paper, so
there is no honest scheme to derive their point rows from. A best-effort match
on `(subject_code, session_month, session_year, paper_number, paper_variant)`
was considered and rejected: it would attach *today's* parsed scheme to a paper
marked against a possibly different one, which is exactly the drift D3 forbids.
Existing attempts therefore have no point rows, and spec 2's surface is absent
for them. This is stated plainly to users rather than faked.

**D5 — Ship the columns spec 2 writes.** The student self-review columns are
created here, nullable and unwritten, so spec 2 adds no migration of its own.
Spec 2's design shaped this schema; splitting the DDL across both would mean
designing the same table twice.

## Data model

### New table `question_result_points`

```
id                     uuid pk
question_result_id     fk -> question_results.id, on delete cascade, indexed
mark_point_id          text        -- id as it appears in the parsed scheme
ordinal                int         -- index of the point within the question, as the
                                   -- parsed scheme orders them; stable display order
mark_type              enum M/A/B/null  -- from MathMarkType, lemely/core/loose_schemas.py:79;
                                        -- null where the scheme's points carry no type
tariff                 int         -- marks this point is worth
point_text             text        -- verbatim from the scheme, snapshotted (D3)
awarded                bool        -- AI verdict: id present in matched_point_ids
rationale              text null   -- per-point why; null until a marker emits it (D2)
student_selfmark       bool null   -- written by spec 2; null = not self-marked
student_selfmark_at    timestamptz null
student_evidence       text null
evidence_verdict       enum accepted/rejected/not_required null
unique (question_result_id, mark_point_id)
```

### New table `question_result_revisions`

```
id                 uuid pk
question_result_id fk -> question_results.id, on delete cascade, indexed
revision           int          -- 1, 2, 3…
source             enum ai / teacher / student_selfmark / remark
awarded_marks      int
points_snapshot    jsonb        -- per-point state at this revision
actor_user_id      fk users.id null
reason             text null
created_at         timestamptz
unique (question_result_id, revision)
```

### Added to `question_results`

All nullable, all additive; no existing column changes type or meaning.

```
extraction_confidence   float null   -- computed today at schemas.py:117, then dropped
plagiarism_flagged      bool         -- computed today, only used for queue fan-out
ai_detection_flagged    bool         -- same
rationale               text null    -- question-level marker reasoning
student_selfmark_marks  int null     -- written by spec 2 (D5)
student_selfmarked_at   timestamptz null
```

### Added to `CorrectedQuestion` (`lemely/core/schemas.py:117`)

```python
rationale: str | None = None
point_notes: dict[str, str] | None = None
```

Both default to `None`, so no prompt change is required to ship this spec. When
the marker change of D1 lands later, it fills them and the columns stop being
null.

### Added to `ReviewReason` (`lemely/db/models/enums.py`)

One new value, `student_evidence_unjudged`, created here per D5 so spec 2 needs
no enum migration. Unused until spec 2 writes it.

`ReviewQueueItem` itself needs **no** new column: `resolved_by`
(`lemely/db/models/ops.py`, a nullable FK to `users.id`), `resolution_note` and
`resolved_at` already exist and carry everything spec 2 records. Whether a
resolution came from a teacher or a student is recoverable from the
`question_result_revisions` row's `source`, not from a duplicate column here.

## Write path

All of it lands in `AttemptRepository._persist`
(`lemely/db/attempt_repo.py:200`) — the single writer both `persist_correction`
and `persist_quiz_correction` already call. The derivation runs inside the
existing `with self._sm.begin()` block, after `session.flush()`, beside the
review-queue fan-out. One transaction, no second write path to drift.

`persist_correction` and `_persist` take a new keyword-only
`mark_scheme: MarkScheme | None = None`, threaded from the correction call site
(D6). `_persist` also now sets `attempt.paper_id` when the caller supplies it.

**Derivation.** For each `(qr, cq)` pair, look up the question in the supplied
`mark_scheme`, and write one row per point **in the scheme** — not per point in
`cq.matched_point_ids` — setting `awarded` from membership in
`cq.matched_point_ids`.

That inversion is the crux. Missed points must become rows too, with
`awarded = false`. A table of only the matched points has nothing for a student
to self-mark against, and no missed-point breakdown for a teacher to read.

**Revision 1** is written in the same transaction, `source = ai`, with
`points_snapshot` set to the derived rows.

### Edge cases

Each resolves to writing nothing rather than fabricating something.

- `mark_scheme is None` — the caller passed no scheme. Quizzes are the standing
  case: `persist_quiz_correction` has no scheme to pass. No scheme, no point
  rows; the question behaves exactly as it does today. **Consequence: the
  spec-2 self-review surface is past-papers-only at launch.** Quizzes get it
  when quiz mark schemes exist, not before.
- The supplied scheme carries no entry for this `question_id` — no point rows
  for that question; the others are unaffected.
- A dangling point id (one `matched_point_ids` claims but the scheme lacks).
  `_check_coherence` (`lemely/io/correction_ai.py:441`) already detects these
  upstream, but if one survives, no row is written for it. Never a row with a
  null tariff pretending to be a mark point.

## Backfill

There is none, per D7. The migration creates tables and columns only. Existing
attempts keep working exactly as they do today; they have no point rows, and
spec 2's surface is absent for them. Point rows accrue from the first attempt
corrected after this ships.

## Error handling

- **Atomicity.** Point rows and the revision are written in the same transaction
  as the attempt and its review-queue rows. A failure rolls back the whole
  attempt rather than leaving an attempt with no points, or points with no
  attempt.
- **Derivation failure** (malformed `parsed_payload`) is logged and yields no
  point rows for that question. It must never fail the correction itself — a
  student losing their marked paper because a breakdown could not be derived is
  a strictly worse outcome than a missing breakdown.

## Testing

- Derivation unit tests against a mark-scheme fixture, covering the inversion
  (missed points become rows), dangling ids, `mark_scheme is None`, and a
  scheme with no entry for a given `question_id`.
- `attempts.paper_id` is written when the caller supplies it and stays NULL when
  it does not (D6) — the latent bug this spec fixes, pinned.
- Snapshot independence: mutating the source scheme after an attempt is written
  must not change that attempt's stored `point_text` or `tariff` (D3).
- Revision 1 written exactly once per question result, with `points_snapshot`
  matching the derived rows.
- The three previously-dropped fields (`extraction_confidence`,
  `plagiarism_flagged`, `ai_detection_flagged`) now round-trip from
  `CorrectedQuestion` to the row.
- An accuracy guard asserting `awarded_marks` is untouched by anything in this
  spec, which is what keeps `lemely/eval` measurement honest.
- Migration test asserting upgrade and downgrade are clean, and that existing
  attempt rows are untouched by it (D7).

## Open items

- **Source page and bounding box** were raised as part of "marker reasoning and
  evidence" and are deliberately **not** in this spec. Whether the extraction
  pipeline produces coordinates at all is unverified. Promising a "show me where
  on my paper" affordance the data cannot support would be the same invented
  precision D2 rejects. Verify first; if coordinates exist, they are an additive
  follow-up to `question_result_points`.
