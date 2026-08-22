# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-72-evalrecords-are-discarded-the-run-id
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #72 IS STARTED AND NOT IMPLEMENTED — no production code on the branch yet. Board = In progress; branch feature/accuracy-72-evalrecords-are-discarded-the-run-id cut from origin/develop at 0760277. The name came from 'accuracy_board.py start 72' — reuse THIS branch, never invent one. NEXT ACTION: accuracy-issue-execute {issue:72, root:'/home/sico/Lemely-worktrees/accuracy', branch:'feature/accuracy-72-evalrecords-are-discarded-the-run-id'}. #72 = AccuracyResult/save_result DISCARD the per-record EvalRecord list, so the run_id -> RunManifest join is unobservable outside measure_accuracy and the M0 analyses cannot be run over a real sweep at all. IF YOU ARE AN IMPLEMENTER AGENT: there is NO concurrent agent on this worktree. If you find a live accuracy-implementer process for this branch, that is almost certainly YOU — check whether the agentId/PID is your own BEFORE concluding a rival exists and refusing. That exact self-deadlock burned run wf_dba29fea-8af, whose implementer found its own agentId af504b54bd135b41a and refused; the rule it applied (never two agents on one worktree) is right, it just could not tell it was looking at itself. A branch carrying only bookkeeping commits and no production code is EXPECTED at this stage, not evidence of a rival. #72 IS THE LAST PREREQUISITE BEFORE THE BASELINE RUN. Section 4's order is M0.0 -> M0.1/M0.2 -> M0.8 -> baseline -> M0.3/M0.4/M0.5. #73 landed, so once #72 lands the baseline is UNBLOCKED and the order becomes: baseline run, then #27 (M0.3 A/A floor), #28 (M0.4 ablation), #29 (M0.5). DO NOT run a baseline, A/A, ablation or A/B sweep until #72 is merged — without it the analyses cannot observe the records at all. That ordering is NOT in section 8's edge table; it is PROPOSED, not decided, as a section 7 row on #43 at https://github.com/LemelyIG/Lemely/issues/43#issuecomment-5375246756 per the DA5 precedent, and ACCURACY-SPEC.md must NOT be edited until the human says. Remember measurement work spends real money and needs the accuracy-measure workflow's costed preflight — 'not reportable, with reason' is a SUCCESSFUL outcome, not a failure. #73 IS MERGED AND DONE: PR #75 squashed to 0760277, branch deleted, board Done, origin/develop..origin/main = 0. Verified directly, not from a report: all five CI jobs green on head 08ac1d9 (test 3.12 14m44s, 3.13 16m3s, 3.14 12m52s, pre-commit, web; PR CLEAN/MERGEABLE) after accuracy-pr-land's watch timed out at 720s — that watch has now capped short on 4 of 5 uses, so EXPECT to poll 'gh pr checks <pr>' yourself and merge by hand; squash is this repo's convention. The supervisor sweep at 2026-08-22T02:19 also covered 6b544e3 with pytest ABSENT from its failure list. #73's own history worth keeping: accuracy-issue-execute returned ready_for_pr=false with 5 blockers; the two REAL ones were fixed by me at 69a07fb and each verified at source — (a) the M0.7a gate authorize_test_split_join sat inside _build_run_manifest, which measure_accuracy calls only in its FINAL RETURN, after the extract/correct loop, so an unauthorised split='test' run read the split and SPENT before being refused; now authorised at the top of measure_accuracy, with _build_run_manifest trusting the already-authorised split and not re-gating (exactly one ledger entry per run). Falsified by me AND independently by the reviewer on parent b318afe: 'Expected correct_paper to not have been called. Called 1 times.' (b) the authorised-split unit test was appending to the REAL reports/accuracy/test-touch-ledger.jsonl — 11 entries, all 11 forged by the buggy test, recording test-split touches that never happened; ledger_path is now threaded through, the test uses tmp and asserts exactly one entry, and the polluted untracked ledger was DELETED with that deletion disclosed in the PR body rather than done silently. accuracy-review wf_2f56d604-60b then returned recommendation=MERGE with ZERO findings and zero unreviewed dimensions. KNOWN LIMITATION carried forward from #73: manifest.cache_mode reports only the CLIENT DEFAULT, so a future per-call cache_mode='bypass' A/B sweep would still stamp 'read_write'; no production call site (cli.py, scripts/run_real_paper_accuracy.py, web/deps.py) can set default_cache_mode yet. The reviewer judged that gap to belong to M0.2 by strict ordering, not to #73 — but M0.3/M0.4 attribution depends on it, so CHECK IT before trusting a per-call-bypass sweep's provenance. BRANCH-CUT TRAP, hit twice now: 'accuracy_board.py start' does NOT create the branch, and cutting from origin/develop REVERTS BUILD/ACCURACY-STATE.md to whatever rode in with the last squashed PR, silently discarding any state commit that was never pushed. Re-check this header IMMEDIATELY after cutting any branch. Also: after merging a PR, local develop can DIVERGE from origin/develop (an unpushed state commit) and 'git pull --ff-only' will refuse — inspect 'git log --oneline origin/develop..develop' and reset when the local-only commits are stale bookkeeping. 'git cherry-pick' DROPS signatures unless given -S. BOARD MECHANICS: 'next' says 'nothing ready' because nothing sits in Ready and there is NO 'ready' subcommand — section 3.2 says YOU maintain that column: select per (1) Ready (2) lowest milestone (3) unblocks-most, then call 'start'. NOTE the board's M0 counts (11 total) do NOT include #72/#73 — I set their GitHub milestone to 'M0 — Instrument' and added them to project 'Lemely Progress' #1, but their PROJECT milestone field is unset, so they sit outside the milestone rollup. 'start' REFUSES issues that are not board items ('gh project item-add 1 --owner LemelyIG --url <url>' first). Remaining M0: #27 (M0.3), #28 (M0.4), #29 (M0.5), #30 (M0.6 paired stats), #33 (M0.9 ratchet); #30 and #33 have no in-edges. Blocked: #57/#59 wait on #44, #36 waits on #33. STANDING RED GATE, do NOT re-triage: impeccable-detect, playwright-e2e and ui-thresholds have failed every sweep for eight sweeps — escalated at BUILD/BLOCKERS.md:666, which names this exact '0625 mastery: 88%' e2e failure and the lighthouse student-route floor. NOT accuracy-caused, awaiting a human. CARRY-FORWARD from #32 for M3/T1.5: '(a)(i) -> (b)' cross-branch ECF is UNREACHABLE BY DESIGN (correction_ai.py groups siblings by EXACT parent_id equality; 1a_i's parent is '1a', 1b's is '1'), covered as (a)(i) -> (a)(ii) instead; disclosed at https://github.com/LemelyIG/Lemely/issues/32#issuecomment-5374580059; downstream must NOT assume it is corpus-covered. CORPUS: 11 case dirs, 71 rows, 31 distinct leaves (DA6b in BUILD/DECISIONS.md, DA6a supersede style). review_rate 19.1% is still quoted on the PRE-#32 denominator and deliberately NOT recomputed — recompute on the first post-merge measurement; the M0.9 ratchet is unarmed. ENV: jq NOT installed (use gh --jq); pre-commit's language:system hooks need .venv/bin on PATH; its ruff-format auto-fix does NOT amend itself into your commit — re-run and re-stage or you ship a false green; verify signing with 'git cat-file commit <sha> | grep -c gpgsig', NEVER %G?. VERIFY EVERY WORKFLOW CLAIM YOURSELF — this programme has had repeated false greens, and one workflow EMPTIED this in_the_middle_of key when it checkpointed state, so re-check it after any workflow writes state.
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

