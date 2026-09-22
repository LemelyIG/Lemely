# Deleting an uploaded paper — design

Date: 2026-09-22 · Status: design, **owner-ruled** (R1–R6), ready for plan
Decisions: `docs/superpowers/specs/2026-09-21-paper-deletion-decisions.md` (D1–D10, plus the owner rulings R1–R6 appended 2026-09-22)

Written against the interview record rather than re-deciding it. Every point
this design raised has now been ruled on. **The owner reversed four of this
document's recommendations** — R2 (teacher-console deletion is in scope),
R3 (unshare clears the class queue), R5 (the page is reviewed after merge,
not before) and R6 (one pull request, not a split). Those reversals are
reflected in the sections below; the arguments this design made against them
are left standing on the record rather than deleted, because they are the
reason to look twice if something goes wrong there.

## 1. Shape, in one paragraph

Soft delete via a session-level loader criterion on `Attempt` and `Upload`
with a single `include_deleted` escape hatch; attempt-id-keyed
delete/restore/recently-deleted routes in a new thin router
(`lemely/web/routers/student_deletion.py`, on the `student_self_review.py`
precedent); one `RETENTION_DAYS` constant shared by D8's hold and the purge
window; purge is GCS-first and row-as-intent, made safe against restore by
disjoint time windows with an hour's gap rather than by locks; unshare is a
separate `(class, attempt)` table applied through a class-scoped history
wrapper that also collapses `classes.py`'s three duplicated roster loops;
`withdrawn` and `review_withdrawn` enum members with reopen-on-restore; D6
amended to "one number, one instant"; the public data-handling page rewritten
in the same PR.

## 2. Three facts the decisions doc did not have

These are not re-litigations. They are verified facts that change what the
design must say.

### 2.1 Result URLs are positional, so deletion reorders them

`GET /student/result/{paper_id}` (`lemely/web/routers/student.py:549`) resolves
`paper_id` as an **integer index into the student's history list** — its own
docstring says `"0" = first recorded`. Delete paper 3 and every later paper's
URL now addresses its predecessor.

D3's optimistic client-side hide makes this worse rather than better: the
client removes row *i*, the student taps what was row *i+1*, and the client
still holds the pre-delete index. The server resolves it to a different paper
and renders someone's wrong result with full confidence.

**This is the single most likely way this feature ships visibly broken.**

Consequently:

- Every route in this design is keyed on **`attempt_id`**, never on a position.
  `PaperRecord.attempt_id` already exists (`lemely/core/history.py:57`) and
  `studentTypes.ts` already carries `attemptId?: string | null`.
- The optimistic hide covers **the disappearance of the deleted row only**. It
  is never trusted for the neighbours' links. The client refetches the
  overview before any navigation that depends on ordering.
- Migrating `/student/result/{paper_id}` itself to attempt-id addressing is
  already in flight in the self-review series and is **not** in this spec's
  scope. This spec must not make the positional route worse, and the e2e test
  in §11 pins that it does not.

### 2.2 D5's teacher clause lands on a different table

"Teachers may delete papers they uploaded themselves" is about `TeacherPaper`
(`lemely/db/models/teacher_papers.py`) — its own `storage_path`, its own branch
of the review queue, and **no `Attempt` row at all**. Nothing in this design's
attempt-level `deleted_at` reaches it.

This design recommended deferring it. **The owner ruled otherwise (R2): it is
in scope now, mirroring the student flow exactly** — `teacher_papers.deleted_at`,
the same `RETENTION_DAYS`, a restore path, a recently-deleted surface and the
same purge sweeper pass.

What that means concretely, and why it is not simply "the same code twice":

- `TeacherPaper` needs its own `deleted_at` and its own loader criterion in the
  same listener (§3.1), so the entity tuple becomes `(Attempt, Upload, TeacherPaper)`.
- Its review-queue branch is the `teacher_paper_id` one, so the withdraw/reopen
  rule of §6 applies to it through a different foreign key.
- There is **no student and no integrity hold**: D8 exists to stop a student
  destroying evidence about themselves, and a teacher deleting their own console
  upload is not that. Applying the hold here would block a teacher on the
  strength of a flag raised against a paper with no attributed student at all.
