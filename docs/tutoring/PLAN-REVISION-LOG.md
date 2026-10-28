# Tutoring PLAN rev 2: revision log

**Date:** 2026-10-25 · **Branch:** `feat/tutoring-marketplace` @ `9447b47a` (docs only; nothing committed by this revision)
**Input:** `docs/tutoring/ADVERSARIAL-PLAN.md` (P1–P30: 4 blocker, 13 major, 13 minor; open decisions D1–D4) and the lead's six execution decisions (commits and pushes pre-authorised; plain command shapes; no local full suite; one PR; shared-worktree parallelism; dedicated databases).
**Outputs:** `BUILD/tutoring/PLAN.md` (rewritten as rev 2), `docs/tutoring/SPEC.md` (amended in §header, §a.1, §b.2 legend, §b.5, §c.1, §c.4, §f, §h O-13; no locked decision row changes), this log, `.omc/plans/open-questions.md`.
**Method:** every review claim the fix depends on was re-checked in this worktree; command shapes were probed in this session's guard, which is the guard the plan's lanes inherit (read-only or scratch-only probes; nothing was committed, staged or pushed).

**Totals.** P: 27 fixed, 3 fixed with a different mechanism (P13, P15, P26: the rejected part is rebutted below), 0 needs-user. D1–D4: resolved by the lead's decisions, except the PR timing inside D1/D4, which goes back to the lead as Q1. Ten new findings (N1–N10) surfaced while verifying; all are fixed in the plan.

## A. Command shapes probed in this session (P2; lead decision 2)

