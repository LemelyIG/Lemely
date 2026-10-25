# Tutoring SPEC: adversarial review

**Reviewer:** critic (Opus), 2026-10-25, using the `engineering-skills:adversarial-reviewer` personas (Saboteur, New Hire, Security Auditor) plus an ops pass.
**Target:** `docs/tutoring/SPEC.md` (1,194 lines) and `docs/tutoring/adr/ADR-T01..T04`, read against `BUILD/tutoring/decision-log.md` (all rows LOCKED), `BUILD/tutoring/recon.md`, `DELIVERY.md` §3–§5, `tests/test_authz_matrix_complete.py`, and `docs/LEMELY_UI_SPEC.md` §1.
**Tree:** worktree `feat/tutoring-marketplace` at `314ef8ec`. The marking pipeline was out of scope.

**Verdict: REVISE. Wave 4 (outcomes) is blocked until F1 is resolved.**
**Counts:** 1 blocker, 17 major, 18 minor (36 findings).
**Mode:** escalated to adversarial after F1 and the third major finding. Locked decisions are not findings here. Where the SPEC fails to honour a locked row, or quietly softens one, that is flagged.

**Method.** Every claim the SPEC makes about the codebase was checked by a direct read at the worktree's HEAD. Two throwaway-database probes ran on the local Supabase Postgres 17.6 (SQLAlchemy 2.0.51, Alembic 1.18.5); each created its own database and then dropped it. The Cairo DST instants were checked with `zoneinfo`.

**What is solid.** The route count and the authz arithmetic check out: 60 routes, 58 new 401 cases, 221 new 403 cases, and the section counts 12/63/3/4/9 match the test file. The grant gate also stands up: one repository method, a SQL predicate with a parity test against the pure function, and a fail-closed audit write.

---

## Blocker

