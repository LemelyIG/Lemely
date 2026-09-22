# Deleting an uploaded paper — decisions from interview

Date: 2026-09-21 · Status: decisions captured, **not yet a design spec**

This records what the product owner decided in interview. It is deliberately
not a design: no schema, no endpoints, no task breakdown. Those come next, and
should be written against this rather than re-deciding any of it.

## What exists today

`uploads` holds the scan's object key in GCS plus `status`, `page_count` and
the `idempotency_key` that migration 0036 dedupes on. Its model docstring
notes that the public "How Lemely handles your data" page cites this model for
what an upload keeps — **so changing what deletion removes is a change to a
published disclosure**, not only to a schema.

`attempts.upload_id` is a nullable foreign key with no `ondelete`, so today
nothing expects an upload to vanish. Attempts cascade to `question_results`,
the per-point ledger, and `review_queue`; quizzes hold `SET NULL`.

There is **no `deleted_at` anywhere in the schema**. This would be the first
soft delete in the product.

There is a working precedent for the purge job: the notification sweeper
(`lemely/web/scheduled_notifications.py`), started at app startup, gated by a
settings flag, made idempotent by a unique index rather than by locking.

## Decisions

**D1 — Delete means the scan and the result.** Not the scan alone. The
attempt, its question results, the points ledger and the marks feeding the
student's grade all go. The paper did not happen.

**D2 — Mark schemes are never deleted.** They are shared reference data
belonging to a paper, not to a student's upload. A student's deletion does not
touch `mark_schemes`.

**D3 — Soft delete, 30 days, then purge.** Optimistic hide on the client;
`deleted_at` on **`attempts` and `uploads`**, with the attempt's marker as the
gate every reader checks. Rejected: a marker on `uploads` alone (the marks
live on the attempt, so it would not hide the result), and moving rows to a
separate table (no reader changes, but foreign keys make the move awkward).

*Cost accepted:* roughly a dozen existing readers of `attempts` — paper
history, teacher class analytics, placement, study plan, weaknesses, standings
— must learn to exclude deleted rows, and a new reader must not be able to
forget. The design should make that structural rather than a discipline.

**D4 — A "Recently deleted" area, not a hidden safety net.** Deleted papers
sit in their own list for 30 days with restore and a countdown. The window is
a feature the student can use, not only a support-recovery mechanism.

**D5 — Who can delete.** The student who uploaded it. A teacher **cannot**
delete a student's paper — a teacher unshares it from their class instead
(D9). Teachers may delete papers they uploaded themselves.

**D6 — Recompute: the student's own view immediately, the rest at 5 minutes.**
Their grade, predicted grade and weaknesses update at once, because a student
who deletes a paper to fix their grade must see it change. Class averages and
placement recompute on a 5-minute deferral. Reversed on restore.

*Tension to resolve in the design, flagged not settled:* this creates two
recompute paths for the same number. The self-review spec's D5 accepted
self-reported marks reaching teacher averages specifically to keep **one
accessor and one number**, and `recompute_attempt_totals` exists as the single
implementation for the same reason. Two paths that disagree — even for five
minutes — is the drift both of those rules were written to prevent. The design
must either derive both from one function or state plainly why a bounded
divergence is acceptable here.

**D7 — XP and streaks never move.** Grades, weaknesses and placement
recompute; engagement history does not. A student did the work on the day they
did it, and deleting a paper months later does not retroactively break a
streak.

**D8 — An integrity-flagged paper cannot be deleted for 30 days**, matching
the purge window so the product carries one number rather than two. The
refusal copy is generic and **never names the reason** — QUALITY-BAR.md makes
integrity flags teacher-only, and "you can't delete this because it was
flagged for plagiarism" is exactly the accusation that rule forbids.

*Risk accepted:* a flag raised near a school holiday can expire before any
teacher looks at it.

**D9 — A teacher unshares, and it hides the paper from their view and from
that class's analytics.** Not cosmetic: it stops counting toward class
averages and per-question performance. The student is unaffected and keeps
their own copy.

**D10 — A student's delete proceeds over a teacher's in-flight work, and the
teacher is told.** An open `ReviewQueueItem` closes as withdrawn and the
teacher is notified, so nobody is left holding a queue item that silently
vanished. A mark the teacher already overrode does not block the delete.

## Open, for the design to settle

- Does purge delete the GCS object itself at 30 days, and what happens if that
  call fails — does the row survive to be retried, or is the row the record of
  intent?
- What a parent linked to the student sees, during the 30 days and after.
- Attempts with no upload (quizzes) — out of scope, or deletable by the same
  route?
- Whether the "How Lemely handles your data" page needs rewording once
  deletion exists, and who signs that off.
- The exact reader-exclusion mechanism for D3, given a missed reader leaks a
  deleted paper back onto a screen.

---

## Owner rulings, 2026-09-22

Put to the product owner after the design pass surfaced what the code makes
possible. Recorded verbatim in effect; where a ruling reverses the design's
recommendation that is noted, because the design argued the other way and the
owner's call stands.

**R1 — D6 amended, ratified. "One number, one instant."** The 5-minute
deferral is withdrawn. Every derived figure — the student's grade, predicted
grade and weaknesses, and every class average, at-risk count, parent card and
school roll-up — is computed on read from the same store and changes at the
moment the paper is hidden, changing back on restore. There is no second
recompute path. The deferral had nothing to attach to: implementing it would
have meant building a cache whose only purpose was to hold a number already
known to be wrong.

**R2 — D5's teacher clause is in scope now.** *Reverses the design's
recommendation to defer it.* Teacher-console papers (`teacher_papers`) get
their own soft delete in this work, mirroring the student flow exactly: the
same `RETENTION_DAYS`, a restore path, a recently-deleted surface and the same
purge sweeper pass. One retention number across the product.

**R3 — Unshare does remove the paper's open review items from that class's
queue.** *Reverses the design's v1 recommendation.* The queue is class-scoped,
so an unshared paper leaving it is the consistent behaviour. The design's
objection stands on the record: the teacher who unshares is the teacher who
would review it, so this hands them a way to clear their own queue. Accepted
knowingly.

**R4 — D8's block lifts when a teacher closes the integrity item.**
*Amends D8.* A block held for the full 30 days regardless of adjudication was
judged too blunt. Lifting outcomes are `resolved` **or** `dismissed` — both
mean a teacher looked, and the student is never told which.

**R4a — `withdrawn` never lifts the block.** A student must not be able to
lift their own hold by deleting and restoring the paper; that is exactly the
laundering cycle the restore-reopens rule closes.

**R4b — The timing signal is accepted, not papered over.** A paper that
refuses deletion on Monday and allows it on Thursday tells the student that a
teacher acted on something. Jitter was considered and rejected as unexplainable
in copy. The student learns that something was resolved, never what.

**R5 — The data-handling page is written by the implementer and reviewed by
the owner after merge.** *Reverses the design's blocking sign-off.* The
rewrite still ships in the same pull request; it simply does not gate the
merge. Noted as a risk: a published disclosure goes live before the owner has
read it.

**R6 — One pull request, everything.** *Reverses the design's split.* The
student flow, the loader criterion, purge, teacher-console deletion, unshare
and the page land together. Noted as a risk: the session-level loader
criterion is the highest-consequence mechanism here and would have been
reviewed in isolation under a split.
