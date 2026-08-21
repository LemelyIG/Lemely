# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-25-lemely-eval-record-model-run-manifest
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #25 (M0.1) implemented on feature/accuracy-25-lemely-eval-record-model-run-manifest at 7356a60, UNPUSHED, no PR. All three structural MUST-FIXes are DONE plus DA6a. Commits: 3f3fbc0 (DA6 record), 0539a56 (collapse/fixture_variant/run_id+RunManifest), 33f0f5b (board state-set fix + its regression test), 4c4aec3 (DA6a record), 7356a60 (ruff fixes). VERIFIED BY ME THIS RUN: ruff check + ruff format + mypy + lint-imports all clean; pre-commit --all-files GREEN ON THE COMMITTED TREE; tree clean; 98 tests pass across tests/eval + tests/test_accuracy_harness.py + tests/test_accuracy_board_state.py; and the four tests that matter pass — wilson n==28 on the real corpus, exclusion_funnel scored-count == wilson n, order-independence, and correct+wrong must not count as correct. NEXT STEP: run accuracy-review {base:'origin/develop', head:that branch, issue:25}; if it returns no blocker, accuracy-pr-land {issue:25, branch:that branch, base:'develop'}. THREE DECISIONS recorded in BUILD/DECISIONS.md, all flagged to the human, do not re-litigate: DA6 (leaf outcome DERIVED from all variant records, never sampled — a leaf is correct iff EVERY scored record is correct; the review's 'deterministic collapse' was a trap because correct<partial<wrong sort in that order and sort-first would push accuracy to ~100% by construction) and DA6a (a leaf is excluded iff EVERY record is excluded; a scored leaf's outcome derives over its SCORED records only; invariant exclusion_funnel scored-count == wilson n, pinned by a test on the real corpus — this corrected a sentence I got WRONG in DA6). DISCLOSE IN THE PR BODY: (a) this branch carries a supervisor-tooling fix (33f0f5b) that is NOT M0.1 work — scripts/accuracy_board.py state set treated ': ' as the key delimiter, so an empty-valued 'in_the_middle_of:' was invisible, state set INSERTED a second line, and the supervisor's grep -m1 read the empty one, silently blinding the resume pointer on every run; repaired by hand once and it came back, so it now has 6 regression tests, 4 of which fail against the old parser; (b) the DA6/DA6a decisions and that the human may override DA6 with the design-effect alternative; (c) accuracy-issue-execute originally returned ready_for_pr=false and its MUST-FIXes were fixed here. KNOWN NON-BLOCKING GAP for its OWN issue after #25 lands (do NOT fix in #25): AccuracyResult does not expose the produced EvalRecords and save_result discards them, so nothing outside measure_accuracy can perform the run_id->RunManifest join the new plumbing exists for. §4 precondition: origin/develop..origin/main = 0. ENV: jq NOT installed (use gh --jq); pre-commit's language:system hooks need .venv/bin on PATH. Standing web-gate FAIL is escalated in BUILD/BLOCKERS.md — not accuracy-caused, not run by ci.yml, do not re-triage. Board 'next' says #32 but #25 is correctly ahead of it per spec §4 — do not switch.
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
