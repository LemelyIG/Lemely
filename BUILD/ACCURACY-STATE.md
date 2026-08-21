# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-25-lemely-eval-record-model-run-manifest
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of:
in_the_middle_of: #25 (M0.1) IMPLEMENTED BUT BLOCKED — do NOT open a PR. Branch feature/accuracy-25-lemely-eval-record-model-run-manifest at 79693b0, UNPUSHED (0 remote refs). accuracy-issue-execute returned ready_for_pr=FALSE, review_verdict=blocked, 5 blocking items. I FIXED THE TWO MECHANICAL ONES THIS RUN and verified each: (a) ruff format failed on the committed tree ('Would reformat: lemely/eval/analyses.py') because the implementer's auto-fix was never amended — reformatted and amended into 79693b0, recheck now '352 files already formatted'; (b) the dirty BUILD/ACCURACY-STATE.md is committed as a separate chore. THREE STRUCTURAL MUST-FIXes REMAIN, all re-verified by me at the source — re-run accuracy-issue-execute (or accuracy-implementer) on this SAME branch, do not cut a new one: (1) DISTINCT-LEAF COLLAPSING IS INERT. _distinct_leaves (lemely/eval/analyses.py:29-40) keys on (paper_id, question_id) but harness.py:245 hardcodes fixture_variant=None and the golden corpus encodes the variant INSIDE paper_id (0580_s23_qp_22_theory_correct/partial/wrong), so wilson/mcnemar/review_rate count 68 records where spec §3.3 / M0.6 require 28 distinct leaves. Fix: populate fixture_variant from the golden-dir suffix, set paper_id to the variant-stripped base id, key on (paper_id, question_id) with fixture_variant deliberately EXCLUDED, and replace the order-dependent 'first one seen' collapse with a deterministic rule. This is a dishonest denominator — the exact D18 failure M0 exists to prevent — so it must not reach a PR. (2) THE COLLAPSING TESTS ARE VACUOUS. tests/eval/test_analyses.py:105-125 and 240-252 feed rows carrying mark_point_id='1a'/'1b', which _question_level() strips BEFORE _distinct_leaves() runs; monkeypatching _distinct_leaves to the identity leaves every assertion green. Need a test feeding 2+ question-level rows (mark_point_id=None) for the same leaf — ideally over the real tests/golden corpus asserting wilson()['n'] == 28 — that FAILS against the current keying. (3) run_id IS A HARDCODED LITERAL 'measure_accuracy' (harness.py:405) and no RunManifest is ever constructed in the diff (only re-exported). Spec §3.3 makes run_id the join key to RunManifest; a constant makes every run of every arm indistinguishable and breaks M0.3's repeat-run churn measurement. Thread a real run_id param through measure_accuracy (default: generated) and build the RunManifest the records join to. DO NOT weaken any assertion or threshold to get green. WHAT ALREADY HOLDS (do not redo): exactly one 'class RunManifest' (lemely/eval/manifest.py:28) so #31's record was reused not duplicated, EvalRecord fields match spec §3.3, the new import-linter purity contract is real, mypy + lint-imports clean, pytest -q green with no new skips/xfails, no prompt VERSION bump, test_touch.py's split gate untouched, no H issue touched. CARRY TO PR BODY ONCE FIXED (non-blocking): parse_path is overloaded to mean 'which marker ran'; ground-truth ids the extractor never returned are dropped instead of emitted as outcome='unmatched' (the D18 shape); _metrics_from_eval_records omits the _scored 'excluded' filter so denominators will diverge at M0.5/M0.8; risk_coverage drops marker_conf=None rows, narrowing the denominator; the M0.1 equivalence test uses synthetic rows not tests/golden so the theory branch is never exercised end to end. CONTEXT: #31 (M0.7a) is fully LANDED (PR #68 -> 47977cf on develop, board Done, comment posted, branch pruned). #25 was started AHEAD of the board's 'next' (#32) deliberately — spec §4's tighter order is M0.0 -> M0.1/M0.2 -> M0.8, and #56/#26 are closed while #25 was merely never moved out of Backlog; do not 'correct' this back to #32. §4 precondition: origin/develop..origin/main = 0. ENV: 'jq' is NOT installed (use gh --jq; a poll loop piping to jq reports FALSE success); pre-commit's language:system hooks need .venv/bin on PATH or mypy/lint-imports falsely report 'Executable not found'. Standing web-gate FAIL (impeccable-detect, playwright-e2e, ui-thresholds) is escalated in BUILD/BLOCKERS.md awaiting a human — not accuracy-caused, not run by ci.yml, do not re-triage.
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
