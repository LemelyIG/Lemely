# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-73-build-run-manifest-hardcodes-cache-mode
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #73 IS BEING IMPLEMENTED RIGHT NOW by accuracy-issue-execute, RUNNING IN BACKGROUND: run wf_dba29fea-8af, transcript /home/sico/.claude/projects/-home-sico-Lemely-worktrees-accuracy/9685e88a-9272-47a1-b3d3-3a2cbeb96c5c/subagents/workflows/wf_dba29fea-8af — READ journal.jsonl THERE FIRST and do NOT launch a second copy; check 'git log --oneline origin/develop..HEAD' on branch feature/accuracy-73-build-run-manifest-hardcodes-cache-mode to see what it actually committed. Branch was cut from origin/develop at 1e18f05 and carried only the checkpoint commit 501e689 when the workflow started. #73 = _build_run_manifest hardcodes cache_mode='read_write' and split='dev' instead of reading the real values. WHEN IT RETURNS: it does NOT open the PR. Verify its claims YOURSELF before believing them — agent/workflow reports have gone FALSE-GREEN repeatedly in this programme (pre-commit green on a tree whose auto-fix was never amended in; ruff clean with a live D205; a report citing shas not on the branch; and on #32 a claim that a commit was unsigned which was simply wrong). Re-run the gates yourself, confirm the tree is clean, confirm every commit is signed with 'git cat-file commit <sha> | grep -c gpgsig' (NEVER %G?), then run accuracy-review with head=the branch and base='origin/develop' explicitly, then accuracy-pr-land. WHY #73 IS FIRST, ahead of section 4's stated next step: section 4's order is M0.0 -> M0.1/M0.2 -> M0.8 -> baseline run -> M0.3/M0.4/M0.5, so with #32 merged the baseline run is nominally next. DO NOT RUN IT YET. A baseline spent through the current manifest stamps every record with FALSE provenance (a cache-bypassed run records itself as cached; a test-split run records itself as dev), tainting M0.3/#27 and M0.4/#28 attribution irreversibly — the taint is in the recorded attribution, not the figures, so re-reading output later cannot repair it. Then #72 (AccuracyResult/save_result discard the per-record EvalRecord list, so the run_id -> RunManifest join is unobservable outside measure_accuracy and the analyses cannot run over a real sweep). ORDER: #73 -> #72 -> baseline run -> #27/#28/#29. NOT in section 8's edge table; PROPOSED not decided, as a section 7 row on #43 at https://github.com/LemelyIG/Lemely/issues/43#issuecomment-5375246756 per the DA5 precedent. ACCURACY-SPEC.md NOT edited and must not be until the human says. BOOKKEEPING TRAP hit this run: 'accuracy_board.py start' does NOT create the branch, and cutting a branch from origin/develop REVERTED BUILD/ACCURACY-STATE.md to the stale copy that rode in with the squashed PR, silently discarding the post-merge state I had committed — that commit is 3e659a3, on LOCAL develop only, unpushed ('git show 3e659a3' for its full record). RE-CHECK the state header immediately after cutting any branch; and 'git cherry-pick' DROPS signatures unless given -S. #32 IS MERGED AND DONE: PR #74 squashed to 1e18f05, branch deleted, board Done, origin/develop..origin/main = 0. Proof verified directly, not from a report: all five CI jobs green on head 33d9a60 (test 3.12 16m42s, 3.13 15m46s, 3.14 14m4s, pre-commit, web; CLEAN/MERGEABLE) after accuracy-pr-land's watch timed out at 701s and correctly refused to land on a timeout; AND the supervisor sweep at 2026-08-21T23:43 ran over 33d9a60, that exact tip, with pytest NO LONGER in its failure list. Its 3 remaining failures (impeccable-detect, playwright-e2e, ui-thresholds) are the standing escalation at BUILD/BLOCKERS.md:666 naming this exact '0625 mastery: 88%' cluster — NOT accuracy-caused, do NOT re-triage. M0 is 6 of 11 Done. Remaining M0: #27 (M0.3 A/A floor), #28 (M0.4 ablation), #29 (M0.5), #30 (M0.6 paired stats), #33 (M0.9 ratchet), plus #72/#73 which I milestoned to 'M0 — Instrument' and added to project 'Lemely Progress' #1 this run ('start' REFUSES non-board issues, so use 'gh project item-add 1 --owner LemelyIG --url <issue-url>' first). #30 and #33 have no in-edges and may proceed any time. Blocked: #57 and #59 wait on #44, #36 waits on #33. 'accuracy_board.py next' will keep saying 'nothing ready' — there is NO 'ready' subcommand and section 3.2 says YOU maintain that column, so select per (1) Ready (2) lowest milestone (3) unblocks-most and call 'start'. CARRY-FORWARD from #32 for M3/T1.5: '(a)(i) -> (b)' cross-branch ECF is UNREACHABLE BY DESIGN (exact parent_id equality; 1a_i's parent '1a' vs 1b's '1'), covered as (a)(i) -> (a)(ii) instead; disclosed at https://github.com/LemelyIG/Lemely/issues/32#issuecomment-5374580059; downstream must NOT assume it is corpus-covered. CORPUS AFTER #32: 11 case dirs, 71 rows, 31 distinct leaves (DA6b in BUILD/DECISIONS.md, DA6a supersede style). review_rate 19.1% is still on the PRE-#32 denominator, deliberately NOT recomputed — recompute on the first post-merge measurement; M0.9 ratchet still unarmed. ENV: jq NOT installed (use gh --jq); pre-commit needs .venv/bin on PATH and its ruff-format auto-fix does NOT amend itself in — re-run and re-stage or you ship a false green; squash is the merge convention; accuracy-pr-land's CI watch has capped short on 3 of 4 uses so expect to poll and merge by hand; never dispatch a second agent against this worktree while one is live.
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
