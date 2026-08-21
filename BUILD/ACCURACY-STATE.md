# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-32-fixtures-carry-parent-id-and-is-excerpt
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #32 (M0.8) implementation COMPLETE on feature/accuracy-32-fixtures-carry-parent-id-and-is-excerpt at f806193; accuracy-review is RUNNING in background (workflow run wf_3da644c9-037, transcript /home/sico/.claude/projects/-home-sico-Lemely-worktrees-accuracy/9685e88a-9272-47a1-b3d3-3a2cbeb96c5c/subagents/workflows/wf_3da644c9-037 — read journal.jsonl there, do NOT relaunch a second copy). NEXT after a clean verdict: accuracy-pr-land {issue:32, branch:'feature/accuracy-32-fixtures-carry-parent-id-and-is-excerpt', base:'develop'}; if the verdict blocks, fix and re-run accuracy-review, never open the PR to 'see what CI says' (MISSION 7.1). THIS RUN: the prior must-fix was already landed before this session (0d101b4 gave the nested fixture a real sibling pair 1a_i/1a_ii under parent_id='1a'; I re-verified it myself by breaking the parent link in mark_scheme.json and watching test_nested_fixture_1a_i_prior_results_reach_1a_ii go RED, then restored the fixture — the test is genuinely falsifiable, not vacuous). What I fixed this run: the supervisor sweep's pytest FAIL was MINE and real — 'assert 71 == 70' in tests/eval/test_analyses.py, because 0d101b4's third leaf (1a_ii) moved the corpus off the 70-row/n=30 figures that commit 84fc4b9 had written for a 2-leaf nested fixture. Re-verified against the real corpus: 11 case dirs, 71 rows, 7+6+8+7+3 = 31 distinct leaves. Fixed BOTH asserts, renamed the test to test_wilson_n_is_31_distinct_leaves so the name cannot go stale silently, and added DA6b to BUILD/DECISIONS.md following DA6a's supersede-amendment pattern (DA6's '68 rows / 28 leaves' sentence is LEFT INTACT as history; only its two numbers are superseded) — the state note's demand to update DA6's stale 28 is now DONE. DA6b also records that review_rate 19.1% is quoted on the pre-#32 denominator and is deliberately NOT recomputed, because M0.9's ratchet is unarmed and section 2 forbids a baseline run until M0.8 merges. GATE STATUS, stated honestly: the supervisor verdict (FAIL, 4 gates) covers 51e18e6 and does NOT cover my tip f806193 — do not claim pytest green for this branch until the next sweep or CI says so. Of those 4, pytest was mine and is fixed; the other 3 (impeccable-detect, playwright-e2e, ui-thresholds) are the standing escalation at BUILD/BLOCKERS.md:666 ('the same three web gates, six sweeps running'), which names this exact playwright '0625 mastery: 88%' failure — NOT accuracy-caused, do NOT re-triage. Targeted proof I ran myself in the foreground and read: tests/eval/test_analyses.py + tests/test_golden_corpus.py all green, tests/test_correction_ai.py 26 green, ruff+ruff format+mypy+import-linter green via pre-commit --files with .venv/bin on PATH, tree clean, all 7 branch commits signed (verify with 'git cat-file commit <sha> | grep -c gpgsig', NEVER %G? — SSH sigs cannot be verified locally here). SHOULD-FIX items still owed to the PR body (from the spent review): the nested fixture wears a real 0625 w21 identity with a fabricated maximum_mark=5; 0625_s20 leaves 4a/5b/11b keep parent_id=null behind a hardcoded allowlist; _corpus_digest omits mark_scheme.json and the is_excerpt marker, so a future parent_id/is_excerpt edit is invisible to M0.3/M0.4 attribution. Also say in the PR that issue #32's '(a)(i) -> (b)' wording can NEVER hold under correction_ai.py's exact parent_id equality — only (a)(i) -> (a)(ii) is achievable — rather than pretending it was satisfied. AC5: the is_excerpt table (0580 True, 0606 True, 0625_m20 False, 0625_s20 False, nested False) is CORRECT per issue #32's six-of-ten list; do not 'fix' it. UNSTARTED issues filed earlier, still not on the board: #72 and #73 (#73 must land BEFORE M0.3/M0.4 consume the manifest). ENV: jq NOT installed; never dispatch a second agent against this worktree while one is live (one rewrote branch history before).
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