- Its per-question marks live in `teacher_papers.report_json`, not in
  `question_results`, so nothing cascades — purge deletes one row and its object.

**Risk carried:** two soft-deleted tables ship in one change rather than one,
and the second has no prior art in this codebase to copy from.

### 2.3 A published disclosure goes false on deploy

`web/src/portals/marketing/dataHandling.ts` ships a labelled panel:

> **There is no way to delete any of this** — "Lemely has no account deletion
> and no way to remove a scan you have uploaded. Nothing is deleted on a
> schedule either…"

and a module docstring saying "No retention period, because there is no
retention machinery… nothing in `lemely/` purges, expires or anonymises
anything, which was verified rather than assumed."

Both become false the moment this route deploys. The decisions doc's fourth
open question was "whether the page needs rewording"; the answer is that it
does, and the copy ships **in the same pull request as the route**, not as
follow-up. See §10.

## 3. D3 — making the exclusion structural

The decisions doc demands a mechanism where a *new* reader **cannot** forget,
"structural rather than a discipline". Four candidates were weighed.

| Option | What a new reader must do to leak a deleted paper | Why rejected / accepted |
|---|---|---|
| (a) Filter inside `DbHistoryStore.load` | Simply not use the history store — which every bypass reader in §3.2 already does | Covers the ~15 router call sites and nothing else. It is precisely the `grade_bearing` precedent whose own docstring concedes it is a discipline. **Rejected as insufficient alone.** |
| (b) `with_loader_criteria` on `Session.do_orm_execute` | Nothing. A bare `select(Attempt)` is filtered; seeing deleted rows requires a deliberate opt-in | **Shipped.** The only option where the default is safe and leaking is an act. |
| (c) `live_attempts()` builder + source-lint guard test | Write `select(Attempt)` instead | The guard is a regex over source; `session.get(Attempt, …)` and `.join(Attempt, …)` are two shapes it misses on day one, and an incomplete pattern list is a test that cannot fail. **Rejected.** |
| (d) Database view + `LiveAttempt` model | Use `Attempt`, which is what every existing file imports | Option (c) with more ceremony: writes, cascades and relationships stay on `Attempt`, so the obvious class name stays the leaky one. Doubles the model surface. **Rejected.** |

### 3.1 The mechanism

Registered in `lemely/db/session.py`'s module body, at the **class** level:

```python
@event.listens_for(Session, "do_orm_execute")
def _exclude_soft_deleted(state): ...
```

Class-level, not on the sessionmaker instance, because `sessionmaker` is
constructed in two independent places — `lemely/db/session.py:97` and
`tests/conftest.py:470`. An instance-level listener would leave the entire
test suite unfiltered, which is the worst possible failure: green tests over
an unprotected mechanism.

Fires when `state.is_select and not state.is_column_load and not
state.is_relationship_load` and the execution options do not carry
`include_deleted`. Adds `with_loader_criteria(Attempt, lambda cls:
cls.deleted_at.is_(None), include_aliases=True)` and the same for `Upload`.
`propagate_to_loaders` (default `True`) carries it into the `Upload.attempts`
and `Attempt.upload` relationship loads.

`include_deleted=True` is the **sole** escape hatch, permitted in exactly three
callers: the recently-deleted list, restore, and the purge job.

**Schema (migration `0039`, head is `0038_point_group_key`, nothing branched):**
`deleted_at TIMESTAMPTZ NULL` on `attempts` and `uploads`, plus a partial index
`ix_attempts_deleted_at WHERE deleted_at IS NOT NULL` — the purge candidate
query and the recently-deleted list are its only readers and both are small.

### 3.2 What happens to every reader that bypasses the history store

- `seat_repo.py:369` — `select(Attempt.user_id, func.max(Attempt.recorded_at))`,
  a **column-only** ORM select. Whether `with_loader_criteria` reaches the entity
  in the FROM of a column-only select is the **one piece of SQLAlchemy behaviour
  this design has not confirmed in this repo**. §11 names a test with exactly
  this shape. If the criteria do not apply, this reader gets an explicit
  `.where(Attempt.deleted_at.is_(None))` and that test pins it.
