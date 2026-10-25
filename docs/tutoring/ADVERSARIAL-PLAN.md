# Adversarial review: BUILD/tutoring/PLAN.md against docs/tutoring/SPEC.md rev 3

**Reviewed:** `BUILD/tutoring/PLAN.md` at `9447b47a` (the docs commit; byte-identical to the tree read), against SPEC rev 3, REVISION-LOG, ADR-T01..T04, THREAT-MODEL §5–§8, `BUILD/tutoring/decision-log.md` rows 0–19, project `CLAUDE.md`, and the memory notes named in the brief. Code claims were checked against the worktree, `origin/develop` (`e80cb9fc`), `.github/workflows/ci.yml`, `scripts/check.sh`, `pyproject.toml`, `.pre-commit-config.yaml` and the test suite.
**Method:** Saboteur / New Hire / Security Auditor personas (engineering-skills:adversarial-reviewer), plus the critic protocol: dependency audit, ownership audit, gate derivation from `ci.yml`, a pre-mortem, and command execution probes in this session.
**Mode:** escalated to ADVERSARIAL after the first blocker.

## Verdict: REVISE (BLOCK execution until P1–P4 are fixed)

| Severity | Count |
|---|---|
| Blocker | 4 |
| Major | 13 |
| Minor | 13 |