| Shape | Result | Plan use |
|---|---|---|
| `PYTHONPATH=$PWD <python> -c …` | **refused** ("PYTHONPATH is set here to a value that configures what it loads") | never |
| `PYTHONPATH=<literal abs path> <python> -c …` | ran | literal fallback only |
| `env PYTHONPATH=<literal> <python> -c …` | ran | literal fallback; T00's first run |
| `env PATH=<literal> which mypy pyright lint-imports node git` | ran | inside `precommit.sh`/`static.sh` |
| `env LEMELY_DATABASE__URL=<literal> .venv/bin/alembic heads` | ran (`0043_merge_heads`) | probe P-3; inside `gate_db.sh` |
| `/home/sico/Code/Lemely/.venv/bin/python -m pytest --co -q tests/test_db_schema.py` | ran; imports WT (cwd first on `sys.path`) | inside `pytest.sh` |
| `npm --prefix web run` / `env PYTHONPATH=<literal> npm --prefix web run` | ran | every web command (no `cd web`) |
| `cd web && ls package.json` | ran (non-git compound) | not used; `npm --prefix` instead |
| `git archive HEAD <paths> \| tar -t` and `\| tar -x -C <dir>` | ran | inside `export.sh` |
| `git merge-tree --write-tree --name-only HEAD origin/develop` | ran; clean | I0 pre-check |
| `git rev-list --count HEAD..origin/develop` | ran (117) | I0 |
| `gh run list --branch feat/tutoring-marketplace`, `gh pr list --head …` | ran; both empty | CI checks |
| `psql postgresql://…/postgres -tAc "SELECT version_num FROM alembic_version"` | ran (`0043_merge_heads`) | live protocol step 6 |
| `supabase status -o env`, `ss -ltn`, `df -h /` | ran | probes, live protocol, disk rule |
| `grep -lE "rglob\(\|LEMELY_SRC\|ast\.parse" tests/` | ran (10 test files) | inside `scan_py.sh` |
| `bash <abs>/scripts/tutoring/probe.sh` (self-locating: `cd` to its own root, pin `PYTHONPATH`) | ran; imported **the export's** `lemely` | the wrapper pattern for every T00 script |
| `env PATH=/home/sico/Code/Lemely/.venv/bin:/usr/local/bin:/usr/bin:/bin /home/sico/Code/Lemely/.venv/bin/python -m pre_commit run --files <3 docs>` | ran; all hooks passed, nothing modified (import-linter runs even for docs: it has no `types` filter) | inside `precommit.sh` |
| `rm -rf <scratch dir>` | **denied by permissions** (not the guard) | never; `rm -r` |
| `rm -r <scratch dir>` | ran | export clean-up |
| `ls lemely.toml .env …` | denied by permissions | never needed |
| `$(…)` substitution, heredoc | refused (ADVERSARIAL-PLAN P2's own probes; not re-run) | never |
| `git add`, `git commit -S`, `git merge -S`, `git push`, `gh pr create`, `npm --prefix web ci`, `ln -s`, `docker run` | **not probed** (they write) | first run by the lead at I0/I1, where a refusal costs nothing (PLAN §6 "first use") |

## B. Findings P1–P30

| ID | Sev | Status | Where in PLAN rev 2 (and SPEC) | Notes |
|---|---|---|---|---|
| P1 | Blocker | Fixed | Global "Tests"; §0.10; §4 gate table; §6 "Never" | Every "full `check.sh`" removed. Locally: card acceptance + AFFECTED (direct importers) + SCAN-PY + hub pins, all named files through `pytest.sh`, which refuses no-argument and directory runs (needed because `pyproject.toml:388` sets `testpaths = ["tests"]`, so a bare call is the full suite). `check.sh` is not used in either mode: default = full serial suite; `--fast` with no paths = full suite under xdist; with paths it still lacks pyright, Alembic, `check:copy`, `check:installable` and pre-commit. The "skip list ⊆ I0 baseline" rule is gone (§0.8). Full suite = CI (§0.10). |
| P2 | Blocker | Fixed | Global "Shell shape"; §0.7; every card; §6; this log §A | All `$PWD`, `$(…)`, `cd web &&`, `PYTHONPATH=$(cd .. && pwd)` forms replaced: checked-in self-locating wrappers (T00) for anything computed; `npm --prefix` for web; literal absolute paths elsewhere. Shapes probed (§A). Playwright and `scripts/*.py` import WT because `live_e2e.sh` pins `PYTHONPATH` and WT gets a `.venv` symlink at I0 (`playwright.config.ts:161` and `global-setup.ts:50,61` call `repoRoot/.venv/bin/*`). |
| P3 | Blocker | Fixed | §0.3 (Mode A dropped; four soundness rules), §0.4, §0.5, §5.3 | No lane edits a hot file at all: route tests mount routers with `tests/tutoring_app.py::app_with_routers` (T00), idempotent once the lead mounts them. All evidence (static, acceptance, scans, mutations) runs on a candidate export = `HEAD` + exactly the lane's files, so no lane's gate sees another lane's unfinished edits. Rollback reverts a lane's commit range by path (disjoint paths), not merges. "Safe" claim struck. |
| P4 | Blocker | Fixed | T01 owned files and tests; T07 owned files; §1.4 #10; SPEC §a.1 (mirror list + role table) | Verified: `tests/test_notification_repo.py:134-139` pins mapped fields to `notification_prefs_repo.DEFAULTS`; `me.py:102-125,177-186` gates `atRiskAlert`/`reviewWithdrawn` by role. T01 now owns `notification_prefs_repo.py` and `routers/me.py`; T07 owns `NotificationSettings.tsx`. Role table **derived from SPEC §b.4's recipient column**, not invented (it differs from the review's proposal, which omitted the tutor on `booking_update`, the parent on `booking_note` and the student on `tutor_access`, all of which §b.4 sends). The UI hides a toggle whose GET value is null, so no portal `index.tsx` (hot) changes. |
| P5 | Major | Fixed | I0 steps (0)–(1); §6; SPEC header and §f | `git merge -S --no-ff origin/develop`, then a fast-forward push. `merge-tree` reports no conflict today. Step "commit docs" marked done (`9447b47a` is on origin). No rebase, no force-push anywhere. |
| P6 | Major | Fixed | §4 gate table (each CI step mapped); §0.7 AFFECTED; T00 `affected_tests.py`; T07, T09, T10 acceptance | Gate list derived from `ci.yml` step by step, incl. review-rate gate, pyright, `alembic upgrade head`, pre-commit job, `npm run build` at every I-row and `check:installable`. Affected tests computed mechanically (direct importers via `ast`, monkeypatch string targets, test helpers like `storage_fakes`). Hubs (enums has ≈ 115 direct test importers) contribute a pin list instead, with CI as the judge for the rest. T09 and T07 acceptance now include the importers the review named. |
| P7 | Major | Fixed | T00 `tutoring-smoke.spec.ts`; I6, I7 live rows; T32 acceptance; T26, T27 notes | Existing `student-journey`, `teacher-journey`, `parent-journey`, `staff-inbox`, `rbac` specs run at I7 and in T32 (and the first two at I6). A table-driven smoke spec (h1, no console error, no C-11 state) gets rows for every new route at I6/I7. |
| P8 | Major | Fixed (timing → Q1) | §0.10; I0 P-4; I1; SPEC §f "Release groupings", SPEC header line 5 | **New fact:** `ci.yml` triggers only on `pull_request` and `push: main`, so pushes alone never run CI (verified: no runs for the pushed branch). Default: the one PR opens as a draft against `develop` at I1 so every I-row push gets full CI; CI for I<n> must be green before I<n+1>'s hot patches. O-14 also gets a W0 probe (`btree_gist.control` present in `postgres:16`). SPEC:5's "PR mapping" and §f's "each wave = one PR" are amended to one PR. |
| P9 | Major | Fixed | §0.9; T00 live scripts; I0b P-6 | Machine-wide live lock; port check (new N4); clean-tree check; `dedicated` database mode by default so the shared `postgres` database is never migrated past develop's head; `shared` fallback with an unconditional, verified downgrade; race loops only at I-rows with no lane active. Residual (GoTrue and Storage are shared) recorded as Q2. |
| P10 | Major | Fixed | §0.7 EXPORT; T00 `export.sh`; §5.3 disk rule | Path-limited export (`lemely tests corpus scripts pyproject.toml alembic.ini docs/tutoring/SPEC.md` [+ `web`]): measured 44 MB + 8 MB. Written to `WT/.omc/exports/` on disk (new N6: `/tmp` is a 16 GB tmpfs). Deleted with `rm -r` (N3). `df` check in the script and before each wave; 39 GiB free today. Web mutations get `web/` plus a `node_modules` symlink. |
| P11 | Major | Fixed (one item rebutted in part) | §0.8; T04, T08, T11, T12, T16 cards | `RED: n/a (absence|regression guard)` + mandatory MUTATION; NONVACUITY line for every scan. T08 robots/`_headers` mutations added. T11's route list parsed from SPEC §c.1 (exactly 70). T12's CLI test redefined (corrupted aggregates vs an independent computation). T04 discovery iterates `vars(module)` and must equal SPEC §b.3's class list. **Rebutted in part:** T16's "allows 'Verify your email'" is kept: it cannot fail for a correct rule, but it does fail for an over-broad `/verif/i` rule, which is now its mutation. |
| P12 | Major | Fixed | Global "Cache headers"; §1.4 #13; T06 `tutoring_http.py`; T25 `test_tutoring_cross_cutting.py`; SPEC §b.2 legend and §b.5 | **New finding N5:** SPEC's NS marks (21 table rows) disagree with its own §b.5 list (notes and every Booking/Grant/AccessLog/ClassAccess DTO response), so neither can drive a test. Resolved as a strict superset: every non-PUBLIC tutoring route is `no-store` on every status, via one route class. T25 enumerates with `flatten_routes` (not `app.routes`), asserts exactly 70 against the SPEC parse, and checks all 67 non-public routes with one unauthenticated request each (the guard's 401/403 carries the header because it is raised inside the route). |
| P13 | Major | Fixed (different mechanism) | T01 `tutoring_predicates.py` + two test files; §1.4 #9; Global "Shared SQL predicates"; T06, T13, T19, T21 acceptance | Listing, active-block (both directions, keyed on `users.id`) and ever-blocked (student → tutor, ADR-T04) predicates written once in W1, with a direction test, a user-id-not-profile-id test and an `rglob` single-source test that joins SCAN-PY. **Rebutted:** adding T06 to T13's dependencies is unnecessary, because `listed_and_not_paused_sql` now lives in T01. |
| P14 | Major | Fixed | T04 `test_public_dtos_carry_exactly_the_row_5b_fields`; T06 `test_p1_p2_p3_json_keys_within_row_5b_allowlist` | Exact recursive field sets from SPEC §b.3 lines 686-697; mutation "add `bio`". |
| P15 | Major | Fixed (one item rebutted) | §0.2, §1.3; T04, T06, T18 tags | T04, T06, T18 raised to Tier A; T04 writes the admin field table into its hand-off for line-by-line review. **Rebutted:** T12 stays B; its aggregate race has a barrier test, a mutation proof, the 5× loop at I3 and an opus task reviewer. |
| P16 | Major | Fixed | T31 (draft only); I8; IF step (3) status rule; §1.4 #16 | DELIVERY written once at IF: "Delivered" only with test present at the final SHA, green in that SHA's CI, with a recorded red case; else "Built (unverified: …)"; indexing row says "staging check not run". |
| P17 | Major | Fixed | §0.5 steps 4 and 6; T00 `static.sh`, `pyright_config.py`, `precommit.sh` | Lanes skip the whole-package hooks in WT and run pyright with `extraPaths` = the export on the exact candidate. The lead's `--all-files` run skips only the `pyright` hook and runs the override instead. The `.pth` points at `/home/sico/Code/Lemely` today (checked). |
| P18 | Minor | Fixed | §1.2; T05 | `T05[T01,T03]`; T00 under everything; `T15[T04,T16]`. |
| P19 | Minor | Fixed | §0.4 general rule; §3 rows | Every file a wave's tasks owned becomes hot after integration unless a later card owns it; models, enums, predicates and migrations listed explicitly from I1. |
| P20 | Minor | Fixed | §0.6 `HANDOFF`; §1.4 #15; §4 I-row order; T04, T08, T22, T29 | Lead persists hand-offs to `BUILD/tutoring/handoffs/<ID>.md` (committed; `.omc/` is gitignored, checked). |
| P21 | Minor | Fixed | §0.8 "Skips" | One rule: 0 skipped with the stack up, except test ids recorded at I0b. |
| P22 | Minor | Fixed | §1.4 #12; §3; SPEC §c.1 | One heading per guard, count = that guard's total (STUDENT 63 → 80 at the end); verified headings today sum to 169 rows. |
| P23 | Minor | Fixed | §4 I-row order; IF steps (1)–(7) | Pre-commit before every hot-patch commit; final review and its fixes before the final sweep, which is last. |
| P24 | Minor | Fixed | T13 tests and mutations | Core 422, CAS-with-core-bypassed and T01's CHECK test are three tests with three mutations. |
| P25 | Minor | Fixed | Global cross-cutting (f); T06, T10, T12, T14, T18, T19 cases; T25 whole-feature test | `no_tutor_profile` 404 on every tutor route except `POST /api/tutor/profile` (20 routes). |
| P26 | Minor | Fixed (different mechanism) | T16 moved to W0; T15 depends on T16; T22 `bookingErrors.ts` | **Rebutted:** "run T16's rule from its branch in T15's acceptance" does not work in a shared tree with no task branches; moving T16 ahead does. T22 maps T11's typed errors to copy, no second table. |
| P27 | Minor | Fixed | T22–T28 `HOT PATCH` | `handle: { title }` unique per route and crumbs in `data.ts` in every screen hot patch; `documentMeta.test.ts` runs in SCAN-WEB at each I-row. |
| P28 | Minor | Fixed | T33 goal, mutation and acceptance; I9 | `ready` predicates must assert state content (mutation: point one at the login page); `tests/test_check_ui_gates.py` in T33 and I9; the `cd web` cwd error is gone with `npm --prefix`. |
| P29 | Minor | Fixed | I0b, I1 (`gate_db.sh check`) | `alembic check` recorded at I0b and I1, informational, never blocking (SPEC §a.4 F20). |
| P30 | Minor | Fixed | T14 owns `lemely/db/tutoring_preferences_repo.py` (+ test file); T17 names the no-store test's file | |

## C. Open decisions D1–D4

| ID | Status | Resolution |
|---|---|---|
| D1 local full suite or CI only | Resolved by lead decision 3 | CI only (§0.10). The "who pushes, when, draft PR" part: lead pushes at every I-row; PR timing → **Q1**. |
| D2 rebase or merge | Resolved (P5) | Signed merge; no force-push. |
| D3 shared local stack | Resolved by lead decision 6 + §0.9 | Dedicated databases; lock; verified downgrade in fallback mode. Residual GoTrue/Storage sharing → Q2 (non-blocking). |
| D4 commit authorisation and PR shape | Resolved by lead decisions 1 and 4 | Signed explicit-path commits pre-authorised (memory `tutoring-autonomy-commit-push`); one PR, lead opens, never merges; timing → **Q1**. |

## D. New findings while verifying (N1–N10)

| ID | Finding | Evidence | Fix |
|---|---|---|---|
| N1 | Rev 1's mutation recipe (`PYTHONPATH=<scratch>` from the worktree) could never go red: with the cwd reset to WT, `sys.path[0]` is WT, ahead of `PYTHONPATH`. | `python -m site` with `PYTHONPATH=<export>`: WT first, export second; with `-P`: export first. | Wrappers `cd` to their own tree; `-P` documented as the literal alternative (§0.7, §6). |
| N2 | CI never runs on a feature-branch push. | `ci.yml` `on:`; `gh run list --branch feat/tutoring-marketplace` empty. | Draft PR at I1 (Q1); base `develop` because `auto-approve_PR.yml` approves owner PRs into `main`. |
| N3 | `rm -rf` is denied by this session's permissions. | Probe. | `rm -r` everywhere (probed). |
| N4 | Playwright reuses any server already on 8000/5173 (`reuseExistingServer: !process.env.CI`, `playwright.config.ts:165,175`), so a peer session's backend could be tested by mistake. | Config read. | Live wrappers refuse when either port is in use. |
| N5 | SPEC NS marks vs §b.5 list contradict each other. | 21 marked rows vs line 867's list. | P12 resolution; SPEC legend and §b.5 amended. |
| N6 | `/tmp` is a 16 GB tmpfs; scratch exports there consume RAM. | `df -h /tmp`. | Exports go to `WT/.omc/exports/` (gitignored, on disk). |
| N7 | The memory note's export path list lacks `alembic.ini`, which `tests/conftest.py` opens by relative path for every migration test. | `conftest.py` `Config("alembic.ini")`. | Included in `export.sh`. |
| N8 | `pre-commit run` stashes unstaged changes unless `--files`/`--all-files` is given; no pre-commit git hook is installed, so `git commit` does not stash. | `pre_commit/commands/run.py:344`; `.git/hooks` has only samples. | Wrappers always pass `--files` or `--all-files`; never a bare run in the shared tree. |
| N9 | The graphify `post-commit` hook exits early in linked worktrees, so lane commits trigger no rebuild or stray files. | `.git/hooks/post-commit` lines 28-32. | None needed; recorded so nobody chases it. |
| N10 | The review proposed role gating that disagrees with SPEC §b.4's recipients. | §b.4 table. | P4 uses the §b.4-derived table. |

## E. Lead decisions → where applied

| # | Decision | Applied in |
|---|---|---|
| 1 | Signed explicit-path commits, pre-commit first, push own branch only, never develop/main, never force | Global "Commits"; §0.5 steps 4 and 7; §4; §6 |
| 2 | Plain single commands only; wrappers in `scripts/tutoring/` | Global "Shell shape"; §0.7; T00; §6; this log §A |
| 3 | No local full suite; CI as full-suite evidence; DONE = CI green + local gates | Global "Tests"; §0.10; §4 |
| 4 | One PR, lead opens, never merges; intermediate pushes allowed | §0.10; I1; IF; SPEC §f |
| 5 | Shared-worktree parallelism, disjoint files, explicit-path commits, review at SHA | §0.1, §0.3–§0.5; §5.3 |
| 6 | Dedicated databases; live gates in later waves with a protocol | §0.9; GATE-DB; I0b, I6, I7, I9, IF |

## F. Questions for the lead or user

- **Q1 (needs lead/user):** decision 4 says "one PR at the end", decision 3 says "CI on the pushed branch", and `ci.yml` makes the two incompatible. Options: (a) **open the one PR as a draft against `develop` at I1** (plan default; still one PR, never merged by an agent, CI on every integration push); (b) open it only at IF (no CI until after W9; P-4 is the only early `btree_gist` evidence); (c) add `workflow_dispatch` or a `push` trigger to `ci.yml` (changes shared CI config; not recommended).
- **Q2 (non-blocking, in `.omc/plans/open-questions.md`):** do other sessions run e2e or `seed_e2e.py` on this machine during the build? GoTrue and Storage stay shared in `dedicated` mode.