- `study_plan_repo.py:367`, `practice_repo.py:820`, `flashcard_repo.py:804` —
  `.join(Attempt, Attempt.id == WeaknessRecord.attempt_id)`. Criteria land in the
  ON clause; a deleted attempt's weakness rows drop out.
- `placement_repo.py:332`, `practice_repo.py:565`, `self_review_repo.py` —
  `session.get(Attempt, id)`. On a cold session this emits a SELECT through the
  ORM, so a deleted attempt reads as `None` and the routes' existing 404 paths
  fire unchanged. Documented caveat: `session.get` returns from the identity map
  without SQL when the object is already loaded in that session — which only
  arises inside the delete service itself, where it is the desired behaviour.
- `review_repo.list_queue` joins `Attempt`, so open items for a deleted attempt
  leave the queue **structurally**, before D10's status flip. The flip exists for
  the audit trail and for restore (§6), not to hide the row.
- `quiz_results_repo.py:352` — filtered, and harmless: quiz-origin attempts are
  not deletable (§9).
- `admin_repo.py:373` — boundary-source counts stop including deleted attempts.
  Correct; ops gets the purge-backlog metric (§7) instead.
- Writers (`attempt_repo.py`, `quiz_marking_repo.py`, `teacher_paper_repo.py`) —
  INSERT/UPDATE are not `is_select`, so they are unaffected.

**Corollary, verified: `WeaknessRecord` and `QuestionResult` need no criteria of
their own.** Every direct reader of either is reachable only through an attempt —
by a join to `Attempt`, or keyed on an `attempt_id` obtained from an `Attempt`
read. This is a property of today's code, not a guarantee: a future
`select(WeaknessRecord).where(user_id == …)` would break it silently, which is
why §11 backs it with behavioural tests per reader rather than a comment.

### 3.3 The anti-vacuity rule for this mechanism

**Do not add a belt-and-braces `.where(deleted_at.is_(None))` inside
`DbHistoryStore.load`.** If you do, every history test passes even when the
listener is dead, and the listener's only guardian becomes its own unit test.
Left clean, every existing history test is also a listener test.

