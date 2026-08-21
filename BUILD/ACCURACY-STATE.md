# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-31-split-mechanism-the-split-field-test
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #31 (M0.7a) on feature/accuracy-31-split-mechanism-the-split-field-test at ba2aa3a. accuracy-review DONE and CLEAN for this diff (run-2026-08-21-a): merge-with-fixes, no blocker, 6/6 dimensions; its one SHOULD-FIX (duplicated empty in_the_middle_of key) is fixed at ba2aa3a and verified. pre-commit --all-files green (NOTE: the language:system hooks need .venv/bin on PATH or mypy/lint-imports report 'Executable not found' — that is an environment answer, not a code verdict). tests/eval 17/17 green with --no-cov. run-2026-08-21-a is now running accuracy-pr-land {issue:31, branch:that branch, base:develop}. If this session died mid-land: check 'gh pr list --head feature/accuracy-31-split-mechanism-the-split-field-test' FIRST — a PR may already exist; do NOT open a second one. If the PR exists and CI is green, finish the merge BY HAND (pr-land caps its CI watch short). Do NOT re-run accuracy-review unless new CODE lands. Do NOT run the full pytest. §4 precondition: origin/develop..origin/main = 0. The sweep FAIL over this branch is the three standing WEB gates, already escalated in BUILD/BLOCKERS.md, not caused by #31 and not run by ci.yml — do not re-triage. DISCLOSE IN PR BODY: accuracy-issue-execute returned ready_for_pr=false and an earlier run fixed its MUST-FIX (an AST guard matching only ast.Eq, so it flagged nothing and AC5 was unenforced) by hand, then falsified it end-to-end; plus four non-blocking design limits (gate fails open on a split value not exactly 'test'; the token check is self-referential; the ledger is gitignored/unbounded/unchained though it is M0.7a's only evidence artefact; the guard scans only lemely/ and scripts/ and skips dirs named migrations) and the unrelated supervisor/BUILD checkpoint commits on this branch.
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
