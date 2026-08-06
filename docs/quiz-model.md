# Quiz data model and marking path (P3.5 / T-09, T-10)

Design for the teacher quiz builder: persistence, the question pool, difficulty
targeting, and how a submitted quiz becomes marks that reach analytics.

Status: design. Nothing here is implemented. Migration slot: `0007_quiz_model`.

Constraints this document is written against:

- Schema changes are additive only (D1.2/D1.3). No column is dropped or repurposed.
- Every marking operation emits per-question and per-paper confidence; low
  confidence routes to the human review queue (MISSION §3). Applies to quizzes.
- Board-agnostic: nothing below is CAIE-specific except seed data.
- Multi-tenant-safe: every read/write is scoped through `ClassService`.
- One rule, one place. This codebase has been bitten three times by the same
  rule implemented twice and drifting (D3.3, D3.4, D3.5). Two rules below are
  at high risk of that and are each pinned to a single pure function.

---

## 0. The two decisions that matter

**A queryable question bank is required and is in scope.** T-09 step 4's live
count is a query. Today's pool is `output_dir/questions/*.json` scanned on every
request via `_existing_questions()` — no ids to reference, no per-teacher
scoping (it reads a process-global path, so every teacher sees every teacher's
questions: a tenancy hole that shipping quiz persistence on top of would
entrench), and no way to count by difficulty. Section 2 designs the bank.

**Difficulty targeting is a documented heuristic, not a calibrated model.**
There is no evidence in this repo linking question difficulty to grade
outcomes. The mapping is one constant table in one pure module, labelled as an
estimate in the UI, with the telemetry needed to replace it later designed in
from the start. Section 3.

---

## 1. Schema

Seven new tables plus one additive column on `attempts`. All ids are
`uuid` with `server_default gen_random_uuid()`; all tables carry
`TimestampMixin` (`created_at`/`updated_at`).

### 1.1 Enums

Native Postgres enums, matching every existing enum in
`lemely/db/models/enums.py` (`sa.Enum(X, name="...")`, lowercase concatenated
type name). Consistency wins here; the known cost is that adding a member later
needs `ALTER TYPE ... ADD VALUE`, which cannot run inside a transaction on
older Postgres. That cost is accepted rather than introducing a second,
constrained-string convention that a reader has to keep two mental models for.

```python
class QuizStatus(enum.Enum):          # name="quizstatus"
    draft = "draft"
    assigned = "assigned"
    closed = "closed"
    archived = "archived"

class QuizQuestionStatus(enum.Enum):  # name="quizquestionstatus"
    included = "included"
    removed = "removed"               # curated out in step 5; row is kept

class QuizSubmissionStatus(enum.Enum):  # name="quizsubmissionstatus"
    not_started = "not_started"
    in_progress = "in_progress"
    submitted = "submitted"
    marked = "marked"

class QuestionSource(enum.Enum):      # name="questionsource"
    past_paper = "past_paper"
    generated = "generated"
    teacher_upload = "teacher_upload"

class QuestionDifficulty(enum.Enum):  # name="questiondifficulty"
    foundation = "foundation"
    standard = "standard"
    challenge = "challenge"
    # Deliberately identical to GeneratedQuestion.difficulty's Literal.
    # A generated question's band is stored verbatim, never re-derived.

class DifficultySource(enum.Enum):    # name="difficultysource"
    declared_by_generator = "declared_by_generator"
    inferred_from_marks = "inferred_from_marks"
    teacher_set = "teacher_set"

class AttemptOrigin(enum.Enum):       # name="attemptorigin"
    past_paper = "past_paper"
    quiz = "quiz"
    custom_paper = "custom_paper"     # T-11, marked through the same path
```

### 1.2 `attempts.origin` — the additive column

```sql
ALTER TYPE ... -- create attemptorigin
ALTER TABLE attempts
  ADD COLUMN origin attemptorigin NOT NULL DEFAULT 'past_paper';
CREATE INDEX ix_attempts_user_id_origin ON attempts (user_id, origin);
```

Every existing row is a past-paper attempt, so the default is correct and the
migration needs no backfill.

**Why this column exists.** Quiz marks are written as `Attempt` rows (§4). A
ten-question quiz has no grade boundaries; giving it a `grade` would invent
precision (UI-spec §1.4 principle 6) and would silently corrupt
`grade_distribution`, `cohort_trend`, `per_paper_comparison`, and
`at_risk._check_below_target`, all of which read grades and percentages out of
student history with no notion of what kind of assessment produced them. The
column is what lets §5 split "counts toward a grade claim" from "counts toward
a topic claim" in exactly one place.