## Live workflow run — review of #73 (added 2026-08-22)

`accuracy-review` for **#73** is running as **`wf_2f56d604-60b`** (transcript
under `…/subagents/workflows/wf_2f56d604-60b/journal.jsonl`), over
`head=feature/accuracy-73-build-run-manifest-hardcodes-cache-mode`,
`base=origin/develop`, tip `ea83ffb`. Read that journal before launching
another review for #73. It only reads the diff — it does not implement — so it
will not collide with anything on the worktree.

On a clean verdict (`recommendation != block`, no `blocker`-severity finding),
go straight to `accuracy-pr-land {issue:73, branch:…, base:'develop'}`.

### Superseded — the #73 implementation runs

## Live workflow run (added 2026-08-22)

`accuracy-issue-execute` for **#73** was relaunched as run **`wf_ff14f7e7-9a0`**
(transcript under
`.claude/projects/-home-sico-Lemely-worktrees-accuracy/9685e88a-9272-47a1-b3d3-3a2cbeb96c5c/subagents/workflows/wf_ff14f7e7-9a0/journal.jsonl`).
Read that journal before launching anything for #73 — but see the header's
self-deadlock note first: if you are the implementer this run dispatched, that
entry describes **you**, not a rival, and you should proceed.

The earlier run `wf_dba29fea-8af` returned `implementation-blocked` with no
commits. Its **Scope** phase succeeded and its plan is worth recovering; its
**Implement** phase refused, so resuming it replays that refusal from cache.

## Implementation run for #72 (added 2026-08-22)

`accuracy-issue-execute` for **#72** is running as **`wf_f73ff647-3f0`**
(transcript under `…/subagents/workflows/wf_f73ff647-3f0/journal.jsonl`).
Read that journal and `git log --oneline origin/develop..HEAD` before
launching anything else for #72 — but see the header's self-deadlock note
first: **if you are the implementer this run dispatched, that entry describes
you, not a rival.**

It does **not** open the PR. When it returns, verify its claims yourself
(re-run the gates, confirm a clean tree, confirm signing with
`git cat-file commit <sha> | grep -c gpgsig`), then `accuracy-review` with
`head`/`base` passed explicitly, then `accuracy-pr-land`.

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