The listener's own guards are (i) `event.contains(Session, "do_orm_execute",
handler)`, and (ii) a live-Postgres test on a fresh session from
`get_sessionmaker()` asserting the row **is** returned before stamping, **is
not** after, and **is** again under `include_deleted=True` — three assertions on
one row, so it cannot pass against an empty database.

**Trade accepted:** the listener is invisible — a developer printing their SQL
sees a `WHERE` they did not write. Mitigated by a module docstring in
`session.py` naming the escape hatch and this spec.

## 4. D6 — amended: one number, one instant

The decisions doc flagged this tension and deliberately refused to settle it,
asking the design to either derive both paths from one function or state
plainly why a bounded divergence is acceptable.

**The finding: there is no second path to reconcile, because there is nothing
stored to recompute.** `classes.py::_class_row_to_summary` computes the class
average, at-risk count, ranked topic weaknesses and last-activity **live on
every request** from `history_store.load(student_id)` per roster entry
(`:217`, and the same loop at `:298` and `:404`). There is no materialised class
aggregate, no standings table and no cache — `/student/standings` is
structurally empty today. The only stored derivative of attempts is
`StudyPlan`/`StudyPlanSession`, which is already stale-by-design relative to new
uploads and is correctly untouched by deletion.

So the 5-minute deferral has no substrate to attach to. Implementing it would
mean **building a cache whose only purpose is to hold a number the store
already knows is wrong.** That is not a bounded divergence; it is manufacturing
one, and it is exactly the drift the self-review spec's D5 and
`recompute_attempt_totals` exist to prevent.

> **D6 (amended) — One number, one instant.** Every derived figure — the
> student's grade, predicted grade and weaknesses, and every class average,
> at-risk count, parent card and school roll-up — is computed on read from the
> same store, so all of them change at the moment the paper is hidden and change
> back at the moment it is restored. There is no second recompute path and no
> deferral. The 5-minute deferral from the interview is withdrawn, because the
> codebase has nothing that could be deferred without first building a cache to
> make it stale. The one stored derivative, a student's study plan, is not
> regenerated by deletion — exactly as it is not regenerated by a new upload
> today.

**This reverses a decision the product owner made in interview and requires
their ratification before the plan's Task 1 lands.**

Two readings where "5 minutes" could have survived were considered and
rejected. A *teacher-visible settling period* (student sees it gone, teacher
sees it for five more minutes) is literally two numbers for one figure. A
*notification debounce* for D10 — a student deleting eight papers generating
eight withdrawal notices — is real and cheap, and is the only reading where the
number means anything; it is listed as follow-up rather than built, because
keeping "5 minutes" in the spec for that alone would mislead the owner about
what it does.

## 5. D9 — unshare

Grep confirms **no per-paper sharing concept exists anywhere today**; teacher
visibility derives purely from class enrollment. This is the first one.

**Grain: `(class, attempt)`.** Not `(teacher, attempt)` — a class has owners and
administrators, and "their view" of a class is the class's view. Not
`(class, student)` — D9 is explicitly per paper. A student in two classes,
unshared in one, still counts in the other, which is what "that class's
analytics" means.

**Table** `class_paper_exclusions(class_id FK classes CASCADE, attempt_id FK
attempts CASCADE, excluded_by FK users SET NULL, created_at)`, primary key
`(class_id, attempt_id)`. A column on `attempts` cannot hold a set of classes,
and a JSON array is the wrong tool for something that needs a join.

**Application.** `history_store.load(student_id)` has no class context and must
not grow one: `HistoryStoreProtocol` (`lemely/core/history.py:150`) is
`load`/`append`/`list_students` and is satisfied by the JSON file store for the
CLI, where a `class_id` parameter is meaningless.

Ship a **class-scoped wrapper** — `ClassScopedHistoryStore(inner, exclusions,
class_id)` satisfying the same protocol, dropping excluded attempt ids after the
inner load. `classes.py` obtains it through one helper that simultaneously
replaces the three duplicated roster comprehensions at `:217`, `:298` and `:404`.
A future class-analytics site reaching for the raw `history_store` is then
visibly wrong in review, because the module convention is the wrapper.

Rejected: a post-filter helper beside `grade_bearing`, which is precedent-
consistent but leaves every class route remembering to call it — discipline
again.

**Trade accepted:** one small class and one extra query per class request (a
single `select(attempt_id) WHERE class_id = :c`, not one per student). Gained:
one implementation of the filter, and the pre-existing triplication goes away
with it.

**The student is unaffected structurally, not by care:** the exclusions table is
read only by the wrapper, and the wrapper is constructed only in `classes.py`.
`student.py`, `parent.py`, `school.py` and the self-review router never see it.

**Per-question class performance** is named by D9 but has no surface today —
`classes.py` holds only history loads, and the per-question class views that
exist are over quiz assignments, which are not paper attempts. The spec says so
rather than claiming an exclusion reaches something that does not exist.

**Unshare removes the paper's open review items from that class's queue (R3).**
This design recommended leaving the queue alone; the owner ruled for
consistency, the queue being class-scoped.

The objection stands on the record and shapes the implementation: the teacher
who unshares is the teacher who would review it, so this is a route by which a
flagged paper leaves the queue of the person meant to look at it. Two
consequences follow, and both are requirements, not suggestions:

- **Unshare must not change the item's `status`.** It is filtered out of the
  class's queue view by the exclusion join, exactly as the paper is filtered out
  of the class's analytics. It is *not* marked `withdrawn` — that status means
  the subject was deleted, and reusing it here would make a teacher's reversible
  toggle indistinguishable from a student's deletion, and would feed `withdrawn`
  into R4a's blocked set for no reason.
- **Resharing restores the item to the queue unchanged**, with its original
  `created_at`, because nothing about it was ever mutated.

So the queue filter is one more reader of `class_paper_exclusions`, joined in
`review_repo.list_queue`'s class-scoped branch — not a write path.

**Audit consequence to accept:** an integrity-flagged paper can be removed from
a class queue by a teacher with no record beyond the exclusion row. The
`excluded_by` column is therefore not optional bookkeeping; it is the only
trace that this happened.

**Unshare and delete stay separate mechanisms** — different actor, grain,
lifetime and disclosure. Sharing `deleted_at` for both would make a teacher's
reversible toggle indistinguishable from a student's deletion in every audit
and every reader.

## 6. D10 — in-flight teacher work

**`dismissed` is not honestly reusable.** `ReviewRepository.dismiss` is a
teacher's action that stamps `resolved_by`; recording a student's deletion as
`dismissed` lies in the audit column and makes every dismissed-by-teacher
metric count student deletions. The distinction is real.

Migration `0039` adds `ReviewStatus.withdrawn` and
`NotificationType.review_withdrawn` — `ALTER TYPE … ADD VALUE`, with precedent
in `0019_activation_review.py`, `0034_parent_invites.py` and
`0037_question_result_points.py`.

**Sequence.** In the same transaction that stamps `deleted_at`, every `open`
item on the attempt flips to `withdrawn` with `withdrawn_at` **exactly equal to
the attempt's `deleted_at`** — that equality is what lets restore identify
precisely the items this deletion took. After commit, `notify_safely` with
`type=review_withdrawn`, `dedupe_key=f"review_withdrawn:{item_id}:{deleted_at.isoformat()}"`
(the timestamp lets a delete → restore → delete cycle notify twice, which it
should) and a payload of the review item, attempt and student ids. The body
names the student and the paper and **never** why — we never ask why.
Target: `assigned_teacher_id` when set (`ops.py:93`), else the item's visible-class
teacher set. A teacher who already overrode a mark is not blocked; their
revision rows cascade at purge with everything else.

`NotificationService.create` is preference-gated, so the new type needs a default
wherever notification preferences are governed.

**The hole D10 does not mention, and the requirement that closes it.**
Delete withdraws the item; restore brings the paper back **but not the item**.
For a low-confidence item that is a silently lost review. For an integrity item
past D8's window it is a student clearing their own flag out of a teacher's
queue — a laundering cycle.

> **Restore must reopen every item that this deletion withdrew** — selected by
> `status = withdrawn AND withdrawn_at = attempt.deleted_at`, set back to `open`.

Reopened silently, retaining its original `created_at` so it sorts where it
always did. A third enum member for a rare path is not worth it. This is a hard
requirement with its own test (§11).

## 7. Purge, and the GCS object

**Settled:** purge deletes the object, GCS first, and the row is the record of
intent.

Per attempt: (1) `storage.delete(bucket, upload.storage_path)` — already
idempotent, since `storage_gcs.delete` documents "a missing object is not an
error" and swallows `NotFound`. (2) On success, one transaction:
`DELETE FROM attempts WHERE id = :id AND deleted_at <= :cutoff` — cascades take
`question_results` → points and revisions, `weakness_records`, and `review_queue`
— then delete the `uploads` row if no attempt, live or deleted, still references
it. The attempt must go first because `attempts.upload_id` carries no `ondelete`.

If (1) raises `ExternalServiceError`, log at warning and **leave both rows**:
still hidden, still past cutoff, retried next pass. DB-first would leak orphan
objects that no row remembers, which is precisely what the disclosure page
would then be lying about; GCS-first only ever leaves a row a little longer.

**The mark-scheme sibling.** A student's own uploaded `mark_scheme.pdf` sits
under the same object prefix `uploads/{user}/{paperId}/`
(`student.py:1023`). D2 protects the `mark_schemes` **table** — shared reference
data — and says nothing about a student's private scan of a scheme. Purge
deletes the whole prefix, scan and sibling; `mark_schemes` rows are never
touched. Recorded as a **D2 clarification**, not a change.

**Safety against restore comes from disjoint time predicates, not locking.**
Hard-deleting a row is already idempotent — a second run matches zero rows. The
race that matters is purge versus restore, and it is closed by a gap:

- Restore: `UPDATE attempts SET deleted_at = NULL WHERE id = :id AND user_id = :me
  AND deleted_at IS NOT NULL AND deleted_at > now() - RETENTION` — rowcount 0 → 410.
- Purge candidates: `deleted_at <= now() - RETENTION - GRACE`, with `GRACE` one
  hour to absorb clock skew between replicas.

Restore can only win while the row is younger than 30 days; purge only once it
is older than 30 days plus an hour. They can never both succeed on one row, so
GCS-first can never strand a restored paper without its scan. Two replicas
purging the same row: both call GCS delete (the second is `NotFound`), both run
the conditional DELETE (the second matches nothing). **The purge `DELETE` must
carry `deleted_at <= cutoff` in its own WHERE** — never `WHERE id IN (ids
selected a moment ago)`.

**Trade accepted:** a paper deleted at exactly 30 days is un-restorable for one
hour before it is purged. The D4 countdown shows "0 days" as gone.

**Job shape.** One more job on the existing `Sweeper`, every pass, `LIMIT 50`,
`include_deleted=True` on its candidate select, gated by the same
`settings.notifications.sweeper_enabled` the other three use (already forced off
under test by `tests/conftest.py`).

`RETENTION_DAYS = 30` lives as **one constant** in `lemely/core/deletion.py`,
imported by both D8's hold and the purge window — the decisions doc's "one
number rather than two" applies to the code as much as to the product. It is
deliberately **not** a settings knob: a configurable retention makes the public
disclosure page conditional on deployment config.

**Backlog visibility.** An attempt with `deleted_at <= cutoff - 1 day` still
present means purge is failing. Expose that count beside the boundary-source
metric in `admin_repo`. No retry-counter column; the warning log plus this
metric is enough for v1.

**One easily-missed detail:** `ux_uploads_user_idempotency` survives the soft
delete, so a student who deletes and re-uploads the same scan with the same
client key collides with a hidden row and falls into
`_retry_after_releasing_stale_key`. **Null the `idempotency_key` at soft-delete
time.**

**One FK ordering risk:** `review_queue.question_result_id` has no `ondelete`
while `review_queue.attempt_id` cascades. Postgres evaluates NO ACTION at end of
statement and the queue row is itself removed by the attempt cascade in the same
statement, so this is expected to work — but it is not signed off without the
fully-populated fixture in §11. If it fails, the fix is `ondelete="CASCADE"` on
that FK in the same migration.

## 8. D8 — the integrity hold, told honestly

**Predicate, as ruled (R4).** The paper is blocked when **all three** hold:

1. `EXISTS (question_results WHERE attempt_id = :id AND (plagiarism_flagged OR
   ai_detection_flagged))` — the flags are the source of the fact. Never
   `review_reason` text, never the mere presence of a review row; both are
   echoes, and an echo can be resolved away while the fact stands.
2. `now() < attempt.recorded_at + RETENTION_DAYS` — the flags are written at
   marking time, so `recorded_at` is the clock. Do not invent a `flagged_at`.
3. **No integrity review item on the attempt has been closed by a teacher** —
   that is, no `ReviewQueueItem` with `reason IN (plagiarism_flag,
   ai_detection_flag)` and `status IN (resolved, dismissed)`.

Condition 3 is R4's amendment: a teacher who closes the item lifts the hold,
whether they resolved it or dismissed it. Both mean a teacher looked, and the
student is never told which.

**`withdrawn` is excluded from condition 3, deliberately (R4a).** A student must
not be able to lift their own hold by deleting and restoring the paper. Restore
reopens what deletion withdrew (§6), so a cycle leaves the item `open` and the
block standing — but only if `withdrawn` is absent from the lifting set. Putting
it there would reopen the laundering hole from the other side. This needs its own
test, because it is the kind of set membership that looks harmless in review.

**API:** `409 Conflict`, body `{"detail": "This paper can't be deleted yet.",
"deletableFrom": "<ISO date>"}`. No reason, no review language.

**The tension the decisions doc did not name.** The *existence* of a block is
itself a differential signal, because an unflagged paper deletes instantly.
Generic copy hides the reason; it does not hide the fact. Truly closing that
would mean blocking every paper with any open review item, which changes D8 —
so do not. What this design does instead is refuse to make it worse:

> **The paper list must not pre-signal deletability.** No `canDelete` or
> `deletableFrom` field on the history row, no greyed-out control. The block is
> discovered on the POST.

**Trade accepted:** the student taps delete and is refused. Gained: no screen
ever marks one paper as different from another before the student acts.

Copy: *"This paper can't be deleted yet. You'll be able to delete it from
21 October."* A student with an ordinary low-confidence item deletes fine, so
the word "review" must not appear either.

**The cost that R4 buys, and the one it creates.** A cleared student no longer
waits 27 further days for nothing — that was the point of the amendment. In
exchange, **the lift is itself a signal**: a paper that refuses deletion on
Monday and permits it on Thursday tells the student that a teacher acted on
something in between. Jitter (holding a random further 1–7 days) was considered
and rejected as unexplainable in the refusal copy, which must name a date.

**Ruled accepted (R4b), and recorded rather than papered over.** The student
learns that something was resolved; they never learn what it was, and no screen
ever names it. That is a weaker guarantee than D8's original, and it is the
owner's call knowingly made.

One implementation consequence: because the deletable date can now move earlier,
the `deletableFrom` in the 409 body is a **statement about now**, not a promise.
The copy must not say "you will be able to delete it on X" in a way that reads
as a commitment the system might beat.

## 9. The remaining open questions, settled

**Parents.** `parent.py` reads only through `history_store.load`, so a parent's
card, trend and last-activity change at the instant of deletion and look
identical after purge. **Parents see the student's live history and nothing
about deletion**; the recently-deleted area is student-only. Surfacing "your
child deleted a paper" would turn the student's own safety window into
surveillance, and no parent surface for it exists today. Named consequence: a
parent may notice a grade move and ask. That is a conversation, not a UI.

**Quizzes and other upload-less attempts: out of scope, refused at the route.**
There is no object to purge; the motivating case ("fix my grade") does not apply
because `is_grade_bearing` already excludes quizzes; and
`quiz_submissions.attempt_id` is `SET NULL`, so a deleted quiz attempt would
leave a submission pointing at nothing and `_load_attempts` rendering a "missing"
state nobody designed. Placement-test attempts likewise. Backend: `origin !=
past_paper OR upload_id IS NULL` → `409 {"detail": "Only uploaded papers can be
deleted."}`. Distinct copy is safe here because a quiz is visibly a quiz —
nothing integrity-shaped is being concealed. The frontend never offers the
action, because quizzes are not in the paper list.

**D7 — XP and streaks — verified, no action.** XP events carry no foreign key to
attempts, so purge cannot move them. The paper seam dedupes on
`str(owned.id)`, the **upload** id (`student.py:1116`), so delete-then-reupload
does mint a new key and award again — but that is bounded by the pre-existing
`paper_corrected: 5`-per-day cap and is already reachable today by uploading the
same scan under five idempotency keys. **Deletion opens no new XP farm.**

## 10. The disclosure page

Ships **in the same pull request as the route**. Three files:
`web/src/portals/marketing/dataHandling.ts` (the `notYetBuilt` panel and the
"no retention machinery" docstring), and the `Upload` model docstring in
`lemely/db/models/attempts.py`, which names the page as citing it.

The copy must state: what deletion removes (the scan file and its sibling scheme
scan, the upload row, the marks, per-question points and history, and the
weaknesses); what it keeps (mark-scheme reference data per D2; XP and streak
history per D7; and the teacher's notification that a review item was
withdrawn — that is a surviving record that a paper existed, and the page should
say so); the 30-day window, and that the file remains in Google Cloud Storage
during it; and the hold, worded without a reason — *"In some cases a paper can't
be deleted for up to 30 days after it was marked; Lemely tells you the date when
that applies."*

**Sign-off (R5): the implementer writes it, the owner reviews after merge.**
This design asked for a blocking checkbox; the owner ruled it non-blocking. The
rewrite still ships in the same pull request.

**Risk carried, stated once:** a published disclosure about how a product
handles people's data goes live before the person accountable for it has read
it. The mitigation available inside the change is to make the copy hard to get
quietly wrong — the tests in §11 assert what the page must say (the window, what
goes, what stays) and what it must not (any naming of the hold's reason), so a
wrong version fails CI rather than merely reading oddly.

## 11. Test strategy, aimed at the vacuity trap

The branch this work follows had "tests that cannot fail" as its dominant defect
class. Every item below is written so that it fails against an empty database.

1. **The listener** — `event.contains` guard, plus the three-assertion
   presence → absence → `include_deleted` presence test on one row.
2. **The unconfirmed SQLAlchemy shapes** — one test with `seat_repo`'s exact
   column-only `select(Attempt.user_id, func.max(...))` shape, and one with
   `session.get(Attempt, id)` on a fresh session. If either leaks, the explicit
   `.where` goes there and these tests pin it.
3. **Per-bypass-reader behavioural pairs** — `seat_repo`, `study_plan_repo`,
   `practice_repo`, `flashcard_repo`, `admin_repo` each get a presence-then-absence
   pair **through their own function**, never through `load()`.
4. **Restore reopens** — open item → delete → restore → the item is `open` again
   with the same id and `created_at`.
5. **The purge fixture must be fully populated** — an attempt with question
   results, points, revisions, weakness rows, an upload **and** a review item
   with `question_result_id` set, or the FK-ordering question in §7 is never
   exercised. Mock the storage backend but assert `delete` was called with the
   exact `(bucket, storage_path)`; test that the `ExternalServiceError` branch
   leaves both rows; test that a row younger than cutoff is untouched.
6. **Unshare** — deep-equal on the student's `OverviewDTO`/`ResultDTO` before and
   after, **and an inequality on the class average in the same test**. Without
   the inequality the equality proves nothing.
7. **The D8 non-leak** — four assertions: flagged → 409; open low-confidence item
   and no flag → 204 (the predicate is the flag, not "has review"); the fully
   serialised 409 body matches none of the forbidden segments, reusing the list
   `student_safe_review_reason` already maintains rather than a second copy; and
   **the same checker run over a deliberately leaky payload, asserting it
   rejects**. A leak detector never shown to detect is the definition of a test
   that cannot fail.
8. **`include_deleted` containment** — a narrow lint test that the literal token
   appears only in the deletion service, the purge job and `session.py`.
9. **The positional-URL e2e** — delete paper *i*, open what was *i+1*, assert the
   title is the paper the student tapped.

## 12. Rulings, and what they cost

Nothing here is open. All seven questions were put to the owner on 2026-09-22
and answered; the full text is appended to the decisions document.

| Ruling | Outcome | Cost carried |
|---|---|---|
| R1 — D6 amended | Ratified: one number, one instant | None. The live-read architecture gives it for free. |
| R2 — D5 teacher papers | **In scope now**, mirroring the student flow | Two soft-deleted tables in one change; the second has no prior art to copy. |
| R3 — unshare and the queue | **Clears the class queue** | A teacher can remove a flagged paper from their own queue; `excluded_by` is the only trace. |
| R4 — D8 lift | **Lifts on `resolved` or `dismissed`** | The lift is a timing signal (R4b, accepted). Predicate now reads queue state, not only the flags. |
| R4a — `withdrawn` excluded | Never lifts the block | None, provided the test exists. Getting this set wrong reopens the laundering hole. |
| R5 — page sign-off | **Reviewed after merge** | A data-handling disclosure publishes before the accountable person reads it. |
| R6 — delivery | **One pull request** | The loader criterion — the highest-consequence mechanism here — is reviewed inside a large diff rather than alone. |

Four of these reversed this document's recommendation. The arguments are left
in place above rather than edited out, so that if one of the costs above is
paid for real, the reasoning is still there to read.

**Where to look first if something goes wrong:** R4a (a student lifting their
own hold), R3 (a flagged paper quietly leaving a queue), and R6 (a defect in
the loader criterion reaching production inside a large review).
