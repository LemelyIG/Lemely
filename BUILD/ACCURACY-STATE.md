# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-25-lemely-eval-record-model-run-manifest
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: TWO THREADS. (A) NEW ISSUE #69 / PR #70 — https://github.com/LemelyIG/Lemely/pull/70, branch fix/accuracy-board-state-empty-key, PUSHED, base develop, CI not yet watched. This is the supervisor-tooling fix SPLIT OUT of #25 per accuracy-review's scope MUST-FIX. WATCH ITS CI and merge it to develop FIRST — #25 is blocked behind it (see B). Do not re-review it; it is 2 files, pre-commit green, 6 tests of which 4 fail against the old parser. (B) #25 (M0.1) on feature/accuracy-25-lemely-eval-record-model-run-manifest at 1b52922, UNPUSHED, NO PR, review verdict was BLOCK. Of its two MUST-FIXes: MUST-FIX 1 (params_fingerprint) is FIXED at 1b52922 — _build_run_manifest hashed only temperature|top_p|seed|thinking_budget, omitting the MODEL, so two runs on different models hashed identically (demonstrated: both gave ce5aa7b9ccad), which is the false-zero-delta trap once M0.3's A/B reads the field; now hashes sorted(models_by_task)|temperature|top_p|seed|thinking_budget|_MAX_OUTPUT_TOKENS, with the per-call response-schema hash deliberately EXCLUDED and that narrower claim stated in the code; 3 new tests, 2 fail against the old fingerprint. MUST-FIX 2 (scope) is HALF done: the tooling fix is extracted to #69/PR #70, but #25's branch STILL CONTAINS commit 33f0f5b. REMAINING WORK ON #25, IN THIS ORDER: (1) merge PR #70 to develop; (2) git fetch, then rebase #25 onto the new origin/develop and DROP 33f0f5b (git rebase --onto origin/develop 33f0f5b <branch> replays 5944f24/04a778a/d9f6908/1b52922; the accuracy_board.py+test content will already be in develop so expect it to drop cleanly, but BUILD/ACCURACY-STATE.md may conflict — keep the newest checkpoint content, those edits are §7.2-mandated and are NOT scope creep); (3) confirm 'git diff origin/develop...HEAD --stat' no longer lists scripts/accuracy_board.py or tests/test_accuracy_board_state.py; (4) re-run accuracy-review (the previous verdict was block and is SPENT); (5) accuracy-pr-land only if no blocker. GATES ON 1b52922 (run by me): ruff, ruff format, mypy 226 files, lint-imports 3/3, tests/eval + tests/test_accuracy_harness.py all green, tree clean. DECISIONS DA6 + DA6a in BUILD/DECISIONS.md, flagged to the human, do not re-litigate; the human may override DA6 with the design-effect alternative. REVIEWER'S UNRAISED OBSERVATION worth wiring before it matters: _build_run_manifest hardcodes cache_mode='read_write' and split='dev' instead of reading them from settings / the M0.7a authorisation path — harmless today because nothing consumes them, dangerous once M0.7a-gated test-split reads or cache-bypass sweeps rely on the manifest being truthful. NON-BLOCKING FOLLOW-UP for its own issue: AccuracyResult exposes no EvalRecords and save_result discards records+manifest, so the run_id->RunManifest join is unobservable outside measure_accuracy. PROCESS HAZARD: earlier this session TWO agents ran concurrently on this single worktree and one REWROTE the branch history (MISSION §3.2 forbids this). It was benign only because the content converged — I verified git diff between the old and new tips was empty. Never dispatch an implementer while another is live. §4 precondition: origin/develop..origin/main = 0. ENV: jq NOT installed (use gh --jq); pre-commit's language:system hooks need .venv/bin on PATH or mypy/lint-imports falsely report 'Executable not found'. Standing web-gate FAIL is escalated in BUILD/BLOCKERS.md — do not re-triage.
---

## Contract — keep this file THIN

GitHub is the tracker. Issue state, milestone progress, what is Ready, what is
blocked, PR links — all of that lives on the board ("Lemely Progress" #1, epic
#23) and is read and written through `scripts/accuracy_board.py`. **Do not
duplicate tracker state here.** This file holds only what GitHub cannot:

| key | meaning |
|---|---|
| `run_pointer` | label of the supervisor run currently executing, or `none` |
| `worktree` | absolute path of the active worktree (must be outside the repo), or `none` |
| `branch` | the feature branch currently being worked, or `none` |
| `last_run_label` | label of the last completed measurement run, or `none` |
| `last_run_headline` | its headline numbers on one line, or `none` |
| `review_rate` | current measured review rate |
| `ratchet` | the M0.9 ratchet state the review rate is judged against |
| `spend_usd` | cumulative Gemini spend as the ledger records it |
| `in_the_middle_of` | one line: what was mid-flight when the session ended. If anything long-running was left running in the background, this must name the command **and its log path**, so the next run polls that log instead of starting a second copy (MISSION §9.1). A run must never block on work that outlives it. |

The supervisor greps the header with `grep -m1 "^key:"`, so every key above
must stay exactly one line, at column zero, in `key: value` form, above the
`---` rule. Update the header after every completed work unit and before every
planned stop; the body below is for humans and can carry a sentence or two of
context, nothing more.

This file is machine-maintained via `scripts/accuracy_board.py state get/set/
show` (`state set` rewrites one header key in place, atomically, without
touching this body or the key order). **Do not hand-edit the header while the
supervisor is running** — a manual edit racing a `state set` write can be
clobbered, and any edit that breaks the `key: value` shape at column zero
breaks the supervisor's `grep -m1` reads and its 50%/80% spend alarms with it.

## Current state (seeded 2026-08-18)

Nothing has been started. Five tracker issues are closed, all by the human or
with human verification: #34 (H1), #42 (M1.7), #48 (H2), #50 (H5), #60 (H10).
The board's Ready set is #56, #25, #26, #31, #32 — all M0 — and
`python scripts/accuracy_board.py next` currently selects #56 (M0.0, the
fixture-renderer repair).

`spend_usd` is what the ledger recorded (0.4026) under the stale
`_DEFAULT_PRICING` table, which understates real spend by 2-4x and never
counted thinking tokens; M0.2 (#26) corrects the table. Treat the number as a
lower bound until then, and keep recording the ledger's figure here so the
series stays consistent with itself.

`review_rate` is the 19.1% baseline against the 10% budget. The M0.9 ratchet
(#33) is not built yet; once it lands, `ratchet` becomes the
`min(10%, last_merged_review_rate)` value CI enforces, seeded at 19.1% as a
recorded-but-non-blocking breach.