For `origin = quiz`, `grade`, `predicted_grade`, `boundary_source`,
`paper_id`, `paper_number`, `paper_variant`, `session_month` and `session_year`
are all **NULL**. `subject_code`, `awarded_marks`, `maximum_marks`,
`percentage`, `confidence_band`, `needs_teacher_review` and `recorded_at` are
populated normally.

### 1.3 `question_bank`

The queryable pool. One row per markable question, whatever its provenance.

```sql
CREATE TABLE question_bank (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  board             examboard NOT NULL DEFAULT 'caie',
  subject_code      varchar NOT NULL,
  source            questionsource NOT NULL,
  owner_id          uuid NULL REFERENCES users(id) ON DELETE CASCADE,
  school_id         uuid NULL REFERENCES schools(id) ON DELETE CASCADE,
  paper_id          uuid NULL REFERENCES papers(id),
  source_question_id varchar NULL,          -- leaf id within that paper, e.g. "3a_ii"
  topic             varchar NULL,
  difficulty        questiondifficulty NOT NULL,
  difficulty_source difficultysource NOT NULL,
  question_type     varchar NOT NULL,       -- QuestionType member value
  prompt            text NOT NULL,
  model_answer      text NULL,
  mark_scheme_points jsonb NOT NULL DEFAULT '[]'::jsonb,
  mcq_options       jsonb NULL,             -- ["A text","B text",...] for MCQ
  mcq_answer        varchar NULL,           -- "A".."D"
  total_marks       integer NOT NULL,
  source_question_ids jsonb NOT NULL DEFAULT '[]'::jsonb,  -- provenance of generated qs
  is_active         boolean NOT NULL DEFAULT true,
  created_by        uuid NULL REFERENCES users(id),
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_question_bank_pool
  ON question_bank (subject_code, source, difficulty, is_active);
CREATE INDEX ix_question_bank_topic
  ON question_bank (subject_code, topic, is_active);
CREATE INDEX ix_question_bank_owner ON question_bank (owner_id);
CREATE UNIQUE INDEX uq_question_bank_paper_question
  ON question_bank (paper_id, source_question_id)
  WHERE paper_id IS NOT NULL;
```

`question_type` is a plain `varchar` holding a `QuestionType` member value, not
a native enum: `QuestionType` has sixteen members and is owned by the
mark-scheme parser, which will grow members as new boards arrive. Freezing it
into a PG type would mean an `ALTER TYPE` migration every time the parser
learns a question shape. This is the one place where the constrained-string
choice beats the native enum, and the reason is board-agnosticism.

**Visibility.** Three tiers, resolved by one predicate:

| `owner_id` | `school_id` | visible to |
|---|---|---|
| NULL | NULL | everyone (platform-shared: past papers, platform-generated) |
| set | NULL | that user only (their generations, their T-11 uploads) |
| NULL | set | members of that school |

The predicate is `visible_bank_filter(caller_id, school_ids) -> ColumnElement`
in `lemely/db/question_bank_repo.py`, used by **both** the count endpoint and
the selection query. If those two ever diverge, T-09 shows a count of 40 and
then builds a quiz of 12 with no explanation — that is the failure mode the
shared predicate exists to prevent.

`uq_question_bank_paper_question` makes the past-paper ingest (chunk B)
idempotent: re-running it over the same parsed mark scheme updates rather than
duplicates. Without it the live count inflates on every re-ingest, which is
worse than no count at all.

### 1.4 `quizzes`

```sql
CREATE TABLE quizzes (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  teacher_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  school_id      uuid NULL REFERENCES schools(id) ON DELETE SET NULL,
  subject_code   varchar NOT NULL,
  title          varchar NOT NULL,
  status         quizstatus NOT NULL DEFAULT 'draft',
  target_grade   varchar NULL,          -- a GRADE_ORDER member; NULL = untargeted
  included_topics jsonb NOT NULL DEFAULT '[]'::jsonb,   -- step 2
  pool_source    questionsource NULL,   -- step 4 choice; NULL while undecided
  requested_count integer NULL,
  time_limit_minutes integer NULL,
  builder_step   smallint NOT NULL DEFAULT 1,   -- 1..6, for draft resume
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_quizzes_teacher_status ON quizzes (teacher_id, status);
```

Every step-2/3/4 field is nullable and the row is created on entering step 1.
That is what makes "draft saving throughout" (T-09 states) a `PATCH` on an
existing row rather than a client-side blob that has to be validated as a whole
— a half-filled draft is a legal row, not a schema violation.

`builder_step` exists so resuming a draft returns the teacher to where they
were. It is advisory; the server never trusts it for authorization.