The wave structure, route arithmetic and SPEC coverage hold up: the 70 routes are each assigned once, the per-integration `EXPECTED` additions sum to 70, `app.py` gets exactly the 23 new routers, every THREAT-MODEL §7 test is mapped (allowing for SPEC's renames), and every file the plan cites exists. The failures are in **how the plan runs**: its standard commands are refused in this session, its fallback worktree mode is unsafe, it schedules the full suite locally six times against a standing user rule, and its first wave-1 task cannot pass its own acceptance inside its owned files.

---

## Blockers

### P1 · Blocker · The plan runs the full pytest suite locally six times
- **Location:** Global constraints, "Tests" (PLAN:27): "never run bare `pytest` … except through `./scripts/check.sh` at the scheduled checkpoints". §1.1 table and §4 "Full gate" (PLAN:96–108, 502–503): full `check.sh` after I0, I2, I4, I6, I8 and IF.
- **Evidence:** `scripts/check.sh:213` runs `pytest -q --tb=short`, the whole suite (~3800 tests, serial, with coverage; `check.sh:49`). Memory `no-full-test-suite-locally`: "Never run the full test suite locally (`make test`, bare `pytest`, `pytest -q`). CI runs it." The user has said this twice ("do not EVER run the full-suite"). The plan gives itself an exception the user never granted.
- **Failure scenario:** the lead starts `check.sh` at I0. The machine is held for the duration of a ~3800-test Postgres-heavy serial run, six times, which is exactly what the user forbade. The same call also runs Playwright and the audit against the shared database (P9).
- **Fix:** replace every "full `check.sh`" with a gate derived from `ci.yml` (P6) whose pytest step is `./scripts/check.sh --fast <affected files>`, or the plain pytest form (`--no-cov` with named files), over an affected-file list computed from the import graph (P6). Make CI the only full-suite judge. That needs a push, which is open decision D1 (§ Open decisions). Drop the "skip list is a subset of the I0 baseline" rule; it only means anything for a full run.

### P2 · Blocker · The plan's standard commands are refused in this session
- **Location:** §0.7 (PLAN:85–89), §0.5 step 5 (PLAN:66), every card's acceptance, the G-common block (PLAN:485–498), T10 (`$(grep -l "storage_fakes" …)`), T32/T33 (`PYTHONPATH=$(cd .. && pwd)`), and §6.
- **Evidence (reproduced in this session, which is the session the plan's agents inherit; memory `subagents-inherit-session-worktree`):**
  - `PYTHONPATH=$PWD python3 -c …` was **refused**: "runs python after PYTHONPATH is set here to a value that configures what it loads … cannot be shown not to be git".
  - `env PYTHONPATH=<abs> python3 … $(grep -lE "rglob\(|LEMELY_SRC|ast\.parse" tests/test_*.py)` was **refused**: "operand … computed at runtime inside a construct too complex to verify".
  - `PYTHONPATH=/home/sico/Code/Lemely/.claude/worktrees/tutoring-marketplace python3 …` (a literal absolute path) **ran**.
  - Writing this review with a quoted heredoc was also refused ("too complex to verify").
- **Failure scenario:** step 2 (Red) of every task fails on its first command. Agents improvise. The likely improvisation, dropping `PYTHONPATH`, is safe for `python -m pytest` run from the root. It is not safe for `scripts/seed_e2e.py` and `scripts/e2e_server.py` under Playwright: those import through the shared `.pth` (`/home/sico/Code/Lemely`), so the e2e journeys would silently test the main checkout's code (memory `shared-venv-editable-pth`).
- **Fix:** write every command with the literal worktree path (`env PYTHONPATH=/home/sico/Code/Lemely/.claude/worktrees/tutoring-marketplace …`). Replace `$(grep …)` with a wrapper script in the scratch dir (the pattern from memory `secret-via-wrapper-script`) that computes SCAN-PY and runs pytest, or with a literal file list the lead refreshes at each integration (today: the 10 files `test_binding_expect.py … test_web_shared_constants.py`). Before W0, run one acceptance command of each shape as a probe, beside the worktree probe.

### P3 · Blocker · Mode B is the likely mode, and as specified it is not "safe"
- **Location:** §0.3 Mode B (PLAN:54); §0.4 hot-file rule (PLAN:58–59: "A task may edit a hot file in its own worktree to test, but never commits it"); §5.1 W0 (PLAN:524: "Mode B is slower but safe"); §5.3 rollback (PLAN:546: `git revert -m 1 <merge sha>`).
- **Evidence:**
  - Mode A will very likely fail the probe. The guard refuses git operations that target anything other than this worktree, which `git worktree add .claude/worktrees/tut-<ID>` does. Memory `subagents-inherit-session-worktree` says agents cannot run Bash in a sibling worktree. Harness `isolation:"worktree"` checkouts have no `.venv` or `web/node_modules`, so the probe's `ls .venv web/node_modules` fails too.
  - In Mode B, route tasks must mount their router to test it, because 31 `tests/test_web_*.py` files build the app with `create_app()`. Under §0.4 that means a local, uncommitted edit to `lemely/web/app.py`, and to `tests/test_authz_matrix_complete.py` if they check guards. W5 has four lanes (T17–T20) editing `app.py` in one working tree at once, and W2 and W3 have two each.
  - Every acceptance run (SCAN-PY, SCAN-WEB, `npm run typecheck`, and the whole-package mypy, pyright and import-linter hooks behind `pre-commit --files`) sees the other lanes' unfinished edits. Memory `parallel-agents-need-commit-paths`: such gates "are not evidence about the commit being made".
  - §5.3's per-merge revert assumes Mode A branches. Mode B has no merges, only interleaved commits.
- **Failure scenario (W5):** T18's half-written `tutor_bookings.py` has an import error. T17's uncommitted `include_router` line sits beside T18's in `app.py`, so T17's `create_app()` crashes and T17 returns BLOCKED or reports a false red. One lane's Edit overwrites another lane's `app.py` change. At I5 the lead cannot "revert the merge that caused it", because there is none.
- **Fix:**
  - Remove the need for hot-file edits during a task. Each route task's tests mount its own router in a fixture: `app = create_app(); app.include_router(<router>)` when the router's paths are absent from `app.openapi()["paths"]`. Only the lead edits `app.py` and `EXPECTED`.
  - In Mode B, run each lane's acceptance on a scratch export of its **committed** SHA (P10's path-limited export) rather than on the shared tree.
  - Rewrite §5.3 for Mode B: revert the lane's commit range, and tag before each wave.
  - Strike "safe" from §5.1.

### P4 · Blocker · T01 cannot pass its own acceptance inside its owned files (notification-preference mirrors are unowned)
- **Location:** T01 owned files (PLAN:168: `notification_repo.py` "`PREFERENCE_FIELD_FOR_TYPE` only", `schemas_me.py` DTOs only); §1.4 #10 (PLAN:155); T01's acceptance includes `tests/test_notification_repo.py`, `tests/test_notification_prefs_repo.py`, `tests/test_me_router.py`.
- **Evidence:** `tests/test_notification_repo.py:134–139` asserts every mapped field exists on `lemely.db.notification_prefs_repo.DEFAULTS`. The precedent type `review_withdrawn` is mirrored in `lemely/db/notification_prefs_repo.py:67,111,155,183,197` (dataclass, update signature, merge, model mapping) and `lemely/web/routers/me.py:107–122,216` (DTO population with **per-role gating**: `_REVIEW_WITHDRAWN_ROLES`, null on GET, 422 on a disallowed PUT). No task owns either file. The web side needs `web/src/portals/settings/NotificationSettings.tsx` (role-gated toggles, `:123`, `:306`), which T07 does not own either. SPEC §a.1's mirror list (SPEC:81) omits all three, so the plan inherited the gap. SPEC never says which roles see which of the 8 new toggles.
- **Failure scenario:** T01, the first task on the critical path, adds 8 entries to `PREFERENCE_FIELD_FOR_TYPE`. `test_every_preference_field_exists_on_the_preferences_row` goes red. `GET /api/me/notification-preferences` fails validation because the DTO has 8 required fields `me.py` never sets. T01 must touch unowned files (its return contract then says BLOCKED) or narrow its acceptance. Separately, T07's `enqueue_in_session` gates on preferences that `notification_prefs_repo` cannot read.
- **Fix:** add `lemely/db/notification_prefs_repo.py` and `lemely/web/routers/me.py` to T01, and `NotificationSettings.tsx` to T07, with a role-gating table for the 8 types decided by the lead or user. A proposal: `booking_request` and `tutor_listing` to teacher; `booking_update` to student and parent; `booking_note` to student and teacher; `tutor_access` to teacher and parent; `tutor_review` to student and teacher; `parent_link` to parent; `tutoring_report` to platform_admin. Record the decision in DECISIONS and amend SPEC §a.1's mirror list.

---

## Majors

### P5 · Major · I0 rebases a branch that is already on origin
- **Location:** I0 steps (1)–(2) (PLAN:507): user approval to commit, then `git fetch origin && git rebase origin/develop`; §6 bans `git push`.
- **Evidence:** `git rev-parse HEAD origin/feat/tutoring-marketplace` both return `9447b47a…`, and `git status` says the branch is "up to date with 'origin/feat/tutoring-marketplace'". Step (1) has already happened and been pushed.
- **Failure scenario:** the rebase rewrites a published commit. Later pushes are rejected as non-fast-forward and need a force-push (unapproved, and outside the allowlist). Anyone who fetched the branch diverges.
- **Fix:** use `git merge -S origin/develop` (one signed merge commit), or get explicit user approval for a later `push --force-with-lease`. Mark step (1) done.

### P6 · Major · Gate lists are hand-assembled and incomplete
- **Location:** the G-common block (PLAN:485–500), the I-rows' `<WAVE FILES>`, and each card's acceptance list.
- **Evidence:**
  - `ci.yml` runs: `ruff check`, `ruff format --check`, `mypy lemely`, `pyright lemely`, `lint-imports`, `alembic upgrade head`, bare `pytest` (coverage floor 70 via `pyproject.toml:387` addopts), and `python scripts/check_review_rate_gate.py`. It also runs a separate `pre-commit run --all-files --show-diff-on-failure` job, and a web job with `npm ci`, `typecheck`, `npm test`, `lint`, `check:copy`, `build` (whose `postbuild` runs `check:bundle`) and `check:installable`.
  - G-common has no review-rate gate, and no `npm run build` at I1, I3 or I5. `check.sh`, the plan's carrier for the rest, has no pyright, `alembic upgrade`, `check:copy`, `check:installable` or pre-commit.
  - Affected-test lists miss importers. T09 changes `ParentLinkService.unlink`'s return type and the redeem and join handlers, and `class_repo.py` has 45 importing test files. T09's acceptance omits `test_web_notify_seams.py`, `test_auth_e2e_roles.py`, `test_seed.py`, `test_announcement_repo.py` and `test_notification_prefs_repo.py`. T07 omits `test_web_notify_seams.py` and `test_purge_job.py`, which builds the `Sweeper`. Memory `derive-gate-lists-from-ci`: "never hand-assemble a verification contract".
- **Failure scenario:** once P1 removes the full suite, these lists are the only local evidence. A regression in an untouched importer lands at every integration and is first seen in CI after W9.
- **Fix:** derive one gate block from `ci.yml`, step by step. Compute each task's and wave's affected tests mechanically: `git diff --name-only <base> <head>`, then the test files importing each changed module (tokensave `affected`, or `grep -l "<module>"`), then SCAN-PY. Put the result in the card.

### P7 · Major · Existing e2e journeys are never re-run, and tutoring screens first meet a browser in W9
- **Location:** T26 (PLAN:395): "`web/e2e/teacher-journey.spec.ts` stays green in T33". T33's acceptance (PLAN:453) runs no Playwright. T32's acceptance (PLAN:445) runs only the tutoring specs and `seed-contract.spec.ts`.
- **Evidence:** `web/e2e/` has `student-journey`, `teacher-journey`, `parent-journey`, `staff-inbox` and `rbac` specs. These are touched by T09 (parent cap and notices), T07 (`staffInbox.ts`), T26 (StudentDetail extraction) and T27 (`ChildOverview.tsx`). `ci.yml` has no e2e job (its web-job comment says so), so CI will not catch it either.
- **Failure scenario:** T26's "pure extraction" breaks a teacher-journey assertion. Nothing runs it, and the regression ships. Likewise, 23 screens are built in W6–W7 against routes they have never rendered, so every integration defect lands on T33, a single serial fixer at the very end.
- **Fix:**
  - Add `student-journey`, `teacher-journey`, `parent-journey`, `staff-inbox` and `rbac` specs to T32's command and to the IF live run.
  - At I6 and I7, run a Playwright smoke per new route on the live stack (renders its h1, no console errors, no C-11 error state), serialised under P9's lock.

### P8 · Major · CI runs only at the very end, so the plan's riskiest assumption is proven last
- **Location:** §5.1 W1 (PLAN:525): "the first CI run of `test_create_all_on_fresh_database_installs_btree_gist` is the proof". §6 forbids `git push`. IF says "PR only when the user asks". §1.4 #5–#6 ship one final PR.
- **Evidence:** SPEC:5 says PLAN.md contains a "PR mapping", but it has none. SPEC §f (SPEC:1455): "each wave = one PR … and the `dataHandling.ts` sentences that become true in that wave" (F16). SPEC §h O-14 is unverified. CI is the only place that runs Python 3.12/3.13/3.14, the coverage floor and `check:installable` with Chrome.
- **Failure scenario:** after nine waves, the first CI run fails on Python 3.12 or 3.14, or on the coverage floor, or `btree_gist` fails on `postgres:16`. The fix lands under a branch-wide review, and every local sweep is void.
- **Fix:** open decision D4. Push W1 (schema plus core) to a draft PR as soon as I1 is green, then push at each I-row, so CI runs per wave. At minimum, prove O-14 at W0 with a throwaway `docker run postgres:16` and `CREATE EXTENSION btree_gist`. Amend SPEC:5 and §f to match whatever is chosen.

### P9 · Major · Shared-database hazards for the live gates are reactive only
- **Location:** §5.4 (PLAN:551–552), §5.2 #2, the W9 notes.
- **Evidence:**
  - `web/e2e/global-setup.ts:50` runs `alembic upgrade head` on the shared `postgres` database (read-only check: currently `0043_merge_heads`, no `btree_gist`).
  - Once that database is at `0050_tutoring_safety`, another session's worktree on develop runs the same global setup and fails with "Can't locate revision 0050_tutoring_safety". §5.4 downgrades only "if other sessions need" it.
  - Other sessions' `seed_e2e.py` runs can reseed shared users in the middle of T32.
  - T13 and T21 run each race test five times in a loop (8 threads each) while three other lanes run Postgres-heavy suites on the same server.
- **Failure scenario:** another session's e2e breaks without explanation. T32 flakes because a peer reseeded. Race loops exhaust connections and produce false reds or greens.
- **Fix:** before W0, ask whether other sessions use the stack (open decision D3). Take a stack lock (a file in `.omc/state`, checked by the lead) for every live run. Downgrade unconditionally after each live run and verify `alembic_version`. Serialise race-test loops at integration rather than inside parallel lanes.

### P10 · Major · Mutation-proof exports copy the whole tree
- **Location:** §0.5 step 4 (PLAN:65): `git archive HEAD | tar -x -C <scratch>`.
- **Evidence:** memory `scratch-exports-exclude-reports`: a whole-tree export is about 910 MB (`reports/` is 815 MB), and 23 exports took `/` to 100%. The plan asks for about 3 mutations per task across 33 tasks. Web mutations (T04, T08, T11, T16) also need `web/` plus `node_modules` in the scratch copy, which the plan does not provide.
- **Fix:** `git archive <sha> lemely tests corpus scripts pyproject.toml alembic.ini | tar -x -C <dir>` (about 60 MB), plus `web/` with a `node_modules` symlink for web mutations. Delete the export after each proof. Check `df -h /` before each wave.

### P11 · Major · "Red before code" is impossible for absence tests, and several tests cannot fail
- **Location:** §0.5 step 2 (PLAN:63): "confirm every new test fails for the missing behaviour (not an import typo)". §0.6 `RED:` line per new test file.
- **Evidence:**
  - Negative and absence tests (O29 and O31 schema scans, "writes no audit row", "no-store", "no key outside DTO") fail before code only by ImportError, which the plan excludes.
  - Some pass at HEAD today and list no mutation: T08's `test_robots_txt_does_not_disallow_tutors` and `test_headers_file_has_no_tutors_rule` (`robots.txt` has no `/tutors` rule today; no `_headers` rule exists).
  - T16's "allows 'Verify your email'" cannot fail for a rule banning "verified".
  - T11's "every SPEC route has exactly one hook" compares hooks to a literal the same implementer writes.
  - T12's `test_recompute_ratings_matches_incremental` compares the one recompute function SPEC §e.3 mandates with itself.
  - T04's DTO scans pass vacuously if class discovery misses subclasses of subclasses (`PublicTutorCardDTO(TutorCardDTO)`, `TutorOwnProfileDTO(TutorProfileDTO)`).
- **Failure scenario:** the return contract forces agents to fabricate RED lines, which memory `verification-needs-a-failing-case` records as this repo's main source of false claims.
- **Fix:**
  - Allow `RED: n/a (absence test) → MUTATION: <mutation> red` as the proof for absence tests, and require a non-vacuity assertion (for example "≥ 40 DTO classes scanned", "≥ 70 routes enumerated").
  - Add mutations for T08's robots and `_headers` tests (add a `/tutors` rule, then go red).
  - Derive T11's route literal by parsing SPEC §c.1's code block.
  - Drop or redefine T12's CLI test (CLI over N tutors equals the per-tutor function).

### P12 · Major · T25's whole-feature cache-header test will probably be vacuous
- **Location:** T25 (PLAN:388): "every tutoring route via the app's route table: only P1–P3 send `public`, every **NS** route sends `private, no-store`".
- **Evidence:** in this FastAPI version `app.routes` holds `_IncludedRouter` wrappers. `tests/test_web_exam_calendar.py:306–310` and `tests/test_authz_matrix_complete.py:364–381` (`_flatten`) both warn that "walking `app.routes` silently finds nothing". Checking about 45 NS routes for a response header also needs a successful response from each, which needs seeded data per route.
- **Failure scenario:** the test iterates an empty list, or only the routes its fixture happens to make return 200, and passes. SC-26 is claimed for the whole feature with nothing behind it.
- **Fix:** enumerate with `_flatten(create_app().router)` filtered to tutoring prefixes, and assert there are exactly 70. Set NS through a router-level dependency or response class, so the header is on every status. Assert the header on whatever status each route returns with a minimal authenticated request, and fail on any NS route with no header.

### P13 · Major · The active-block predicate (O11) is written six times before its owner exists
- **Location:** O11 is checked in T06 (directory anti-join, SP2), T12 (SP3), T13 (create and accept), T14 (S9), T17 (SP5/SP6) and T19 (SP4). `tutoring_blocks_repo.py` arrives in T21 (W6). §1.4 #9 centralises the booking predicates only. T13's dependencies (PLAN:281) omit T06, so `LISTED_AND_NOT_PAUSED_SQL` may be duplicated too.
- **Evidence:** blocks are keyed on users (`blocker_user_id`, `blocked_user_id`; SPEC:355–364). Profiles are keyed on `tutor_profiles.user_id`. The spec mixes "either way" (create) with "students only" (SP1).
- **Failure scenario:** one task checks only student→tutor, another joins `tutor_profiles.id` instead of `user_id`, and a blocked tutor is visible or bookable on one route. That is an O11 IDOR-class defect that each task's own tests won't catch if they share the author's assumption.
- **Fix:** T01 adds `ACTIVE_BLOCK_BETWEEN_SQL(student_col, tutor_user_col)` and `ANY_BLOCK_EVER_SQL` (for outcomes) to `booking_predicates.py` (or a `tutoring_predicates.py`), with a DB test for each direction. Add T06 to T13's dependencies and make reuse of both predicates mandatory, with a grep test that bans ad-hoc `tutoring_blocks` SQL outside the predicates module.

### P14 · Major · Row 5b / SPEC §a.5's public-field allowlist is not pinned by any test
- **Location:** T04's tests (PLAN:197). They test for no `userId`, no email, `indexable` only on P2, the own profile and admin, and no parent-link fields. None asserts the field set of the PUBLIC DTOs.
- **Evidence:** SPEC:533: "Public on the open web: `public_first_name`, `public_last_initial`, `headline`, modes, `area_code`, subjects, `rating_avg`/`rating_count`. Nothing else, ever." T04's files become hot after I1, so later waves change them through lead hot patches.
- **Failure scenario:** a W5 hot patch adds `bio` or `firstListedAt` to `TutorCardDTO` "for the card", and it is served on the open web with no red test. That violates locked row 5b.
- **Fix:** add `test_public_dtos_carry_exactly_the_row_5b_fields` (exact equality on `TutorCardDTO`, `PublicTutorCardDTO` minus `indexable`, `PublicDirectoryPageDTO`, `DirectoryFacetsDTO`, `AreaListDTO`), plus a P1/P2 route test that compares JSON keys to the same set. Mutation: add `bio` to the card, then red.

### P15 · Major · Tier routing puts security-critical work on sonnet
- **Location:** §0.2 (PLAN:44: Tier A covers "authz, consent, data access … booking concurrency and state machine"); T06 and T18 are `[B·sonnet·high]`.
- **Evidence:**
  - T06 owns `deps_tutoring.require_tutor_profile` and `require_writable_tutor_profile`. Every tutor route depends on them (O1, and CB-7's suspended/closed 409). T06 also owns P2's no-oracle identical 404 and the cursor-injection tests (O21).
  - T18 owns every tutor booking write: row 18 late-cancel 422, O4, the meeting-link allowlist, block and suspension refusals, and `studentShared` without an audit row.
  - T04 (sonnet) invents the admin DTO field sets (SPEC:822 gives only names), including `accountEmail`, evidence URLs and report snapshots.
- **Fix:** raise T06 and T18 to Tier A. Either pin the admin DTO fields in SPEC §b.3 (lead or architect) before W1, or make T04 Tier A. T12 (review fraud, the aggregate race) is a borderline candidate.

### P16 · Major · DELIVERY rows are written before their proofs exist
- **Location:** T31 at W8 (PLAN:433–438) patches DELIVERY "verbatim" from SPEC §g, applied at I8 (PLAN:515). IF says "final DELIVERY.md statuses" (PLAN:517) with no rule for setting them.
- **Evidence:**
  - SPEC §g rows cite `web/e2e/tutoring-discover.spec.ts` and `tutoring-parent.spec.ts`, which T32 creates in W9. T31's own check ("every cited test path is checked to exist with `ls`") therefore fails at W8.
  - Statuses read "Delivered" before T30's fixes and before any e2e run.
  - The row-17 row says "Delivered (limited)" while SPEC §h says the SPA-shell behaviour of `env.ASSETS.fetch()` and the staging `curl -sI` checklist are unverified.
  - Existing DELIVERY rows carry explicit "never live-tested" markers (`DELIVERY.md:67`).
- **Fix:** move the DELIVERY patch to IF. Add a status rule: a row is "Delivered" only when every cited proving test exists at the final SHA, is green in CI, and has a recorded red case. Otherwise it is "Built (unverified: …)". Add "staging check not run" to the indexing row until the §b.5 checklist has run.

### P17 · Major · The pyright pre-commit hook will go red for every Python lane from I2/I3 on
- **Location:** §0.5 step 5 (PLAN:66). The `extraPaths` workaround appears only in G-common (PLAN:500).
- **Evidence:** the hook runs whole-package (`.pre-commit-config.yaml`: `entry: pyright lemely`, `pass_filenames: false`). `pyproject.toml:495`, `:499` and `:528` make `routers/student.py`, `routers/teacher.py` and `app/cli.py` single-file execution roots, which resolve `lemely.*` through the shared `.pth`. That `.pth` currently points at `/home/sico/Code/Lemely`, the main checkout, which has no tutoring modules (memory `shared-venv-editable-pth`: 179 hook errors measured).
- **Failure scenario:** after T09 (`student.py` imports tutoring modules) and the lead's `cli.py` patches, every lane's step 5 reports "Import … could not be resolved". Lanes block, or learn to ignore pyright, and a real pyright error slips through (it happened on 2026-10-01 and failed CI on three Pythons).
- **Fix:** put the temporary-config command (copy `[tool.pyright]` and add `extraPaths=[<worktree>]`) in §0.5 step 5 for every lane. State that only `"X" is not assignable to "X"` and unresolved-tutoring-module errors are artefacts.

---

## Minors

- **P18 · Dependency diagram is missing edges.** §1.2 shows `T05[—]` (PLAN:117), but T05's cross pins need T01 and T03 (PLAN:206). §5.3's STOP rule follows §1.2's edges, so a T01 failure would not stop T05. Add the edges.
- **P19 · Files with no owner after W1.** `lemely/db/models/tutoring.py`, `enums.py`, `booking_predicates.py` and the 0044–0050 migrations have no owner after W1 and are not in the §3 hot list. A predicate or index fix in W4 has no legal owner. Declare them hot (lead) from I1.
- **P20 · Handoffs travel only in ephemeral return NOTES.** T08→T31 (the curl checklist, PLAN:237), T22→T33 (audit slugs, PLAN:366) and T29→T32/T33 (seeded ids, PLAN:422) all rely on return-contract text that will not survive nine waves of context compaction. Have the lead persist each one to `BUILD/tutoring/handoffs/<task>.md` at integration.
- **P21 · Contradictory skip rules.** §0.5 step 6 requires "no `skipped`" (PLAN:67), while §5.2 #5 and §4 accept the I0 baseline skip list (PLAN:503, 540). Today the only skips in the acceptance files are "local Postgres not reachable". State a single rule: 0 skipped with the stack up.
- **P22 · Authz-matrix heading semantics.** §1.4 #12 ("headings carry the count of rows present") can be read as per-section counts. The test compares every heading with its guard's **total** (`test_authz_matrix_complete.py:568–592`), so a second `STUDENT (17)` heading goes red. Say: "update the one existing heading per guard to the guard total (STUDENT 63→80 …), never add a second heading."
- **P23 · Commit order.** Integration rows commit the hot patches **before** G-common's `pre-commit --all-files` (PLAN:483), but project CLAUDE.md requires pre-commit before any commit. IF also runs "full `check.sh` as the last action" and then the whole-branch review, whose fixes would void the sweep (memory `gate-sweep-goes-last`). Reorder both.
- **P24 · T13's defence-in-depth mutation proof is incoherent.** "bypass the core reason check → test … still red" (PLAN:287): a single-layer mutation leaves a defence-in-depth test green. Split it into three tests (the core returns 422; with the core bypassed, the CAS refuses; with the CAS bypassed on a scratch DB, `23514` from the CHECK), each with its own mutation.
- **P25 · ADR-T01 action 3 is not mapped.** "Teacher without profile → 404 on each tutor route" has no mapping; only T1 is tested (T06). Add "(f) `no_tutor_profile` 404 for every tutor route" to the cross-cutting list (PLAN:28).
- **P26 · The copy rule and its first targets land in the same wave.** T16 and T15 are both in W4, so the new rule first applies to T15's copy at I4, and a hit means a revert loop. Run T16's rule from its branch in T15's acceptance, or move T16 earlier. Also, `web/src/lib/tutoring/bookingErrors.ts` (T22) duplicates T11's `apiErrors.ts` mapping. Make T22 consume T11's.
- **P27 · UI hot patches miss two requirements.** `web/tests/unit/documentMeta.test.ts` requires `handle: { title }` on every route with unique titles. Crumb trails live in the portal `data.ts` files. Neither appears in the T22–T28 hot-patch specs.
- **P28 · T33 gaps.**
  - Audit `ready` predicates must assert the state's content. Otherwise axe passes on a login redirect or a C-11 error page.
  - `tests/test_check_ui_gates.py` pins `scripts/check_ui_gates.py` but is not in T33's or I9's gate after T33 patches it.
  - T33's acceptance (PLAN:453) runs `.venv/bin/python` with `$PWD` after `cd web`, so the cwd is wrong. T04 and T08 chain `cd web` before SCAN-PY the same way.
- **P29 · `alembic check` has no defined meaning in G-common.** SPEC §a.4 says it "is not a guard here", and no gate has run it before, so its baseline result is unknown. Record its result at I0 and mark it non-blocking, or drop it.
- **P30 · Unspecified homes.** `TutoringPreferencesRepository` has no file named (T14 Produces). T17's `test_tutoring_private_routes_send_no_store` has no file named.

---

## Open decisions the plan must put to the user before W0

The plan has no open-decision register. These four are implicit in it and each changes how W0 runs:

- **D1 · Local full suite or CI only (P1, P8).** The user's rule says CI only, which requires pushes. Who pushes, when, and to a draft PR?
- **D2 · Rebase or merge (P5).** The branch is already on origin. Rebasing needs a force-push approval; merging `origin/develop` does not.
- **D3 · Shared local stack (P9).** May the plan migrate the shared `postgres` database to 0050? Must other sessions pause during live runs? Is a downgrade after every run mandatory?
- **D4 · Commit authorisation and PR shape.** Project CLAUDE.md says "Do not create commits unless asked", and the plan makes about 45 signed commits (per task and per integration), which needs blanket approval. Also: one final PR (the plan) or one PR per wave (SPEC §f, SPEC:5's "PR mapping")?

---

## Pre-mortem (plan executed as written, failed)

1. **I0:** the full `check.sh` holds the machine for a long serial run (P1), and the user stops the run.
2. **W1:** T01 returns BLOCKED on the prefs mirrors (P4), and every acceptance command is refused (P2). The critical path stalls on day one.
3. **W5 (Mode B):** four lanes clobber `app.py`. Acceptance evidence is polluted and per-merge revert is impossible (P3).
4. **W5:** a block-direction bug in one route passes its lane's tests (P13).
5. **W7:** T25's cache test passes over an empty route list (P12).
6. **W9:** the teacher journey is broken by T26 and nobody runs it (P7).
7. **First CI run after IF:** red on Python 3.12, the coverage floor or `postgres:16`. Every sweep is void (P8).

---

## Locked decision rows → plan task coverage

| Row | Decision | Plan coverage | Status |
|---|---|---|---|
| 0 | Worktree, branch off develop | I0 | ✓, but the rebase of a pushed branch (P5) |
| 1a | `tutor_profiles` 1:1 teacher, no new role; school-less teacher signup | T01, T06 (`test_create_requires_teacher_role`); teacher self-signup exists (`auth.py:81`) | ✓ |
| 1b | Co-teacher as peer, no delegation | nothing to build | ✓ |
| 2+3a | Student opt-in alone, minors included | T14 (S9, no parent gate) | ✓ |
| 3b | All subjects until revoked, derived only, next-read revocation, audit visible to student | T14 (T19/T20 audit, fail-closed, race), T05, T23 (S-38) | ✓ |
| 4 | Parents notified of grants and bookings; read-only | T07, T13, T14, T17 notices; T20 | ✓; delivery depends on the prefs mirrors (P4) |
| 4b | Booking notes visible to student, tutor and parents; report and moderation | T13, T17 (PA3), T25, T15 (C-21) | ✓ |
| 5a | Admin approval; public directory | T06, T10, T22, T28 | ✓ |
| 5b | Minimal public card; nothing else public | T04 DTOs, T06 P1–P3 | ⚠ no allowlist test (P14) |
| 6 | Filters incl. availability; Bayesian; "New" below 3; keyset | T02, T06, T15, T22 | ✓ |
| 7 | One review per completed booking, moderation, one reply, 14-day edit, no parent reviews | T12, T25, T24, T28 | ✓ |
| 8 | Both figures, default-on counting, k ≥ 5, n, table, caveat, insufficient state | T05, T19, T15, T22 | ✓ |
| 8b | Counting notice, one-tap opt-out, k on change, wording | T22/T23 copy, T20 (S13), T05, T15, T16 ("improvement" ban) | ✓ |
| 9 | Request/accept, Cairo wall clock, exclusion, modes, no-show, read-time staleness, email path | T01, T03, T13, T07, T18 | ✓; the email preference gate needs P4 |
| 10 | Parent books for child | T17 (SP6, PA1–PA5), T27 | ✓ |
| 11 | No prices; fees line | global copy rule, T31 (DELIVERY §4) | ✓ (no test; acceptable, no price field exists) |
| 12 | MVP "limited" statements | T31 (SPEC §g) | ⚠ DELIVERY status rule (P16) |
| 13 | SC-14 suppression, k on graded, live figures, R5 accepted | T05, T19, T31 (§5.7 bullet) | ✓ |
| 14 | SC-1/SC-2 on existing routes, no permission change | T09, T21 (`test_existing_route_guards_unchanged`) | ✓; affected importers not run (P6) |
| 15a | Block with 24 h cancel override | T21 (`test_block_cancels_inside_24h`) | ✓ |
| 15b | Reply moderation | T12 | ✓ |
| 15c | Student-side exclusion | T01 | ✓ |
| 15d | `requested` holds slot, pending cap | T01, T13 (race ≤ 5) | ✓ |
| 15e | Higher/same/lower change figure | T05, T15 (C-18) | ✓ |
| 16 i | Parents see grants and tutor-read log, read-only | T20 (PA6/PA7, no audit row), T27 (P-08) | ✓ |
| 16 ii | Safety notice before first booking and first note | T13 (create guard), T17 (S15, O26 on S5), T15 (C-24), T22/T23 | ✓ |
| 17 | Indexable by default, opt-out, worker lookup, directory noindex | T01, T04, T06, T08, T22, T24, T31 | ✓; staging verification not scheduled (P16) |
| 18 | Tutor-only late cancel with reason | T01, T03, T04, T07, T13, T17, T18, T19, T23, T24, T31 | ✓; T13 mutation proof (P24) |
| 19 | Ladder, Cairo wall clock, parent own-booking actions, UI principles and MISSION wording | T05, T03, T17 (O8), T25 (R1), T31 | ✓ (docs only for the wording) |

**No plan task silently softens a locked row.** The two ⚠ rows (5b, 12) are unguarded rather than contradicted.

## Checked and found sound

- 70 routes, each owned once. The per-integration `EXPECTED` additions sum to 70 (10+16+6+29+5+4). There are 23 new routers. `_NON_PUBLIC`/`_REPRESENTATIVE` arithmetic (−15; 7→8→9) matches SPEC §c.1, and guards are added only once their routes exist (so `next()` cannot raise at import).
- Every file the plan cites exists (except the intended new files and `parent/data.ts`, which the plan correctly says does not exist).
- `_student_detail_dto`, `RosterEntry`, `_visible_students` and `teacher_student_detail` exist on `origin/develop`. Upstream has no migration drift.
- `template1` has no `btree_gist` (read-only check), so T01's `create_all` red case is real.
- The optional `Sweeper` field follows the existing `storage`/`bucket` pattern, so the `sweep_once()` pins hold.
- The test databases use UUID names (`conftest.py:648`), so parallel lanes do not collide on database names.
