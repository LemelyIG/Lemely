# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-73-build-run-manifest-hardcodes-cache-mode
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #73 IS STARTED AND NOT IMPLEMENTED — no production code on the branch yet. Board = In progress; branch feature/accuracy-73-build-run-manifest-hardcodes-cache-mode is cut from origin/develop at 1e18f05 and carries ONLY bookkeeping commits (501e689, a313999). The branch name came from 'accuracy_board.py start 73' — reuse THIS branch, never invent one. #73 = _build_run_manifest hardcodes cache_mode='read_write' and split='dev' instead of reading the real values. READ THIS IF YOU ARE AN IMPLEMENTER AGENT: there is NO concurrent agent on this worktree. If you were dispatched to implement #73 and you find a live accuracy-implementer process for this branch, that process is almost certainly YOU (check whether the agentId/PID you found is your own before concluding anything) — proceed with the work; do not refuse for concurrency. That exact self-deadlock already burned one full run: the state file said '#73 is being implemented right now by run wf_dba29fea-8af', the implementer dispatched BY wf_dba29fea-8af read it, independently verified a live agent, found its own agentId af504b54bd135b41a, concluded a rival was running and correctly-but-uselessly refused. The rule it applied (never two agents on one worktree, section 3.2) is RIGHT and still stands — it simply could not tell it was looking at itself. NEXT ACTION: accuracy-issue-execute {issue:73, root:'/home/sico/Lemely-worktrees/accuracy', branch:'feature/accuracy-73-build-run-manifest-hardcodes-cache-mode'}. Do NOT resume wf_dba29fea-8af — its Implement agent completed with a refusal and an unchanged prompt would replay that refusal from cache; launch a FRESH run. THE SCOPE PHASE ALREADY SUCCEEDED and its plan is good — recover it from the journal at /home/sico/.claude/projects/-home-sico-Lemely-worktrees-accuracy/9685e88a-9272-47a1-b3d3-3a2cbeb96c5c/subagents/workflows/wf_dba29fea-8af/journal.jsonl rather than re-deriving it. Plan in brief: give GeminiClient a settable default cache_mode (default 'read_write') so the client instance is the single source of truth, then in _build_run_manifest read the client's real mode instead of the literal; add split (and test_split_token) parameters to measure_accuracy and thread them into _build_run_manifest; when split=='test' route through the EXISTING lemely/eval/test_touch.py authorize_test_split_join gate — never add a second split=='test' comparison, which tests/eval/test_test_touch_static_guard.py's static scan would catch anyway; update _build_run_manifest's docstring, which currently narrates the hardcoded behaviour as intentional and will be stale. Three tests to add in tests/test_accuracy_harness.py: bypassed client records cache_mode='bypass'; authorised split='test' records split='test'; unauthorised test-split raises TestSplitAccessError. HARD CONSTRAINTS: keep the existing default path identical — test_manifest_is_a_run_manifest_instance asserts split=='dev' and must pass UNCHANGED; and do not let the diff expand into full per-call cache_mode threading through extract_answers/correct_paper (they do not accept the kwarg today), which is why the client-level default is the minimal correct fix. WHY #73 IS FIRST, ahead of section 4's stated next step: section 4's order is M0.0 -> M0.1/M0.2 -> M0.8 -> baseline run -> M0.3/M0.4/M0.5, so with #32 merged the baseline is nominally next. DO NOT RUN IT YET. A baseline spent through the current manifest stamps every record with FALSE provenance (cache-bypassed run records itself as cached; test-split run records itself as dev), tainting M0.3/#27 and M0.4/#28 attribution irreversibly — the taint is in the recorded attribution, not the figures, so re-reading output later cannot repair it. Then #72 (AccuracyResult/save_result discard the per-record EvalRecord list, so the run_id -> RunManifest join is unobservable outside measure_accuracy). ORDER: #73 -> #72 -> baseline -> #27/#28/#29. NOT in section 8's edge table; PROPOSED not decided, as a section 7 row on #43 at https://github.com/LemelyIG/Lemely/issues/43#issuecomment-5375246756 per the DA5 precedent. ACCURACY-SPEC.md NOT edited and must not be until the human says. VERIFY ANY WORKFLOW REPORT YOURSELF before believing it — this programme has had repeated false greens (pre-commit green on a tree whose auto-fix was never amended in; ruff clean with a live D205; a report citing shas not on the branch; a wrong 'unsigned commit' claim on #32). Re-run gates, confirm clean tree, confirm signing with 'git cat-file commit <sha> | grep -c gpgsig' (NEVER %G?). Then accuracy-review with head=branch and base='origin/develop' passed EXPLICITLY, then accuracy-pr-land. BRANCH-CUT TRAP: 'accuracy_board.py start' does NOT create the branch, and cutting from origin/develop REVERTS BUILD/ACCURACY-STATE.md to whatever rode in with the last squashed PR — it silently discarded a post-merge state commit this run (3e659a3, on LOCAL develop only, unpushed; 'git show 3e659a3'). Re-check this header immediately after cutting any branch; 'git cherry-pick' DROPS signatures unless given -S. #32 IS MERGED AND DONE: PR #74 squashed to 1e18f05, branch deleted, board Done, origin/develop..origin/main = 0. Verified directly: all five CI jobs green on head 33d9a60 (test 3.12 16m42s, 3.13 15m46s, 3.14 14m4s, pre-commit, web) after accuracy-pr-land's watch timed out at 701s and correctly refused to land on a timeout; AND the supervisor sweep at 2026-08-21T23:43 covered 33d9a60, that exact tip, with pytest NO LONGER failing. Its 3 remaining failures (impeccable-detect, playwright-e2e, ui-thresholds) are the standing escalation at BUILD/BLOCKERS.md:666 naming this exact '0625 mastery: 88%' cluster — NOT accuracy-caused, do NOT re-triage. M0 is 6 of 11 Done. Remaining M0: #27 (M0.3), #28 (M0.4), #29 (M0.5), #30 (M0.6), #33 (M0.9), plus #72/#73 which I milestoned to 'M0 — Instrument' and added to project 'Lemely Progress' #1 this run ('start' REFUSES non-board issues — use 'gh project item-add 1 --owner LemelyIG --url <issue-url>' first). #30/#33 have no in-edges. Blocked: #57/#59 wait on #44, #36 waits on #33. 'next' will keep saying 'nothing ready' — there is NO 'ready' subcommand and section 3.2 says YOU maintain that column: select per (1) Ready (2) lowest milestone (3) unblocks-most, then call 'start'. CARRY-FORWARD from #32 for M3/T1.5: '(a)(i) -> (b)' cross-branch ECF is UNREACHABLE BY DESIGN (exact parent_id equality; 1a_i parent '1a' vs 1b parent '1'); covered as (a)(i) -> (a)(ii) instead; disclosed at https://github.com/LemelyIG/Lemely/issues/32#issuecomment-5374580059; downstream must NOT assume it is corpus-covered. CORPUS AFTER #32: 11 case dirs, 71 rows, 31 distinct leaves (DA6b, DA6a supersede style). review_rate 19.1% is still on the PRE-#32 denominator, deliberately NOT recomputed — recompute on the first post-merge measurement; M0.9 ratchet unarmed. ENV: jq NOT installed (use gh --jq); pre-commit needs .venv/bin on PATH and its ruff-format auto-fix does NOT amend itself in — re-run and re-stage or you ship a false green; squash is the merge convention; accuracy-pr-land's CI watch has capped short on 3 of 4 uses so expect to poll and merge by hand.
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
