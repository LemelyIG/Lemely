# Tutoring SPEC rev 2 — revision log

**Date:** 2026-10-25 · **Branch:** `feat/tutoring-marketplace` @ `314ef8ec` (docs only)
**Inputs:** `docs/tutoring/THREAT-MODEL.md` (SC-1..SC-27), `docs/tutoring/ADVERSARIAL-SPEC.md` (F1..F36), `BUILD/tutoring/decision-log.md` rows 13–16 (user decisions made after both reviews; they override any review recommendation).
**Outputs:** `docs/tutoring/SPEC.md` (rewritten in place, sections 0 and a–h kept), `docs/tutoring/adr/ADR-T01..T04` (T02 and T04 rewritten, T01 and T03 edited), five appended entries in `BUILD/DECISIONS.md`.

**Naming.** `F-n` below means ADVERSARIAL-SPEC findings. The threat model's own §1 "facts" are written `TM-F1..TM-F13` (appendix B).

**Totals.** SC: 27 fixed, 0 rebutted, 0 needs-user. F: 34 fixed, 0 rebutted, 2 needs-user (F15 → D-1, F26 → D-2). Two items are fixed with a different mechanism from the one the review proposed, and the proposed mechanism is rebutted with evidence: SC-5 (contradicts binding D5.9 §1) and part of SC-15 (status code and the report exemption). No item was dropped.

## A. Threat-model SPEC changes (SC-1..SC-27)

