# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: none
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: nothing in flight; worktree is on develop at d5a8424, clean. #25 (M0.1) LANDED: PR #71 squash-merged to develop as d5a8424, CI green on all 5 jobs, issue CLOSED, board Done, finish comment posted, branch deleted and refs pruned — all verified by me directly, not taken from the workflow's report. #69/PR #70 (supervisor state-set fix) also LANDED as 14cabfe and #69 is closed. M0 is now 4 of 11 Done (#56, #25, #26, #31). §4 precondition re-measured AFTER both merges: origin/develop..origin/main = 0. NEXT ITEM IS #32 (M0.8, fixtures carry parent_id and is_excerpt plus a nested multi-part fixture) and it NO LONGER NEEDS AN OVERRIDE — spec §4's tighter order (M0.0 -> M0.1/M0.2 -> M0.8) is now satisfied because #56, #25 and #26 are all merged, so the board's own 'next' is correct on its own. Start it with 'accuracy_board.py start 32' and take the branch name from that command's LAST LINE; never invent one. §8 note: M0.8 must land BEFORE M0.3 (A/A floor) and M0.4 (ablation), and BEFORE the ECF fix in M3/T1.5; and NO baseline run may happen until it lands (§2). Two NEW follow-up issues were filed this run and are unstarted: #72 (AccuracyResult/save_result discard the per-record EvalRecord list, so the run_id->RunManifest join is unobservable outside measure_accuracy and the analyses cannot be run over a real sweep) and #73 (_build_run_manifest hardcodes cache_mode='read_write' and split='dev'; harmless now, WRONG once M0.2's cache bypass or an M0.7a-gated test-split read depends on the manifest being truthful — land #73 before M0.3/M0.4 consume the manifest for attribution). Neither is on the board yet. DECISIONS DA6 + DA6a stand in BUILD/DECISIONS.md and were flagged to the human, who may still override DA6 with the design-effect alternative (point estimate over all 68 records, interval n = 28); if they do, #25's analyses change shape and that is a new issue, not a reopen. HARD-WON ENV AND PROCESS NOTES: 'jq' is NOT installed — use gh's built-in --jq, and never pipe a poll loop through jq because a missing binary reads as FALSE success; pre-commit's language:system hooks need .venv/bin on PATH or mypy/lint-imports falsely report 'Executable not found'; agent reports went false-green THREE times this session (pre-commit green on an unamended tree, ruff clean with a live D205, and shas not on the branch) so re-run every gate yourself before believing it; and TWO agents once ran concurrently on this single worktree and one rewrote branch history (§3.2 forbids it) — never dispatch an implementer while another is live. Standing web-gate FAIL (impeccable-detect, playwright-e2e, ui-thresholds) is escalated in BUILD/BLOCKERS.md awaiting a human decision — not accuracy-caused, not run by ci.yml, do NOT re-triage; ui-thresholds now flags up to 4 routes as its variance widens, but student-profile at ~57 remains the single genuine defect.
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
