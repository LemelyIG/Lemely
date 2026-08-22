# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-29-honest-denominators-fix-d18-exclusion
last_run_label: none
last_run_headline: none
review_rate: 29.03% (9/31 leaves, union numerator, on the #33 branch; NOT yet merged)
ratchet: unarmed; 29.03% recorded as a non-blocking M0 breach (#33 branch, unmerged)
spend_usd: 0.4026
in_the_middle_of: #29 (M0.5 honest denominators) IMPLEMENTED on feature/accuracy-29-honest-denominators-fix-d18-exclusion (761231c) but NOT PR-READY — accuracy-issue-execute wf_2479f430-373 returned ready_for_pr=FALSE and the review returned BLOCKED. NO PR is open. I verified all three blockers myself. BLOCKER 1, THE REAL ONE, STILL OPEN: lemely/accuracy/harness.py:386 _metrics_from_eval_records builds 'qlevel = [r for r in records if r.mark_point_id is None]' with NO outcome filter, while _is_correct is 'outcome == correct' — so 'excluded' rows land in the mark_accuracy denominator AND COUNT AS WRONG. I reproduced it directly: one correct + one excluded row gives mark_accuracy=0.5 (honest answer 1.0) and flag_recall collapses 1.0 -> 0.0. analyses.py already has the DA6a machinery (_collapse_leaf_group_scored_aware, _distinct_leaves_scored_aware) treating excluded as non-evidence, so the harness metric and the analyses layer DISAGREE. FIX: 'qlevel = [r for r in records if r.mark_point_id is None and r.outcome != "excluded"]', mirroring analyses._scored(); unmatched and abstain MUST STAY IN. I CORRECTED ONE OVERSTATEMENT IN THE VERDICT: it implies this corrupts the published 90.1% honest baseline. IT DOES NOT, TODAY — I checked every outcome in both saved golden runs and they contain ONLY correct(64)/under(6)/over(1); there is not a single excluded or unmatched row, and BUILD/DECISIONS.md already says so explicitly. The bug is LATENT, not active. It is still a genuine MUST-FIX because #29's entire purpose is to START producing excluded rows, so the headline number would silently drop the moment one appears — i.e. it would bite exactly the future runs D18 exists to protect. Do not describe the published number as currently wrong. BLOCKER 2: tests/test_accuracy_harness.py:466 test_never_attempted_leaf_is_excluded_not_unmatched asserts only the analyses-layer funnel (excluded=1/scored=1) and never result.metrics.mark_accuracy, so it passes straight over blocker 1. The criterion it discharges is about the DENOMINATOR, so it must assert the denominator the run actually reports — extend it to assert mark_accuracy==1.0 and flag_recall unaffected, and show it FAILING before the harness filter is added. BLOCKER 3, fixed by me: the state key was blanked again by commit c7ced69 (SEVENTH occurrence). pre-commit passes at the tip this time (no trailing space), so this did not break a gate. UNRESOLVED GOVERNANCE ITEM I FOUND MYSELF, record rather than guess: the baseline re-run (run-ef443fc2931e, saved to tests/golden/results/2026-08-22-79f5fa8.json) was a LIVE run with cache_mode=read_write, but spend_usd is UNCHANGED at 0.4026 and the manifest carries NO cost field, so the actual spend of that run is UNKNOWN and unrecorded. Probably small (cache reads), but unproven. Do not silently assume zero; either recover the cost from the ledger (lemely/io/cost_ledger.py) or record it as unmeasured. NON-BLOCKING, carry into the PR body: non-monotonic funnel (matched=3 > extracted=2, harness.py:680); a SECOND funnel implementation (FunnelCounts) was added in harness.py instead of extending analyses.exclusion_funnel(), and 'funnel' is not serialised by save_result so the printed funnel is NOT reproducible from saved runs; DA7 provenance is weak (gitignored artifact whose manifest git_sha 79f5fa8 is the PRE-fix commit); excluded rows hardcode id_match='unmatched'; DELIVERY.md:71/:139 and CHANGELOG.md:57 still quote 83.8% with NO 'historical' qualifier, which this issue's acceptance requires. WHAT IS GOOD, DO NOT REDO: the D18 loop fix itself is real and was falsified BEHAVIOURALLY against origin/develop's harness (four failures, not ImportError); it now iterates case.ground_truth so every leaf produces exactly one EvalRecord; no gate was weakened; #33's ratchet artifacts were untouched. FOUR BRANCHES QUEUED BEHIND THE BILLING BLOCK, DO NOT REDO ANY: #77 -> PR #78 OPEN and reviewed clean; #30 (M0.6) at 3f569ee PUSHED no PR; #33 (M0.9) at 693d76e PUSHED no PR; #29 in flight, NOT yet pushed. The supervisor sweep at 2026-08-22T12:15 covered EXACTLY 693d76e (#33's tip) with pytest ABSENT from failures. ORDER WHEN BILLING IS FIXED: (1) 'gh pr checks 78', if green merge --squash --delete-branch then 'accuracy_board.py done 77'; (2) accuracy-pr-land #30; (3) #33; (4) #29; (5) then #27 (M0.3), which MUST use '--cache-mode bypass' never 'refresh' (gemini.py:350-356, :425). REBASE HAZARD: #30/#33/#29 all cut from origin/develop; #30 and #33 both touch lemely/eval/analyses.py, #29 touches lemely/accuracy/harness.py. Rebase and RE-GATE whichever lands later; never merge blind. CROSS-ISSUE INTERACTION I identified and posted on both #29 and #33: #29 puts abstain/unmatched INTO the denominator, so after both merge, #33's BUILD/review-rate-baseline.json, config.py review_rate_last_merged=0.2903 and DA-M0.9 MUST ALL be recomputed. STILL HALTED: Actions is billing-blocked for LemelyIG — a human must fix Settings > Billing & plans. Re-verified this run: no workflow run after 32547620531 (2026-08-22T02:56Z). Do NOT re-triage, re-run it, or trim the CI matrix. Precondition re-checked: origin/develop..origin/main = 0. WORKFLOW HAZARD SEEN SEVEN TIMES: accuracy-issue-execute blanks this key, twice committing damage, once leaving a trailing space that made pre-commit FAIL. Re-read and re-write this header after EVERY run, then re-run pre-commit. RE-RUN EVERY GATE YOURSELF; MUTATION-TEST EVERY NEW TEST; an ImportError is NOT a falsification. STANDING RED GATE, do NOT re-triage: impeccable-detect, playwright-e2e, ui-thresholds (BUILD/BLOCKERS.md:666). ENV: jq NOT installed (use gh --jq); pre-commit needs .venv/bin on PATH; verify signing with 'git cat-file commit <sha> | grep -c gpgsig', NEVER %G?.
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
