# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-25-lemely-eval-record-model-run-manifest
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #25 (M0.1) at 4623eb6 on feature/accuracy-25-lemely-eval-record-model-run-manifest. accuracy-review returned MERGE, ZERO findings, 6/6 dimensions (run-2026-08-21-a) — the earlier BLOCK verdict is superseded and both its MUST-FIXes are fixed (params_fingerprint now covers the models; the tooling scope split to #69/PR #70, merged as 14cabfe, and commit 33f0f5b rebased OUT of this branch — verified absent from the net diff). accuracy-pr-land is RUNNING now {issue:25, branch:that branch, base:develop}. IF THIS SESSION DIED MID-LAND: run 'gh pr list --head feature/accuracy-25-lemely-eval-record-model-run-manifest' FIRST — a PR may already exist; do NOT open a second. If it exists and all 5 CI jobs pass, MERGE BY HAND (gh pr merge <n> --squash), then 'accuracy_board.py done 25', post the finish comment, close the branch, and re-measure origin/develop..origin/main. pr-land has capped its CI watch short on every previous use (690s vs a ~17min pytest matrix), so expect to finish the merge yourself; 'timeout' is NOT a failure and NOT a pass. Do NOT re-run accuracy-review — it is spent and clean for this exact tree; only re-run if new CODE lands. Do NOT run the full pytest. AFTER #25 LANDS the board's next item is #32 (M0.8) — by then spec §4's tighter order is satisfied (M0.0 #56, M0.1 #25, M0.2 #26 all merged), so #32 is genuinely next and no longer needs overriding. ALSO AFTER #25: open a follow-up issue for the gap the reviewer and the journal both name — AccuracyResult/save_result persist the manifest and metrics but DISCARD the per-record EvalRecord list, so downstream analyses cannot consume real runs and the run_id->RunManifest join is unobservable outside measure_accuracy. AND consider an issue for _build_run_manifest hardcoding cache_mode='read_write' and split='dev' rather than reading settings / the M0.7a authorisation path — harmless until a cache-bypass sweep or an M0.7a-gated test-split read depends on the manifest being truthful. DECISIONS DA6 + DA6a stand in BUILD/DECISIONS.md, flagged to the human, who may override DA6 with the design-effect alternative. PROCESS HAZARD: two agents once ran concurrently on this single worktree and one rewrote branch history (§3.2 forbids it) — never dispatch an implementer while another is live. §4 precondition was 0 before this land; RE-MEASURE after merging. ENV: jq NOT installed (use gh --jq); pre-commit's language:system hooks need .venv/bin on PATH. Standing web-gate FAIL (impeccable-detect, playwright-e2e, ui-thresholds) is escalated in BUILD/BLOCKERS.md awaiting a human — ui-thresholds is now flagging 4 routes as its variance widens, but student-profile at 57 remains the one genuine defect; do not re-triage.
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