| ID | Status | Where in SPEC rev 2 (and ADRs) | Notes |
|---|---|---|---|
| SC-1 | Fixed (row 14) | §a.2 `parent_link_events`; §b.4 rows "Parent link removed/added"; §c.4 (routes, before/after, tests); §g; ADR-T02 | Cap 4 enforced in `ParentLinkService.link_in_session` under the child's `users` row lock; also checked before account creation in `POST /api/auth/parent/signup` (verified that signup swallows redeem errors, `auth.py:475-482`). The unlink notice is the parent's last notice (stated in ADR-T02 R1 and DELIVERY) |
| SC-2 | Fixed (row 14) | §a.2 `tutoring_blocks` effects; §a.3 suspension/close; §b.2 S16, S17; §b.3 `ClassAccessDTO`, `GrantDTO.alsoTeachesClasses`; §c.3 O24, O25; §c.4; §d S-38; ADR-T03 | Verified that teacher direct enrolment needs a seat (`classes.py:683`), so code entry is the only school-less path. Re-joining after a block is not refused (row 14: no permission change); parents are told. Residual listed in §h and ADR-T03 |
| SC-3 | Fixed | §a.1 `grantrevokereason`; §a.3 suspension/reinstate/close; §e.1 `GrantFacts`, `grant_status`; ADR-T02 | Adds `tutor_closed` alongside `tutor_suspended` |
| SC-4 | Fixed | §a.4b (lock order table, write-route 409s, T8 rule); §a.3 guards; §b.2 codes | Global lock order stated to rule out deadlocks |
| SC-5 | Fixed (different mechanism) | §b.4 "Decision"; ADR-T02 options table | SC-5's `create_in_session` would put inbox writes inside the change transaction, which D5.9 §1 forbids ("the notify call sits at the router layer after the action has committed", `BUILD/DECISIONS.md` D5.9; `lemely/web/notify.py` header). Chosen: outbox in transaction (durable email), inbox after commit via `notify_safely`, parent screens as the durable record (D5.9 §2). Covers EM-2's lost/false-notice concern except an inbox loss on a crash between commit and notify |
| SC-6 | Fixed | §b.4 "Email delivery"; §b.2 A1 `emailDelivery`; §d X-04; §g | |
| SC-7 | Fixed | §0 "Free text"; §a.2 field notes; §b.2 422 codes; §e.1 `contact_patterns`, `MEETING_HOSTS`; §d rule + C-21; §g | `other_mode_note` added to the moderated list (§a.3) |
| SC-8 | Fixed | §a.3 notes table; §e.1 `MAX_BOOKING_HORIZON`; §b.2 SP5/SP6 | `awaiting_outcome` treated like `completed` for posting |
| SC-9 | Fixed | §b.4 table (tutor-note row) and copy rules; §d C-21; §c.3 O29 | The push part of CS-9 is moot: push is payload-less (D5.10, DELIVERY §5.3) |
| SC-10 | Fixed | §a.2 `tutoring_reports` queue index; §a.2 `notes_frozen_at`; §a.1 `tutoring_report`; §b.4; §c.3 O12; §d X-07 and report sheet copy | |
| SC-11 | Fixed | §b.2 T20, T11; §b.3 viewer-dependent serialisation; §d T-20 | |
| SC-12 | Fixed | §a.2 `tutor_reviews` invariants; §b.3 `ReviewDTO.period`, `BookingDTO.review`; §b.4 (no new-review notice); §e.1 `review_open_at`, `quarter_label` | Implemented as "a review can be created only after `ends_at + 7 d`" rather than "hidden until then": same visibility, no hidden-but-counted state. Residual (rating count changes when a review is added) stated in DELIVERY §5.7 |
| SC-13 | Fixed (row 13) | §e.1 `tutor_outcomes`; §e.3 statements; ADR-T04 | (a) k on contributors; (b) window closes at `S + 120 d` (redefined so no tutor action after a session moves membership); (c) steps of k; (d) 90-day hold on opt-out changes and student blocks; (e) verified email + 30-day account |
| SC-14 | Fixed (row 13) | §e.1 `outcome_for_subject`; ADR-T04 "When a figure is shown" rules 2–3 | Revoked grants count as "granted" (R6 in ADR-T04) |
| SC-15 | Fixed (with deviations) | §0 Errors; §b.2 **V** marks; §b.4 recipients and quotas | Deviation 1: unverified email returns **403** `email_unverified`, the existing contract of `require_verified_email` (`deps.py:966-1010`), not 409. Deviation 2: R1 (reports) is not gated, because a report is a safety path; spam is bounded by the open-report unique index and a 20/day quota |
| SC-16 | Fixed | §a.2 rating columns, `ix_tutor_reviews_student_latest`; §e.1 `aggregate_latest_per_student`; §d C-22 | Recompute-from-reviews on every change |
| SC-17 | Fixed | §a.3 booking table; §b.2 S14, PA5, A11; §a.1 `disputed_outcome`, `booking_completed`; §c.3 O23 | Cohort no longer depends on outcome marks (stronger than SC-17's "no_show stays in") |
| SC-18 | Fixed (placement); opt-in → D-1 | §b.5; §e.4 config tests; §d G-16/G-17 | The per-tutor opt-in is F15's open decision |
| SC-19 | Fixed | §b.2 B2, B3; §b.3 `BlockCreateDTO`, `BlockDTO`; §c.3 O28, O29 | |
| SC-20 | Fixed | §e.2 `project_for_tutor`; §d T-20 | |
| SC-21 | Fixed | §a "Deletion rule"; §a.2 FKs (RESTRICT); §a.1 `closed`; §b.2 A12; ADR-T01 | Retention period for notes/reports to be set in `docs/deployment.md` (ADR-T02 Consequences) |
| SC-22 | Fixed | §a.2 `tutor_evidence_files`; §b.3 admin DTOs (300 s, attachment); wave 1 hot files (`create_signed_url(..., disposition=None)`) | Sniffer is a new helper, not an import from the marking pipeline; Pillow verified as a dependency (`pyproject.toml:22`) |
| SC-23 | Fixed | §a.2 `tutoring_admin_access`; §b.2 A2, A10; §c.3 O15, O17; ADR-T03 | |
| SC-24 | Fixed | §a.4b (users-row lock); §a.3 create guard; §b.2 SP6 422 | |
| SC-25 | Fixed | §a.2 name CHECK + service allowlist; §a.2 `email_outbox` (no address, typed context); §b.4 links and `last_error` | |
| SC-26 | Fixed | §b.2 **NS** marks; §b.5 | Worker read-through cache chosen; WAF rule as an ops step (plan availability not verified, §h) |
| SC-27 | Fixed | §c.3 O18–O21; §0 Paging | |

## B. Adversarial findings (F1..F36)

| ID | Sev | Status | Where in SPEC rev 2 (and ADRs) | Notes / evidence |
|---|---|---|---|---|
| F1 | blocker | Fixed per row 13; residual accepted by user | ADR-T04 (definitions, rules, "What the tutor can and cannot do", R5 scenario); §a.3 "Outcome marks do not move outcome figures"; §e.4 byte-identical test; §g DELIVERY bullet; DECISIONS row-13 entry | The brief asked whether the tutor can be stopped from triggering a change by marking complete without a snapshot: **yes** — membership is decided by accepted sessions whose time has passed, so completion, no-show and tutor blocks change nothing. What cannot be removed without a snapshot: the tutor can predict each step and read before/after it (stated plainly in ADR-T04 and DELIVERY) |
| F2 | major | Fixed | §a.4 "Test databases built with `create_all`" | Verified: 88 test files run `CREATE DATABASE` + `create_all`; `migrated_sessionmaker` at `tests/conftest.py:617`; CI user is superuser (`ci.yml:28-32`). Decision: table-level `before_create` DDL listener in the new models module (no hot-file edit beyond one import in `import_all_models`); alternatives rejected with reasons; proving test with red case |
| F3 | major | Fixed | §b.4 "Decision"; §e.4 `test_transition_commits_when_inbox_write_raises`; ADR-T02 | Verified `notify.py` header and `NotificationService.create` opening its own session |
| F4 | major | Fixed (+ D-3 for information) | §0 Process state; §b.4 "Email delivery"; §g first bullet; ADR-T02 Context; DECISIONS correction entry | Verified: `lemely/web/app.py:63-90`, `NotificationsSettings` (`sweeper_enabled = True`, 60 s), `Sweeper.sweep_once` jobs; `deploy.yml:313` `--min-instances=0`. Sweeper used only for first-attempt email delivery; read-time evaluation stays the source of truth; row 12's limits (no retry, no expiry job) kept and stated honestly. `recon.md` and `design-summary.md` are locked inputs and were not edited; the correction is recorded in DECISIONS |
| F5 | major | Fixed | §f "Reversibility" | Verified `docs/deployment.md` §5.7 (0039 runbook, lines 539-558); the `DELETE` lists all 8 new types; "always safe" struck |
| F6 | major | Fixed | §a.3 effective-state predicate table; §a.4b pending count under the `users` row lock; §b.2 T9 filter, S1 split; §d T-15; §e.4 parity tests | |
| F7 | major | Fixed | §a.3 (completion after `ends_at`; student/parent claim after 48 h; admin dispute); §a.2 review invariants (14-day account, block keeps review right); §b.2 V on SP6/S6; §g "Completion is recorded…" | Stars-only puppets also face SC-16 (one rating per student) |
| F8 | major | Fixed | §e.1; §d S-34 insufficient copy; ADR-T04 rule 1; §e.4 "cohort 5, n_graded 4 → insufficient" | |
| F9 | major | Fixed | §e.1 `AttemptFacts`, `is_outcome_eligible` (SQL mirror, parity); §e.3 "Outcome statements" with one DB test per exclusion | Verified columns on `attempts` (`origin`, `deleted_at`, `boundary_source`, `subject_code`, `recorded_at`) |
| F10 | major | Fixed | (1) estimated boundaries excluded and captioned (§e.1, §d S-34, ADR-T04); (2) caption states the window in days; (3) explainer reworded, tie-break `first_listed_at`, `rank_score` default 4.0 (§a.2, §b.2, §d S-33); (4) `first_listed_at` column | Verified `BoundarySource` values (`enums.py:141-146`) |
| F11 | major | Fixed (row 14) | ADR-T02 R1/R3 "Limit" statements; §g child-safety bullet; SC-1 controls | |
| F12 | major | Fixed | §0 "Display names"; §e.1 `student_label`; §b.3 DTO comments; §c.3 O29 schema test | |
| F13 | major | Fixed | §b.2 T21 (`GET /api/tutor/reviews`), P3 (`GET /api/public/tutoring-areas`), `BookingDTO.studentShared`; §c.1 rows; route count 70 | |
| F14 | major | Fixed | §a.2 `other_mode_note` moderated, `documents_seen_at` cleared; §a.3 T3 on suspended/closed → 409; §d T-16 copy | |
| F15 | major | **Needs user (D-1)**; placement fixed | §b.5; §h D-1; §d T-16 (opt-in shown only if D-1 = B); DECISIONS correction entry | Rev 1 silently turned row 5b's "noindex until tutor opts in" into "always noindex". Changing a locked row needs the user. Options and recommendation in §h D-1 |
| F16 | major | Fixed | §f wave plan (each wave lists its `dataHandling.ts` sentences) | |
| F17 | major | Fixed | §b.4 table (inbox and outbox keys per event); §a.2 `ON CONFLICT DO NOTHING`; §e.4 tests | Verified inbox unique `(user_id, type, dedupe_key)` exists (`ops.py:225-227`) |
| F18 | major | Fixed | §a "Deletion rule"; §a.2 RESTRICT FKs; `email_outbox` stores no address and cascades; one recompute function + CLI (§e.3, §f); §h O-12 rewritten | |
| F19 | minor | Fixed | §a.2 notes `author_party`; §a.3 create guard; §b.2 SP6 422; §d P-07 | |
| F20 | minor | Fixed | §a.4 "`alembic check` is not a guard here"; §e.4 migration tests (`pg_get_constraintdef`); ACTIVE_STATES pinned to ORM `where` too | Stale claim at `tests/test_flashcard_schema.py:205` noted, out of scope |
| F21 | minor | Fixed | §d renumbered: students S-33..S-38, teachers T-15..T-21, new P-08 | Verified `audit.mjs` uses `S-32-provisional`, `T-13-provisional`, `T-14-provisional`; UI spec last IDs G-15, S-31, T-12, P-04, X-03 |
| F22 | minor | Fixed | §d rules (44 px not measured; copy-lint rule), gate-routes section (admin session, `check_ui_gates.py` slugs, Lighthouse default state only, local-evidence status) | |
| F23 | minor | Fixed | §c.1 headings in final form; one test file name; §e.4 per-module fixtures; `scripts/seed_e2e.py`; `web/src/portals/marketing/` | |
| F24 | minor | Fixed | §e.3 query budget (first page 3, SP4 3, P2/SP2, PA7) | |
| F25 | minor | Fixed | §b.2 S1 split in cursor; §0 typed cursors; §b.2 P1 `minRating` predicate; §a.2 `ix_tutor_profiles_rated` | |
| F26 | minor | **Needs user (D-2)** | §h D-2; §d S-37 copy marked pending | The review's own fix asks the user; row 9 does not say whom the 24 h rule binds. Recommended option A keeps outcome figures safe because it acts before the session |
| F27 | minor | Fixed | §e.1 `occurrences`/`bookable_slots` (absolute time, clock-change hour not bookable); §e.4 slot tests; §0 Times; §a.2 `zone` (kept, not settable, drives the label) | |
| F28 | minor | Fixed | §b.4 (Resend provider built in wave 2; mock otherwise; daily cap 60); §g | |
| F29 | minor | Fixed | §d S-38 explainer names target grades and at-risk warnings; §e.2 projection | |
| F30 | minor | Fixed (row 15) | Marked "approved, row 15" at each place: §a.2 blocks and student exclusion, §a.2 replies, §a.3 slot hold, §d C-18; removed from §h; DECISIONS row-15 entry | |
| F31 | minor | Fixed | §e.2 route-level test replaces the parity test | |
| F32 | minor | Fixed | §a.1 mirrors list (`NotificationPreferencesDTO`, `staffInbox.ts`); §a.4b and O7 (`ParentLinkService` only); §b.5 persist allowlist test | |
| F33 | minor | Fixed | §g DELIVERY bullets on edge caching, "logged in" and review guessability | |
| F34 | minor | Fixed | §a.2 composite FKs + matching unique constraints; FK indexes; §a naming-convention note | |
| F35 | minor | Fixed | §f table (0048 downgrade resets to literals; 0044 never drops `btree_gist`); `lemely tutoring recompute-ratings`; tests named by content | |
| F36 | minor | Fixed | §f "Before wave 1" (rebase + re-check); citations corrected (`_visible_students` 1890, `_student_detail_dto` 2322, `teacher_student_detail` 2380) | The rebase itself is implementation work, not doable in a docs pass |

## C. Other review items

**Threat-model §6 recommendations**

| Item | Status |
|---|---|
| O-1, O-2 [U] | Adopted (row 16): §b.2 PA6, PA7, S15; §d P-08, C-24 |
| In-person needs a linked verified parent (CS-5) [U]; unlink-then-grant alert (CB-1) [U]; admin investigation read (CS-8) [U] | Not adopted at spec review; listed in §h as optional, default not built |
| Grant needs an accepted booking (CB-9) [A] | Not adopted (optional; not an SC item) |
| Hold stars from accounts under 14 days (RF-1) [A] | Adopted as the 14-day review account age (F7) |
| COI declaration at approval (XT-3) [A] | Not adopted (optional) |
| Only `bookable_slots` instants; DB `now()`; tzdata (BK-7) [A] | Adopted: §0 Clock, §a.2 `starts_at`, §e.1 |
| Opaque audit id (ID-5) [A]; identifiability copy (PP-4) [A] | Adopted: §a.2 audit `id` uuid, no `entryId`; §d T-16 line. Governorate-level areas: data-file choice, not adopted |
| react-router upgrade; `pip-audit` | Listed in §h "Not verified" |

**Threat-model §8 not-verified items:** XT-6 settled (console grading passes `student_id=None, history_store=None`, `teacher.py:614-625`; ADR-T03). `_headers` on SPA fallback, Cloudflare cache/WAF, `pip-audit`: still open (§h).

**Rev 1 open items:** O-1, O-2 adopted (row 16); O-3 resolved by row 13 (homogeneity rule); O-8 → D-1; O-12 rewritten with F18 facts; O-13, O-14 kept as not verified; O-17 updated (admin reads now logged); O-4, O-5, O-6, O-7, O-11, O-15 still await the user (§h). Rev 1's last two "not verified" bullets (`alembic check` drift; nginx/worker unread; admin prefix) are settled by ADVERSARIAL and removed.

## Rev 3 (2026-10-25)

**Inputs:** decision-log rows 17–19 (LOCKED), the T-PLAN brief (O-15 recorded as decided). **Outputs:** SPEC rev 3, ADR-T02/T03/T04 edits, three appended `BUILD/DECISIONS.md` entries, `BUILD/tutoring/PLAN.md`.

| Item | Resolution | Where in SPEC rev 3 (and ADRs) |
|---|---|---|
| D-1 (F15, SC-18) | Row 17: card indexable by default, per-tutor opt-out, honoured by a worker lookup on P2; directory always `noindex, follow`; nginx stays `noindex`; onboarding notice | §a.2 `indexable` (default true); §b.2 P2 `PublicTutorCardDTO`, T3; §b.3; §b.5 (mechanism, failure modes, tests, deploy checklist); §c.3 O31; §d G-16/G-17, T-16; §e.4 worker tests (replace `test_headers_file_has_tutors_noindex_rule`); §f wave-1 hot files; §g DELIVERY row and §5.7 bullet |
| D-2 (F26) | Row 18: tutor may cancel inside 24 h with a reason; student and parent may not | §a.2 `ck_tutor_bookings_late_cancel_reason`; §a.3 accepted → cancelled rows; §a.4b cancel locks; §b.2 T13, PA4; §b.3 `cancel_with_reason`, `cancelledLate`; §b.4 copy; §c.3 O30; §d S-37, T-18, P-06; §e.1 `check_transition(has_reason)`, `is_late_cancel`; §e.4 tests; §g; ADR-T04 "Can" bullet |
| O-4, O-5, O-6, O-7, O-11 | Row 19: confirmed as read | §i.1; removed from §h; ADR-T02 principle paragraph (not blocked); ADR-T04 ladder note |
| O-15 | Decided: no subscription or activation gate on any tutoring route | §i.1; ADR-T03 consequence |
| D-3 | No change: locked row 12 stands | §i.1 |
| Optional safeguards CS-5, CB-1, CS-8 | Not adopted (unchanged); moved out of the open list | §i.1 |
| §h | Now lists only unverified facts, each with its check; constants and accepted limits moved to the new §i | §h, §i |
| Plan alignment | §b.1 notes that `BUILD/tutoring/PLAN.md` splits routers, repositories and test files for parallel ownership (routes and behaviour unchanged); §c.1 clarifies that authz-matrix headings carry the rows present at each run and reach the listed counts when the last route lands | §b.1, §c.1 |

New facts read for rev 3: `web/wrangler.jsonc` (`run_worker_first: ["/api/*"]`, `not_found_handling: "single-page-application"`, binding `ASSETS`), `web/worker/index.ts` (API proxy only), `web/public/_headers` (one `/*` block), `web/public/robots.txt` (no `/tutors` rule), `web/nginx.conf`; Cloudflare docs: `_headers` is not applied to Worker-generated responses. Not verified: whether `env.ASSETS.fetch()` serves the SPA shell for `/tutors/<id>` (staging check in §b.5).

## Appendix B. Threat-model §1 facts (TM-F1..TM-F13)

| ID | Used in |
|---|---|
| TM-F1 unlink is silent | SC-1, §c.4 |
| TM-F2 child-issued, uncapped parent links | SC-1 cap |
| TM-F3 school-less class side door | SC-2, ADR-T03 |
| TM-F4 no account disable | ADR-T01 consequence; suspension/close sweeps |
| TM-F5 `NotificationService.create` own transaction | SC-5 / F3, §b.4 |
| TM-F6 mock provider silent | SC-6 |
| TM-F7 unverified accounts are free | SC-15 |
| TM-F8 timestamps and `questionIds` in the T-05 DTO | SC-20 |
| TM-F9 Workers/nginx header placement | SC-18, §b.5 |
| TM-F10 1 h inline signed URLs | SC-22 |
| TM-F11 cooldown store is per process | §0 Process state; quotas are DB COUNTs |
| TM-F12 worker does not cache | §b.5 read-through cache |
| TM-F13 notifications persisted in IndexedDB | SC-9 fixed copy; §b.5 allowlist test |
