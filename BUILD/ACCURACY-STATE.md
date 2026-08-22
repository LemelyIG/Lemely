# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-30-paired-statistics-mcnemar-wilson
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #30 (M0.6 paired stats) is COMPLETE AND PR-READY on feature/accuracy-30-paired-statistics-mcnemar-wilson (tip d32bba7, 5 signed commits above origin/develop) but is DELIBERATELY NOT PUSHED AND HAS NO PR, because Actions is billing-blocked. DO NOT re-implement it — verify with 'git log --oneline origin/develop..HEAD' before touching anything. WHAT TO DO WHEN BILLING IS FIXED, in this order: (a) 'gh pr checks 78'; if green, 'gh pr merge 78 --squash --delete-branch' then 'accuracy_board.py done 77' (#77's review wf_d2272bef-33f is already clean and does NOT need re-running); (b) run accuracy-pr-land {issue:30, branch:'feature/accuracy-30-paired-statistics-mcnemar-wilson', base:'develop'}; (c) then #27 (M0.3 A/A floor) is unblocked and MUST use '--cache-mode bypass', never 'refresh' (lemely/io/gemini.py:350-356 and :425 — bypass skips the cache read AND the write; refresh writes and would overwrite the shared cache on all ~10 repeats). WHY NO PR WAS OPENED THIS RUN: mission section 7.1 makes accuracy-pr-land the mandatory owner of the PR lifecycle, but it watches CI to conclusion and routes a red run into accuracy-gate-triage — and the standing order forbids re-triaging the billing block. Opening the PR by hand instead would bypass a mandatory workflow; running pr-land would force a forbidden re-triage. So the branch waits. This is a deliberate choice, not an omission. WHAT I VERIFIED MYSELF rather than trusting the workflow (wf_c44daa3d-c42 returned ready_for_pr=true, review=mergeable, but this programme has a false-green history): tree clean; all 5 commits gpgsig=1; 'grep -rn MCNEMAR_N_FLOOR' outside git history = 0 hits so the rename is complete; paired_proportion_min_n(0.838,0.888,alpha=0.05,power=0.80) now returns 155, exactly the Connor/Fleiss favourable limit it claims (it returned 157 last pass, and DA7's 'lower bound' wording is now true); monotonicity holds both ways (bigger effect 0.70->0.90 gives 37; power 0.95 gives 254); inspect.signature(mcnemar) is (records: list[EvalRecord]) so AC1's no-two-rate-summaries property is structurally enforced; mcnemar_improvement_p_value exists as the sole refusal point; 32/32 tests in tests/eval/test_analyses.py pass; and 'scripts/check.sh --fast tests/eval' ran TO COMPLETION green (ruff-check, ruff-format, mypy, import-linter, pytest, web-typecheck, web-lint, web-build, web-test all PASS; 4 skips are fast-mode browser/network gates). MUTATION-TESTED THE TESTS, since two were vacuous last pass: reverting the formula to 157 fails test_paired_proportion_min_n_pinned_value_and_monotonicity; removing the reporting refusal fails TestReportingLayer::test_underpowered_result_returns_the_sentinel; forcing underpowered=False fails test_below_floor_still_returns_numeric_statistic. All three bite; analyses.py restored byte-identical afterwards. THE DESIGN ADJUDICATION I MADE AND WHY IT MATTERS DOWNSTREAM: the first pass nulled chi2/p_value below the floor; I reversed that. Spec line 504 calls n=219 the floor for detecting IMPROVEMENT, line 450 says such a metric PRINTS as underpowered, and lines 506-508 make M1's BLOCKING gate non-regression at alpha=0.05 over a dev split the spec itself calls 'an order of magnitude below the n-floor'. Nulling at the computation layer would have made M1's own gate uncomputable. mcnemar() now always returns numbers, carries underpowered: bool, and the refusal lives in mcnemar_improvement_p_value. OPEN FOLLOW-UPS to carry into the PR body (all non-blocking, none weaken a gate): the refusal function currently has NO callers, so it becomes MUST-FIX the moment a reporting caller of mcnemar() lands — add a guard then; the 60-line hand-rolled Acklam _inverse_normal_cdf duplicates statistics.NormalDist().inv_cdf and has two untested tail branches; TestWilson may still be satisfiable by a clamped normal approximation, so AC2 is not fully enforced; the reporting fn is annotated '-> float | str' where DA7 documents Literal['underpowered']. STILL HALTED, RE-VERIFIED THIS RUN: no workflow run exists after 32547620531 (2026-08-22T02:56Z) and 'gh pr checks 78' shows all five jobs failing in 1-4s. GitHub Actions is billing-blocked for LemelyIG — a human must fix Settings > Billing & plans. Do NOT re-triage it, do NOT re-run that workflow, do NOT trim the CI matrix. FIRST MEASUREMENT MUST RECOMPUTE review_rate: 19.1% is on the PRE-#32 denominator (28 leaves; corpus is now 31 distinct leaves / 71 rows, DA6b). spend_usd 0.4026 is a LOWER BOUND (stale _DEFAULT_PRICING, no thinking tokens). NO BUDGET SPENT this run. Precondition re-checked: origin/develop..origin/main = 0. Local develop is 1 ahead of origin/develop (2096e77, state bookkeeping), left unpushed. WORKFLOW HAZARD, NOW SEEN FOUR TIMES AND IT COMMITS THE DAMAGE: accuracy-issue-execute blanked this key again and committed it as d32bba7 'clear in_the_middle_of', after overwriting it as 'implementing #30' in c42f78b — it did this DESPITE this very key warning about it. Assume it will happen again; re-read and re-write this header after every accuracy-issue-execute run. STANDING RED GATE, not accuracy-caused, do NOT re-triage: impeccable-detect, playwright-e2e, ui-thresholds (BUILD/BLOCKERS.md:666). ENV: jq NOT installed (use gh --jq); pre-commit needs .venv/bin on PATH; verify signing with 'git cat-file commit <sha> | grep -c gpgsig', NEVER %G?.
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