### F1 · blocker · A tutor can read the grade of a student who never granted access, on demand, through the outcome figures
**Location:** ADR-T04 §Definitions (the cohort is built from completed bookings); SPEC §a.3, the booking transition table (`accepted → completed`: the tutor is the only actor, guard `now >= starts_at`); T8 `GET /api/tutor/profile/preview` returns `OutcomesDTO` "as students would see it, any listing state" (L486); §e.1 `tutor_outcomes`.
**Evidence:** The cohort is "distinct students with ≥ 1 `completed` booking" (ADR-T04 L49–50), and only the tutor writes `completed` (SPEC L348). The tutor can see the figure through T8. Any account can also see it through SP4, because student self-signup is open (DELIVERY §3, issue #10). ADR-T04 L101–102 does name differencing, but only as "a viewer who sees the figure before and after one student joins". It misses that the one party who knows who every member is also controls the moment each member joins.
**Failure scenario:** A tutor has 5 students in 0625, so the figure shows as sufficient. Student X has a session with the tutor but never granted access. The tutor opens T8 (D0), marks X's booking completed (T14), and opens T8 again (D1). D1 − D0 is X's bucket in the distribution and X's higher/same/lower result in the change figure. The tutor can repeat this for every new student. X also leaks again on opting out, because opt-out is "effective on the next read" (L1159), and again on uploading a paper inside `[S, E+60d]`. This defeats row 3b's grant model, where a tutor sees a student's grades only with a grant, and it breaks MISSION §3. k ≥ 5 does not help: k limits how small the set can be, not how small a change can be.
**Fix (compatible with locked rows 8/8b, which fix default-on counting and k but not when figures update):**
1. A member contributes only once their window has closed (`now ≥ E + DURING_GRACE`), and only with papers recorded before that point.
2. Evaluate every figure as of the first day of the current month. This is computed when the page is read, so no scheduler is needed, and a click never moves the figure.
3. If fewer than 2 members changed since the last as-of date, keep showing the older figure.
4. Apply an opt-out at the next as-of date, and say so in the notice.
5. Exclude students who have blocked the tutor. Today they stay counted, because L1062 subtracts opt-outs only.

Add a test: complete one booking, re-read T8 and SP4, and assert the `OutcomesDTO` is byte-identical. These steps reduce the leak but do not remove it, so record the remaining risk in ADR-T04. Raise the timing change with the user alongside O-3, because it changes when figures update.

---

## Major

### F2 · major · Registering the tutoring models breaks every DB test that builds its schema with `create_all`
**Location:** §a.4 L396 ("The ORM models declare the same constraints … so `alembic check` stays clean"); §e.3 ("Every model module is registered in `import_all_models()`").
**Evidence:** About 88 test files build their schema with `CREATE DATABASE "lemely_test_…"` followed by `Base.metadata.create_all(engine)`, for example `tests/test_web_platform_admin.py:83-104` and `tests/test_db_schema.py:319-337`. Only `migrated_sessionmaker` (`tests/conftest.py:617`) runs the migrations. A new database starts without `btree_gist`. **Probe:** `create_all` of the SPEC's `tutor_availability_rules` and `tutor_bookings` on a fresh database fails with `data type uuid has no default operator class for access method "gist"`. With the extension installed, it succeeds. CI's `postgres:16` template1 has no `btree_gist` either.
**Failure scenario:** The wave 1 PR turns the whole Postgres-backed suite red, not just the tutoring tests.
**Also wrong:** the stated reason for declaring the constraints. **Probe:** `compare_metadata` reports 0 diffs whether or not the ORM declares the ExcludeConstraints. Declaring them does nothing for `alembic check`. The real value is that `create_all` test databases then contain the constraints the tests depend on.
**Fix:** Keep the ORM declarations. Add `event.listen(Base.metadata, "before_create", DDL("CREATE EXTENSION IF NOT EXISTS btree_gist"))` in `lemely/db/base.py` (or in the tutoring models module). Add a test that `CREATE DATABASE` plus `create_all` succeeds on a fresh database. Correct the reasoning at L396.

### F3 · major · Writing the inbox row "in the same transaction as the state change" is impossible with the existing service, and contradicts binding decision D5.9 §1
**Location:** §b.4 heading (L656) and rules (L670); §e.3 L1056 ("transition + inbox + outbox … is one transaction"); §e.4 L1085.
**Evidence:** `NotificationService.create` opens and commits its own session (`with self._sessionmaker() as session, session.begin():`, `lemely/db/notification_repo.py:292-361`). It reads preferences in a separate call and takes no session argument. The header of `lemely/web/notify.py` says: "Every seam that produces a notification does so *after* the thing being announced has already committed … D5.9 §1 is binding". It also makes `notify_safely` "the **single** place `lemely.web` calls `NotificationService.create`". Push is only sent through `notify_safely`.
**Failure scenario:** The implementer has two options and both are bad:
- Write `Notification` rows directly inside the booking transaction. That bypasses the preference gate, duplicate handling and push, and creates a second call site.
- Call `notify_safely` after commit. Then the SPEC's claim is false. The §e.4 "transactionality" test proves nothing either way, because a failed transition never reaches the notify call.

**Fix:** Decide this explicitly. Recommended: write the outbox row inside the transaction (it is the SPEC's own table), and send inbox plus push through `notify_safely` after commit, as D5.9 requires. Rewrite L656, L670 and L1056. Replace the §e.4 test with this one: the transition commits while the inbox write raises; the transition still returns 200, the outbox row exists, and the error is logged.

### F4 · major · "No scheduler" is false, and both the locked rationale and the proposed DELIVERY text rest on it
**Location:** recon.md L18; ADR-T02 L16; ADR-T04 L81; SPEC §g L1155 ("No scheduler, so nothing happens on its own"); §b.4, which sends email from a FastAPI `BackgroundTask`.
**Evidence:**
- `lemely/web/app.py:63-90` starts `run_sweeper` when the app starts.
- In `lemely/runtime/config.py:922-948`, `sweeper_enabled = True` by default and the sweep runs every 60 s.
- `lemely/web/scheduled_notifications.py` already runs due announcements, `streak_warning`, `study_plan_reminder` and the paper purge job.
- DELIVERY §5.3's last bullet already records the sweeper, and its dedupe keys are designed to be safe across replicas.

**Failure scenario:** DELIVERY §5.7 would publish a false statement. The user locked "no email retry or scheduler, no auto-expiring pending requests" (row 12) while believing no scheduler existed. In fact, each of those three would cost one sweeper job. Separately, outbox mail is sent from a post-response `BackgroundTask` on Cloud Run, which runs with `--min-instances=0` and default CPU throttling (`.github/workflows/deploy.yml:313`). Work after the response may never get CPU time, so rows can stay `pending` forever. The SPEC only ever promises `failed`.
**Fix:**
- Correct the facts in recon.md, both ADRs and the SPEC.
- Reword §5.7 to "this feature registers no sweeper job (decision row 12)".
- Tell the user at spec review that a sweeper exists, so row 12 can be reopened (draining the outbox with retry, expiring requests). Do not build any of it without approval.
- Document that an outbox row can stay `pending`.

### F5 · major · The rollback claim is false, and the repo's own 0039 runbook explains why
**Location:** §f L1127 ("Rollback of application code without downgrading the schema is always safe … which is the preferred incident path").
**Evidence:** 0044 adds six values to the existing `notificationtype` enum. `docs/deployment.md:539-558` records what happened with 0039's `review_withdrawn`: after a Cloud Run revision rollback, pre-0039 code raises `LookupError` (a 500) in the inbox for anyone holding a row with the new value. The documented fix is a `DELETE` run before rolling back.
**Failure scenario:** Wave 2 ships. Tutors, students and parents receive `booking_request` and `booking_update` rows. An incident leads to a revision rollback, and every one of those users gets a 500 on G-13.
**Fix:** Add an entry like §5.7 to `docs/deployment.md` that runs `DELETE FROM notifications WHERE type IN (<the six values>)` before any revision rollback. Better still, ship a wave-0 change before 0044 that makes the notification reader skip unknown types. Strike "always safe".

### F6 · major · States computed at read time and states stored in the table disagree across endpoints, and one case locks a student out for good
**Location:**
- §a.3 L342 ("≤ `MAX_PENDING_PER_STUDENT` pending (row-locked count)").
- L345: the guard for requested → cancelled is `now < starts_at`.
- L346: an expiry is written only by a later write from the same student to the same tutor.
- T9 `state?` (L487); T-13 "Requests awaiting reply" (L882).
- `ix_tutor_bookings_tutor_requests … WHERE state = 'requested'` (L192).
- S1 `when` (L460); SP1's SQL copy of `rule_matches` (L1030).

**Evidence:** The SPEC gives grant validity a SQL predicate plus a parity test (L1084). It gives none to `effective_state`, the pending count, or `rule_matches`.
**Failure scenario:**
- A student sends requests to 5 tutors. Nobody replies, and all 5 start times pass. The rows stay `requested` in the table. If the pending count reads the stored state, every new request returns 409 `pending_limit` forever. The student cannot cancel those rows (guard `now < starts_at`), and the late expiry write only touches rows for the same tutor.
- T9 `state=expired` returns nothing, while the UI shows those same rows as expired under `state=requested`.
- T-13's inbox lists requests that have already expired.
- "Row-locked count" cannot stop new rows from being inserted alongside the count. Two simultaneous requests to different tutors each count 4, and both insert.

**Fix:**
- Define one SQL predicate per derived state:
  - live pending: `requested AND starts_at > now`
  - expired: `requested AND starts_at <= now`
  - awaiting outcome: `accepted AND ends_at <= now`
- Use these predicates in the pending count, the T9 filter (which should filter on the effective state), T-13, and the S1/T9 `when` split.
- Parity-test them against `core.booking.effective_state`, the way grants are tested. Do the same for `rule_matches`.
- Serialise the pending count by locking the student's `users` row (`SELECT … FOR UPDATE`), not the rows being counted.

### F7 · major · The tutor alone controls which sessions can be reviewed and which students enter the outcome cohort, so row 7's "limits fraud" does not hold
**Location:** §a.3 L348–349 (only the tutor marks completed or no_show); §a.2 L225 (a review needs a completed booking); L354 (stars count from the moment of insert); §e.1 `allowed_actions(..., blocked)` (L990); block effects (L304).
**Evidence:** Locked row 7's rationale is "Ties each review to a real session; limits fraud". Student self-signup is open (DELIVERY §3).
**Failure scenario (suppressing reviews):** A student has a bad session. The tutor can mark no_show (a terminal state, L350), never mark an outcome so the session sits in `awaiting_outcome` forever, or block the student. In every case no review can ever be written. The student's only recourse is a free-text report.
**Failure scenario (inflating ratings):** The tutor creates student accounts, books themself, accepts, marks the sessions completed, and leaves 5-star reviews with no text. Those count at once and are never moderated, because only text is moderated. If those accounts upload papers, they also enter the outcome cohort.
**Fix (within the locked rows):**
- Let the booking's student, or the parent who requested it, confirm or dispute the outcome.
- Allow a review when `accepted AND now ≥ ends_at + 72h` and the tutor has recorded no outcome.
- State that a block does not remove an existing right to review.
- Require a verified email to book.
- Keep stars-only reviews from very new accounts, or from accounts with no papers, out of the public average, or flag them in A6.
- Add to §5.7: "Completion is attested by the tutor alone."

### F8 · major · The k threshold for the distribution is ambiguous, and one reading publishes a single student's grade
**Location:** S-33's insufficient-data copy (L853: "once at least 5 students have had sessions in this subject"); ADR-T04 L36–38 ("below 5 contributing students"); `OutcomeDistributionDTO(nGraded, nWithoutGrade)` (L566–568); §e.4 L1077.
**Evidence:** The copy applies k to cohort size, the ADR applies it to contributing students, and the DTO exposes both counts.
**Failure scenario:** The implementer follows the copy. The cohort is 5, but only 1 of them has a grade from the tutoring window. Every logged-in user sees a bar with one segment of count 1 and `nWithoutGrade = 4`, and the tutor knows exactly who that one student is.
**Fix:** Apply k to `nGraded` for the distribution and to `nPaired` for the change figure, never to cohort size. Rewrite the S-33 copy to "once at least 5 students have a marked paper from their sessions". Add a unit test: cohort 5 with nGraded 4 is insufficient.

### F9 · major · The outcome SQL is unspecified and untested, and the obvious implementation counts deleted, non-paper and off-subject attempts
**Location:** ADR-T04 §Definitions; §e.1 `GradeObservation(ref, grade, recorded_at)` (L1020); the SP4 query budget (L1062); §e.4 L1077; the DELIVERY row at L1148, whose only proving test is `tests/test_core_tutor_outcomes.py`.
**Evidence:**
- Soft delete is enforced by a `do_orm_execute` loader criterion that only applies to ORM entity selects (`lemely/db/session.py:178-218`). The docstring of `deletion_repo.py` (L18–22) warns about exactly this hazard.
- `is_grade_bearing` means `origin == "past_paper"` and `grade in GRADE_ORDER` (`lemely/core/history.py:66-92`), so the SQL itself must exclude `custom_paper` and `quiz`.
- `GradeObservation` has no `origin` field, so the §e.4 unit test "quiz … excluded" cannot be written against the pure core function.
- The opt-out anti-join, the subject match and the blocked-pair exclusion exist only in SQL.

**Failure scenario:** A Core or text query, the natural choice for a 2-statement budget, counts papers the student deleted, custom papers and attempts from other subjects. Every core test stays green.
**Fix:** Specify both statements:
- Use ORM entities so the loader criterion applies, or add an explicit `deleted_at IS NULL`.
- Filter `origin = 'past_paper'`, grade on the ladder, and `subject_code` equal to the booking's subject.
- Add the opt-out and block anti-joins.

Add one DB test per exclusion, each with a case that fails, and list that test as proof in the DELIVERY row.

### F10 · major · "Never invent precision" (UI spec §1.4, principle 6) is broken in four places
**Location:** C-17 (L820), C-18 (L821), ADR-T04 definitions, the S-32 explainer (L847), `listedSince` (L559 and L90), the rank prior (L994).
**Evidence and failures:**
1. **Grades on estimated boundaries.** Attempts carry `boundary_source` (`attempts.py:151`); `subject_default` and `global_default` are not exact (`enums.py:141-146`). C-1 has an `estimated` variant (`grade-badge.tsx:104-119`) because principle 6 requires estimates to be labelled "visibly and every time". C-17 adds them up as plain grades.
2. **The tutoring window.** "Change in grade while with this tutor" counts papers recorded up to 60 days after the last session. `recorded_at` is the upload time, not the date the paper was sat, so a past paper uploaded during tutoring counts as "during".
3. **The rank explainer.** S-32 says new tutors are "shown closer to the middle". In fact a tutor with 0 reviews has a rank score of exactly 4.0, the prior, which puts them above every tutor whose real average is below 4.0. New tutors then all tie at 4.000000 and are ordered by random UUID for ever.
4. **"Listed since".** `listedSince` reads `listed_at`, which is the last approval date. Any re-review after a bio edit resets it.

**Fix:**
1. Count estimated-boundary grades separately, or exclude them and say so under the figure.
2. Keep the locked title, but have the caption state the window: "papers uploaded from the first session until 60 days after the last".
3. Reword the explainer to describe the actual rule ("tutors with few reviews are ranked as if they also had five 4-star reviews"). Break ties by `listed_at`, then id.
4. Add a `first_listed_at` column.

### F11 · major · The minor controls the safeguarding notifications, and the ADR does not say so
**Location:** ADR-T02 R1 and R3 (L110–112); SPEC §b.4 L660–666; DELIVERY §5.7 L1158.
**Evidence:** `DELETE /api/student/parent-links/{parent_id}` (`lemely/web/routers/student.py:1375-1389`) lets the student remove a parent link at any time, without telling the parent. Notifications go only to parents who are linked at that moment, and notes never notify parents at all (L664).
**Failure scenario:** A minor unlinks their parent, grants indefinite all-subject access, books an in-person session and uses the notes thread. The parent hears about none of it. Meanwhile the ADR's table of compensating controls still reads as if parents are told about every grant and booking.
**Fix:** Do not change locked row 4. State the limit in ADR-T02 R1/R3 and in DELIVERY §5.7: "A student can remove a parent link at any time; after that, that parent is told nothing." Offer the user these options alongside O-1/O-2: notify the parent when a link is removed, and/or keep notifying for grants made within N days of an unlink.

### F12 · major · Student names fall back to the email address by codebase convention; the SPEC never closes this, so a minor's email reaches an adult stranger
**Location:** `BookingStudentDTO.displayName` (L581), `TutorStudentItemDTO.displayName` (L637), `BlockDTO.displayName` (L650), `NoteDTO.authorName` (L601), §e.2 `RosterEntry(display_name=...)` (L1048); §a.5 L411 ("Never exposed … `users.email`").
**Evidence:** `users.display_name` is nullable at signup (`users.py:40`; `leaderboard_repo.py:104-108`). The established helpers use `display_name or email` (`class_repo.py:246, 578, 586`; `parent_repo.py:131, 165`). The leaderboard refuses that fallback precisely because strangers see it (`leaderboard_repo.py:485-500`).
**Failure scenario:** A student with no display name requests a session. The tutor sees their email address on T-13 and T-16 and can contact them off-platform, outside the reportable notes thread.
**Fix:** Specify the fallback: "Student" plus a short stable suffix, or require a display name before a student can book or grant. Add a test that no tutoring DTO ever contains a `users.email` value.

### F13 · major · Three screens need data that no route provides
**Location:** T-19 (L911–913); T-16 (L898); the area list for T-14 and the filters (L86, L440).
**Evidence:**
1. T-19 lists every review with the tutor's reply state. SP3 is guarded STUDENT_OR_PARENT (L450, L696), and T8 returns only `TutorProfileDTO + OutcomesDTO` (L486), so a tutor has no route that returns reviews.
2. T-16 shows "whether this student has shared their data", but `BookingDTO` has no such field. The only tutor-side reads are T19, which writes a `list` audit row per student, and T20, which writes a `detail` audit row before it loads anything.
3. T-14 needs the full list of areas. The facets list only areas already used by listed tutors (L550), and no route serves `lemely/data/tutoring_areas.json`.

**Failure scenario:** The implementer adds unreviewed routes outside the authz table, or probes T20 to render T-16. The student's access log then shows "viewed your progress" visits the tutor never made.
**Fix:**
- Add `GET /api/tutor/reviews`, cursor-paged, guarded TEACHER plus own profile. It includes the pending or rejected state of the tutor's reply, but never review text that is still pending.
- Add `studentShared: bool` to the tutor's `BookingDTO`, computed from the grant predicate and writing no audit row.
- Serve the area list through `/api/reference`, or a new AUTH_ANY or PUBLIC route.

Add each new route to §c.1 and to the route count.

### F14 · major · Moderation and "documents seen" can be bypassed after approval
**Location:** §a.3 L332 (the list of moderated fields) and L333–334; `other_mode_note` (L84, L557, L859); `documents_seen_at` (L93); T3 (L481); T6 and T7 (L484–485).
**Evidence and failures:**
1. **`other_mode_note` is not moderated.** It is 200 characters of free text shown to every logged-in student on S-33 and S-34, and it is missing from the moderated-field list. After approval, a listed tutor can put a phone number there with no re-review. That gives the tutor a way to contact minors outside the notes thread.
2. **Suspended profiles.** The transition table does not say what editing a moderated field does to a `suspended` profile. Applied literally, "edit → pending_review" lets a suspended tutor get back into the admin queue just by editing their bio.
3. **"Documents seen" never resets.** `documents_seen_at` is set when an admin approves with `documentsSeen=true` and is never cleared. A tutor can delete the evidence the admin saw and upload different files, or be re-approved with `documentsSeen=false`, and S-33 still says "Documents seen by Lemely".

**Fix:** Add `other_mode_note` to the moderated list. Make T3 return 409 `illegal_transition` on suspended profiles. Clear `documents_seen_at` on any change to the evidence and on any approval with `documentsSeen=false`. Add a test for each.

### F15 · major · noindex: the SPEC names the wrong place to set it, changes a locked row without approval, and has no test of the page header
**Location:** §0 L23; P1/P2 L440–441; §h O-8 L1181; §g L1139 and L1160; locked row 5b ("`noindex` until tutor opts in").
**Evidence:**
- Production serves the SPA from Workers Static Assets with `run_worker_first: ["/api/*"]` (`web/wrangler.jsonc`). The header comment of `web/worker/index.ts` says: "Every request this fetch handler sees is therefore already an API call". Editing the worker therefore does nothing for `/tutors*`.
- The place that works is `web/public/_headers`, which already adds headers to `/*`.
- In nginx, a new `location` that has its own `add_header` stops inheriting the security headers (`web/nginx.conf:26-35`).
- The DELIVERY row's proving tests only check `X-Robots-Tag` on the JSON API. That does not stop search engines indexing the HTML page.
- Separately, O-8 turns row 5b's "until tutor opts in" into "always noindex" and files it as a "known limit accepted in this spec". Row 5b is locked, and changing it needs the user's approval.

**Failure scenario:** The implementer follows O-8 and edits the worker or nginx. The HTML at `lemelyig.com/tutors/:id` ships without noindex, and tutor names and areas get indexed, while DELIVERY says "pages always noindex".
**Fix:** Add a rule to `web/public/_headers` that sends `X-Robots-Tag: noindex` for `/tutors` and `/tutors/*`. For nginx, repeat the security headers inside the new location. Add a test that parses `_headers` (and `nginx.conf`) for the rule. Move O-8 to "Decision points for the user".

### F16 · major · The public data-handling page will become false, and the SPEC does not update it
**Location:** §g; `web/src/portals/marketing/dataHandling.ts:147` ("A teacher can see the work of students in their own classes …"). The file's header says: "If a sentence here stops being true, that is a defect in this file".
**Failure scenario:** After wave 4, a tutor holding a grant can read a student's grades, and every student's grades are counted in tutor profiles by default. For minors, the published description of who sees a student's work then omits both.
**Fix:** Add `dataHandling.ts` to wave 4. Cover grants, the audit log, default-on counting and the opt-out, the fields on the public tutor card, and notes that parents can read and admins can read on report. Give each sentence its source comment, as that file requires.

### F17 · major · The notification dedupe keys break notes and can silently drop a safeguarding notice, or a grant
**Location:** §b.4 L664–666 and L670; `email_outbox.dedupe_key` (L314).
**Evidence:** The inbox's unique index is `(user_id, type, dedupe_key)` (migration 0018, `uq_notifications_user_type_dedupe`), and the SPEC uses `"{booking_id}:{event}"` for every event. `email_outbox` has a plain unique index on `dedupe_key`, keyed `"{booking_id}:{event}:{recipient_user_id}"`, but grant and listing events have no booking id.
**Failure scenario:**
1. Every note after the first on a booking comes back as a duplicate, so the other participant is never told about later notes.
2. If grant keys are built from the student/tutor pair (there is no booking id to use), a re-grant after a revoke is deduplicated and parents are not told about the second grant.
3. If an outbox insert collides, the `IntegrityError` aborts the grant or booking transaction itself.

**Fix:** Specify a key for each event:

| Event | Key |
|---|---|
| Note | `"{note_id}"` |
| Grant | `"grant:{grant_id}:{event}"` |
| Listing decision | `"listing:{approval_event_id}"` |
| Review | `"review:{review_id}:{event}"` |

Make outbox inserts `ON CONFLICT (dedupe_key) DO NOTHING`. Add tests for two notes on one booking and for revoke-then-regrant.

### F18 · major · Deleting an account destroys safeguarding evidence and leaves personal data behind, and O-12 is out of date
**Location:** §a.2 L75, L158, L201, L245, L310–311; §h O-12 L1183.
**Evidence:** No account-deletion route exists in `lemely/`; `lemely/db/deletion_repo.py` only soft-deletes papers. Tests do hard-delete users, though (`tests/test_notification_repo.py:585`; `tests/test_teacher_paper_repo.py:408,426`). The ON DELETE rules are therefore exercised, and any erasure request will be handled as a manual `DELETE FROM users`.
**Failure scenario:**
- Deleting a tutor's user row cascades through `tutor_profiles` and `tutor_bookings` to `tutor_booking_notes`. Every unreported thread between that adult and minors disappears; reports keep only a snapshot of the item that was reported.
- Deleting a student cascades their reviews. `rating_sum`, `rating_count` and `rank_score` stay wrong until someone runs `recompute_tutor_ratings`, which nobody owns.
- `email_outbox.to_email` outlives the user's deletion indefinitely, because only the id is set to NULL.

**Fix:**
- Make `tutor_profiles.user_id` and `tutor_bookings.tutor_profile_id` ON DELETE RESTRICT, so offboarding has to anonymise rather than cascade.
- State a retention rule for notes.
- On student deletion, recompute ratings in the same transaction, or make `tutor_reviews.student_id` SET NULL and keep the stars.
- Make `email_outbox.recipient_user_id` ON DELETE CASCADE, or purge those rows.
- Update O-12 with the facts above.

---

## Minor

### F19 · minor · A parent's first note contradicts the notes CHECK constraint
**Location:** `BookingCreateDTO.firstNote` (L580); `ck_tutor_booking_notes_author_party IN ('student','tutor')` (L203); P-07 reuses the S-34 layout, including its "optional first note" (L859, L927); O-6.
**Failure scenario:** A parent books with a first note, the insert raises `IntegrityError`, and the parent gets a 500.
**Fix:** Reject `firstNote` from parents with a 422 and hide the field in P-07, unless the user decides under O-6 that parents may write; in that case, widen the CHECK. Rated minor because the first parent-booking test will catch it and the fix is trivial.

### F20 · minor · `alembic check` guards nothing here, and no gate runs it
**Location:** §a.4 L396; §e.4 L1081.
**Evidence:**
- Neither CI nor `scripts/check.sh` runs `alembic check`. The check.sh gates are ruff (×2), mypy, import-linter, the review-rate gate, pytest, four web gates, impeccable, playwright, the audit and ui-thresholds.
- `tests/test_flashcard_schema.py:205` still claims check.sh runs it.
- **Probe:** the comparator reports 0 diffs with or without the ExcludeConstraints. It ignores Computed expressions, warning "Computed default … cannot be modified" on every comparison. A partial enum predicate, a COALESCE unique index and an Identity column also produce 0 diffs.

**Fix:** Say so in the SPEC: the `pg_constraint` and `pg_indexes` tests are the real guard. Assert that `pg_get_constraintdef` contains the predicate and the operator. Pin `ACTIVE_STATES` against the ORM `where` text as well; L1073 pins only the migration.

### F21 · minor · New screen IDs collide with existing provisional IDs
**Location:** §d L805–806.
**Evidence:** `web/scripts/audit.mjs` already labels `/student/parents` as `S-32-provisional` (:1209, :1813), `/teacher/grading` as `T-13-provisional` (:1711), and uses `T-14-provisional`.
**Fix:** Start the new screens at S-33 and T-15, or give the provisional screens permanent IDs first. Renumber §d and the audit registry to match.

### F22 · minor · Several of the UI gates in §d are not actually enforced
**Evidence:**
- Lighthouse runs on default states only (D3.17, DELIVERY §5.5), but §d lists several states per screen.
- The performance floor covers `/student` plus a list of named slugs (`scripts/check_ui_gates.py:72-74`, around line 102), so `/tutors` has to be added to that list.
- The audit registry has no `platform_admin` session.
- `check_copy.mjs` checks dashes only, so "never improvement / never verified" (L24) has no gate.
- The 44px touch-target rule (L814) is not measured, and DELIVERY §5.5 records 54 `size="sm"` controls at about 31px.
- CI runs no Playwright or audit job (ci.yml comment "B7"), and check.sh skips both when the local stack is down.

**Fix:** Add the named slugs and an admin session to the audit. Add a copy-lint rule for the banned words in tutoring copy. State that Lighthouse covers default states only. Treat e2e and audit results as local evidence, as DELIVERY already does.

### F23 · minor · Details of the authz-matrix edit that will trip up an implementer
**Evidence:**
- The SPEC's headings, such as `# ── PUBLIC: +2 (12 → 14) ──` (L689), do not match the section-count regex `#\s*─+\s*([A-Z_]+)\s*\((\d+)\)` (`test_authz_matrix_complete.py:578`). Pasted as written, those sections silently drop out of the count check.
- The object-level test file is named `tests/test_web_tutor_authz.py` at L715 but `tests/test_web_tutoring_authz.py` at L779.
- `pg_engine` and `pg_sessionmaker` are defined in each test module, not shared (`test_db_schema.py:319`; `test_web_platform_admin.py:83`).
- E2E data is seeded by `scripts/seed_e2e.py`, not `make seed` (L1093).
- `web/src/portals/public/` (L1139) does not exist; public pages live in `portals/marketing`.

**Fix:** Write the headings in their final form (`# ── PUBLIC (14) ──`), choose one file name, and name the real files.

### F24 · minor · The query budgets contradict the responses
**Evidence:** P1/SP1 return `facets` on page 1 (L440, L550), but the budget allows only 2 statements (L443, L1061). Besides its 2 statements, SP4 also needs the listed and blocked checks and the subject names (L1062).
**Fix:** Allow 3 statements on page 1 (one for facets), or move facets to their own route. Restate the SP4 budget.

### F25 · minor · Keyset paging details
**Evidence:**
- S1 and T9 split upcoming from past at `now`. Between page 1 and page 2, a row can cross that line and be skipped or shown twice.
- `decode_cursor` returns strings (L1035). A cursor holding a non-UUID id or a non-numeric rank becomes a database error (500), not a 422.
- "`minRating` excludes New" needs `rating_count >= 3` as well as the `rating_avg` filter, and the index at L102 covers only `rating_avg`.

**Fix:** Carry the split instant inside the cursor. Validate each cursor element's type in the router. Spell out the full predicate.

### F26 · minor · A session within 24 hours that cannot go ahead has no honest final state
**Evidence:** MIN_NOTICE is 2 h (L964), and the 24 h CANCEL_CUTOFF applies to tutors too (L347). S-36 says "Message your tutor" (L871).
**Failure scenario:** A session is booked 10 hours ahead and accepted, and then one side can't make it. Neither side can cancel. The tutor's only options are no_show, which blames the student and blocks their review, or completed, which is false and enters the outcome figures.
**Fix:** Let the tutor cancel at any time with a reason (row 9 does not say who the 24 h limit applies to), or add a mutual cancel. Confirm with the user.

### F27 · minor · Time-zone edge cases
**Evidence** (checked with `zoneinfo`):
- 2026-10-29 23:30 Cairo is ambiguous: 20:30Z with fold 0, 21:30Z with fold 1.
- 2026-04-24 00:30 Cairo does not exist, and `zoneinfo` returns an instant instead of raising. "Skipped" therefore needs an explicit round-trip check.
- On 29 Oct, a Thursday rule of 22:00–24:00 spans three absolute hours. Two 60-minute slots both render as "23:00", and one renders as "23:00–23:00 Cairo time".
- The rest of the product renders times in each user's own zone (`users.timezone`, TimezoneSync, the `NotificationsSettings` docstring). Tutoring hard-codes Cairo, and `tutor_profiles.zone` is a column that nothing can set, because it is not in the create or update DTOs.

**Fix:** Generate slots in absolute time from each occurrence's UTC bounds, and test the transition nights. Either drop `zone` or derive the time label from it.

### F28 · minor · Email operations
**Evidence:** The configured real provider is Resend's free tier, "3,000 mails/month, 100/day" (`EmailSettings` docstring in `lemely/runtime/config.py`). That quota is shared with verification and password-reset mail. Each booking event goes to the tutor, the student and every linked parent. §b.4 says "a real provider reuses `[email]` settings", while DELIVERY says "mock provider", so it is unclear which one ships.
**Failure scenario:** A busy day uses up the daily quota, and new users stop receiving their verification codes.
**Fix:** Decide whether wave 2 builds a Resend `TransactionalEmailProvider`. If it does, cap booking mail per day below the quota and give account mail priority. Make DELIVERY match.

### F29 · minor · The consent explainer understates what a tutor sees
**Evidence:** The explainer on S-37 and S-33 (L875, L854) lists grades, predicted grades, marks, weak topics, trend and activity. `StudentDetailDTO` also carries at-risk flags whose evidence includes the student's own target grade (`targetGrade`, `schemas_teacher.py:317-326`, fed by `target_grades_for`), plus the `questionIds` on weaknesses.
**Fix:** Add "your target grades and any at-risk warnings" to the copy. Alternatively, strip those fields from the tutor view, but that changes the reuse of T-05, so ask the user first.

### F30 · minor · Additions beyond the locked rows that need the user's confirmation
**Evidence:**
- Blocks, with strong side effects. Row 4 says "report/block … still to confirm", and row 4b locks only reporting and moderation. A block also cancels accepted sessions within 24 h, which overrides row 9.
- Moderation of tutor replies.
- A second exclusion constraint, on the student.
- A `requested` booking holds the tutor's slot, so any student can sit on a prime slot weeks ahead until the tutor declines.
- Row 8's "before/after grade-change figure" is drawn as higher/same/lower counts, and the SPEC does not say this is an interpretation.

**Fix:** List each of these in §h as a decision point.

### F31 · minor · The `build_student_detail` parity test cannot fail
**Evidence:** At L1048–1052 the function is a one-line call to `_student_detail_dto`, and the test compares its output with `_student_detail_dto`'s.
**Fix:** Test the routes instead. T20's `detail` should equal the teacher route's response for the same seeded student, with acknowledgements removed, and T20 should never return fields beyond `StudentDetailDTO`.

### F32 · minor · Places in the existing code the SPEC misses
**Evidence:**
- `NotificationPreferencesDTO` (`schemas_me.py:18`) needs the six new fields too, and `web/src/lib/staffInbox.ts` keeps its own copy of the notification types.
- `parent_repo.py:8-13` makes `ParentLinkService` "the single `parent_child_links` query in the codebase". Parent fan-out, O6/O7 and O16 must call `list_parents` and `get_child`, not join the table.
- New tutoring react-query keys must stay out of `web/src/lib/offline/persistAllowlist.ts`. The default is already safe; say so in the SPEC so nobody adds T-18's key.

**Fix:** Add these to the per-wave checklists.

### F33 · minor · The claims about public exposure overstate their limits
**Evidence:**
- "`Cache-Control: public, max-age=60` instead of a rate limiter" (L23, L1161) slows nobody down: a scraper ignores client caching, and the Worker does not cache proxied responses.
- "Logged-in only" (row 5b) means any free self-signup student account (DELIVERY §3).
- Reviews show "A student" and a month, but the tutor knows which students completed sessions that month.

**Fix:** Say this plainly in DELIVERY §5.7.

### F34 · minor · Data-model details
**Evidence:**
- `tutor_reviews.tutor_profile_id`, `tutor_reviews.student_id` and `tutor_review_replies.tutor_profile_id` are copied from the booking or review with no composite foreign key to keep them in step.
- Several foreign-key columns have no index: `text_moderated_by`, `moderated_by`, `resolved_by`, `hidden_by_user_id`.
- `ix_tutor_data_grants_tutor_live` covers live grants only, so a cascade from `tutor_profiles` has to scan revoked rows.
- The naming convention adds `ck_%(table_name)s_` itself, so the code must pass short names like `first_name_len`, not the full names the SPEC prints. Migration 0034 (line 66) records this trap.

**Fix:** Add composite foreign keys `(booking_id, tutor_profile_id) → tutor_bookings(id, tutor_profile_id)`, with a matching unique constraint. Add the missing indexes. Note the naming rule in the SPEC.

### F35 · minor · Migration details
**Evidence:**
- 0047's downgrade leaves the rating columns stale, and re-upgrading "requires `recompute_tutor_ratings()`". But `rank_score` is "never computed in SQL", so a migration cannot recompute it, and no owner or command is named.
- 0044's downgrade drops `btree_gist` even if it existed before 0044.
- "Renumber at merge time" conflicts with the hard-coded test names `test_migration_0044…0050`.

**Fix:**
- In 0047's downgrade, reset the counts to 0 and `rank_score` to the prior constant, written as a literal.
- Name the recompute command.
- In 0044, record whether it created the extension, or never drop it.
- Name the migration tests by what they cover, not by number.

### F36 · minor · The SPEC was written against a stale base
**Evidence:** The worktree HEAD is `314ef8ec`. `origin/develop` (`e80cb9fc`) is 117 commits ahead and changes `lemely/web/routers/teacher.py` and `lemely/web/app.py`. It adds no migrations, so the head is still `0043_merge_heads`. Several citations point one line below the `def`: `_visible_students` is at 1890, not 1891; `_student_detail_dto` at 2322, not 2323; `teacher_student_detail` at 2380, not 2381.
**Fix:** Rebase onto `origin/develop` before wave 1, and re-check every citation.

---

## Unverified items from the author that this review settled

| Item | Finding |
|---|---|
| O-12: "No account-deletion path was found in recon" | **Confirmed.** No account-deletion service or route exists in `lemely/`; `deletion_repo.py` only soft-deletes papers. Tests hard-delete users (`tests/test_notification_repo.py:585`, `tests/test_teacher_paper_repo.py:408,426`), so the ON DELETE rules are live (see F18). |
| O-13: Alembic head | `alembic heads` in the worktree returns `0043_merge_heads (head)`. `origin/develop` is 117 commits ahead but adds no migration files, so the head is unchanged for now. |
| Whether `alembic check` reports drift for an `ExcludeConstraint` with an expression element | **No drift.** A probe on PG 17.6 with SA 2.0.51 / Alembic 1.18.5 showed 0 diffs with the constraints declared, and also 0 diffs with them omitted. Computed columns emit a harmless "cannot be modified" warning. The enum partial unique index, the COALESCE expression unique index and the Identity column also showed 0 diffs (see F20). |
| (new) Can `create_all` build the tutoring tables? | **No, not without `btree_gist`.** It fails on a fresh database with `data type uuid has no default operator class for access method "gist"` (see F2). |
| Where to put the `noindex` header (`web/nginx.conf`, `web/worker` unread) | **In `web/public/_headers`.** `web/wrangler.jsonc` sets `run_worker_first: ["/api/*"]`, so the worker never sees `/tutors*`. In nginx, a new location must repeat the security headers (`nginx.conf:26-35`). See F15. |
| Admin portal URL prefix | **`/platform`.** See `web/src/portals/admin/index.tsx:400` (`path: "platform"`) and `web/src/lib/auth/RequireAuth.tsx:74`. |
| recon: shape of `EXPECTED` | Section counts are PUBLIC 12, STUDENT 63, TEACHER 3, PARENT 4, PLATFORM_ADMIN 9. `_REPRESENTATIVE` comes from a guard tuple (:514-517). `len(_NON_PUBLIC) == len(ROUTES) - 12` (:562); `len(_REPRESENTATIVE) == 6` (:564); the heading regex is at :578. |
| recon: the notification type list | 6 values (`enums.py:245-253`). Copies also exist in `web/src/lib/staffInbox.ts`, `notificationTypes.ts` and `notificationPrefs.ts`, and the public page `portals/marketing/dataHandling.ts` describes data handling (see F16, F32). |
| recon: audit-runner route list | `audit.mjs` already uses S-32, T-13 and T-14 as provisional IDs, and its registry has no platform-admin session or routes (see F21, F22). |
| recon: `check.sh` gate count | 14 gates. `alembic check` is not one of them (see F20). |
| recon: the arbitrary-literal lint | No gate across the codebase. `check_copy.mjs` checks dashes only, and DELIVERY §5.5 records about 600 arbitrary literals. |
| recon: "a scheduler: none" | **False.** An in-process sweeper runs every 60 s and is on by default (see F4). |
| Real email provider | `ResendEmailProvider` exists (`lemely/auth/email.py:240`) and is wired whenever `[email].api_key` is set (`deps.py:305-321`). The free tier is shared with account mail (see F28). |
| DST instants in O-5 and §e.4 | **Correct.** Thursday 17:00 Cairo is 14:00Z on 2026-10-29 and 15:00Z on 2026-11-05. 2026-04-24 00:30 does not exist, and `zoneinfo` does not raise for it. 2026-10-29 23:30 is ambiguous (see F27). |
| Not settled | O-14 (whether `btree_gist` loads on CI's Debian `postgres:16`): no such image exists locally. The `docs/database.md` tenancy wording: no "tenan…" text was found there to compare against. |

## Predictions made before the deep read, and what happened

| Prediction | Result |
|---|---|
| Read-time states would disagree between endpoints | Confirmed (F6, F7). |
| Safeguarding controls would be overstated | Confirmed (F11, F12, F14). |
| Migration and test infrastructure would not cope with the new DDL | Confirmed (F2, F5, F20). |
| Outcome figures would re-identify students | Confirmed, and worse than predicted (F1, F8, F9). |
| Claims about the codebase would be stale | Confirmed (F4, F13, F15, F36). |