`target_grade` is a plain `varchar` validated against
`at_risk.GRADE_ORDER` at the API boundary rather than a PG enum: grade ladders
are board-specific (Edexcel 9-1 arrives later) and `GRADE_ORDER` is already the
single Python-side source of truth. A PG enum here would create a second one.

`status` lifecycle: `draft → assigned → closed → archived`. `draft → archived`
is also legal (abandoned draft). No transition ever goes backwards; an assigned
quiz whose questions a teacher wants to change is duplicated into a new draft.
Editing a live quiz under students mid-attempt is the failure this forbids.

### 1.5 `quiz_questions`

The curated, ordered, **materialized** question set.

```sql
CREATE TABLE quiz_questions (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  quiz_id          uuid NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
  question_bank_id uuid NULL REFERENCES question_bank(id) ON DELETE SET NULL,
  question_ref     varchar NOT NULL,   -- "q1".."qN"; becomes question_results.question_id
  position         integer NOT NULL,
  status           quizquestionstatus NOT NULL DEFAULT 'included',
  replaced_by_id   uuid NULL REFERENCES quiz_questions(id) ON DELETE SET NULL,
  -- frozen snapshot (see below)
  topic            varchar NULL,
  difficulty       questiondifficulty NOT NULL,
  question_type    varchar NOT NULL,
  prompt           text NOT NULL,
  model_answer     text NULL,
  mark_scheme_points jsonb NOT NULL DEFAULT '[]'::jsonb,
  mcq_options      jsonb NULL,
  mcq_answer       varchar NULL,
  total_marks      integer NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_quiz_questions_ref ON quiz_questions (quiz_id, question_ref);
CREATE INDEX ix_quiz_questions_quiz_position ON quiz_questions (quiz_id, position, status);
```

**The question text is copied, not referenced.** `question_bank_id` is a
nullable provenance pointer only. A bank row can be edited, deactivated, or
have its difficulty relabelled after a quiz is assigned; if the quiz read
through the FK, a student's marked answer could end up displayed next to a
different question than the one they answered, and T-10's per-question analysis
would silently re-describe history. Snapshotting costs duplicated text and buys
an assessment record that cannot change after the fact. That is the right trade
for anything a mark is attached to.

