# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-29-honest-denominators-fix-d18-exclusion
last_run_label: none
last_run_headline: none
review_rate: 29.03% (9/31 leaves, union numerator, on the #33 branch; NOT yet merged)
ratchet: unarmed; 29.03% recorded as a non-blocking M0 breach (#33 branch, unmerged)
spend_usd: 0.4026
in_the_middle_of: #29 (M0.5 honest denominators) is IMPLEMENTED and gate-green on feature/accuracy-29-honest-denominators-fix-d18-exclusion, but has NOT had a clean adversarial review pass and has NO PR. DO NOT re-implement — check 'git log --oneline origin/develop..HEAD' first. WHAT I FIXED MYSELF this run, after wf_82bbea23-f04 came back BLOCKED for the second time on #29 (a third identical workflow invocation would have been hoping for a different answer): (1) THE SELECTIVE-DISCLOSURE DEFECT, the serious one. The first pass qualified mark_accuracy's legacy 83.8% as 'historical, superseded' and published the honest 90.1% beside it — but left flag_recall (27.3%) and flag_precision_high (91.7%) stated in the present tense, UNQUALIFIED, in DELIVERY.md, CHANGELOG.md and docs/ACCURACY-STRATEGIES.md, while the SAME honest run (run-ef443fc2931e) reports flag_recall 14.29% and flag_precision_high 89.8%. So the ONLY metric that got the historical treatment was the one that moved in the FLATTERING direction; the two that moved unfavourably kept their better-looking legacy numbers. The review caught flag_recall; I found flag_precision_high as a THIRD instance it missed. All three now carry the qualifier and the honest figure in all three files, and the pattern is recorded in BUILD/DECISIONS.md as the same family of defect as D18. (2) THE NON-MONOTONIC FUNNEL: harness.py incremented funnel.extracted (on 'qid in extracted_ids') and funnel.matched (on 'cq is not None') from INDEPENDENT predicates, so the printed chain could RISE mid-funnel, reading as a denominator growing. 'extracted' is now reported as a separate non-nested count and the chain is leaves -> matched -> marked -> scored. (3) Added tests/test_accuracy_harness.py::test_printed_funnel_chain_never_rises. IMPORTANT HONESTY NOTE ON THAT TEST: my FIRST version asserted only monotonicity and I MUTATION-TESTED IT AND IT PASSED under the reverted code — the fixture produced extracted=3 > matched=2, so it never exercised the rise. That was exactly the vacuity I have been rejecting from the workflow. I rewrote it to assert structurally that the chain stages are exactly [leaves, matched, marked, scored] and that 'extracted' does not appear in the chain line; that version DOES fail under mutation ('extracted' unexpectedly found). 43/43 harness tests pass. (4) Appended DA7 notes: the two-funnel open risk (FunnelCounts vs analyses.exclusion_funnel, and 'funnel' is not serialised by save_result so 'extracted' is unrecoverable from saved runs) and a PROVENANCE CORRECTION — DA7 says the artifact was produced 'with the D18 fix in place' but its manifest git_sha is 79f5fa8, the PRE-fix commit; the figures reproduce exactly only because this corpus has no unmatched/excluded rows, so the artifact is NOT evidence the fix works, the behavioural tests are. VERIFIED MYSELF: pre-commit clean at tip; 'scripts/check.sh --fast tests/test_accuracy_harness.py tests/eval' ran TO COMPLETION green. I DELIBERATELY DID NOT FOLLOW one instruction in the workflow's next_action: it told me to 're-run the FULL pytest -q suite to completion'. That VIOLATES the standing order — the full suite is the SUPERVISOR's job, takes 20+ minutes and every session that tried was killed mid-wait, which is exactly why that gate reported exit_code -1. Do not do it. NOTE THE SUPERVISOR SWEEP DOES NOT COVER THIS BRANCH: the 2026-08-22T12:15 sweep covered 693d76e, which is #33's tip, NOT #29's. #29's backend is UNSWEPT — say so plainly rather than claiming pytest green. WHAT STILL NEEDS DOING ON #29: a fresh accuracy-review pass over the full diff (the last one predates all four of my fixes), then accuracy-pr-land once billing is fixed. Also still open, non-blocking: no test pins 'abstain' into the denominator (acceptance criterion 2 unverified); excluded rows hardcode id_match='unmatched'; the D18 regression test asserts only an inequality (pinning A=2/3 vs B=1/3 would be stronger). FOUR BRANCHES QUEUED BEHIND THE BILLING BLOCK, DO NOT REDO ANY: #77 -> PR #78 OPEN and reviewed clean; #30 (M0.6) at 3f569ee PUSHED no PR; #33 (M0.9) at 693d76e PUSHED no PR; #29 NOT yet pushed. ORDER WHEN BILLING IS FIXED: (1) 'gh pr checks 78', if green merge --squash --delete-branch then 'accuracy_board.py done 77'; (2) accuracy-pr-land #30; (3) #33; (4) #29; (5) then #27 (M0.3), which MUST use '--cache-mode bypass' never 'refresh' (gemini.py:350-356, :425). REBASE HAZARD: #30/#33/#29 all cut from origin/develop; #30 and #33 both touch lemely/eval/analyses.py, #29 touches lemely/accuracy/harness.py. Rebase and RE-GATE whichever lands later. CROSS-ISSUE INTERACTION posted on both #29 and #33: #29 puts abstain/unmatched INTO the denominator, so after both merge, #33's BUILD/review-rate-baseline.json, config.py review_rate_last_merged=0.2903 and DA-M0.9 MUST ALL be recomputed. UNMEASURED SPEND, recorded not guessed: run-ef443fc2931e was a live run (cache_mode=read_write) but spend_usd is unchanged at 0.4026 and RunManifest carries NO cost field, so that run's cost is UNKNOWN. DA7 now records this and proposes adding a per-run cost field. STILL HALTED: Actions is billing-blocked for LemelyIG — a human must fix Settings > Billing & plans. Re-verified this run: no workflow run after 32547620531 (2026-08-22T02:56Z). Do NOT re-triage, re-run it, or trim the CI matrix. Precondition: origin/develop..origin/main = 0. WORKFLOW HAZARD SEEN EIGHT TIMES: accuracy-issue-execute blanks this key, titling commits '#N landed' when nothing merged. RE-RUN EVERY GATE YOURSELF; MUTATION-TEST EVERY NEW TEST INCLUDING YOUR OWN. STANDING RED GATE, do NOT re-triage: BUILD/BLOCKERS.md:666. ENV: jq NOT installed (use gh --jq); pre-commit needs .venv/bin on PATH; verify signing with 'git cat-file commit <sha> | grep -c gpgsig', NEVER %G?.
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

## Review run for #72 (added 2026-08-22)

`accuracy-review` for **#72** is running as **`wf_95facc24-239`** (transcript
under `…/subagents/workflows/wf_95facc24-239/journal.jsonl`), over
`head=feature/accuracy-72-evalrecords-are-discarded-the-run-id`,
`base=origin/develop`, tip `91e9aa5`. It only reads the diff — it does not
implement — so it cannot collide with the worktree.

On a clean verdict (`recommendation != block`, no `blocker` finding), go to
`accuracy-pr-land {issue:72, branch:…, base:'develop'}`. Expect its CI watch to
time out (4 of 5 uses so far): a timeout is neither pass nor fail — poll
`gh pr checks <pr>` and merge by hand with `--squash`.

### Superseded — the #72 implementation run

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
