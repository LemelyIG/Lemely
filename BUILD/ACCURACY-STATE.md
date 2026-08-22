# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-30-paired-statistics-mcnemar-wilson
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #30 (M0.6 paired stats) IMPLEMENTED on feature/accuracy-30-paired-statistics-mcnemar-wilson (c42f78b) but NOT PR-READY — accuracy-issue-execute wf_9c1d6a03-31d returned ready_for_pr=FALSE with 4 blockers, and I VERIFIED ALL FOUR MYSELF rather than trusting it. NO PR IS OPEN FOR #30 and none should be opened until the fixes below land. (1) ORCHESTRATOR ADJUDICATION, settled by me this run, READ THIS BEFORE RE-IMPLEMENTING — the commit sets chi2/p_value to None below the floor; that is WRONG and must be changed. Spec line 504 calls n=219 'the n-floor for detecting IMPROVEMENT'; line 450 (M0.6) says a metric below its floor 'PRINTS as underpowered rather than as a number'; lines 506-508 (M1 acceptance) say McNemar is 'reported, not gated for improvement' and the BLOCKING condition is non-regression at alpha=0.05 over the golden dev split, which the spec itself states is 'an order of magnitude below the n-floor'. So the floor governs IMPROVEMENT claims only. Nulling the statistic at the COMPUTATION layer makes M1's own blocking gate uncomputable from mcnemar(). Correct shape: keep computing and RETURNING chi2/p_value always, keep the 'underpowered: bool' flag, and make the REPORTING layer refuse to present a bare p-value as an improvement claim. Rename the constant to say improvement (e.g. MCNEMAR_IMPROVEMENT_N_FLOOR) so the two uses cannot be confused. (2) paired_proportion_min_n IS NOT THE LOWER BOUND IT ADVERTISES: I ran it — it returns 157 for (0.838, 0.888, alpha=0.05, power=0.80) while the Connor/Fleiss favourable limit it claims to compute, ceil((z_a + z_b*sqrt(1-d))^2 / d), gives 155 (I recomputed with the module's own _inverse_normal_cdf: z_a=1.959964, z_b=0.841621). Either correct the formula or STRIKE the 'lower bound' claim from the docstring AND from BUILD/DECISIONS.md DA7. It is also DEAD outside its own test (grep: only lemely/eval/__init__.py exports it). (3) AC1 IS UNMET: no test asserts there is no code path taking two independent rate summaries and returning a p-value; DA7 claims the criterion but the diff does not deliver it. Add an inspect.signature test. (4) AC7 IS UNTRUE FOR 2 OF 4 NEW TESTS — I confirmed this at source: 'git show origin/develop:lemely/eval/analyses.py' ALREADY has _distinct_leaves_by_arm, n_pairs and the collapse (lines 199/230/244/253), so test_leaf_count_is_derived_not_hardcoded asserts ONLY pre-existing DA6/DA6b behaviour and fails pre-fix solely on the module-level ImportError, proving nothing about the new feature; and test_paired_proportion_min_n_is_a_real_lower_bound_under_the_floor asserts only '0 < lower_bound <= 219', satisfied by ANY value in 1..219, so it pins nothing while being the ONLY checkable link between spec section 6's 219 and the code. An ImportError is NOT a falsification — demand a behavioural failure. (5) GATES UNCONFIRMED: the workflow's gate agent DIED (parallel[0], no StructuredOutput) and scripts/check.sh --fast never completed. Partial local re-verification only: pytest tests/eval passes, ruff/mypy/lint-imports clean. TREAT THE GATE AS UNRUN. Also carry into the PR body when it opens: TestWilson's assertions are satisfied by a clamped normal approximation so they do NOT enforce AC2 (Wilson-not-normal), and the below-floor test leaves b=31/c=0 unasserted. STILL HALTED AND NOTHING CAN MERGE: GitHub Actions is billing-blocked for LemelyIG (Settings > Billing & plans); re-verified this run — no workflow run exists after 32547620531 (2026-08-22T02:56Z) and 'gh pr checks 78' still shows all five jobs failing in 1-4s. Do NOT re-triage, do NOT re-run that workflow, do NOT trim the CI matrix. PR #78 for #77 is OPEN, REVIEWED CLEAN (wf_d2272bef-33f: merge, zero findings), deliberately unmerged; #77 in Backlog. WHEN BILLING IS FIXED: 'gh pr checks 78'; if green 'gh pr merge 78 --squash --delete-branch' then 'accuracy_board.py done 77' — review does NOT need re-running. Then #27 (M0.3 A/A floor) unblocks and MUST use '--cache-mode bypass', never 'refresh' (gemini.py:350-356,425). FIRST MEASUREMENT MUST RECOMPUTE review_rate: 19.1% is on the PRE-#32 denominator (28 leaves; corpus is now 31 distinct leaves / 71 rows, DA6b). spend_usd 0.4026 is a LOWER BOUND (stale _DEFAULT_PRICING, no thinking tokens). NO BUDGET SPENT this run or last. Precondition re-checked this run: origin/develop..origin/main = 0. Local develop is 1 ahead of origin/develop (2096e77, state bookkeeping), left unpushed. BRANCH-CUT TRAP fired AGAIN this run exactly as documented. WORKFLOW HAZARD CONFIRMED A THIRD TIME: accuracy-issue-execute overwrote this key with 'implementing #30' inside its own commit c42f78b and then left it BLANK and uncommitted. RE-RUN EVERY GATE YOURSELF and TRY TO MAKE EVERY NEW TEST FAIL. STANDING RED GATE, not accuracy-caused, do NOT re-triage: impeccable-detect, playwright-e2e, ui-thresholds (BUILD/BLOCKERS.md:666). ENV: jq NOT installed (use gh --jq); pre-commit needs .venv/bin on PATH; verify signing with 'git cat-file commit <sha> | grep -c gpgsig', NEVER %G?.
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