**Removed questions are kept, not deleted** (`status = 'removed'`, with
`replaced_by_id` set when step 5's swap produced a replacement). T-09 curates a
pool; the audit of what a teacher took out is cheap to keep and impossible to
reconstruct later, and it is the raw material for ever answering "are our
generated questions any good?".

`question_ref` is the stable per-quiz identifier that flows all the way to
`question_results.question_id`. It is assigned at insert and never renumbered,
so removing question 3 does not turn question 4 into question 3 and silently
re-point an existing mark. Display order comes from `position`, which may be
rewritten freely while the quiz is a draft.

### 1.6 `quiz_assignments`

```sql
CREATE TABLE quiz_assignments (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  quiz_id      uuid NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
  class_id     uuid NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  assigned_by  uuid NOT NULL REFERENCES users(id),
  assigned_at  timestamptz NOT NULL DEFAULT now(),
  due_at       timestamptz NULL,
  closes_at    timestamptz NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_quiz_assignments ON quiz_assignments (quiz_id, class_id);
CREATE INDEX ix_quiz_assignments_class ON quiz_assignments (class_id, assigned_at);
```

A separate table rather than a `class_id` on `quizzes`: the same quiz assigned
to two classes is an obvious teacher need, and modelling it now costs one table
and no complexity, whereas retrofitting it later means rewriting every
submission's parentage.

T-10 aggregates per assignment (a class's results), not per quiz.

### 1.7 `quiz_submissions`

```sql
CREATE TABLE quiz_submissions (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assignment_id uuid NOT NULL REFERENCES quiz_assignments(id) ON DELETE CASCADE,
  student_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status        quizsubmissionstatus NOT NULL DEFAULT 'not_started',
  started_at    timestamptz NULL,
  submitted_at  timestamptz NULL,
  marked_at     timestamptz NULL,
  attempt_id    uuid NULL REFERENCES attempts(id) ON DELETE SET NULL,
  marking_error text NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_quiz_submissions ON quiz_submissions (assignment_id, student_id);
CREATE INDEX ix_quiz_submissions_status ON quiz_submissions (assignment_id, status);
```

Rows are created lazily on first open, not pre-seeded at assignment time.
T-10's completion rate is therefore
`count(submissions with status in (submitted, marked)) / count(class roster)` —
computed against the live roster through `ClassService`, so a student who joins
or leaves the class after assignment is counted correctly. Pre-seeding would
freeze a roster snapshot into the denominator and drift.

`attempt_id` is the join to the marking universe. It is NULL until marking
succeeds, and `marking_error` holds the failure text if it did not, so a failed
Gemini call leaves a visible `submitted`-but-unmarked row rather than a silently
missing result.

No confidence column here. Quiz confidence is read from
`attempts.confidence_band` — one source (§5).

### 1.8 `quiz_answers`

```sql
CREATE TABLE quiz_answers (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id    uuid NOT NULL REFERENCES quiz_submissions(id) ON DELETE CASCADE,
  quiz_question_id uuid NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
  answer_text      text NULL,
  working_text     text NULL,
  answered_at      timestamptz NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_quiz_answers ON quiz_answers (submission_id, quiz_question_id);
```

Separate from `question_results` because an answer exists before any marking
run and must outlive every one of them. Re-marking (a retry after a Gemini
outage, or a future re-run against a corrected T-11 mark scheme) deletes and
rewrites the `Attempt` and its `QuestionResult`s; it must never touch what the
student actually wrote. `working_text` is present because the method-mark
awareness in `AICorrector.mark_question(question, answer, working)` is the
product's core claim and the quiz path should not throw the working away.

---

## 2. The pool problem (T-09 step 4)

**Verdict: a queryable bank is required, and it is in Phase-3 scope.** T-09 as
specified asks for a live count that responds to subject + topics + target
grade + pool choice. That is a `SELECT count(*)` with a `WHERE`; no arrangement
of on-disk JSON answers it honestly at request latency, and the current
directory scan additionally leaks every teacher's questions to every other
teacher.

The count endpoint:

```
GET /teacher/quizzes/pool-count
    ?subjectCode=0580&topics=algebra,trigonometry&targetGrade=C&source=past_paper
->  { "matching": 34, "requested": 12, "byBand": {"foundation": 12, "standard": 18, "challenge": 4},
      "shortfall": null, "difficultyEstimated": true }
```

`byBand` is the same allocation the builder will use (§3), so "not enough
questions for the constraints" (a T-09 state) is answerable precisely: the
response names which band is short, which is what "suggest which constraint to
loosen" needs.

**How the bank gets filled.**

- `generated`: `/quizzes/generate` writes bank rows instead of a JSON file.
  `GeneratedQuestion` maps field-for-field; `difficulty_source =
  declared_by_generator`. Existing on-disk `GeneratedQuiz` files are imported
  once by a one-shot CLI command with `owner_id = NULL` and left on disk
  afterwards; the disk path is then dead and removed in a later cleanup.
- `teacher_upload`: T-11's parsed custom paper, `owner_id = teacher`.
- `past_paper`: an ingest job walking `mark_schemes.parsed_payload` →
  `MarkScheme.all_questions_flat()`, one row per leaf question, `paper_id` and
  `source_question_id` set, `difficulty_source = inferred_from_marks`.

**The honest degraded behaviour.** Until the past-paper ingest has run for a
subject, that subject's `past_paper` count is genuinely 0 and T-09 must say so
in those words — "no past-paper questions indexed for Physics 0625 yet; use
generated questions" — not display a plausible-looking number. A count that is
right for one subject and fabricated for another is worse than a count that is
sometimes zero, because the teacher cannot tell which they are looking at. This
is the same principle as the "estimated" boundary label (UI-spec §1.4.6).

A second honesty note: past-paper questions in the bank carry the question
*prompt text* only if the parsed mark scheme contains it. Where the mark scheme
has marking points but not the question stem, the bank row must be created with
`is_active = false` and excluded from counts, because a quiz question with no
prompt is not a question. The ingest must count and report how many it skipped
for this reason. Expect this to be a non-trivial fraction; it is the main
uncertainty in chunk B's yield.

---

## 3. Difficulty targeting by expected grade

One new pure module: **`lemely/core/difficulty.py`**. No I/O, no DB, imports
only `GRADE_ORDER` from `lemely.core.at_risk`. Everything in this section lives
there and nowhere else — the pool count, the builder's selection, and any
future UI explanation all call these functions rather than re-expressing the
table. This is the D3.3/D3.5 discipline applied pre-emptively, because a
difficulty rule expressed twice will drift and the symptom (a count that does
not match the quiz produced) is exactly the kind of thing that erodes trust in
the number.

### 3.1 Grade → difficulty mix

```python
Band = Literal["foundation", "standard", "challenge"]

#: Heuristic. Not calibrated against outcome data — see §3.4.
DIFFICULTY_MIX: dict[str, tuple[float, float, float]] = {
    # target grade: (foundation, standard, challenge)
    "A*": (0.00, 0.30, 0.70),
    "A":  (0.00, 0.50, 0.50),
    "B":  (0.20, 0.60, 0.20),
    "C":  (0.30, 0.60, 0.10),
    "D":  (0.50, 0.50, 0.00),
    "E":  (0.70, 0.30, 0.00),
    "U":  (1.00, 0.00, 0.00),
}

def difficulty_mix(target_grade: str | None) -> tuple[float, float, float]:
    """Proportions for a target grade; (0.2, 0.6, 0.2) when untargeted/unknown."""

def allocate_difficulty(target_grade: str | None, count: int) -> dict[Band, int]:
    """Whole-question allocation summing exactly to ``count``.

    Largest-remainder rounding, ties broken toward ``standard``. Deterministic:
    the same (grade, count) always yields the same allocation, so the live count
    and the built quiz can never disagree.
    """
```

A **mix**, not a single band, because a quiz aimed at a C student made entirely
of "standard" questions discriminates nothing: it cannot show the teacher who
is nearly a B or who is slipping to a D. Every target keeps at least two bands
in play. An unknown or NULL target is not an error — it degrades to a balanced
spread, which is the correct behaviour for a teacher who skipped step 3.

Selection then takes `allocate_difficulty(...)` per band, fills each band from
the visible bank ordered by `(topic coverage, random)`, and reports a shortfall
per band rather than silently substituting from another band. Silent
substitution is what would make step 4's count a lie.

### 3.2 Where past-paper difficulty comes from

Past-paper questions carry no difficulty label anywhere in the corpus. Two
ways to give them one:

- **Ask Gemini to label each at ingest.** Best quality, but it is a per-question
  model call across the whole corpus, which is a direct hit on MISSION's cost
  ceiling for a field used only to sort a pool. Rejected as the default.
- **Derive it from data already parsed.** Chosen:

```python
def infer_difficulty(marks: int, question_type: str) -> Band:
    """Estimate a band from mark allocation and question shape.

    A proxy for effort, not for difficulty: a 1-mark question can be brutal.
    Recorded with ``difficulty_source = inferred_from_marks`` so it is never
    confused with a band a generator declared or a teacher set.
    """
    if question_type in {"multi_step", "levels_based", "indicative_content"}:
        return "challenge"
    if question_type == "mcq" or marks <= 1:
        return "foundation"
    if marks <= 3:
        return "standard"
    return "challenge"
```

Consequences that must be surfaced, not buried:

- T-09 step 4 labels past-paper difficulty **"estimated from mark allocation"**
  whenever the returned set contains any `inferred_from_marks` row
  (`difficultyEstimated: true` in the count response). Generated questions carry
  a declared band and are not so labelled.
- A teacher can override any bank row's difficulty; `teacher_set` wins and is
  never recomputed by a re-ingest.
- `difficulty_source` exists precisely so that replacing the rule later is a
  data migration over rows still marked `inferred_from_marks`, not a schema
  change and not a guess about which values were human-set.

### 3.3 What backs the mapping

Nothing, empirically. There is no dataset in this repo relating question
difficulty to grade outcomes, and none is acquirable within Phase 3. The
mapping is a product judgement, and the design's obligations are therefore:
state that in the module docstring, never let the UI claim calibration ("questions
are weighted toward this level", not "calibrated to grade C"), and make the
evidence collectable.

### 3.4 The calibration hook (design now, build later)

Once quiz results exist, the evidence is a single join:

```sql
SELECT qq.difficulty, a.origin, count(*), avg(qr.awarded_marks::float / qr.maximum_marks)
FROM question_results qr
JOIN attempts a       ON a.id = qr.attempt_id AND a.origin = 'quiz'
JOIN quiz_submissions s ON s.attempt_id = a.id
JOIN quiz_questions qq  ON qq.quiz_id = ... AND qq.question_ref = qr.question_id
GROUP BY 1, 2;
```

Mean per-band accuracy segmented by the student's most recent past-paper
predicted grade is exactly the calibration signal. Everything needed for it is
in the schema above; no additional column is required later. That is the
justification for `question_ref` being stable and for `quiz_questions.difficulty`
being snapshotted rather than read through the bank FK.

---

## 4. The marking path

### 4.1 Principle

Quiz marks are `Attempt` + `QuestionResult` + `WeaknessRecord` rows, written by
the same repository, marked by the same engine, and reviewed in the same queue
as a past-paper attempt. There is no parallel quiz-marks structure and no second
aggregation path. Everything downstream — T-10, class weakness analytics,
at-risk, the review queue, the student's own results view — reads the rows it
already reads.

The alternative (a `quiz_question_marks` table) was rejected in §7; the short
version is that it would require duplicating `effective_marks`, the teacher
override path, the weakness recompute, and the review queue, and would produce
a teacher console with two inboxes.

### 4.2 Sequence

1. Student submits. `quiz_submissions.status = 'submitted'`, `submitted_at` set.
   Idempotent: a second submit is a no-op.
2. `QuizMarkingService.mark_submission(submission_id)` loads the frozen
   `quiz_questions` (`status = 'included'`, by `position`) and the
   `quiz_answers`.
3. Each quiz question is materialized into a core `loose_schemas.Question` by
   one pure adapter:

   ```python
   def quiz_question_to_scheme_question(qq: QuizQuestion) -> Question:
       """id=qq.question_ref, marks=qq.total_marks, type=QuestionType(qq.question_type),
       topic_hint=qq.topic, answer_points=[AnswerPoint(id=f"p{i+1}", point=text, marks=...)
       for each mark_scheme_points entry], mcq_answer set for MCQ."""
   ```

   `question_ref` becomes `Question.id` and therefore
   `question_results.question_id` — one identifier end to end.
4. Those `Question`s are assembled into an in-memory `MarkScheme` and run
   through **the existing `correct_paper`**. No new marking engine, no new
   prompt. `correct_paper` already routes MCQ to the deterministic
   `_build_mcq_corrected` and everything else to `AICorrector.mark_question`,
   with the existing borderline-thinking retry, Pro escalation, and
   `REVIEW_CONFIDENCE_THRESHOLD` gate. Because a T-11 custom paper *is* already
   a parsed `MarkScheme`, it enters at this same step with no adapter at all —
   which is what makes MISSION §9's "T-11 delivered via teacher quiz marking"
   true rather than aspirational.
5. Weaknesses via the existing `summarize_weaknesses` / `group_weak_areas`.
   **No grade prediction is run.** A quiz has no boundaries.
6. Persist via `AttemptRepository.persist_quiz_correction(...)`, which writes
   the same rows with `origin = 'quiz'` and grade/boundary/paper columns NULL.
7. `quiz_submissions.attempt_id`, `status = 'marked'`, `marked_at` set.

Marking runs as a background task; the endpoint returns immediately and the
student sees "being marked". A synchronous mark would put a multi-question
Gemini round trip inside an HTTP request.

### 4.3 The synthetic-metadata trap

`CorrectionResult.metadata` is a required `ExamMetadata`, whose validators
demand a 4-digit subject code and `paper_number`/`paper_variant` in 1..9. A
quiz has a subject code and nothing else.

The rule: synthesize `paper_number=1, paper_variant=1, session_month="Specimen"`
**only to satisfy the in-memory marking call**, and never persist them.
`persist_quiz_correction` writes NULL to those columns regardless of what
metadata the report carries. The fiction stays inside the marking call, where it
is inert, and out of the database, where it would create a bogus "Paper 1/1"
bucket in `per_paper_comparison` for every class that ever took a quiz. An
implementer copying `persist_correction` line by line will get this wrong by
default; it needs an explicit assertion and a test.

### 4.4 One writer, not two

`AttemptRepository.persist_correction` is refactored into a private
`_persist(*, owner, correction, weaknesses, prediction: GradePrediction | None,
origin: AttemptOrigin, upload_id, recorded_at)`. Both `persist_correction`
(prediction present, `origin=past_paper`) and `persist_quiz_correction`
(prediction `None`, `origin=quiz`) call it. The review-queue fan-out — the
low-confidence / plagiarism / AI-detection `ReviewQueueItem` construction — is
inside `_persist` and is therefore identical for both. Copying that fan-out into
a second method is how one of the three reasons for flagging quietly stops
firing for quizzes.

When `prediction is None`: `percentage = 100 * awarded / max` (guard max = 0),
`grade`/`predicted_grade`/`boundary_source` NULL, and
`confidence_band = min(band across question results)` — the per-paper
confidence for an assessment with no grade prediction is the weakest per-question
confidence in it. Stated as a rule so it is not re-invented per caller.

### 4.5 Review queue: yes, the same one

Low-confidence quiz answers enter the existing `review_queue`. The argument:

- Structurally it already fits. `review_queue` FKs `attempt_id` and
  `question_result_id`; a marked quiz has both. No column changes.
- Tenancy already works. `ReviewService._visible_class_map` scopes items by
  student → class, and a quiz's audience is *defined* by a class. A quiz item is
  visible to exactly the teachers who should see it, with no new logic.
- P3.4's `resolve()` already does the right thing: override, recompute attempt
  totals, recompute weakness records, `effective_marks` wins on every read. A
  teacher correcting a quiz mark needs precisely that.
- A parallel queue would give the teacher console two inboxes for the same job
  (T-07 is explicitly a batch workflow with keyboard shortcuts — splitting it in
  two is a direct regression), and would need a second copy of the
  override→weakness-recompute logic, which is D3.4's drift trap re-opened.

**One change is mandatory in `ReviewService`.** `_recompute_attempt_totals`
currently calls `_boundaries_for(attempt)` and assigns `attempt.grade`,
`attempt.predicted_grade`, `attempt.boundary_source`. For `origin = quiz` it
must skip all three and leave them NULL. Without this guard, the *first teacher
override on any quiz* invents a grade that the marking path deliberately never
wrote — the exact "never invent precision" violation this design spent a column
avoiding, arriving through a side door. This needs its own test.

Optionally surface `quiz_submissions` context in the review row (quiz title
instead of paper reference) so a teacher knows what they are looking at; that is
a DTO concern, not a schema one.

### 4.6 T-10 without a second aggregation path

| T-10 panel | source |
|---|---|
| Completion rate | `quiz_submissions` status vs live `ClassService` roster |
| Score distribution | `attempts.percentage` for the submissions' attempts |
| Per-question analysis | `question_results` grouped by `question_id` (= `question_ref`) joined to `quiz_questions` for prompt/topic/difficulty |
| Per-student results | `attempts` + `question_results.effective_marks` |
| Class-wide weaknesses | `rank_topic_weaknesses` over the same `WeaknessRecord` rows the class analytics already read |

Per-question analysis must aggregate `QuestionResult.effective_marks`, never
`awarded_marks` — the same single-accessor rule P3.4 established, so a teacher
correction cannot appear on the student's screen but be missing from the class
view. Score distribution is deliberately a *percentage* distribution, not a
grade distribution: there are no boundaries to bucket by.

---

## 5. Grade-bearing vs topic-bearing records

Quiz attempts must feed topic analytics (MISSION: "results feed analytics") and
must **not** feed grade or paper-comparison analytics. That split is one
predicate, in one place.

In `lemely/core/history.py`:

```python
class PaperRecord(StrictModel):
    ...
    origin: Literal["past_paper", "quiz", "custom_paper"] = "past_paper"

def is_grade_bearing(record: PaperRecord) -> bool:
    """Whether this record may back a grade, boundary, or paper-comparison claim.

    True only for full past-paper attempts with a real grade. A quiz has no
    grade boundaries, so its percentage is not comparable to a paper's and its
    grade does not exist. Topic-level aggregation ignores this predicate: a
    weakness is a weakness whatever revealed it.
    """
    return record.origin == "past_paper" and record.grade in GRADE_ORDER
```

`HISTORY_SCHEMA_VERSION` bumps 1 → 2 (additive, with a default, so old files
load unchanged). `DbHistoryStore._to_record` sets `origin` from
`attempts.origin` and continues to load **all** origins.

Consumers:

| function | filter |
|---|---|
| `rank_topic_weaknesses` | all records |
| `topic_student_heatmap` | all records |
| `engagement_stats` | all records (a quiz *is* activity) |
| `at_risk._check_inactivity` | all records (same reason) |
| `grade_distribution` | `is_grade_bearing` |
| `cohort_trend` | `is_grade_bearing` |
| `per_paper_comparison` | `is_grade_bearing` |
| `at_risk._check_declining_trend` | `is_grade_bearing` |
| `at_risk._check_below_target` | `is_grade_bearing` |

This refactor is a behavioural no-op until the first quiz attempt exists, so it
can and should land **before** quiz marking does. Landing it after means a
window in which quiz data quietly corrupts class grade distributions.

---

## 6. Sequencing

Suggested order: **C → A → G → B → D → E → F**.

| chunk | content | risk |
|---|---|---|
| **C** | `lemely/core/difficulty.py`: `DIFFICULTY_MIX`, `difficulty_mix`, `allocate_difficulty`, `infer_difficulty`. Pure, fully unit-tested, no dependencies. | low |
| **A** | Migration `0007_quiz_model` + ORM models + enums + `attempts.origin`. Schema only, no behaviour. | low |
| **G** | `PaperRecord.origin`, `is_grade_bearing`, wire into the nine consumers in §5. Behavioural no-op today. | low, but must precede F |
| **B** | `question_bank` repo, visibility predicate, past-paper ingest from parsed mark schemes, import of existing on-disk `GeneratedQuiz` files. | **highest** |
| **D** | Quiz CRUD, draft PATCH, pool-count endpoint, question selection; `/quizzes/pools` moves off disk onto the bank. All scoped through `ClassService`. | medium |
| **E** | Assignment endpoints, student take/submit (S-26), `quiz_answers` writes. | medium |
| **F** | `QuizMarkingService`, `persist_quiz_correction`, `_persist` refactor, review-queue integration, `_recompute_attempt_totals` quiz guard, T-10 endpoints. | **second-highest** |

**B is the riskiest** and should be the first thing scheduled after C and A,
because everything T-09 promises about the pool depends on how much usable
question text actually comes out of the parsed mark schemes. If the yield is
poor, the product answer is the honest zero-count degradation in §2 — but that
needs to be known early, not discovered in chunk D when the count endpoint
returns 3. Chunk B should begin with a measurement: run the extraction over the
existing corpus and report rows produced, rows skipped for missing prompt text,
and topic coverage, before any of it is persisted.

**F is second** because it touches the shared `_persist` path and
`ReviewService`, both of which past-paper marking depends on. The regression
suite for past-paper persistence and review resolution must stay green
throughout; treat any change in its behaviour as a defect in the refactor, not
an acceptable consequence.

---

## 7. Rejected alternatives, and why

**Store the quiz as a filter spec, materialize questions at assign time.**
Smaller schema, and step 5's edits become "exceptions to the filter". Rejected:
the question set would be re-derived from a bank that changes underneath it, so
two students could receive different quizzes, and T-10's per-question analysis
could describe a question nobody answered. Assessment records must be frozen.

**Reference `question_bank` from `quiz_questions` by FK instead of
snapshotting.** Saves duplicated text. Rejected for the same reason: editing or
deactivating a bank row would retroactively change an assessment that has
already been marked.

**A parallel `quiz_question_marks` table instead of `Attempt`/`QuestionResult`.**
Superficially cleaner (no NULL grade columns, no `origin` enum). Rejected: it
would require a second `effective_marks`, a second teacher-override path, a
second weakness recompute, a second review queue, and a second aggregation for
class analytics — five duplications of logic the codebase has already been
burned by duplicating three times. The cost of the chosen design is one nullable
enum column and a discipline about NULL grades; the cost of the alternative is a
permanently forked marking universe.

**Skip `attempts.origin`; distinguish quizzes by `paper_id IS NULL`.** Free, no
migration. Rejected: `paper_id` is already nullable for past-paper attempts
whose paper was not matched in the catalogue, so the test would misclassify real
attempts as quizzes and drop them out of grade analytics. An explicit column
cannot be ambiguous.

**Give quiz attempts a grade by applying subject-default boundaries.**
Rejected outright: a curated ten-question quiz targeted at grade C has no
defensible mapping to a CAIE grade, and producing one would violate UI-spec
§1.4.6 in the most damaging possible place — a number a parent will read.

**Label past-paper difficulty with Gemini at ingest.** Better labels. Rejected
as the default for cost (a model call per question across the corpus, against a
hard budget ceiling) for a field that only orders a pool. `difficulty_source`
leaves the door open to do it later for a single subject as an experiment.

**A single `difficulty` band per target grade instead of a mix.** Simpler.
Rejected: a single-band quiz cannot discriminate within a grade, which is most
of what a teacher wants a targeted quiz for.

**Native PG enum for `question_type`.** Consistent with every other enum.
Rejected here alone: `QuestionType` is owned by the mark-scheme parser and will
gain members as new boards arrive, and each would force an `ALTER TYPE`
migration. Board-agnosticism beats local consistency in this one column.

**A separate quiz review queue.** Rejected in §4.5.

---

## 8. Testability notes

- `lemely/core/difficulty.py` is pure: table-driven tests over all seven grades
  × counts 1..30 asserting the allocation sums exactly to `count` and that no
  grade produces a single-band quiz for `count >= 3`.
- `is_grade_bearing`: assert the nine consumers in §5 by constructing a history
  containing one past-paper record and one quiz record and checking that topic
  functions see two and grade functions see one. One test file, one table.
- The synthetic-metadata trap (§4.3): mark a quiz submission end to end against
  a fake marker and assert the persisted `Attempt` has NULL `paper_number`,
  `paper_variant`, `session_month`, `grade`, `predicted_grade`,
  `boundary_source`.
- The review guard (§4.5): resolve an override on a quiz-origin attempt and
  assert `grade` is still NULL afterwards.
- Confidence: assert a quiz question marked below `REVIEW_CONFIDENCE_THRESHOLD`
  produces a `ReviewQueueItem` with `reason = low_confidence`, using the same
  fixture shape the past-paper persistence tests use.
- Tenancy: for every new route, a test that teacher B cannot read, patch,
  assign, or see results for teacher A's quiz, and that a student not enrolled
  in the assigned class cannot open the submission.
- Bank visibility: a test that teacher A's `teacher_upload` rows do not appear
  in teacher B's pool count — the hole the current disk-based pool has today.
