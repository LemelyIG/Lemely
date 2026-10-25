# Tutoring marketplace — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` (per task: implementer → task reviewer → lead integration) and `superpowers:test-driven-development` inside every task. Steps use checkbox (`- [ ]`) syntax. Per the user's delegate-by-model rule this plan fixes interfaces, file ownership, behaviour and test names; implementers write the code.

**Goal:** Build the tutoring marketplace exactly as `docs/tutoring/SPEC.md` rev 3 specifies (70 routes, 7 migrations, 23 screens), in 9 execution waves of at most 4 parallel tasks, with every hot file changed only by the lead.

**Architecture:** Layered as the repo already is: pure rules in `lemely/core/*`, SQL in `lemely/db/*_repo.py`, HTTP in new `lemely/web/routers/*` modules, React screens in `web/src/portals/*`. Contract first: wave 1 freezes the schema, the pure rule modules and the API DTOs (Python and TypeScript), so later tasks build against fixed names. Everything is integrated on `feat/tutoring-marketplace` by the lead, wave by wave.

**Tech stack:** Python 3.12–3.14, FastAPI, SQLAlchemy 2, Alembic, Postgres 16/17 (`btree_gist`), pytest; React 19 + TypeScript, react-query, Tailwind tokens, vitest (node env), Playwright; Cloudflare Workers Static Assets; nginx (self-host).

**Sources of truth (read before any task):** `docs/tutoring/SPEC.md` rev 3 (behaviour, DDL, routes, DTOs, tests), `docs/tutoring/adr/ADR-T01..T04`, `docs/tutoring/THREAT-MODEL.md` §7 (required tests), `BUILD/tutoring/decision-log.md` rows 0–19 (LOCKED), `BUILD/DECISIONS.md` entries `D-2026-10-25 — tutoring: *`. Where this plan names a file differently from SPEC §b.1/§e.3, the plan wins (SPEC §b.1 says so); routes, paths, guards, DTOs and behaviour never differ.

## Global constraints

Every task's requirements include these. Values copied from SPEC §0 and the repo rules.

- **Out of bounds for every task:** `lemely/core/correction.py`, `lemely/io/correction_ai.py`, `eval/`, `corpus/`. No tutoring path calls Gemini.
- **Layering:** pure logic in `lemely/core/*` (no `lemely.db`, `lemely.web`, `lemely.io`, `lemely.app`, `sqlalchemy`, `fastapi`); SQL in `lemely/db/*_repo.py`; HTTP in `lemely/web/routers/*` + `schemas_*.py`.
- **Times:** API instants ISO-8601 with offset, stored `timestamptz` UTC; weekly rules are tutor-zone wall clock (`Africa/Cairo`). Every compare-and-set and time guard inside a write transaction uses DB `now()`.
- **IDs:** UUID v4 everywhere, including log tables; no log id is ever exposed.
- **DTOs:** `ApiModel` (`extra="forbid"`, camelCase). Errors: 422 validation; 409 `{"code","message"}` for state/policy; 403 `email_unverified` via `require_verified_email`; 429 `too_many_requests`; 404 for anything not visible (no existence oracle).
- **Paging:** keyset only, `cursor` + `limit` 1..50 (default 20), typed cursor decode via `lemely/core/keyset.py`; wrong tag/arity/type → 422.
- **No process state:** no in-memory caches, limiters or queues; quotas are DB COUNTs.
- **Free text:** every user-written tutoring field passes `lemely.core.contact_patterns`; rendered as plain text, never auto-linked.
- **Display names:** a student's name shown to a tutor is `core.tutor_directory.student_label(...)`, never the `display_name or email` fallback.
- **Copy:** English; passes `npm run check:copy` (no prose em dashes, no exclamation marks) and the tutoring rule from T16 (never "improvement"; never "verified" without "documents seen"). No prices anywhere; "Fees are agreed between you and the tutor, outside Lemely."
- **Tests:** never run bare `pytest`, `make test` or the full suite locally except through `./scripts/check.sh` at the scheduled checkpoints; partial runs always pass `--no-cov`. Every test that guards a rule has a case shown to go red without the rule (mutation on a scratch copy, never in a shared tree).
- **Cross-cutting tests split by owner:** each route task adds, for its own routes, (a) a `Cache-Control: private, no-store` case for every **NS** route, (b) the SC-7 contact-detail case for every free-text field it accepts, (c) the `email_unverified` 403 case for every **V** route, (d) the `tutor_suspended`/`tutor_closed` 409 case for every tutor write route, and (e) the SPEC §e.3 query-budget case for every endpoint in that table. The THREAT-MODEL §7 parametrised tests are therefore spread across tasks; their union covers the full parameter lists.
- **Commits:** signed, explicit paths only: `git commit -S -m "<conventional msg>" -- <paths>`; never `-a`, `git add -A`, `git add .`; never `git stash`. Conventional scopes: `feat(tutoring):`, `test(tutoring):`, `docs(tutoring):`, `fix(tutoring):`. Do not push.
- **Imports from this worktree:** the venv is shared across worktrees, so every Python command runs with `PYTHONPATH=$PWD` from the worktree root.

---

## 0. Execution model

### 0.1 Roles
- **Lead** (opus): owns every hot file (§3), creates task worktrees, merges, runs gates, applies hot-file patches in the integration rows (`I0`–`IF`), decides escalations. Never writes feature code.
- **Implementer** per task: agent type and model from the task's tier tag. Backend tasks → `implementer`; UI tasks → `designer` (invoke the Impeccable audit/normalize/polish cycle; compose C-1..C-24 from `docs/COMPONENT_CATALOGUE.md`, never new primitives); e2e → `test-engineer`; UI QA → `visual-qa`; docs → `reporter`; review → `reviewer`.
- **Task reviewer** after every task, before integration: a `general-purpose` agent on **opus** filled from the SDD `task-reviewer-prompt.md`, reviewing at the task SHA (`git show <sha>:<path>`, never the open file), told the task's owned-file list and its SPEC sections.

### 0.2 Tier routing (prefix on every task)
| Tier | Tag | Use |
|---|---|---|
| A | `[A·opus·xhigh]` | schema + migrations; authz, consent, data access; cross-tenant queries; booking concurrency and state machine; outcome stats and min-cohort logic; edge indexing; integration merges; security review |
| B | `[B·sonnet·high]` | routers/services/repos following an existing pattern; React screens/components; API hooks; test suites against finished spec; seed with non-trivial invariants |
| C | `[C·sonnet·medium]` | copy-lint rule; Phase 4 docs and DELIVERY/CHANGELOG rows |

### 0.3 Worktrees (two modes; W0 probe picks one)
Memory note `subagents-inherit-session-worktree`: an agent's Bash is pinned to the lead session's current worktree, so an agent launched into a lead-created sibling worktree may have every Bash call refused. W0 runs a probe before any wave.

