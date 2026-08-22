# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-33-review-rate-as-a-two-part-ratchet-ci
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #33 (M0.9 review_rate two-part ratchet) SELECTED, board=In progress, branch CUT from origin/develop; accuracy-issue-execute launched in THIS run. If you read this in a LATER run, that workflow's result is LOST (same-session only) — run 'git log --oneline origin/develop..HEAD' and re-run from scratch if it committed nothing. TWO FINISHED BRANCHES ARE QUEUED, DO NOT REDO EITHER: (a) #77 -> PR #78 OPEN, reviewed clean (wf_d2272bef-33f: merge, zero findings), deliberately unmerged; (b) #30 (M0.6 paired stats) COMPLETE on feature/accuracy-30-paired-statistics-mcnemar-wilson, tip 3f569ee, 7 signed commits, NOW PUSHED to origin (protective only — NO PR is open and 'gh pr list --head ...' returned 0; ci.yml triggers on pull_request so the push started no CI). The supervisor sweep at 2026-08-22T09:36 covered EXACTLY 3f569ee with a clean tree and pytest ABSENT from its failures, so #30's backend is genuinely green on its own tip; the 3 failures (impeccable-detect, playwright-e2e, ui-thresholds) are the STANDING RED GATE, not accuracy-caused, do NOT re-triage. ORDER WHEN BILLING IS FIXED: (1) 'gh pr checks 78', if green 'gh pr merge 78 --squash --delete-branch' then 'accuracy_board.py done 77' — #78's review does NOT need re-running; (2) accuracy-pr-land {issue:30, branch:'feature/accuracy-30-paired-statistics-mcnemar-wilson', base:'develop'}; (3) accuracy-pr-land for #33; (4) THEN #27 (M0.3 A/A floor), which MUST use '--cache-mode bypass', never 'refresh' (lemely/io/gemini.py:350-356 and :425 — bypass skips the cache read AND the write; refresh writes and would overwrite the shared cache on all ~10 repeats). WHY #33 IS BEING WORKED NOW, reversing last run's deferral: it is the last in-edge-free M0 item and it unblocks #36. Last run I deferred it as 'unverifiable while CI is dead'; that was OVERSTATED — the gate LOGIC is a script provable locally with scripts/check.sh --fast, and only the .github/workflows/ci.yml WIRING is unexecutable (reviewable, not runnable). With the block possibly lasting days, deferring the last available item indefinitely is worse. BINDING CONSTRAINT ON #33 — THE 19.1% IN ITS BODY IS STALE, DO NOT HARDCODE IT: that figure is 13/68 records on the PRE-#32 denominator (28 distinct leaves). The corpus is now 31 distinct leaves / 71 rows over 11 case dirs (DA6b). The acceptance box 'M0 records 19.1% as the ratchet starting value' must be satisfied by a value COMPUTED from the current golden run, with the recomputed number recorded and the divergence from 19.1% stated plainly. review_rate is defined over QUESTION-LEVEL EvalRecord rows (mark_point_id is None) with a non-empty triggers list, over the frozen dev split; the split field exists since #31 merged. wilson() already exists on origin/develop (untouched by #30) so per-paper intervals need no dependency on the unmerged #30 branch. STILL HALTED: GitHub Actions is billing-blocked for LemelyIG — a human must fix Settings > Billing & plans. Re-verified THIS run: still no workflow run after 32547620531 (2026-08-22T02:56Z), and 'gh pr checks 78' still shows all five jobs failing in 1-4s. NOTHING CAN MERGE, #33 included. Do NOT re-triage the block, do NOT re-run that workflow, do NOT trim the CI matrix to fit it. FIRST MEASUREMENT MUST RECOMPUTE review_rate before any A/B claim. spend_usd 0.4026 is a LOWER BOUND (stale _DEFAULT_PRICING, no thinking tokens). NO BUDGET SPENT this run or the last two. Precondition re-checked this run: origin/develop..origin/main = 0. Local develop is 1 ahead of origin/develop (2096e77, state bookkeeping), left unpushed. BRANCH-CUT TRAP fired AGAIN this run, third time in this session. WORKFLOW HAZARD SEEN FOUR TIMES AND IT COMMITS THE DAMAGE: accuracy-issue-execute blanks this key and commits it (d32bba7 'clear in_the_middle_of'), and overwrote it mid-run as 'implementing #30' (c42f78b) — it did this DESPITE this key warning about it. Re-read and re-write this header after EVERY accuracy-issue-execute run. Its first #30 pass also returned ready_for_pr=false with a false AC7 falsification claim (2 of 4 tests 'failed' only on a module-level ImportError) — an ImportError is NOT a falsification; demand behavioural failure and MUTATION-TEST every new test yourself. STANDING RED GATE, not accuracy-caused, do NOT re-triage: impeccable-detect, playwright-e2e, ui-thresholds (BUILD/BLOCKERS.md:666). ENV: jq NOT installed (use gh --jq); pre-commit needs .venv/bin on PATH; verify signing with 'git cat-file commit <sha> | grep -c gpgsig', NEVER %G?.
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
