# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-25-lemely-eval-record-model-run-manifest
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #25 (M0.1) implemented on feature/accuracy-25-lemely-eval-record-model-run-manifest at d9f6908, UNPUSHED, no PR. accuracy-review IS RUNNING on this branch (launched run-2026-08-21-a). HISTORY WAS REWRITTEN MID-RUN — read this before you are confused by shas: a second agent ran CONCURRENTLY on this shared worktree and rebased/amended the branch, so my commits 943c67e/7356a60/4c4aec3/0539a56 are no longer on it (they still exist as dangling objects). Current chain: d9f6908 (checkpoint) / 04a778a (D205 style) / 5944f24 (DA6a record) / 33f0f5b (MY board state-set fix, survived) / a1e268c (the M0.1 code) / 3f3fbc0 (DA6 record). I VERIFIED THE REWRITE WAS CONTENT-NEUTRAL: 'git diff 943c67e d9f6908' is EMPTY and both tips give an identical 13 files/1812 insertions diff vs origin/develop, so the running review's verdict is valid for the tree that would be merged. Nothing was lost — board fix present (4 uses of _state_line_value), tests/test_accuracy_board_state.py present, both DA6 and DA6a in DECISIONS.md, exactly one 'class RunManifest', one in_the_middle_of key. GATES RE-RUN BY ME ON d9f6908 (not on the pre-rewrite tip): ruff check + ruff format + mypy (226 files) + lint-imports (3/3 contracts) all clean, 98 tests green across tests/eval + tests/test_accuracy_harness.py + tests/test_accuracy_board_state.py, tree clean. PROCESS HAZARD TO RAISE WITH THE HUMAN: two agents operated on the single shared worktree at once, which MISSION §3.2 forbids precisely because a second actor 'checks out a branch on top of the first's dirty state and corrupts both'. It was benign ONLY because the content converged; it could equally have destroyed work. Do not dispatch an implementer while another is live. NEXT: read the accuracy-review verdict; if no blocker, accuracy-pr-land {issue:25, branch:that branch, base:'develop'}. If the verdict names shas 943c67e/7356a60/4c4aec3/0539a56, it is still valid — same content. DISCLOSE IN PR BODY: (a) 33f0f5b is supervisor tooling, NOT M0.1 — accuracy_board.py's state set treated ': ' as the key delimiter so an empty-valued key was invisible, state set INSERTED a duplicate, and the supervisor's grep -m1 read the empty one, blinding the resume pointer every run; now has 6 regression tests, 4 of which fail against the old parser; (b) DA6 and DA6a, and that the human may override DA6 with the design-effect alternative; (c) accuracy-issue-execute originally returned ready_for_pr=false. NON-BLOCKING FOLLOW-UP for its own issue (do NOT fix in #25): AccuracyResult exposes no EvalRecords and save_result discards records+manifest, so the run_id->RunManifest join is unobservable outside measure_accuracy; test_explicit_run_id_propagates_to_manifest_and_eval_records therefore only checks result.manifest.run_id, not any EvalRecord's. §4 precondition: origin/develop..origin/main = 0. ENV: jq NOT installed (use gh --jq); pre-commit's language:system hooks need .venv/bin on PATH. Standing web-gate FAIL is escalated in BUILD/BLOCKERS.md — do not re-triage. Board 'next' says #32 but #25 is correctly ahead per spec §4.
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