- **Mode A — per-task worktrees (the lead's preferred model).** Use it only if the probe passes. The lead creates one worktree per task off the current feature HEAD (after the previous integration):
  `git worktree add -b tut/<ID> .claude/worktrees/tut-<ID> feat/tutoring-marketplace`
  then provisions it: `ln -s /home/sico/Code/Lemely/.venv .claude/worktrees/tut-<ID>/.venv` and `ln -s <feature-worktree>/web/node_modules .claude/worktrees/tut-<ID>/web/node_modules` (run `npm ci` there instead if a tool rejects the symlink). The task commits on `tut/<ID>`; the lead merges with `git merge --no-ff -S tut/<ID>` in the integration row, then removes the worktree and branch.
- **Mode B — one shared worktree (fallback).** All tasks of a wave work in the feature worktree. Ownership is enforced by the owned-file lists, every commit is `git commit -S -- <owned paths>`, nobody runs `pre-commit run --all-files` mid-wave, and integration gates run only after every task in the wave has committed.

**Probe (W0):** dispatch one trivial agent with `isolation: "worktree"` that runs `pwd`, `git rev-parse HEAD`, `git branch --show-current` and `ls .venv web/node_modules`. Mode A is usable only if Bash runs, HEAD equals the feature HEAD and the worktree is under `.claude/worktrees/`. If the harness's own isolation works but lead-created worktrees do not, use `isolation: "worktree"` per task and merge its branch; if neither works, Mode B.

### 0.4 Hot-file rule
A task may edit a hot file in its own worktree to test, but **never commits it**. It returns the change as a unified diff in its return contract (`HOT PATCH` section). The lead applies every hot patch in the wave's integration row, on the feature branch, after the merges.

### 0.5 Standard TDD protocol (every task)
- [ ] **1. Read** the task card, its SPEC sections and its `Consumes` interfaces at the current feature HEAD.
- [ ] **2. Red:** write the test files listed under *Tests first*; run the acceptance pytest/vitest command; confirm every new test fails for the missing behaviour (not an import typo). Record one failing line per test file.
- [ ] **3. Green:** implement the minimum in the owned files to pass.
- [ ] **4. Mutation proof:** for each invariant in *Mutation proof*, copy the tree to the agent's scratch dir (`git archive HEAD | tar -x -C <scratch>` plus the uncommitted files), break the guard there, run the named test with `PYTHONPATH=<scratch>` and record that it goes red. Never mutate the worktree.
- [ ] **5. Static checks:** `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pre_commit run --files <owned files>`; then `git status --short` (the ruff hook autofixes; a modified file is a finding, re-stage it explicitly).
- [ ] **6. Acceptance:** run the card's acceptance command **and the scan suite for its side** (§0.7); each must exit 0 and every pytest summary line must show **no `skipped`** (local Supabase up; `supabase status` first). The scan suites are part of every card's acceptance even where the card does not repeat them.
- [ ] **7. Commit:** `git commit -S -m "<type>(tutoring): <summary>" -- <owned paths>`.
- [ ] **8. Return** the contract (§0.6).

### 0.6 Return contract (every task; ≤ 40 lines plus the hot patch)
```
STATUS: DONE | BLOCKED (<one-line reason>)
SHA: <branch> <sha>
FILES: <changed paths>   # must be a subset of the owned files; any other path = BLOCKED
RED: <test file>: <first failing assertion before code>   # one line per new test file
MUTATION: <invariant> -> <test id> red   # one line per listed invariant
ACCEPTANCE: <command> -> <pytest/vitest summary line>   # must show 0 skipped
PRODUCES: <the interface names the card lists, as implemented (signature lines)>
HOT PATCH: <unified diff per hot file, or "none">
NOTES: <deviations from SPEC/plan, follow-ups; <= 5 lines>
```

### 0.7 Commands every acceptance uses
Prefix (from the worktree root): `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs`. Web (from `web/`): `npx vitest run <files>`; `npm run typecheck`.

Scan suites (they read the source tree, so a task's own file list cannot see what they catch; memory `sweep-must-include-source-scanning-tests`):
- **SCAN-PY** (every task that changes a file under `lemely/` or `tests/`): `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py)`
- **SCAN-WEB** (every task that changes a file under `web/`): `cd web && npm test` (the node-only vitest suite; 94 of its 204 files walk `src/`, e.g. `a11yRules`, `adaptRules`, `darkConsumers`, `chartTheme`).

---

## 1. Summary

### 1.1 Waves
| Wave | Tasks (parallel ≤ 4) | Theme | Gate after | Full `./scripts/check.sh` |
|---|---|---|---|---|
| W0 | lead only (I0) | commit docs, rebase, provision, probe, config hot patch, baseline | G0 | **yes** (baseline) |
| W1 | T01, T02, T03, T04 | schema; pure rules; API contract | G1 | no |
| W2 | T05, T06, T07, T08 | grant/outcome rules; profiles + directory; notifications + email; edge indexing | G2 | **yes** |
| W3 | T09, T10, T11, T12 | existing-route changes (row 14); admin approval + evidence; web API hooks; reviews | G3 | no |
| W4 | T13, T14, T15, T16 | booking service; grants + audit + tutor view; UI components; copy rule | G4 | **yes** |
| W5 | T17, T18, T19, T20 | booking routes (family, tutor); outcomes; settings + parent sharing views | G5 | no |
| W6 | T21, T22, T23, T24 | blocks + sweeps + sanctions; discovery, student and teacher screens | G6 | **yes** |
| W7 | T25, T26, T27, T28 | reports; tutor-student, parent and admin screens | G7 | no |
| W8 | T29, T30, T31 | seed; security review; Phase 4 docs | G8 | **yes** |
| W9 | T32 then T33 (live stack, serial) | e2e journeys; UI QA (audit, screenshots, a11y) | G9 | — |
| Final | lead (IF) | fix tasks from T30/T33, final review, final gates | GF | **yes** |

### 1.2 Dependency diagram
Each task lists the tasks it depends on in brackets; every dependency sits in an earlier wave.
```
I0  commit docs · rebase · provision · probe · config hot patch · baseline
 │
W1  T01 schema[—]      T02 core-a[—]      T03 core-booking[—]      T04 contract[—]
 │  ── I1 ──
W2  T05 core-grants/outcomes[—]   T06 profiles+directory[T01,T02,T04]   T07 notify+email[T01]   T08 edge indexing[T04]
 │  ── I2 ── (full check.sh)
W3  T09 row-14[T01,T04,T07]   T10 admin+evidence[T01,T04,T06,T07]   T11 web hooks[T04]   T12 reviews[T01,T02,T04,T06,T07]
 │  ── I3 ──
W4  T13 booking service[T01,T03,T07,T09]   T14 grants+audit[T01,T04,T05,T06,T07,T09]   T15 components[T04]   T16 copy rule[—]
 │  ── I4 ── (full check.sh)
W5  T17 family booking routes[T06,T07,T13,T14]   T18 tutor booking routes[T06,T07,T13,T14]   T19 outcomes[T05,T06,T13]   T20 settings+parent views[T14]
 │  ── I5 ──
W6  T21 blocks+sweeps[T09,T10,T13,T14,T19]   T22 discovery screens[T11,T15]   T23 student screens[T11,T15]   T24 teacher screens[T11,T15]
 │  ── I6 ── (full check.sh)
W7  T25 reports[T09,T12,T13,T21]   T26 tutor-student screens[T11,T15]   T27 parent screens[T11,T15,T22,T23]   T28 admin screens[T11,T15]
 │  ── I7 ──
W8  T29 seed[T06..T25]   T30 security review[I7]   T31 docs[I7]
 │  ── I8 ── (full check.sh)
W9  T32 e2e[T29,T22..T28]  ──then──  T33 UI QA[T29,T22..T28,T32]
 │  ── I9 ──
IF  fix tasks · final review · full check.sh last
```
**Critical path:** I0 → T01 → T07 → T09 → T13 → T19 → T21 → T25 → T29 → T32 → T33 → IF, which spans all nine waves.

### 1.3 Task count per tier
- **Tier A (opus·xhigh): 14** — T01, T03, T05, T08, T09, T10, T13, T14, T17, T19, T20, T21, T25, T30.
- **Tier B (sonnet·high): 17** — T02, T04, T06, T07, T11, T12, T15, T18, T22, T23, T24, T26, T27, T28, T29, T32, T33.
- **Tier C (sonnet·medium): 2** — T16, T31.
- **Lead integration rows (opus): 11** — I0–I9, IF.

Tier choices that go up from the default: T10 (evidence upload and admin reads of PII), T17 (the first parent write path, "acting for child"), T20 (parent reads of the child's grants and tutor-read log), T29 (the seed must satisfy the SC-14 suppression rules to show a "sufficient" outcome figure; the lead's default for seed data is C).

### 1.4 Deviations from SPEC file layout (recorded once)
1. Routers split per task (paths unchanged): `tutoring_public.py`, `tutoring_directory.py`, `tutor_profile.py`, `tutor_evidence.py`, `admin_tutors.py`, `tutoring_reviews.py`, `student_reviews.py`, `tutor_reviews.py`, `admin_tutoring_moderation.py`, `tutor_students.py`, `student_tutor_access.py`, `tutoring_booking.py`, `student_bookings.py`, `parent_bookings.py`, `tutor_bookings.py`, `tutoring_outcomes.py`, `tutor_preview.py`, `student_tutoring_settings.py`, `parent_tutor_access.py`, `tutoring_blocks.py`, `admin_tutor_sanctions.py`, `tutoring_reports.py`, `admin_tutoring_reports.py`. S17 lives on the existing `student_classes.py` (prefix `/api/student/classes`); S16 (`/api/student/tutor-access/classes`) lives on the existing `student.py` (prefix `/api`), because `student_classes.py`'s prefix cannot mount it.
2. Repositories split: `tutor_approval_repo.py` and `tutor_evidence_repo.py` (from `tutor_profile_repo`), `tutor_outcomes_repo.py` (from `tutor_directory_repo`), `tutoring_blocks_repo.py` + `tutoring_reports_repo.py` + `tutoring_sweeps.py` (from `tutoring_safety_repo`).
3. `tests/test_web_tutoring_authz.py` becomes one file per task, prefix `tests/test_web_tutoring_authz_` (F23's single name cannot have one owner). Race tests go to `tests/test_tutoring_concurrency_<area>.py`, not the existing `tests/test_concurrency.py`.
4. Each task keeps its own dependency providers (lru-cached `get_*` functions) in its own router or service module; `lemely/web/deps.py` is touched only by the lead (sweeper wiring). The shared tutor-profile guards live in `lemely/web/deps_tutoring.py` (created by T06, then hot).
5. All seven migrations are written in W1 by T01 (one author for the chain). They ship in the release order SPEC §f gives; reversibility per revision is unchanged.
6. `web/src/portals/marketing/dataHandling.ts` sentences land once in W8 (T31), not per wave: nothing ships before the final PR.
7. SPEC gap filled: `create_signed_url(..., disposition=None)` is also implemented in `lemely/io/storage_gcs.py` (production backend) and the test fake `tests/storage_fakes.py`, not only `storage.py`/`storage_local.py`.
8. `review_open_at(ends_at)` moves from `core/tutor_ratings.py` to `core/booking.py` (it is `ends_at + NOTE_POST_GRACE`, a booking constant; two W1 tasks cannot import each other). `review_edit_deadline` stays in `tutor_ratings.py`.
9. The effective-state, active-state and live-pending SQL fragments of SPEC §a.3 live in a new `lemely/db/booking_predicates.py` written by T01 in W1, so every later task (T13 bookings, T14's upcoming-session count, T18's state filter) uses one copy; T13 parity-tests them against `core.booking`.
10. Python mirrors of the 8 new notification types (`ops.py` columns, `notification_repo.PREFERENCE_FIELD_FOR_TYPE`, `schemas_me.py` DTOs) move into T01, because `tests/test_notification_repo.py:131` pins the map to the enum and would be red between I1 and I2 otherwise. T07 keeps the three web mirrors.
11. Cross-module pins that need two W1 tasks (`ACTIVE_STATES` vs migration/ORM text, `CANCEL_CUTOFF` vs the late-cancel CHECK text, core literals vs Python enums) move to `tests/test_tutoring_cross_pins.py` in T05 (W2).
12. `tests/test_authz_matrix_complete.py` section headings carry the count of rows present **at each integration**, because `test_the_section_counts_in_this_file_match_what_it_registers` compares them with the registered rows on every run; they reach the SPEC §c.1 final counts at I7.

---

## 2. Task cards

Each card is one row of the task table: **ID · goal · tier · depends-on · owned files · tests written first · acceptance · return**, then interfaces and mutation proofs.

### T01 `[A·opus·xhigh]` Schema, models, migrations 0044–0050
- **Goal:** every tutoring enum, table, constraint, index and the `btree_gist` listener, exactly as SPEC §a.1–§a.4 rev 3 (incl. `indexable DEFAULT true` and `ck_tutor_bookings_late_cancel_reason`), in seven additive Alembic revisions chained from the head I0 names; the Python mirrors of the 8 new notification types; the shared booking SQL predicates.
- **Depends on:** I0.
- **Owned files:** `lemely/db/models/enums.py`, `lemely/db/models/ops.py` (8 preference columns only), `lemely/db/models/tutoring.py` (new), `lemely/db/booking_predicates.py` (new), `lemely/db/notification_repo.py` (`PREFERENCE_FIELD_FOR_TYPE` only), `lemely/web/schemas_me.py` (`NotificationPreferencesDTO`, `NotificationPreferencesUpdateDTO` only), `lemely/db/migrations/versions/0044_tutoring_enums_ext.py`, `0045_tutor_profiles.py`, `0046_tutoring_outbox_links.py`, `0047_tutor_bookings.py`, `0048_tutor_reviews.py`, `0049_tutor_grants_audit.py`, `0050_tutoring_safety.py`; `tests/test_db_schema.py` (the `get_heads() == ["0043_merge_heads"]` assertion at `:250` becomes the new head, nothing else); tests below.
- **Tests first:** `tests/test_migration_tutoring_enums.py`, `tests/test_migration_tutor_profiles.py`, `tests/test_migration_outbox_parent_links.py`, `tests/test_migration_tutor_bookings.py`, `tests/test_migration_tutor_reviews.py`, `tests/test_migration_tutor_grants.py`, `tests/test_migration_tutoring_safety.py` (each: `test_upgrade_downgrade_upgrade_round_trip`, `test_constraints_present_by_name`, plus `test_enums_downgrade_keeps_btree_gist`, `test_bookings_exclusion_defs_contain_gist_overlap_and_active_states`, `test_reviews_downgrade_resets_rating_literals`); `tests/test_db_tutoring_schema.py`: `test_create_all_on_fresh_database_installs_btree_gist`, `test_overlapping_active_tutor_slot_rejected_23p01`, `test_overlapping_student_slot_rejected_23p01`, `test_second_pending_same_pair_rejected_23505`, `test_adjacent_slots_accepted`, `test_cancelled_row_frees_slot`, `test_availability_rules_overlap_rejected`, `test_one_live_grant_per_pair`, `test_ck_late_tutor_cancel_requires_reason`, `test_review_composite_fk_rejects_mismatched_tutor`, `test_delete_user_with_booking_restricted`, `test_delete_tutor_user_restricted`, `test_tutor_profile_delete_restricted_when_bookings_exist`, `test_every_check_constraint_rejects_its_violation` (parametrised over §a.2 CHECKs), `test_indexable_defaults_true`, `test_booking_predicates_cover_every_effective_state`. The pins that need `core.booking` too are T05's (§1.4 #11).
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_migration_tutoring_enums.py tests/test_migration_tutor_profiles.py tests/test_migration_outbox_parent_links.py tests/test_migration_tutor_bookings.py tests/test_migration_tutor_reviews.py tests/test_migration_tutor_grants.py tests/test_migration_tutoring_safety.py tests/test_db_tutoring_schema.py tests/test_db_schema.py tests/test_notification_repo.py tests/test_notification_prefs_repo.py tests/test_me_router.py tests/test_web_notifications.py` + SCAN-PY
- **Return:** standard; `PRODUCES` lists ORM class names and the predicate constants; `HOT PATCH`: `lemely/db/models/__init__.py` (`tutoring` added to `import_all_models`), and the head revision id it chained from.
- **Produces (ORM, `lemely/db/models/tutoring.py`):** `TutorProfile`, `TutorSubject`, `TutorAvailabilityRule`, `TutorEvidenceFile`, `TutorApprovalEvent`, `TutoringAdminAccess`, `EmailOutbox`, `ParentLinkEventLog`, `StudentTutoringPreferences`, `TutorBooking`, `TutorBookingNote`, `TutorReview`, `TutorReviewReply`, `TutorDataGrant`, `TutorAccessAudit`, `TutoringReport`, `TutoringBlock`; enums per SPEC §a.1 in `enums.py`; 8 `NotificationType` members; `NotificationPreference` columns named as the 8 values; `booking_predicates.EFFECTIVE_STATE_SQL: Mapping[str, str]` (one fragment per effective state, SPEC §a.3 table), `ACTIVE_STATES_SQL`, `LIVE_PENDING_SQL`, `OUTCOME_MEMBERSHIP_SQL` (SPEC §a.3 "Outcome marks do not move outcome figures").
- **Mutation proof:** remove the `before_create` listener → `test_create_all_on_fresh_database_installs_btree_gist` red; drop the `IS NOT NULL` conjunct in the late-cancel CHECK → `test_ck_late_tutor_cancel_requires_reason` red; change a tutor-profile FK to `CASCADE` → `test_tutor_profile_delete_restricted_when_bookings_exist` red.

### T02 `[B·sonnet·high]` Pure rules A: keyset, contact patterns, directory helpers, ratings
- **Goal:** `lemely/core/keyset.py`, `contact_patterns.py`, `tutor_directory.py`, `tutor_ratings.py` with exactly the SPEC §e.1 signatures and constants.
- **Depends on:** I0.
- **Owned files:** those four modules; `tests/test_core_keyset.py`, `tests/test_core_contact_patterns.py`, `tests/test_core_tutor_directory.py`, `tests/test_core_tutor_ratings.py`.
- **Tests first:** keyset: `test_cursor_round_trip_typed`, `test_cursor_from_other_endpoint_raises`, `test_cursor_wrong_arity_or_type_raises`, `test_cursor_malformed_base64_raises`; contact: `test_contact_patterns_egyptian_mobile_latin_and_arabic_indic_digits`, `test_contact_patterns_email_url_social_handles`, `test_contact_patterns_no_false_positive_on_grades_and_times` ("A*", "72/80", "17:00", "0625/42"), `test_meeting_link_allowlist_rejects_userinfo_http_wa_me`, `test_meeting_link_rejects_lookalike_host_and_port`; directory: `test_rule_matches_table`, `test_public_name_formats_initial`, `test_public_first_name_charset_rejects_digits_urls_bidi`, `test_validate_public_name_accepts_arabic`, `test_student_label_never_contains_at`, `test_zone_label_cairo`; ratings: `test_bayesian_zero_reviews_is_4_000000`, `test_n1_five_star_ranks_below_twenty_at_4_5`, `test_aggregate_latest_per_student_counts_once`, `test_rating_display_new_below_three_students`, `test_quarter_label`, `test_review_edit_deadline_is_created_plus_14_days` (`review_open_at` is T03's, §1.4 #8).
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_core_keyset.py tests/test_core_contact_patterns.py tests/test_core_tutor_directory.py tests/test_core_tutor_ratings.py` + SCAN-PY
- **Return:** standard; `HOT PATCH`: `pyproject.toml` import-linter `forbidden` contract block for these four modules (lead merges it with T03/T05's).
- **Mutation proof:** strip Arabic-Indic digit normalisation → mobile test red; accept `http:` in `meeting_link_allowed` → allowlist test red; remove the endpoint tag check → other-endpoint test red.

### T03 `[A·opus·xhigh]` Pure rules B: booking state machine and slots
- **Goal:** `lemely/core/booking.py` exactly as SPEC §e.1 rev 3 (incl. `check_transition(..., has_reason)`, `is_late_cancel`, `cancel_with_reason`, and `review_open_at(ends_at) -> ends_at + NOTE_POST_GRACE` moved here, §1.4 #8), DST-safe slots. Booking literals are written out in the module; the pin against the Python enums is T05's.
- **Depends on:** I0.
- **Owned files:** `lemely/core/booking.py`; `tests/test_core_booking.py`, `tests/test_core_booking_slots.py`.
- **Tests first:** `test_transition_table_exhaustive` (state × action × viewer × requester × outcome-recorded × {>24 h before, <24 h before, in progress, <48 h after end, ≥48 h after end}); `test_effective_state_per_state_and_time`; `test_can_post_note_table`; `test_tutor_cancel_inside_24h_requires_reason`, `test_tutor_cancel_inside_24h_with_reason_allowed`, `test_tutor_cancel_after_start_refused_already_started`, `test_student_cancel_inside_24h_refused_cancel_window_closed`, `test_parent_cancel_inside_24h_refused_cancel_window_closed`, `test_cancel_at_exactly_24h_is_not_late`, `test_allowed_actions_tutor_inside_24h_offers_cancel_with_reason_only`, `test_is_late_cancel_truth_table`, `test_complete_requires_ends_at`, `test_student_may_complete_after_48h_awaiting_outcome`, `test_booking_horizon_28_days`, `test_review_open_at_is_ends_at_plus_note_grace`; slots: `test_dst_end_2026_10_29_thursday_17_is_14z_then_15z`, `test_repeated_hour_offers_no_slot_and_no_duplicate_label`, `test_dst_start_nonexistent_0030_offers_nothing`, `test_slots_never_overlap_busy_or_leave_rule`, `test_slots_respect_min_notice_horizon_step_durations`, `test_bookable_equals_membership_in_bookable_slots`, `test_normalize_rules_rejects_overlap`.
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_core_booking.py tests/test_core_booking_slots.py` + SCAN-PY
- **Return:** standard; `HOT PATCH`: import-linter contract line for `lemely.core.booking`.
- **Mutation proof:** allow student cancel inside 24 h → `test_student_cancel_inside_24h_refused_cancel_window_closed` red; drop the round-trip check in `occurrences` → nonexistent-time test red; `>=` vs `>` at the 24 h boundary → exactly-24 h test red.

### T04 `[B·sonnet·high]` API contract: DTOs (Python + TypeScript)
- **Goal:** every DTO in SPEC §b.3 rev 3 (incl. `PublicTutorCardDTO`, `cancelledLate`, `cancel_with_reason`, `indexable`) and the admin DTOs (field sets derived from §b.2 A1–A12 and §d X-04..X-07), plus a byte-for-byte TypeScript mirror.
- **Depends on:** I0.
- **Owned files:** `lemely/web/schemas_tutoring.py`, `lemely/web/schemas_tutoring_admin.py`, `web/src/lib/tutoringTypes.ts` (all new); `tests/test_schemas_tutoring.py`, `web/tests/unit/tutoringTypesParity.test.ts`.
- **Tests first:** `test_every_dto_is_apimodel_extra_forbid`, `test_idor_no_public_student_parent_dto_contains_tutor_user_id` (field-name scan for `userId`), `test_no_tutoring_dto_contains_email_field_except_admin_account_email`, `test_idor_tutor_dto_never_reveals_parent_link_presence` (no `parents`/`linkedParents`-shaped fields on tutor-facing DTOs), `test_indexable_only_on_public_card_own_profile_and_admin` (O31), `test_no_admin_dto_contains_student_detail_fields` (ADR-T03), `test_viewer_action_literal_includes_cancel_with_reason`; vitest "every Python DTO class has a TS interface with the same field names" (parses the two Python files as text).
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_schemas_tutoring.py` and `cd web && npx vitest run tests/unit/tutoringTypesParity.test.ts && npm run typecheck` + SCAN-PY + SCAN-WEB
- **Return:** standard. After I1 all three owned source files are **hot** (lead).
- **Mutation proof:** add `tutorUserId` to `TutorCardDTO` → O29 test red; add `indexable` to `TutorCardDTO` → O31 test red; rename one TS field → parity test red.

### T05 `[A·opus·xhigh]` Pure rules C: grant validity and outcome statistics
- **Goal:** `lemely/core/tutor_grants.py` and `lemely/core/tutor_outcomes.py` exactly as SPEC §e.1 and ADR-T04 (k on `nGraded`/`nPaired`, closed windows, steps of k, never-granted rule, largest-bucket rule, 90-day hold).
- **Depends on:** — (no task dependency; scheduled in W2 for the ≤ 4 cap).
- **Owned files:** those two modules; `tests/test_core_tutor_grants.py`, `tests/test_core_tutor_outcomes.py`, `tests/test_tutoring_cross_pins.py` (new; §1.4 #11).
- **Tests first:** cross pins (need T01 and T03, both merged at I1): `test_active_states_pinned_to_migration_and_orm_where`, `test_cancel_cutoff_pinned_to_late_cancel_check_text`, `test_core_booking_literals_equal_python_enums` (`BookingStateLit`/`Party` vs `BookingState`/`BookingParty`); grants: `test_grant_status_truth_table_with_precedence`, `test_grant_invalid_when_listing_rejected`, `test_grant_valid_while_pending_review_or_paused`, `test_reinstatement_does_not_restore_grant_status`; outcomes: `test_outcomes_k_counts_n_graded_not_cohort`, `test_outcomes_insufficient_hides_n_without_grade`, `test_outcomes_member_counts_only_after_window_closed`, `test_outcomes_window_edges`, `test_outcomes_published_set_moves_in_steps_of_k`, `test_outcomes_single_completion_causes_no_visible_change`, `test_outcomes_opt_out_hold_90_days`, `test_outcomes_member_requires_verified_and_30_day_account`, `test_outcomes_no_show_does_not_remove_member`, `test_outcomes_never_granted_between_1_and_k_minus_1_suppresses`, `test_outcomes_largest_bucket_n_minus_1_suppresses`, `test_outcomes_recent_change_hides_both_figures`, `test_outcomes_ladder_argument_honoured`, `test_is_outcome_eligible_truth_table`.
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_core_tutor_grants.py tests/test_core_tutor_outcomes.py tests/test_tutoring_cross_pins.py` + SCAN-PY
- **Return:** standard; `HOT PATCH`: import-linter contract lines for both modules.
- **Mutation proof:** apply k to cohort size → `test_outcomes_k_counts_n_graded_not_cohort` red; drop the never-granted test → its suppression test red; let `tutor_unavailable` rank above `revoked` → precedence test red; on a scratch copy drop `requested` from one exclusion `where` → `test_active_states_pinned_to_migration_and_orm_where` red.

### T06 `[B·sonnet·high]` Tutor profiles, public and logged-in directory
- **Goal:** profile create/edit/pause/indexable/availability/submit (T1–T5), public directory and card (P1–P3), logged-in directory and profile (SP1–SP2) with filters, Bayesian keyset order, block anti-join and the query budget.
- **Depends on:** T01, T02, T04.
- **Owned files:** `lemely/db/tutor_profile_repo.py`, `lemely/db/tutor_directory_repo.py`, `lemely/io/tutoring_areas.py`, `lemely/data/tutoring_areas.json`, `lemely/web/deps_tutoring.py`, `lemely/web/routers/tutoring_public.py`, `lemely/web/routers/tutoring_directory.py`, `lemely/web/routers/tutor_profile.py` (all new); tests below.
- **Tests first:** `tests/test_tutor_profile_repo.py` (`test_create_requires_teacher_role`, `test_moderated_field_edit_sends_listed_profile_to_review`, `test_indexable_change_does_not_send_profile_back_to_review`, `test_availability_replace_maps_overlap_to_422_code`, `test_submit_requires_complete_profile_and_verified_email`, `test_edit_suspended_or_closed_409`); `tests/test_tutor_directory_repo.py` (`test_directory_sort_rank_then_first_listed_then_id`, `test_min_rating_excludes_new_tutors`, `test_time_of_day_filter_sql_matches_rule_matches` (parity), `test_block_anti_join_hides_blocked_tutor_for_student`, `test_query_budget_first_page_3_later_pages_2`, `test_p2_sp2_two_statements`); `tests/test_web_tutoring_public.py` (`test_p1_p3_public_cache_and_noindex_api_headers`, `test_p2_carries_indexable_and_p1_does_not`, `test_p2_404_identical_for_unlisted_paused_suspended_closed_unknown`, `test_p3_lists_every_area`); `tests/test_web_tutor.py` (`test_indexable_defaults_true_and_tutor_can_opt_out`, `test_t1_without_profile_404_no_tutor_profile`, `test_t2_profile_exists_409`, `test_free_text_fields_reject_contact_details` for profile fields); `tests/test_web_tutoring_authz_profiles.py` (O1, O11 directory half, O21: `test_idor_cursor_from_other_endpoint_422`, `test_idor_cursor_typed_decode_rejects_injection`).
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_tutor_profile_repo.py tests/test_tutor_directory_repo.py tests/test_web_tutoring_public.py tests/test_web_tutor.py tests/test_web_tutoring_authz_profiles.py` + SCAN-PY
- **Return:** standard; `HOT PATCH`: `lemely/web/app.py` (three routers), `tests/test_authz_matrix_complete.py` rows P1–P3, SP1, SP2, T1–T5 with the `STUDENT_OR_PARENT` constant.
- **Produces:** `TutorProfileRepository(sessionmaker)`: `for_user(user_id) -> TutorProfileRow | None`, `get(profile_id) -> TutorProfileRow | None`, `create(...)`, `update(profile_id, changes) -> tuple[TutorProfileRow, bool]` (bool = re-review required), `replace_availability(profile_id, rules)`, `submit(profile_id)`; `TutorProfileRow` (frozen dataclass: `id, user_id, listing_state, paused_at, closed_at, zone, public_first_name, public_last_initial, indexable, first_listed_at`); `TutorDirectoryRepository`: `list_public(...)`, `list_for_viewer(viewer_id, viewer_role, ...)`, `public_card(tutor_id)`, `profile_for_viewer(tutor_id, viewer_id, viewer_role)`, `facets()`; `deps_tutoring.require_tutor_profile(auth) -> TutorProfileRow` (404 `no_tutor_profile`), `require_writable_tutor_profile(auth) -> TutorProfileRow` (also 409 `tutor_suspended`/`tutor_closed`); `LISTED_AND_NOT_PAUSED_SQL` predicate constant.
- **Mutation proof:** drop the block anti-join → block test red; make P2 return 200 for `paused` → identical-404 test red; let `indexable` edits re-enter review → that test red.

### T07 `[B·sonnet·high]` Notifications, email outbox, transactional provider, web type mirrors
- **Goal:** SPEC §b.4: outbox written in the change's transaction (`ON CONFLICT DO NOTHING`, preference-gated), inbox fan-out after commit through `notify_safely` with fixed copy, the sweeper delivery job (first attempt only, SKIP LOCKED, verified recipients, daily cap, mock = `skipped`), and the 8 notification types in the web mirrors (the Python mirrors are T01's, §1.4 #10). The job runs **only on a sweeper built with an email provider** (new optional `Sweeper` field defaulting to `None`, the same pattern as the purge job's `storage`/`bucket`), so the existing `sweep_once()` dict pins in `tests/test_scheduled_notifications.py` stay true for a sweeper built without one.
- **Depends on:** T01.
- **Owned files:** `lemely/db/email_outbox_repo.py`, `lemely/io/notify_email.py`, `lemely/web/tutoring_email.py`, `lemely/web/tutoring_notify.py` (new); `lemely/web/scheduled_notifications.py` (the optional provider field and the job, nothing else); `web/src/lib/notificationTypes.ts`, `web/src/lib/notificationPrefs.ts`, `web/src/lib/staffInbox.ts`; `tests/test_scheduled_notifications.py` (new cases only); tests below.
- **Tests first:** `tests/test_email_outbox_repo.py` (`test_enqueue_on_conflict_does_not_abort_caller_transaction`, `test_enqueue_skips_when_preference_off`, `test_deliver_job_claims_with_skip_locked_across_two_workers`, `test_failed_row_never_retried`, `test_daily_cap_skips_beyond_cap`); `tests/test_notify_email.py` (`test_email_context_schema_rejects_extra_keys`, `test_email_links_only_from_app_base_url`, `test_email_last_error_has_no_address`, `test_templates_html_escaped`, `test_email_context_never_contains_note_link_location_or_address`); `tests/test_tutoring_email.py` (`test_email_mock_marks_skipped_not_sent`, `test_email_skipped_for_unverified_recipient`, `test_placeholder_parent_address_skipped`, `test_email_delivery_mode_reports_mock_without_api_key`); `tests/test_tutoring_notify.py` (`test_transition_commits_when_inbox_write_raises`, `test_notify_note_notification_has_no_body_text`, `test_notify_parent_notified_of_tutor_note_without_text`, `test_parent_note_notice_once_per_day_tutor_notes_only`, `test_two_notes_one_booking_two_notices`, `test_late_cancel_notice_and_email_carry_no_reason_text`, `test_idor_tutor_review_notification_has_no_booking_or_student_ref`, `test_dedupe_keys_match_spec_table`); `tests/test_scheduled_notifications.py`: `test_sweep_once_runs_email_job_only_with_provider`, `test_sweep_once_without_provider_keeps_existing_job_set`; web: extend `web/tests/unit/notificationPrefs.test.ts`, `notifications.test.ts`, `staffInbox.test.ts` for the 8 types.
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_email_outbox_repo.py tests/test_notify_email.py tests/test_tutoring_email.py tests/test_tutoring_notify.py tests/test_scheduled_notifications.py tests/test_scheduled_announcements.py tests/test_web_notifications.py tests/test_notification_repo.py` and `cd web && npx vitest run tests/unit/notificationPrefs.test.ts tests/unit/notifications.test.ts tests/unit/staffInbox.test.ts` + SCAN-PY + SCAN-WEB
- **Return:** standard; `HOT PATCH`: `lemely/web/deps.py` (`get_sweeper` passes the provider, sessionmaker and cap), `lemely/web/app.py` (startup WARNING when `email_delivery_mode(settings) == "mock"` and tutoring routers are mounted), `lemely/app/cli.py` (`lemely doctor` WARNING line).
- **Produces:** `email_outbox_repo.enqueue_in_session(session, *, recipient_user_id: UUID, template: str, context: Mapping[str, object], dedupe_key: str) -> bool`; `notify_email.EMAIL_TEMPLATES`, `TransactionalEmailProvider`, `ResendTransactionalEmailProvider`, `MockTransactionalEmailProvider`, `build_transactional_provider(settings)`; `tutoring_email.deliver_tutoring_email(*, sessionmaker, provider, daily_cap: int, now: Callable[[], datetime], batch: int = 20) -> int`, `email_delivery_mode(settings) -> Literal["provider", "mock"]`, `MOCK_WARNING`; `tutoring_notify.InboxNotice` and builders `booking_notices(...)`, `note_notices(...)`, `grant_notices(...)`, `listing_notices(...)`, `review_notices(...)`, `parent_link_notices(...)`, `class_join_notices(...)`, `report_notices(...)`, plus `send_after_commit(notices, *, service) -> None`. Every builder takes ids and public names only.
- **Mutation proof:** send note text in a notice body → no-body-text test red; mark mock rows `sent` → mock test red; remove the address scrub → `last_error` test red.

### T08 `[A·opus·xhigh]` Edge indexing (row 17) and edge cache
- **Goal:** SPEC §b.5 rev 3 exactly: `/tutors` and `/tutors/*` run the worker; directory `noindex, follow`; card indexable only on a 200 lookup with `indexable === true`; fail closed everywhere else; security headers set by the worker; `caches.default` read-through (60 s) for `/api/public/tutors*` and `/api/public/tutoring-areas`; nginx stays `noindex` for `/tutors*`.
- **Depends on:** T04 (P2 shape).
- **Owned files:** `web/worker/index.ts`, `web/worker/robots.ts` (new), `web/worker/tsconfig.json` (only if `Fetcher`/`caches` types need it), `web/wrangler.jsonc`, `web/nginx.conf`; `web/tests/unit/workerTutorRobots.test.ts` (new), `web/tests/unit/headerParity.test.ts`, `web/tests/unit/headers.test.ts`, `tests/test_deploy_headers.py` (new).
- **Tests first:** the ten vitest cases named in SPEC §e.4 "Indexing" plus "/api/public/tutors read-through serves the cached response on the second call" and "/api/* other paths are not cached"; `tests/test_deploy_headers.py`: `test_nginx_index_html_sets_x_robots_tag_for_tutors`, `test_nginx_index_html_repeats_security_headers`, `test_robots_txt_does_not_disallow_tutors`, `test_headers_file_has_no_tutors_rule`, `test_wrangler_run_worker_first_lists_tutors_paths`.
- **Acceptance:** `cd web && npx vitest run tests/unit/workerTutorRobots.test.ts tests/unit/headerParity.test.ts tests/unit/headers.test.ts && npm run typecheck` and `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_deploy_headers.py` + SCAN-PY + SCAN-WEB
- **Return:** standard; `NOTES` must carry the staging `curl -sI` checklist text for T31 (`docs/deployment.md`). No hot patch.
- **Mutation proof:** always omit the header on the card branch → opted-out and 404 tests red; forward the inbound `cookie` header on the lookup → "carries no cookie" test red; drop the UUID check → "non-UUID without backend call" test red.

### T09 `[A·opus·xhigh]` Existing routes (row 14), parent-link lock, class helpers, S16/S17
- **Goal:** SPEC §c.4 in full (parent-link cap 4, unlink/link events and notices, class-join notices, leave a school-less class, class-access list), plus the methods later tasks need from the single `parent_child_links` and class queries. S16 is added to `routers/student.py` (prefix `/api`), S17 to `routers/student_classes.py` (§1.4 #1).
- **Depends on:** T01, T04 (`ClassAccessDTO`), T07.
- **Owned files:** `lemely/db/parent_repo.py`, `lemely/db/invite_repo.py`, `lemely/db/class_repo.py`, `lemely/web/routers/student.py`, `lemely/web/routers/invites.py`, `lemely/web/routers/auth.py`, `lemely/web/routers/student_classes.py`; `tests/test_parent_link_integrity.py`, `tests/test_class_side_door.py` (new).
- **Tests first:** every name in SPEC §c.4 "Tests" except the three block/suspension/close enrolment tests (T21 owns those), plus `test_race_two_redeems_at_three_links_exactly_one_succeeds` (in `test_parent_link_integrity.py`), `test_lock_link_in_session_blocks_concurrent_unlink`, `test_linked_parent_ids_in_session`, `test_remove_school_less_enrolments_only_school_less`, `test_s16_lists_only_callers_classes_with_teacher_is_your_tutor`, `test_authz_student_can_leave_school_less_class_only`, `test_existing_route_guards_unchanged`.
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_parent_link_integrity.py tests/test_class_side_door.py tests/test_parent_repo.py tests/test_invite_repo.py tests/test_class_repo.py tests/test_web_invites.py tests/test_web_student_classes.py tests/test_web_student.py tests/test_web_auth.py tests/test_auth_router.py tests/test_web_parent.py tests/test_schemas_student_classes.py` + SCAN-PY
- **Return:** standard; `HOT PATCH`: `tests/test_authz_matrix_complete.py` rows S16, S17 (STUDENT). No `app.py` change (both routes sit on routers already included).
- **Produces:** `ParentLinkService.lock_link_in_session(session, parent_id, child_id) -> bool`; `ParentLinkService.linked_parent_ids_in_session(session, child_id) -> list[UUID]`; `ParentLinkService.unlink(...) -> bool`; `ClassService.join_by_code_outcome(student_id, join_code) -> tuple[ClassRow, bool]`; `ClassService.leave_school_less_class(student_id, class_id) -> bool`; `ClassService.remove_school_less_enrolments_in_session(session, *, teacher_user_id: UUID, student_ids: Sequence[UUID] | None) -> int`; `ClassService.class_access_for_student(student_id) -> list[ClassAccessItem]`.
- **Mutation proof:** remove the `FOR UPDATE` on the child row → two-redeems race test red; let S17 delete a school class enrolment → leave test red; skip the unlink event row → `test_unlink_writes_link_event` red.

### T10 `[A·opus·xhigh]` Admin approval and tutor evidence
- **Goal:** A1–A4 (queue, detail with 300 s attachment URLs logged per issue, approve incl. reinstate, reject) and T6/T7 (evidence upload with magic-byte sniff, Pillow re-encode, 5 × 10 MiB, delete), `documents_seen_at` rules, `emailDelivery` on A1.
- **Depends on:** T01, T04, T06, T07 (`listing_notices`, `enqueue_in_session`, `email_delivery_mode`).
- **Owned files:** `lemely/db/tutor_approval_repo.py`, `lemely/db/tutor_evidence_repo.py`, `lemely/io/evidence_files.py`, `lemely/web/routers/tutor_evidence.py`, `lemely/web/routers/admin_tutors.py` (new); `lemely/io/storage.py`, `lemely/io/storage_local.py`, `lemely/io/storage_gcs.py`, `tests/storage_fakes.py` (`disposition` parameter); tests below.
- **Tests first:** `tests/test_tutor_approval_repo.py` (`test_approve_sets_first_listed_once`, `test_documents_seen_cleared_by_upload_delete_and_false_approval`, `test_reinstate_restores_nothing`, `test_reject_requires_note`); `tests/test_evidence_files.py` (`test_sniffed_type_overrides_declared`, `test_polyglot_rejected_415`, `test_reencode_drops_exif`, `test_filename_sanitised`); `tests/test_tutor_evidence.py` (`test_evidence_limit_409`, `test_delete_after_commit_logs_orphan`); `tests/test_web_admin_tutoring.py` (`test_idor_a2_evidence_url_ttl_300_and_attachment`, `test_a2_writes_one_evidence_open_row_per_url_and_fails_closed`, `test_a1_reports_email_delivery_mode`); `tests/test_web_tutoring_authz_admin.py` (`test_idor_t7_cannot_delete_other_tutors_evidence` (O20), O17, O15 admin half); extend `tests/test_storage_local.py`, `tests/test_storage_gcs.py` with `test_signed_url_disposition_attachment`.
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_tutor_approval_repo.py tests/test_evidence_files.py tests/test_tutor_evidence.py tests/test_web_admin_tutoring.py tests/test_web_tutoring_authz_admin.py tests/test_storage_local.py tests/test_storage_gcs.py tests/test_web_platform_admin.py $(grep -l "storage_fakes" tests/test_*.py)` + SCAN-PY
- **Return:** standard; `HOT PATCH`: `lemely/web/app.py` (two routers), `tests/test_authz_matrix_complete.py` rows T6, T7 (TEACHER), A1–A4 (PLATFORM_ADMIN).
- **Produces:** `TutorApprovalRepository.record_event_in_session(session, *, tutor_profile_id, admin_user_id, decision, documents_seen: bool, note: str | None) -> UUID` (snapshot taken inside), `approve(...)`, `reject(...)`; `StorageBackend.create_signed_url(bucket, object_path, expires_in, *, disposition: str | None = None) -> str`.
- **Mutation proof:** trust the declared content type → sniff test red; skip the access-log insert → fail-closed test red; keep `documents_seen_at` on upload → clearing test red.

### T11 `[B·sonnet·high]` Web API hooks and query keys
- **Goal:** one react-query hook per route (70), typed from `tutoringTypes.ts`; typed error mapping for every 409/422 code in SPEC §b.2; query keys outside the persist allowlist; clears a student's cached detail on 403 `access_ended`.
- **Depends on:** T04.
- **Owned files:** `web/src/lib/hooks/useTutoringApi.ts`, `web/src/lib/tutoring/queryKeys.ts`, `web/src/lib/tutoring/apiErrors.ts` (new); `web/tests/unit/tutoringQueryKeys.test.ts`, `web/tests/unit/tutoringApiErrors.test.ts` (new), `web/tests/unit/persistAllowlist.test.ts`.
- **Tests first:** "every SPEC route has exactly one hook" (route table literal in the test), "every refusal code maps to a typed error", `persistAllowlist.test.ts` "excludes tutoring query keys", "access_ended clears the student detail key".
- **Acceptance:** `cd web && npx vitest run tests/unit/tutoringQueryKeys.test.ts tests/unit/tutoringApiErrors.test.ts tests/unit/persistAllowlist.test.ts && npm run typecheck` + SCAN-WEB
- **Return:** standard. After I3 `useTutoringApi.ts`, `queryKeys.ts`, `apiErrors.ts` are **hot**.
- **Mutation proof:** add a tutoring key to the allowlist → persist test red.

### T12 `[B·sonnet·high]` Reviews, replies, moderation, rating recompute
- **Goal:** S6, S7, T18, T21, SP3, A6–A8; one review per completed booking, 7-day open, 14-day edit, account ≥ 14 days, latest review per student counted once, `rank_score` written in the same transaction under `FOR UPDATE` on the tutor row; `lemely tutoring recompute-ratings`.
- **Depends on:** T01, T02, T04, T06, T07 (`review_notices`).
- **Owned files:** `lemely/db/tutor_review_repo.py`, `lemely/app/tutoring_cli.py`, `lemely/web/routers/tutoring_reviews.py`, `lemely/web/routers/student_reviews.py`, `lemely/web/routers/tutor_reviews.py`, `lemely/web/routers/admin_tutoring_moderation.py` (new); tests below.
- **Tests first:** `tests/test_tutor_review_repo.py` (`test_review_create_refused_before_notes_window_closes`, `test_review_requires_completed_booking_and_own_student`, `test_account_too_new_409`, `test_block_keeps_review_right`, `test_edit_returns_text_to_pending_and_closes_after_14_days`, `test_rank_score_written_with_rating_change`, `test_removed_review_leaves_aggregate`); `tests/test_web_tutor_reviews.py` (`test_review_text_public_only_after_approval`, `test_reply_moderated_before_public`, `test_t21_own_reply_any_state_text_only_when_approved`, `test_reviews_show_quarter_and_a_student`); `tests/test_web_tutoring_authz_reviews.py` (O10, O27, O11 for SP3: `test_sp3_404_for_unlisted_paused_or_blocked_tutor`; parents refused by guard); `tests/test_tutoring_concurrency_reviews.py` (`test_race_two_reviews_same_student_aggregate_counts_once`); `tests/test_tutoring_cli.py` (`test_recompute_ratings_matches_incremental`).
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_tutor_review_repo.py tests/test_web_tutor_reviews.py tests/test_web_tutoring_authz_reviews.py tests/test_tutoring_concurrency_reviews.py tests/test_tutoring_cli.py` + SCAN-PY
- **Return:** standard; `HOT PATCH`: `lemely/web/app.py` (four routers), `lemely/app/cli.py` (register `tutoring recompute-ratings` calling `tutoring_cli.recompute_ratings_command`), `tests/test_authz_matrix_complete.py` rows SP3, S6, S7, T18, T21, A6–A8.
- **Produces:** `TutorReviewRepository.recompute_ratings_in_session(session, tutor_profile_id) -> None`, `remove_review_in_session(session, review_id, admin_user_id) -> bool`, `hide_reply_in_session(session, reply_id, admin_user_id) -> bool`.
- **Mutation proof:** count every review instead of the latest per student → race test red; drop the 7-day guard → window test red.

### T13 `[A·opus·xhigh]` Booking service and repository
- **Goal:** SPEC §a.3, §a.4, §a.4b: create (lock order 1→5, lazy expiry, pending cap, quotas, safety-notice check by its own in-session read of `student_tutoring_preferences.safety_notice_acknowledged_at` — T14's preferences repository is in the same wave —, parent link lock), compare-and-set transitions incl. row 18 using `booking_predicates` from T01, notes, freeze/hide, admin and system cancels for sweeps and reports, slots with busy intervals, constraint-name error mapping, effective-state SQL predicates, outbox enqueue in the transaction, viewer-dependent `BookingDTO`/`NoteDTO` builders.
- **Depends on:** T01, T03, T07, T09.
- **Owned files:** `lemely/db/booking_repo.py`, `lemely/web/booking_view.py` (new); tests below.
- **Tests first:** `tests/test_booking_repo.py` (create guards incl. `test_authz_booking_horizon_28_days`, `test_authz_parent_first_note_rejected`, `test_safety_notice_required_for_student_requester_only`, `test_quota_booking_create_429_after_10_per_day`, `test_lazy_expiry_frees_one_pending_index`, transitions incl. row 18 `test_tutor_late_cancel_persists_reason_and_party`, `test_tutor_late_cancel_refused_without_reason_even_if_core_bypassed`, `test_failed_transition_writes_no_outbox_row`, `test_can_post_note_enforced`, error mapping per constraint name); `tests/test_booking_predicates_parity.py` (each §a.3 predicate and the live pending count vs `core.booking`); `tests/test_booking_view.py` (`test_meeting_link_only_after_accept_to_participants_and_parents` (O16), `test_system_cancel_reason_shows_cancelled_to_tutor`, `test_review_fields_student_viewer_only`, `test_cancelled_late_flag`); `tests/test_tutoring_concurrency_bookings.py` (slot race 8 threads → one 201, accept vs cancel, `test_race_pending_limit_concurrent_requests_at_most_5`, `test_race_unlink_vs_parent_booking_create`).
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_booking_repo.py tests/test_booking_predicates_parity.py tests/test_booking_view.py tests/test_tutoring_concurrency_bookings.py` + SCAN-PY; each race test also run 5 times in a loop (§5.1 W4)
- **Return:** standard. No hot patch.
- **Produces:** `BookingService(sessionmaker, *, clock)`: `create(...) -> BookingRow`, `transition(*, booking_id, actor: Actor, action: Action, reason: str | None = None, accept: AcceptDetails | None = None) -> BookingRow`, `slots(tutor_profile_id, *, start: date, days: int, duration_minutes: int) -> SlotsView`, `get_for_viewer(...)`, `list_for_student(...)`, `list_for_tutor(...)`, `list_for_child(...)`, `post_note(...)`, `list_notes(...)`; session-level helpers for later tasks: `freeze_notes_in_session`, `unfreeze_notes_in_session`, `hide_note_in_session(session, note_id, admin_user_id)`, `cancel_future_for_pair_in_session(session, *, tutor_profile_id, student_id) -> list[UUID]`, `cancel_future_for_tutor_in_session(session, *, tutor_profile_id) -> list[UUID]`, `admin_cancel_in_session`, `admin_complete_in_session`; `BookingRefused(code: str, status: int)`; `booking_view.build_booking_dto(view, *, viewer, now, student_shared: bool | None) -> BookingDTO`, `build_note_dto(...)`.
- **Mutation proof:** remove the `users` row `FOR UPDATE` in create → `test_race_pending_limit_concurrent_requests_at_most_5` red; bypass the core reason check in the service → `test_tutor_late_cancel_refused_without_reason_even_if_core_bypassed` still red (CAS `WHERE` + `ck_tutor_bookings_late_cancel_reason`, defence in depth); serialise `meeting_link` before accept → O16 test red.

### T14 `[A·opus·xhigh]` Grants, audit log, preferences, tutor's view of a student
- **Goal:** S8–S11, T19, T20 (validity + audit row in one transaction before data loads; fail closed), the tutor projection (SPEC §e.2), preferences repo (opt-out, safety-notice acknowledgement), `studentShared` predicate, revoke helpers for sweeps. T19's upcoming-session count uses `booking_predicates.EFFECTIVE_STATE_SQL` from T01 (not T13, same wave). Grant notices to linked parents use `ParentLinkService.linked_parent_ids_in_session` (T09) and the outbox (T07).
- **Depends on:** T01, T04, T05, T06, T07, T09.
- **Owned files:** `lemely/db/tutor_grant_repo.py`, `lemely/web/student_detail_view.py`, `lemely/web/routers/tutor_students.py`, `lemely/web/routers/student_tutor_access.py` (new); tests below.
- **Tests first:** `tests/test_tutor_grant_repo.py` (`test_one_live_grant_returns_existing_200`, `test_revoke_idempotent`, `test_audit_row_written_before_data_and_in_same_transaction`, `test_audit_failure_returns_500_no_body`, `test_t19_one_list_row_per_listed_student`, `test_403_and_404_write_no_audit`); `tests/test_grant_predicate_parity.py` (SQL `grant_is_valid` vs core over generated inputs); `tests/test_student_detail_view.py` (`test_privacy_tutor_projection_truncates_timestamps_and_drops_question_ids`); `tests/test_web_tutor_students.py` (route-level `test_t20_equals_projection_of_teacher_route`, `test_t20_json_has_no_key_outside_dto`, `test_authz_t20_reason_code_generic_access_ended`); `tests/test_web_student_tutor_access.py` (S8–S11 incl. `alsoTeachesClasses`; O11 for S9: `test_s9_refused_for_unlisted_paused_or_blocked_tutor`; `test_revoke_then_regrant_notifies_parents_twice`; `test_authz_grant_invalid_when_listing_rejected` at route level through T20 → 403 `access_ended`); `tests/test_web_tutoring_authz_grants.py` (O2, O3, O14 both directions, O18: `test_idor_t20_other_tutors_grant_does_not_authorize`, `test_idor_t20_unknown_and_never_granted_are_identical_404`, `test_authz_cross_gate_class_teacher_without_grant_t20_404`, `test_authz_cross_gate_granted_tutor_not_on_roster_teacher_route_403`); `tests/test_tutoring_concurrency_grants.py` (`test_race_revoke_vs_t20_no_200_after_revoke_commit`, concurrent grants).
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_tutor_grant_repo.py tests/test_grant_predicate_parity.py tests/test_student_detail_view.py tests/test_web_tutor_students.py tests/test_web_student_tutor_access.py tests/test_web_tutoring_authz_grants.py tests/test_tutoring_concurrency_grants.py` + SCAN-PY
- **Return:** standard; `HOT PATCH`: `lemely/web/app.py` (two routers), `tests/test_authz_matrix_complete.py` rows T19, T20, S8–S11.
- **Produces:** `TutorGrantRepository`: `create(student_id, tutor_profile_id) -> tuple[GrantRow, bool]`, `revoke(student_id, grant_id) -> GrantRow`, `require_valid_grant(caller_profile_id, student_id) -> GrantRow` (raises `AccessEnded` / `NoGrant`; audit inside), `students_page(caller_profile_id, cursor, limit)`, `grants_for_student(student_id)`, `access_log_page(student_id, *, tutor_id, cursor, limit)`, `student_shared(tutor_profile_id, student_ids) -> set[UUID]`, `revoke_live_in_session(session, *, tutor_profile_id, student_id: UUID | None, reason) -> list[UUID]`; `TutoringPreferencesRepository`: `get(student_id)`, `set_opt_out(student_id, value: bool)`, `acknowledge_safety_notice(student_id)`.
- **Mutation proof:** consult the roster in `require_valid_grant` → O14 test red; key the lookup on a passed profile id → O18 test red; insert audit after loading data → ordering test red.

### T15 `[B·sonnet·high]` UI components C-17..C-24, report and block sheets
- **Goal:** the eight catalogue components (SPEC §d) plus `report-sheet.tsx` and `block-sheet.tsx`; pure layout/copy logic in `web/src/lib/tutoring/` so node-env vitest can test it; catalogue rows.
- **Depends on:** T04.
- **Owned files:** `web/src/components/ui/{ordinal-distribution,grade-change-summary,slot-picker,booking-status,notes-thread,rating-summary,tutor-card,safety-notice-sheet}.tsx`, `web/src/components/tutoring/{report-sheet,block-sheet}.tsx`, `web/src/lib/tutoring/{ordinalLayout,gradeChange,slotGroups,bookingStatus,ratingLabel,safetyNoticeCopy}.ts` (all new); `docs/COMPONENT_CATALOGUE.md`; `web/tests/unit/{ordinalDistribution,gradeChangeSummary,slotPicker,bookingStatus,ratingSummary,safetyNotice,tutoringCatalogue}.test.ts` (new).
- **Tests first:** zero rungs listed with 0 and labels move outside narrow segments; change bar fixed title "Change in grade while with this tutor"; slots grouped by tutor-zone day with zone label; every effective state has icon + text; rating `aria-label` full sentence and "New" below 3; safety notice copy equals SPEC C-24 verbatim; catalogue has C-17..C-24 rows naming existing files.
- **Acceptance:** `cd web && npx vitest run tests/unit/ordinalDistribution.test.ts tests/unit/gradeChangeSummary.test.ts tests/unit/slotPicker.test.ts tests/unit/bookingStatus.test.ts tests/unit/ratingSummary.test.ts tests/unit/safetyNotice.test.ts tests/unit/tutoringCatalogue.test.ts && npm run typecheck && npm run lint && npm run check:copy` + SCAN-WEB
- **Return:** standard. No hot patch.

### T16 `[C·sonnet·medium]` Tutoring copy-lint rule
- **Goal:** `check_copy.mjs` bans "improvement" and "verified" in tutoring copy files (paths: `web/src/**/tutoring/**`, `web/src/portals/marketing/tutors/**`, the C-17..C-24 files); "Verify your email" stays allowed.
- **Depends on:** —.
- **Owned files:** `web/scripts/check_copy.mjs`, `web/tests/unit/checkCopy.test.ts`.
- **Tests first:** "flags 'improvement' in a tutoring file", "flags 'verified' in a tutoring file", "allows 'Verify your email'", "ignores non-tutoring files".
- **Acceptance:** `cd web && npx vitest run tests/unit/checkCopy.test.ts tests/unit/ciCopyGate.test.ts && npm run check:copy` + SCAN-WEB
- **Return:** standard.

### T17 `[A·opus·xhigh]` Booking routes for students and parents
- **Goal:** SP5, SP6, S1–S5, S14, S15, PA1–PA5 with O5–O9, O23, O26, O30 (family side), `Cache-Control: private, no-store`, after-commit notices.
- **Depends on:** T06, T07, T13, T14.
- **Owned files:** `lemely/web/routers/tutoring_booking.py`, `lemely/web/routers/student_bookings.py`, `lemely/web/routers/parent_bookings.py` (new); tests below.
- **Tests first:** `tests/test_web_tutoring_booking.py` (SP5 bounds, SP6 every code in §b.2, `test_authz_verified_email_required_for_booking_review_grant_submit` booking half, O11 for SP5 and SP6: `test_sp5_sp6_refused_for_unlisted_paused_or_blocked_tutor`, `test_query_budget_s1_pa1_two_statements`); `tests/test_web_student_bookings.py` (`test_s3_late_cancel_409_cancel_window_closed`, `test_t13_late_cancel_with_reason_200_reason_visible_to_student_and_parent` student half, `test_authz_student_may_complete_after_48h_awaiting_outcome`, S15 idempotent); `tests/test_web_parent_bookings.py` (`test_pa4_late_cancel_409_cancel_window_closed`, `test_authz_parent_cancel_requires_requester`, `test_authz_parent_actions_refused_after_unlink`, `test_idor_pa2_booking_review_null_for_parent_viewer`); `tests/test_web_tutoring_authz_bookings_family.py` (O5, O6, O7, O8, O9, O23, O26, O30 family side; `test_authz_can_post_note_state_table_s5`); `test_tutoring_private_routes_send_no_store` (these routes).
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_web_tutoring_booking.py tests/test_web_student_bookings.py tests/test_web_parent_bookings.py tests/test_web_tutoring_authz_bookings_family.py` + SCAN-PY
- **Return:** standard; `HOT PATCH`: `lemely/web/app.py` (three routers), `tests/test_authz_matrix_complete.py` rows SP5, SP6, S1–S5, S14, S15, PA1–PA5.
- **Mutation proof:** skip the per-call link re-check on PA routes → after-unlink test red; let a student send another `studentId` → `not_self` test red.

### T18 `[B·sonnet·high]` Booking routes for tutors
- **Goal:** T9–T17 with O4, O9 (tutor side), O30 (tutor side), `studentShared` without an audit row, 409 on suspended/closed profiles.
- **Depends on:** T06, T07, T13, T14.
- **Owned files:** `lemely/web/routers/tutor_bookings.py` (new); `tests/test_web_tutor_bookings.py`, `tests/test_web_tutoring_authz_bookings_tutor.py` (new).
- **Tests first:** `test_t13_late_cancel_without_reason_422`, `test_t13_late_cancel_with_reason_200_reason_visible_to_student_and_parent` (tutor half), `test_t9_state_filter_uses_effective_predicates`, `test_t11_meeting_link_allowlist_and_location_required`, `test_authz_accept_refused_when_blocked`, `test_authz_accept_refused_when_suspended`, `test_authz_suspended_tutor_cannot_post_note_on_completed_booking`, `test_idor_t10_booking_review_null_for_tutor_viewer`, `test_t10_student_shared_writes_no_audit_row`, `test_authz_suspended_tutor_write_routes_409` (T11–T15, T17 cases), `test_authz_complete_requires_ends_at` (T14/T15 before `ends_at` → 409 `not_ended`), `test_authz_can_post_note_state_table` (T17 route over every effective state; S5 is covered the same way in T17's family file), `test_query_budget_t9_two_statements`.
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_web_tutor_bookings.py tests/test_web_tutoring_authz_bookings_tutor.py` + SCAN-PY
- **Return:** standard; `HOT PATCH`: `lemely/web/app.py` (one router), `tests/test_authz_matrix_complete.py` rows T9–T17.

### T19 `[A·opus·xhigh]` Outcome figures
- **Goal:** SP4 and T8 per ADR-T04 and SPEC §e.3: three statements (profile check, cohort, observations), explicit predicates (no reliance on the soft-delete loader), SQL mirror of `is_outcome_eligible`, nothing cached.
- **Depends on:** T05, T06, T13.
- **Owned files:** `lemely/db/tutor_outcomes_repo.py`, `lemely/web/routers/tutoring_outcomes.py`, `lemely/web/routers/tutor_preview.py` (new); `tests/test_tutor_outcomes_repo.py`, `tests/test_outcome_eligibility_parity.py`, `tests/test_web_tutoring_outcomes.py` (new).
- **Tests first:** one DB test per exclusion with a red case (deleted, custom paper, quiz, other subject, estimated boundary, opted out, student-initiated block, unverified, account too new); `test_query_budget_outcomes_three_statements`; `test_outcomes_marking_complete_no_show_changes_nothing` (byte-identical `OutcomesDTO` from T8 and SP4 before and after complete and no-show), `test_late_cancel_leaves_outcomes_unchanged` (same check around a tutor's late cancel, SPEC §e.4); `test_idor_t8_preview_omits_outcomes_when_suspended_or_rejected`; O11 for SP4: `test_sp4_404_for_unlisted_paused_or_blocked_tutor`; the opt-out/opt-in hold. The tutor-block case is T21's (`test_tutor_block_leaves_outcomes_unchanged`).
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_tutor_outcomes_repo.py tests/test_outcome_eligibility_parity.py tests/test_web_tutoring_outcomes.py` + SCAN-PY
- **Return:** standard; `HOT PATCH`: `lemely/web/app.py` (two routers), `tests/test_authz_matrix_complete.py` rows SP4, T8.
- **Produces:** `TutorOutcomesRepository.outcomes(tutor_profile_id, *, now) -> OutcomesDTO`.
- **Mutation proof:** drop `boundary_source = 'exact'` → estimated-boundary test red; use `completed` instead of `accepted_at IS NOT NULL` for membership → byte-identical test red.

### T20 `[A·opus·xhigh]` Student tutoring settings and parent sharing views
- **Goal:** S12, S13 (opt-out with `outcome_pref_changed_at`), PA6, PA7 (child's grants and tutor-read log, read-only, link checked every call through `ParentLinkService.get_child`, no audit row written).
- **Depends on:** T14.
- **Owned files:** `lemely/web/routers/student_tutoring_settings.py`, `lemely/web/routers/parent_tutor_access.py` (new); `tests/test_web_student_tutoring_settings.py`, `tests/test_web_parent_tutor_access.py`, `tests/test_web_tutoring_authz_parent_sharing.py` (new).
- **Tests first:** `test_opt_out_sets_changed_at_only_on_value_change`; `test_pa6_returns_only_childs_grants_also_teaches_empty`; `test_pa7_writes_no_tutor_access_audit_row`; O22 (other child 403/404); `test_notify_grant_commit_implies_parent_inbox_rows` read through PA6.
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_web_student_tutoring_settings.py tests/test_web_parent_tutor_access.py tests/test_web_tutoring_authz_parent_sharing.py` + SCAN-PY
- **Return:** standard; `HOT PATCH`: `lemely/web/app.py` (two routers), `tests/test_authz_matrix_complete.py` rows S12, S13, PA6, PA7.

### T21 `[A·opus·xhigh]` Blocks, suspension and close sweeps, sanction routes
- **Goal:** B1–B3, A5, A12 and the one-transaction sweeps of SPEC §a.2 (blocks) and §a.3 (suspend/close) under the §a.4b locks: revoke grants, cancel future bookings (block overrides 24 h), remove school-less enrolments, approval event, notices after commit.
- **Depends on:** T09, T10, T13, T14, T19.
- **Owned files:** `lemely/db/tutoring_sweeps.py`, `lemely/db/tutoring_blocks_repo.py`, `lemely/web/routers/tutoring_blocks.py`, `lemely/web/routers/admin_tutor_sanctions.py` (new); tests below.
- **Tests first:** `tests/test_tutoring_sweeps.py` (`test_block_removes_school_less_enrolment_keeps_school_enrolment`, `test_suspension_removes_school_less_enrolments_of_tutoring_students_only`, `test_close_removes_school_less_enrolments`, `test_authz_suspension_revokes_grants_with_reason`, `test_authz_reinstatement_does_not_restore_grants`, `test_block_cancels_inside_24h`, `test_tutor_block_leaves_outcomes_unchanged`, `test_authz_block_keeps_notes_readable_and_reportable`); `tests/test_tutoring_blocks_repo.py` (re-block clears `removed_at`, rows never deleted); `tests/test_web_tutoring_blocks.py` (`test_idor_b2_student_blocks_by_tutor_id`, O13, O28, 422 wrong field); `tests/test_web_admin_tutor_sanctions.py` (A5, A12 `already_closed`); `tests/test_tutoring_concurrency_sweeps.py` (`test_race_block_vs_booking_create_no_active_booking_survives`, `test_race_suspend_vs_booking_create_no_active_booking_survives`, `test_race_suspend_vs_accept_exactly_one_outcome`, `test_race_block_vs_note_post_no_note_after_block`, `test_race_grant_create_vs_block_grant_never_valid`); `tests/test_web_tutoring_authz_blocks.py` (`test_authz_suspended_tutor_write_routes_409` B2 case).
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_tutoring_sweeps.py tests/test_tutoring_blocks_repo.py tests/test_web_tutoring_blocks.py tests/test_web_admin_tutor_sanctions.py tests/test_tutoring_concurrency_sweeps.py tests/test_web_tutoring_authz_blocks.py` + SCAN-PY; each race test also run 5 times in a loop
- **Return:** standard; `HOT PATCH`: `lemely/web/app.py` (two routers), `tests/test_authz_matrix_complete.py` rows B1–B3 (`STUDENT_OR_TEACHER`), A5, A12.
- **Produces:** `tutoring_sweeps.sweep_block_in_session(session, *, student_id, tutor_profile_id, now) -> SweepResult`, `sweep_sanction_in_session(session, *, tutor_profile_id, reason: Literal["tutor_suspended", "tutor_closed"], admin_user_id, note) -> SweepResult`.
- **Mutation proof:** take the tutor row `FOR SHARE` in the sweep → suspend-vs-create race red; delete school enrolments too → keep-school test red.

### T22 `[B·sonnet·high]` Screens: public directory and student discovery (G-16, G-17, S-33, S-34, S-35)
- **Goal:** SPEC §d for these screens incl. robots meta (row 17), results section (C-17/C-18 with caption and insufficient state), share sheet, C-24 before the first request, every 409 copy. Build the reusable compositions P-07 needs.
- **Depends on:** T11, T15.
- **Owned files:** `web/src/portals/marketing/tutors/{TutorDirectory,TutorPublicCard}.tsx`, `web/src/portals/student/screens/tutoring/{FindTutor,TutorProfile,BookSession}.tsx`, `web/src/components/tutoring/{directory-view,directory-filters,tutor-profile-view,booking-form,share-progress-sheet}.tsx`, `web/src/lib/tutoring/{discovery,bookingErrors,robotsMeta}.ts` (all new); `web/tests/unit/{tutoringDiscovery,tutoringBookingErrors,tutoringRobotsMeta}.test.ts` (new).
- **Tests first:** filter state ↔ query params; every SP6 refusal code maps to the SPEC copy; robots meta `noindex, follow` on G-16, `noindex, nofollow` on G-17 unless `indexable === true` (and while loading or failed).
- **Acceptance:** `cd web && npx vitest run tests/unit/tutoringDiscovery.test.ts tests/unit/tutoringBookingErrors.test.ts tests/unit/tutoringRobotsMeta.test.ts && npm run typecheck && npm run lint && npm run check:copy` + SCAN-WEB
- **Return:** standard; `HOT PATCH`: `web/src/routes.tsx` (`/tutors`, `/tutors/:tutorId`), `web/src/portals/student/index.tsx` (three routes), `web/src/portals/student/data.ts` ("Tutors" nav); plus `NOTES` listing audit slugs and states for T33.

### T23 `[B·sonnet·high]` Screens: student sessions and data (S-36, S-37, S-38)
- **Goal:** SPEC §d incl. row 18 states (inside 24 h copy; tutor late-cancel reason), review form, C-21 with C-24 gate, S-38's five sections (sharing, who looked, class access with Leave, results counting toggle, blocked tutors). Build `session-detail-view` reusable for P-06.
- **Depends on:** T11, T15.
- **Owned files:** `web/src/portals/student/screens/tutoring/{Sessions,SessionDetail,TutorAccess}.tsx`, `web/src/components/tutoring/{session-detail-view,review-form,stop-sharing-sheet}.tsx`, `web/src/lib/tutoring/{sessionView,accessView}.ts` (new); `web/tests/unit/{tutoringSessionView,tutoringAccessView}.test.ts` (new).
- **Tests first:** actions rendered only from `allowedActions`; inside-24 h copy for the student; late-cancel line uses `cancelReason` as plain text; stop-sharing sheet adds the class line only when `alsoTeachesClasses` is non-empty.
- **Acceptance:** `cd web && npx vitest run tests/unit/tutoringSessionView.test.ts tests/unit/tutoringAccessView.test.ts && npm run typecheck && npm run lint && npm run check:copy` + SCAN-WEB
- **Return:** standard; `HOT PATCH`: `web/src/portals/student/index.tsx` (three routes), `web/src/portals/student/data.ts` ("Sessions" nav).

### T24 `[B·sonnet·high]` Screens: teacher tutoring (T-15, T-16, T-17, T-18, T-21)
- **Goal:** SPEC §d incl. row 17 search notice and toggle on T-16, row 18 `cancel_with_reason` sheet on T-18, availability editor with DST note, reply composer.
- **Depends on:** T11, T15.
- **Owned files:** `web/src/portals/teacher/screens/tutoring/{TutoringHome,TutorProfileEditor,Availability,TutorSessionDetail,PreviewReviews}.tsx`, `web/src/lib/tutoring/{availabilityEditor,profileSteps,tutorSessionActions}.ts` (new); `web/tests/unit/{tutoringAvailabilityEditor,tutoringProfileSteps,tutorSessionActions}.test.ts` (new).
- **Tests first:** 15-minute steps and midnight split into two rules; moderated-field edit shows the re-review line, `indexable`/`paused` do not; search notice copy equals SPEC; `cancel_with_reason` requires a non-blank reason before submit.
- **Acceptance:** `cd web && npx vitest run tests/unit/tutoringAvailabilityEditor.test.ts tests/unit/tutoringProfileSteps.test.ts tests/unit/tutorSessionActions.test.ts && npm run typecheck && npm run lint && npm run check:copy` + SCAN-WEB
- **Return:** standard; `HOT PATCH`: `web/src/portals/teacher/index.tsx` (five routes), `web/src/portals/teacher/data.ts` ("Tutoring" nav).

### T25 `[A·opus·xhigh]` Reports and admin report handling
- **Goal:** R1 (no verified-email gate; 20/day; one open per reporter and target), A9–A11 with every resolution, `safety_concern` freezes notes and notifies admins, report-target visibility resolved server-side (O12, O19), thread views logged (SC-23).
- **Depends on:** T09, T12, T13, T21.
- **Owned files:** `lemely/db/tutoring_reports_repo.py`, `lemely/web/routers/tutoring_reports.py`, `lemely/web/routers/admin_tutoring_reports.py` (new); `tests/test_tutoring_reports_repo.py`, `tests/test_web_tutoring_reports.py`, `tests/test_web_admin_tutoring_reports.py`, `tests/test_web_tutoring_authz_reports.py`, `tests/test_tutoring_cache_headers.py` (new).
- **Tests first:** `test_idor_report_note_visibility_resolved_from_note_booking`, `test_idor_report_reply_requires_visible_review`, `test_authz_report_tutor_profile_allowed_for_participant_when_paused`, `test_authz_safety_report_freezes_thread_until_resolved`, `test_authz_report_allowed_without_verified_email`, `test_a10_writes_report_thread_view_and_fails_closed`, `test_a11_resolution_not_applicable_cases`, `test_a11_suspend_resolution_runs_sanction_sweep`, `test_report_quota_429_after_20`; plus the whole-feature cache test `tests/test_tutoring_cache_headers.py::test_public_routes_only_p1_p3_cacheable` (every tutoring route via the app's route table: only P1–P3 send `public`, every **NS** route sends `private, no-store`).
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_tutoring_reports_repo.py tests/test_web_tutoring_reports.py tests/test_web_admin_tutoring_reports.py tests/test_web_tutoring_authz_reports.py tests/test_tutoring_cache_headers.py` + SCAN-PY
- **Return:** standard; `HOT PATCH`: `lemely/web/app.py` (two routers), `tests/test_authz_matrix_complete.py` rows R1 (`TUTORING_PARTY`), A9–A11.

### T26 `[B·sonnet·high]` Screens: tutor's students (T-19, T-20)
- **Goal:** T-19 list; T-20 renders the T-05 composition fed by the tutor projection with the removed actions absent, one `access_ended` state, cache cleared on 403.
- **Depends on:** T11, T15.
- **Owned files:** `web/src/portals/teacher/screens/tutoring/{MyStudents,TutorStudentDetail}.tsx`, `web/src/lib/tutoring/tutorStudentView.ts` (new); `web/tests/unit/tutorStudentView.test.ts` (new). If the T-05 composition is not reusable as is, also `web/src/portals/teacher/screens/StudentDetail.tsx` for a pure extraction (no behaviour change; `web/e2e/teacher-journey.spec.ts` stays green in T33).
- **Tests first:** removed actions (drill-down, remark, assign practice, at-risk acknowledge, integrity) never render for the tutor view; dates only, no times.
- **Acceptance:** `cd web && npx vitest run tests/unit/tutorStudentView.test.ts && npm run typecheck && npm run lint && npm run check:copy` + SCAN-WEB
- **Return:** standard; `HOT PATCH`: `web/src/portals/teacher/index.tsx` (two routes).

### T27 `[B·sonnet·high]` Screens: parent (P-05, P-06, P-07, P-08)
- **Goal:** SPEC §d parent screens, reusing T22's discovery compositions (child selector, no first-note field, no share/block/C-24) and T23's `session-detail-view` (read-only notes, cancel/complete only for the requester).
- **Depends on:** T11, T15, T22, T23.
- **Owned files:** `web/src/portals/parent/screens/tutoring/{ChildTutoring,ParentSessionDetail,ParentFindTutor,ChildTutorAccess}.tsx`, `web/src/lib/tutoring/parentTutoring.ts` (new); `web/src/portals/parent/screens/ChildOverview.tsx` (one "Tutoring" link to P-05 for the child; P-05 links on to P-08 and P-07); `web/tests/unit/parentTutoring.test.ts` (new).
- **Tests first:** booking form for a parent never contains `firstNote`; actions shown only when `requestedBy === "parent"` and the action is in `allowedActions`; P-08 has no revoke control.
- **Acceptance:** `cd web && npx vitest run tests/unit/parentTutoring.test.ts && npm run typecheck && npm run lint && npm run check:copy` + SCAN-WEB
- **Return:** standard; `HOT PATCH`: `web/src/portals/parent/index.tsx` — the child routes (`/parent/children/:childId/tutoring`, `/parent/children/:childId/sessions/:bookingId`, `/parent/children/:childId/tutor-access`, `/parent/tutors`, `/parent/tutors/:tutorId`, `/parent/tutors/:tutorId/book`) and one "Tutors" link (`/parent/tutors`) in its `Header()` beside the existing Notifications link. The parent portal has no `data.ts` nav; the header is its nav.

### T28 `[B·sonnet·high]` Screens: platform admin (X-04, X-05, X-06, X-07)
- **Goal:** utilitarian admin screens per SPEC §d incl. the "Email delivery: mock" banner, required "I looked at the documents" checkbox, close confirm copy, resolution choices limited by A11's applicability.
- **Depends on:** T11, T15.
- **Owned files:** `web/src/portals/admin/screens/tutoring/{TutorQueue,TutorApplication,Moderation,Reports,ReportDetail}.tsx`, `web/src/lib/tutoring/adminTutoring.ts` (new); `web/tests/unit/adminTutoring.test.ts` (new).
- **Tests first:** approve disabled until the documents checkbox is ticked; resolution options for a booking target after start exclude `booking_cancelled`.
- **Acceptance:** `cd web && npx vitest run tests/unit/adminTutoring.test.ts && npm run typecheck && npm run lint && npm run check:copy` + SCAN-WEB
- **Return:** standard; `HOT PATCH`: `web/src/portals/admin/index.tsx`, `web/src/portals/admin/data.ts` (`platformNavItems`: Tutors, Moderation, Reports), `web/tests/unit/adminRoutes.test.ts` (both directions).

### T29 `[B·sonnet·high]` E2E seed data
- **Goal:** extend `scripts/seed_e2e.py` and the `SeedContract` with: two listed tutors (one indexable, one opted out), one tutor with a **sufficient** outcome figure (≥ 5 eligible students with closed windows, exact-boundary grades, never-granted count 0 or ≥ 5, largest bucket ≤ n−2) and one insufficient; a draft tutor for onboarding; bookings in every effective state incl. a tutor late cancel; one grant with audit rows; a linked parent; one open safety report; a platform admin.
- **Depends on:** T06–T25 merged (I7).
- **Owned files:** `scripts/seed_e2e.py`, `web/e2e/seed.ts`, `web/e2e/seed-contract.spec.ts`, `tests/test_seed_e2e.py`.
- **Tests first:** `test_seed_tutoring_outcome_fixture_is_sufficient` (runs `core.tutor_outcomes.outcome_for_subject` on the seed's derivable inputs), `test_seed_tutoring_insufficient_fixture`, contract keys for every new group.
- **Acceptance:** `PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_seed_e2e.py tests/test_seed.py` and `cd web && npm run typecheck` + SCAN-PY + SCAN-WEB
- **Return:** standard; `NOTES`: the seeded ids/names T32 and T33 use.

### T30 `[A·opus·xhigh]` Security review (read-only)
- **Goal:** adversarial review of the integrated branch at the I7 SHA: authz and IDOR (O1–O31 against code), tenancy (three gates never union), grant/audit fail-closed, parent acting-for-child path, outbox and notices carrying no PII, evidence upload, the edge worker lookup, cache headers, SQL injection through cursors and filters, rate/quotas.
- **Depends on:** I7.
- **Owned files:** none (read-only). Every finding is checked at the SHA (`git show <sha>:<path>`).
- **Tests first:** none; each finding must name a failing test the fix task will add.
- **Acceptance:** report delivered with severity, file:symbol, exploit sketch, and the red test to add; zero unverified claims.
- **Return:** `STATUS`, findings table, and a proposed fix-task list (owner = the task whose files hold the fix; the lead reopens ownership).

### T31 `[C·sonnet·medium]` Phase 4 docs
- **Goal:** CHANGELOG entry; `docs/LEMELY_UI_SPEC.md` Part 3 rows (G-16, G-17, S-33..S-38, T-15..T-21, P-05..P-08, X-04..X-07) and Part 4 sections, and §1.4 principles 3 and 5 reworded (row 19); `BUILD/MISSION.md` §3 note that "their teachers" includes a tutor the student granted (row 19); `docs/database.md` (`btree_gist` is the first extension Alembic creates; tenancy unchanged per ADR-T03); `docs/deployment.md` (§5.7 rollback `DELETE` entry from SPEC §f, WAF ops step, retention note, row 17 staging `curl -sI` checklist from T08's NOTES, email mock note); `docs/email-delivery.md` (transactional outbox path); `docs/push-notifications.md` (only if it lists notification types); `web/src/portals/marketing/dataHandling.ts` sentences for every wave (SPEC §f, with source comments). Every file path copied from SPEC §g into `DELIVERY.md` is mapped through §1.4 first (SPEC names `routers/{tutor,admin_tutoring,parent_tutoring,student_tutoring}.py`, `tutoring_safety_repo.py`, `tests/test_web_tutoring_safety.py`, `tests/test_web_parent_tutoring.py`, `tests/test_web_tutoring_authz.py`, `tests/test_concurrency.py`, and puts outcomes in `tutor_directory_repo.py`; none of those is the built name), and every cited test path is checked to exist with `ls`.
- **Depends on:** I7.
- **Owned files:** `CHANGELOG.md`, `docs/LEMELY_UI_SPEC.md`, `BUILD/MISSION.md`, `docs/database.md`, `docs/deployment.md`, `docs/email-delivery.md`, `docs/push-notifications.md`, `web/src/portals/marketing/dataHandling.ts`, `web/tests/unit/dataHandling.test.ts`.
- **Tests first:** extend `dataHandling.test.ts` for the new sentences and their source comments.
- **Acceptance:** `cd web && npx vitest run tests/unit/dataHandling.test.ts tests/unit/designDocs.test.ts && npm run check:copy`
- **Return:** standard; `HOT PATCH`: `DELIVERY.md` (SPEC §g: §3 rows, §4 Payments line, new §5.7 verbatim incl. row 17 and row 18 bullets).

### T32 `[B·sonnet·high]` E2E journeys
- **Goal:** SPEC §e.4 E2E 1–5: (1) student discovers and books; (2) tutor onboards, is approved, and sees granted data, with S-38 and P-08 showing the visit; (3) consent revoked → denied with no new audit row; (4) parent books for child; (5) double-booking race.
- **Depends on:** T29, T22–T28 merged (I8).
- **Owned files:** `web/e2e/tutoring-discover.spec.ts`, `web/e2e/tutoring-onboard.spec.ts`, `web/e2e/tutoring-revoke.spec.ts`, `web/e2e/tutoring-parent.spec.ts`, `web/e2e/tutoring-double-booking.spec.ts` (new).
- **Tests first:** the five specs (red on a stack without the feature is not meaningful; instead prove each assertion can fail by pointing it at a seeded wrong value once on a scratch copy).
- **Acceptance (live stack, run by the lead or the agent serially):** `cd web && PYTHONPATH=$(cd .. && pwd) npx playwright test e2e/tutoring-discover.spec.ts e2e/tutoring-onboard.spec.ts e2e/tutoring-revoke.spec.ts e2e/tutoring-parent.spec.ts e2e/tutoring-double-booking.spec.ts e2e/seed-contract.spec.ts`
- **Return:** standard; `NOTES`: DB hygiene done (§5.4).

### T33 `[B·sonnet·high]` UI QA: audit registry, screenshots, accessibility
- **Goal:** register every SPEC §d gate route with its states, add the `platform_admin` audit session, add performance slugs, capture screenshots, and fix axe serious/critical, Lighthouse a11y < 95, perf < 80 on the listed routes, and 320 px horizontal scroll, in the tutoring screen files (ownership reassigned from T22–T28, whose tasks are closed).
- **Depends on:** T32 (serial on the live stack).
- **Owned files (fixes only; reassigned from closed tasks):** all files under `web/src/portals/*/screens/tutoring/`, `web/src/portals/marketing/tutors/`, `web/src/components/tutoring/`, `web/src/lib/tutoring/`, and T15's eight `web/src/components/ui/` files (the SVG charts and the radio-group slot picker are the likeliest axe failures). Hot (patch only): `web/scripts/audit.mjs`, `web/scripts/capture_surface.mjs`, `scripts/check_ui_gates.py`.
- **Tests first:** registry entries for every route in SPEC §d "Accessibility and performance gate routes".
- **Acceptance (live stack):** `cd web && PYTHONPATH=$(cd .. && pwd) npm run audit` then `PYTHONPATH=$PWD .venv/bin/python scripts/check_ui_gates.py` then `cd web && npm run typecheck && npm run lint && npm run check:copy && npm run build`
- **Return:** standard; `HOT PATCH`: the three hot files above; screenshot and contact-sheet paths under `reports/.scratch`.

---

## 3. Hot files (lead-owned) and the change each wave needs

| Hot file | I0 | I1 | I2 | I3 | I4 | I5 | I6 | I7 | I8 | I9 |
|---|---|---|---|---|---|---|---|---|---|---|
| Alembic chain `lemely/db/migrations/versions/` | confirm single head after rebase | verify 0044→0050 chain from the I0 head; `alembic heads` = 1 | — | — | — | — | — | — | — | — |
| `lemely/db/models/__init__.py` `import_all_models()` | — | add `tutoring` (T01) | — | — | — | — | — | — | — | — |
| `lemely/web/app.py` | — | — | 3 routers (T06); mock-email startup WARNING (T07) | 6 routers (T10, T12) | 2 (T14) | 8 (T17 ×3, T18, T19 ×2, T20 ×2) | 2 (T21) | 2 (T25); total 23 new routers | — | — |
| `tests/test_authz_matrix_complete.py` `EXPECTED` (every row: each section heading set to the rows present now, §1.4 #12) | re-derive section counts on the rebased base | — | P1–P3, SP1–SP2, T1–T5; new constant `STUDENT_OR_PARENT` added to `_REPRESENTATIVE`, assert `len(_REPRESENTATIVE) == 7`; `_NON_PUBLIC == len(ROUTES) - 15` | S16, S17, SP3, S6, S7, T6, T7, T18, T21, A1–A4, A6–A8 | T19, T20, S8–S11 | SP4–SP6, S1–S5, S12–S15, PA1–PA7, T8–T17 | B1–B3, A5, A12; new constant `STUDENT_OR_TEACHER`, assert `== 8` | R1, A9–A11; new constant `TUTORING_PARTY`, assert `== 9`; 70 routes; headings now equal SPEC §c.1's final counts | — | — |
| `pyproject.toml` (import-linter contract) | — | add the SPEC §e.1 `forbidden` contract for the five core modules present (T02: `keyset`, `contact_patterns`, `tutor_directory`, `tutor_ratings`; T03: `booking`) | add `tutor_grants`, `tutor_outcomes` (T05) | — | — | — | — | — | — | — |
| `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example` | add `[tutoring] email_daily_cap = 60`, `storage.tutor_evidence_bucket`, `storage.tutor_evidence_signed_url_ttl_seconds = 300`; regenerate with `python -m lemely.runtime.example_toml` | — | — | — | — | — | — | — | — | — |
| `lemely/web/deps.py` | — | — | `get_sweeper` passes the email provider, so the job runs in the app (T07; the job itself lives in T07's owned `scheduled_notifications.py`) | — | — | — | — | — | — | — |
| `lemely/app/cli.py` | — | — | doctor WARNING (T07) | `tutoring recompute-ratings` registration (T12) | — | — | — | — | — | — |
| `lemely/web/deps_tutoring.py` (after T06) | — | — | becomes hot | — | — | — | — | — | — | — |
| Shared API types: `lemely/web/schemas_tutoring.py`, `schemas_tutoring_admin.py`, `web/src/lib/tutoringTypes.ts` (after T04); `web/src/lib/hooks/useTutoringApi.ts`, `web/src/lib/tutoring/{queryKeys,apiErrors}.ts` (after T11) | — | become hot | — | hooks become hot | — | — | — | — | — | — |
| Web route registry: `web/src/routes.tsx`, `web/src/portals/{student,teacher,parent,admin}/index.tsx` (the parent's nav is the `Header()` in `parent/index.tsx`; there is no `parent/data.ts`), nav in `web/src/portals/{student,teacher,admin}/data.ts`, `web/tests/unit/adminRoutes.test.ts` | — | — | — | — | — | — | G-16, G-17, S-33..S-38, T-15..T-18, T-21 (T22, T23, T24) | T-19, T-20, P-05..P-08, X-04..X-07 (T26, T27, T28) | — | — |
| Audit runner + screenshots: `web/scripts/audit.mjs` (`ROUTE_REGISTRY`, `platform_admin` session), `web/scripts/capture_surface.mjs` (`SURFACES`), `scripts/check_ui_gates.py` (perf slugs) | — | — | — | — | — | — | — | — | — | T33 patch |
| `DELIVERY.md` | — | — | — | — | — | — | — | — | T31 patch | final status edits |
| `BUILD/DECISIONS.md` | (rows 17–19 already appended) | — | — | — | — | — | — | — | — | any decision taken during execution |
| `docs/tutoring/SPEC.md` | — | spec changes only by escalation (§5.3) | | | | | | | | |
| `tests/conftest.py` / test bootstrap | **no change planned** (SPEC F2: the `btree_gist` listener lives in `models/tutoring.py`); any need to change it is an escalation | | | | | | | | | |

---

## 4. Integration rows (lead) and per-wave gates

Every integration row: `git status --short --branch` first; tag `git tag tutoring/pre-I<n>`; merge each task branch (`git merge --no-ff -S tut/<ID>`) in card order; apply hot patches; commit them as `git commit -S -m "chore(tutoring): integrate W<n> hot files" -- <hot paths>`; run the gate; on red, see §5.

### Common gate block (G-common), from the feature worktree root
```bash
supabase status
.venv/bin/ruff check .
.venv/bin/ruff format --check .
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" .venv/bin/mypy lemely
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pyright lemely
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" .venv/bin/lint-imports
PGPASSWORD=postgres psql -h 127.0.0.1 -p 54322 -U postgres -c "DROP DATABASE IF EXISTS lemely_tutoring_gate" -c "CREATE DATABASE lemely_tutoring_gate"
LEMELY_DATABASE__URL=postgresql+psycopg://postgres:postgres@127.0.0.1:54322/lemely_tutoring_gate PYTHONPATH=$PWD .venv/bin/alembic upgrade head
LEMELY_DATABASE__URL=postgresql+psycopg://postgres:postgres@127.0.0.1:54322/lemely_tutoring_gate PYTHONPATH=$PWD .venv/bin/alembic check
LEMELY_DATABASE__URL=postgresql+psycopg://postgres:postgres@127.0.0.1:54322/lemely_tutoring_gate PYTHONPATH=$PWD .venv/bin/alembic heads
PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs tests/test_authz_matrix_complete.py tests/test_settings_example_drift.py tests/test_db_schema.py $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py) <WAVE FILES>
cd web && npm run typecheck && npm test && npm run lint && npm run check:copy
```
`alembic check` runs against a scratch database, never the shared `postgres` database, and is a sanity check only: SPEC §a.4 F20 records that it cannot see exclusion constraints, computed columns or partial predicates; the migration tests are the real guard. `npm test` is the node-only vitest suite (no browser, no DB); 94 of its 204 files scan the source tree, so a file list would miss them. Pyright: if errors are shaped `"X" is not assignable to "X"` or fail to resolve this worktree's modules, rerun with a temporary config adding `extraPaths` for this worktree (memory `shared-venv-editable-pth`); any other error is real. `pre-commit run --all-files` runs only here, never while a task is mid-edit: `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pre_commit run --all-files --show-diff-on-failure`, then `git status --short` must be clean.

### Full gate (after I0, I2, I4, I6, I8, IF)
`./scripts/check.sh` with the local Supabase stack up. Pass: every gate PASS, and the pytest skip list is a subset of the **I0 baseline skip list** (gates that need a key, such as live Gemini tests, may skip at baseline; no DB test and no tutoring test may skip). From I2 on, `web/` is touched, so `check.sh` also runs Playwright, the Puppeteer audit and `check_ui_gates.py`; Playwright's global setup runs `alembic upgrade head` on the shared local database (see §5.4).

| Row | Wave | Merges | Hot patches applied | Gate (<WAVE FILES>) |
|---|---|---|---|---|
| **I0** | W0 | — | Steps: (1) user approval to commit (CLAUDE.md), then commit `docs/tutoring/`, `BUILD/tutoring/`, `BUILD/DECISIONS.md` with `git commit -S -- <paths>`; (2) `git fetch origin && git rebase origin/develop` (117 commits; `app.py`, `teacher.py`, `student.py`, `config.py`, `example_toml.py`, `lemely.toml.example`, `pyproject.toml`, `docs/deployment.md` changed upstream); (3) `alembic heads` on the scratch DB (expect `0043_merge_heads`); confirm `_student_detail_dto`, `RosterEntry`, `_visible_students`, `teacher_student_detail` still exist (`git show HEAD:lemely/web/routers/teacher.py`); (4) provision `.venv` symlink and `cd web && npm ci`; (5) worktree probe (§0.3); (6) config hot patch (§3) and regenerate `lemely.toml.example`; (7) baseline full gate, record the skip list and any standing reds in `.omc/state/tutoring-baseline.md` | G-common with `<WAVE FILES>` empty; full `check.sh` |
| **I1** | W1 | T01, T02, T03, T04 | `import_all_models` + `tutoring`; import-linter contract; mark T04 files hot | `tests/test_migration_tutoring_enums.py tests/test_migration_tutor_profiles.py tests/test_migration_outbox_parent_links.py tests/test_migration_tutor_bookings.py tests/test_migration_tutor_reviews.py tests/test_migration_tutor_grants.py tests/test_migration_tutoring_safety.py tests/test_db_tutoring_schema.py tests/test_core_keyset.py tests/test_core_contact_patterns.py tests/test_core_tutor_directory.py tests/test_core_tutor_ratings.py tests/test_core_booking.py tests/test_core_booking_slots.py tests/test_schemas_tutoring.py tests/test_notification_repo.py tests/test_notification_prefs_repo.py tests/test_me_router.py tests/test_web_notifications.py`; plus downgrade round trip on the scratch DB: `alembic downgrade 0043_merge_heads` then `alembic upgrade head` (same env prefix) |
| **I2** | W2 | T05, T06, T07, T08 | `app.py` (T06 routers, T07 warning); EXPECTED (T06) incl. `STUDENT_OR_PARENT`; import-linter (T05); `deps.py` `get_sweeper` (T07); `cli.py` doctor (T07); `deps_tutoring.py` becomes hot | T05–T08 acceptance files + `tests/test_cli_doctor.py tests/test_scheduled_notifications.py tests/test_scheduled_announcements.py tests/test_web_app.py tests/test_runtime_config.py`; full `check.sh` |
| **I3** | W3 | T09, T10, T11, T12 | `app.py` (T10, T12 routers); EXPECTED (T09, T10, T12); `cli.py` (T12); hooks become hot | T09–T12 acceptance files + `tests/test_cli.py` |
| **I4** | W4 | T13, T14, T15, T16 | `app.py` (T14); EXPECTED (T14) | T13–T16 acceptance files; full `check.sh` |
| **I5** | W5 | T17, T18, T19, T20 | `app.py` (8 routers); EXPECTED (SP4–SP6, S1–S5, S12–S15, PA1–PA7, T8–T17) | T17–T20 acceptance files + the T13 and T14 files (shared service paths) |
| **I6** | W6 | T21, T22, T23, T24 | `app.py` (T21); EXPECTED (B1–B3, A5, A12) incl. `STUDENT_OR_TEACHER`; web routes and nav (T22, T23, T24) | T21 acceptance files + T13, T14, T19 files; web: add `npm run build`; full `check.sh` |
| **I7** | W7 | T25, T26, T27, T28 | `app.py` (T25); EXPECTED final (70 routes) incl. `TUTORING_PARTY`; web routes and nav (T26, T27, T28) incl. the parent `Header()` link and `adminRoutes.test.ts` | T25 acceptance files + every `tests/test_web_tutoring_authz_*.py`; web `npm run build` |
| **I8** | W8 | T29, T31 (T30 is read-only) | `DELIVERY.md` (T31); schedule fix tasks from T30 (§5.3) | T29, T31 acceptance; full `check.sh` |
| **I9** | W9 | T32, T33 | audit/screenshot/perf hot files (T33) | T32 and T33 acceptance on the live stack, serially; then DB hygiene (§5.4) |
| **IF** | final | fix tasks | final `DELIVERY.md` statuses; `BUILD/DECISIONS.md` for any execution-time decision | G-common + `cd web && npm run build && npm run check:installable` (CI runs it; locally it needs Chrome, and "Could not find Chrome" is neither a pass nor a fail — report it as not run) + full `check.sh` as the **last** action (memory `gate-sweep-goes-last`); final whole-branch review with the `requesting-code-review` reviewer on opus; PR only when the user asks |

---

## 5. Risks, rollback and stop rules

### 5.1 Per-wave risk callouts
- **W0:** the rebase crosses 117 commits touching `app.py`, `teacher.py`, `student.py`, config and `pyproject.toml`; SPEC line citations drift (work from symbols). If `alembic heads` is not `0043_merge_heads`, T01 chains from the new head and nothing else changes (tests are named by content). The worktree probe may fail (§0.3) — Mode B is slower but safe.
- **W1:** T01 is the widest schema change in the repo's history. `btree_gist` on CI `postgres:16` is unverified (SPEC O-14); the first CI run of `test_create_all_on_fresh_database_installs_btree_gist` is the proof. The contract (T04) freezes names: a wrong field name in W1 costs a hot patch in every later wave, so the task reviewer checks T04 against SPEC §b.3 line by line.
- **W2:** T08 is new edge attack surface (row 17); the lookup must fail closed and never forward client headers. T07's sweeper job runs in every API process; a MagicMock-settings test elsewhere may read the new cap as truthy (memory `sweep-must-include-source-scanning-tests`): I2 runs `tests/test_scheduled_notifications.py`. First `check.sh` with `web/` touched → shared local DB migrated to the tutoring head (§5.4).
- **W3:** T09 changes four existing routes' behaviour (no guard change); `test_existing_route_guards_unchanged` and the existing route tests are the safety net. T10 handles uploaded files; polyglot and EXIF cases must have red proofs.
- **W4:** T13 holds the concurrency invariants (lock order, exclusion constraints, pending cap); races are flaky by nature — each race test uses a barrier and is run 5 times in the task (`--count` is not installed; loop the command) before acceptance. T14 is the consent gate: fail-closed audit and no roster union.
- **W5:** first parent write path (T17); T19 relies on predicates mirrored in SQL — parity tests must evaluate generated inputs, not hand-picked rows (memory `verification-needs-a-failing-case`).
- **W6:** T21's sweeps lock the tutor row `FOR UPDATE` and touch bookings, grants and enrolments in one transaction; deadlock risk if any path takes locks out of the §a.4b order. First UI wave: bundle budget (`check:bundle`) may fail on the screen chunks; tutoring routes must be lazy.
- **W7:** route count must reach exactly 70 with headings carrying final counts; X-07 shows safeguarding text — no notes text in any list view.
- **W8:** T30 may produce blocking findings late; fix tasks reopen closed owners' files (one owner per file per fix wave).
- **W9:** live-stack runs share the local Supabase DB, ports and GoTrue with other sessions; T32 and T33 run serially, never in parallel with each other or with `check.sh`.

### 5.2 Top risks (whole plan)
1. **Per-task worktrees may not be drivable** by subagents (Bash pinned to the lead's worktree). Mitigation: W0 probe; Mode B fallback.
2. **Shared local database:** Playwright global setup and `check.sh` migrate the shared `postgres` DB to `0050`, which other worktrees cannot downgrade from. Mitigation: §5.4 hygiene and a user decision.
3. **Contract drift** between T04 DTOs and later behaviour → hot patches every wave. Mitigation: T04 reviewed line by line; the TS parity test.
4. **Concurrency defects** in booking/sweeps that pass single-threaded tests. Mitigation: barrier race tests with red proofs; Tier A on T13/T21.
5. **"0 skipped" may be unattainable** for key-gated tests; the gate uses the I0 baseline skip list instead (§4).
6. **Spec-scale risk:** 70 routes and 23 screens in one release; review fatigue. Mitigation: per-task opus review, T30 security review, final whole-branch review.

### 5.3 Rollback and stop plan
- **A task fails its acceptance twice** (two full implementer attempts, each followed by a reviewer verdict): escalate one tier and re-dispatch fresh with both failure reports (C → B → A).
- **A Tier A task fails twice:** one more attempt at effort `max`. If that fails: **STOP** the task and every task depending on it (§1.2 edges); finish independent tasks in the wave; record `BLOCKED` with the failure evidence in `.omc/state/tutoring-blocked.md`; ask the user.
- **An integration gate goes red:** do not patch on top. Identify the merge that caused it (re-run the gate after reverting merges one at a time on a scratch branch), `git revert -m 1 <merge sha>` on the feature branch (non-destructive), return the task to its owner with the failing output. `git reset --hard tutoring/pre-I<n>` only with the user's approval (it discards integrated work).
- **A spec gap or contradiction** found by a task: the task returns `BLOCKED` with the exact SPEC section; the lead decides or asks the user, edits SPEC/DECISIONS, and re-dispatches. No implementer edits SPEC.
- **A hot-file patch conflicts** with another task's patch: the lead resolves by hand and re-runs that wave's gate.
- **Agent failure notice** (API timeout): check `git status`/`git log` on the task branch before re-dispatching (memory `agent-failure-notice-is-not-death`).

### 5.4 Shared-database hygiene
Before the first run that migrates the shared local DB (the I2 `check.sh`), tell the user. After each such run (I2, I4, I6, I8, I9, IF), if other sessions need the DB on develop's schema: `PYTHONPATH=$PWD .venv/bin/alembic downgrade 0043_merge_heads` from the feature worktree (drops tutoring tables and the 8 new notification rows; `btree_gist` and the 8 enum values remain, which develop tolerates).

---

## 6. Commands this plan runs (allowlist)

Lead (git and worktrees):
```
git status --short --branch
git log --oneline -<n>
git fetch origin
git rebase origin/develop
git rev-list --count HEAD..origin/develop
git diff --name-only <a> <b> -- <paths>
git show <sha>:<path>
git add -- <paths>
git commit -S -m "<msg>" -- <paths>
git tag tutoring/pre-I<n>
git worktree add -b tut/<ID> .claude/worktrees/tut-<ID> feat/tutoring-marketplace
git worktree list
git worktree remove .claude/worktrees/tut-<ID>
git branch -d tut/<ID>
git merge --no-ff -S tut/<ID>
git revert -m 1 <merge sha>
ln -s /home/sico/Code/Lemely/.venv <worktree>/.venv
ln -s <feature worktree>/web/node_modules <worktree>/web/node_modules
```
Environment and database:
```
supabase status
supabase start
PGPASSWORD=postgres psql -h 127.0.0.1 -p 54322 -U postgres -c "DROP DATABASE IF EXISTS lemely_tutoring_gate" -c "CREATE DATABASE lemely_tutoring_gate"
LEMELY_DATABASE__URL=postgresql+psycopg://postgres:postgres@127.0.0.1:54322/lemely_tutoring_gate PYTHONPATH=$PWD .venv/bin/alembic upgrade head
LEMELY_DATABASE__URL=postgresql+psycopg://postgres:postgres@127.0.0.1:54322/lemely_tutoring_gate PYTHONPATH=$PWD .venv/bin/alembic check
LEMELY_DATABASE__URL=postgresql+psycopg://postgres:postgres@127.0.0.1:54322/lemely_tutoring_gate PYTHONPATH=$PWD .venv/bin/alembic heads
LEMELY_DATABASE__URL=postgresql+psycopg://postgres:postgres@127.0.0.1:54322/lemely_tutoring_gate PYTHONPATH=$PWD .venv/bin/alembic downgrade 0043_merge_heads
PYTHONPATH=$PWD .venv/bin/alembic downgrade 0043_merge_heads
PYTHONPATH=$PWD .venv/bin/python -m lemely.runtime.example_toml
```
Python checks and tests:
```
PYTHONPATH=$PWD .venv/bin/python -m pytest --no-cov -q -rs <named test files>
.venv/bin/ruff check .
.venv/bin/ruff format --check .
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" .venv/bin/mypy lemely
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" pyright lemely
PYTHONPATH=$PWD PATH="$PWD/.venv/bin:$PATH" .venv/bin/lint-imports
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pre_commit run --files <owned files>
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pre_commit run --all-files --show-diff-on-failure
grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py
grep -l "storage_fakes" tests/test_*.py
PYTHONPATH=$PWD .venv/bin/python scripts/check_ui_gates.py
./scripts/check.sh
```
Web (from `web/`):
```
npm ci
npm run typecheck
npm test
npx vitest run <named test files>
npm run lint
npm run check:copy
npm run build
npm run check:installable
PYTHONPATH=$(cd .. && pwd) npx playwright test <named e2e specs>
PYTHONPATH=$(cd .. && pwd) npm run audit
```
Never: bare `pytest`, `make test`, `pytest` without `--no-cov` and named files, `git add -A`/`.`, `git commit -a`, `git stash`, `git push`, `git reset --hard` without user approval.

---

## 7. Self-review against SPEC rev 3

- §a.1–§a.4 → T01; §a.4b locks → T13 (create, transitions, cancel), T21 (block, suspend, close); §a.5 → T04 schema tests + T13 `booking_view`.
- §b.2 routes: P1–P3, SP1–SP2, T1–T5 → T06; T6–T7, A1–A4 → T10; SP3, S6–S7, T18, T21, A6–A8 → T12; S8–S11, T19–T20 → T14; SP5–SP6, S1–S5, S14–S15, PA1–PA5 → T17; T9–T17 → T18; SP4, T8 → T19; S12–S13, PA6–PA7 → T20; B1–B3, A5, A12 → T21; R1, A9–A11 → T25; S16–S17 → T09. Total 70.
- §b.4 → T07 (+ every route task's after-commit calls); §b.5 → T08 (edge), T06/T17/T18/T14 (`no-store`), T11 (persist allowlist).
- §c.1 → lead (I2–I7); §c.3 O1–O31 → the `test_web_tutoring_authz_*` files named per task; §c.4 → T09 (+ T21 for the three enrolment sweeps).
- §d screens → T22, T23, T24, T26, T27, T28; components → T15; gate routes → T33; copy rule → T16.
- §e.1 → T02, T03, T05; §e.2 → T14; §e.3 → T06, T13, T14, T19, T12; §e.4 → every card's *Tests first*, races per §5.1, E2E → T32.
- §f migrations → T01; reversibility runbook → T31 (`docs/deployment.md`); CLI → T12. §g → T31 + lead. Row 17 → T01, T04, T06, T08, T22, T24, T31. Row 18 → T01, T03, T04, T07, T13, T17, T18, T19, T23, T24, T31. Row 19 → T31.
