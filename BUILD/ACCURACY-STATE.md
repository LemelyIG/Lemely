# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-33-review-rate-as-a-two-part-ratchet-ci
last_run_label: none
last_run_headline: none
review_rate: 29.03% (9/31 leaves, union numerator, recomputed 2026-08-22; supersedes the stale pre-#32 19.1%)
ratchet: unarmed; starting value 29.03% recorded as a non-blocking M0 breach (#33 branch, unmerged)
spend_usd: 0.4668
in_the_middle_of: #33 (M0.9 ratchet) is COMPLETE AND PR-READY on feature/accuracy-33-review-rate-as-a-two-part-ratchet-ci, PUSHED to origin with NO PR. DO NOT re-implement it — check 'git log --oneline origin/develop..HEAD' first. THREE FINISHED BRANCHES ARE NOW QUEUED BEHIND THE BILLING BLOCK, none merged, none to be redone: (a) #77 -> PR #78 OPEN, reviewed clean (wf_d2272bef-33f: merge, zero findings); (b) #30 (M0.6 paired stats) at 3f569ee, pushed, no PR; (c) #33, pushed, no PR. ORDER WHEN BILLING IS FIXED: (1) 'gh pr checks 78', if green 'gh pr merge 78 --squash --delete-branch' then 'accuracy_board.py done 77' — #78's review does NOT need re-running; (2) accuracy-pr-land {issue:30, branch:'feature/accuracy-30-paired-statistics-mcnemar-wilson', base:'develop'}; (3) accuracy-pr-land {issue:33, branch:'feature/accuracy-33-review-rate-as-a-two-part-ratchet-ci', base:'develop'}; (4) THEN #27 (M0.3 A/A floor), which MUST use '--cache-mode bypass', never 'refresh' (gemini.py:350-356, :425 — bypass skips the cache read AND write; refresh writes and would overwrite the shared cache on all ~10 repeats). NOTE #30 and #33 BOTH touch lemely/eval/analyses.py and were both cut from origin/develop, so whichever lands second may need a rebase — #30 adds the McNemar n-floor block, #33 changes review_rate's numerator and adds _group_by_leaf; they touch different functions so a conflict should be textual, not semantic. THE HEADLINE RESULT OF #33, and the reason it took two passes: the first pass recorded a ratchet baseline of 3.23% which was a LEAF-COLLAPSE ARTIFACT. I recomputed independently over tests/golden/results/2026-08-22-f7be062.json: 71 question-level rows, 31 distinct leaves, 12 flagged rows (16.9%), 9 of 31 leaves (29.0%) carrying a non-random_audit trigger. review_rate() was reading triggers off the single DA6 representative row, and _collapse_leaf_group is built for OUTCOME semantics (a leaf is correct iff EVERY record is correct), so for unanimously-correct leaves min() picked an arbitrary representative and silently discarded the others' triggers — hiding 8 of the 9 flagged leaves, a ~9x undercount, and inverting the incentive so a run generating MORE reviews would score BETTER (the D18 shape). This defect was INHERITED from origin/develop (review_rate has been there since #25/M0.1), NOT introduced by #33. FIXED: the numerator is now a union over each leaf's raw records (analyses.py:446-447), denominator still distinct leaves so DA6 interval independence is preserved; wilson/risk_coverage/exclusion_funnel/_collapse_leaf_group untouched. review_rate is now 29.03% and review_rate_last_merged=0.2903 (truncated DOWN, the stricter direction). BUILD/DECISIONS.md now RETRACTS the old 'correctly-denominatored' / '6x smaller than 19.1%' claims by name and publishes the funnel; the surviving grep hit for that phrase is INSIDE the retraction, which is correct, not a residual false claim. WHAT I VERIFIED MYSELF, not from the workflow (wf_6c222c18-c17 said ready_for_pr=true / mergeable): pre-commit passes at the tip with a clean tree; 'python scripts/check_review_rate_gate.py' prints all four limbs FAIL with '(ratchet unarmed — recorded, not blocking)' and exits 0, which is exactly the M0 acceptance; 'scripts/check.sh --fast tests/eval tests/test_cli_review_rate_gate.py' ran TO COMPLETION green including the new review-rate-gate step. MUTATION-TESTED, all three caught by named tests: reverting the union to all() fails test_counts_leaf_via_trigger_union_not_representative; making the ratchet ceiling ignore last_merged fails TestRatchetCeiling and TestRatchetDirection; forcing blocking_failure=False fails TestArmedTrueBlocking and the total==signal invariant test. analyses.py and review_gate.py restored byte-identical afterwards. OPEN FOLLOW-UPS for the PR body (non-blocking, none weaken a gate): scripts/check_review_rate_gate.py (the CI entry point) has ZERO test coverage; on the CI path it reads the committed baseline's frozen numbers and cross-checks corpus_digest against nothing, so CI currently gates a COMMITTED CONSTANT and cannot detect a review-rate regression from a code change — THIS MUST BE RESOLVED BEFORE THE RATCHET IS ARMED AT M1; cli.py's split refusal fires AFTER save_result() has already persisted the wrong-split run; and the ci.yml wiring is written-only and honestly NOT claimed CI-verified. HONEST CAVEAT recorded in DA-M0.9 and worth repeating: the golden corpus replays each leaf as correct/partial/wrong variants, so 29.0% (leaf-union) is an UPPER bound, 16.9% (row-level) weights synthetic variants equally, and 3.23% (representative-only) is biased LOW — none is unambiguously 'the' review rate; the union was chosen because a burden gate must not flatter. STILL HALTED: Actions is billing-blocked for LemelyIG — a human must fix Settings > Billing & plans. Re-verified this run: no workflow run after 32547620531 (2026-08-22T02:56Z); 'gh pr checks 78' still shows all five jobs failing in 1-4s. Do NOT re-triage, do NOT re-run that workflow, do NOT trim the CI matrix. spend_usd 0.4026 is a LOWER BOUND (stale _DEFAULT_PRICING, no thinking tokens). NO BUDGET SPENT in the last four runs. Precondition re-checked: origin/develop..origin/main = 0. Local develop is 1 ahead of origin/develop (2096e77, bookkeeping), unpushed. WORKFLOW HAZARD NOW SEEN SIX TIMES, twice committing the damage: accuracy-issue-execute blanks this key and titles the commit 'clear in_the_middle_of after #33 landed' when #33 has NOT landed; once it left a TRAILING SPACE that made pre-commit FAIL at the tip. Re-read and re-write this header after EVERY accuracy-issue-execute run, and re-run pre-commit after doing so. RE-RUN EVERY GATE YOURSELF; MUTATION-TEST EVERY NEW TEST; an ImportError is NOT a falsification. STANDING RED GATE, not accuracy-caused, do NOT re-triage: impeccable-detect, playwright-e2e, ui-thresholds (BUILD/BLOCKERS.md:666). ENV: jq NOT installed (use gh --jq); pre-commit needs .venv/bin on PATH; verify signing with 'git cat-file commit <sha> | grep -c gpgsig', NEVER %G?.
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
