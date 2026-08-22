# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: none (all four queued branches pushed; nothing in flight)
last_run_label: none
last_run_headline: none
review_rate: 29.03% (9/31 leaves, union numerator, on the #33 branch; NOT yet merged)
ratchet: unarmed; 29.03% recorded as a non-blocking M0 breach (#33 branch, unmerged)
spend_usd: 0.4026
in_the_middle_of: NOTHING IN FLIGHT. FULLY HALTED ON THE EXTERNAL BILLING BLOCKER — and this time there is genuinely no independent work left, which is a change from the last four runs. Do NOT start a fifth branch. GitHub Actions has been billing-blocked for LemelyIG since 2026-08-22T02:56Z (~13h as of this run); re-verified AGAIN this run that no workflow run exists after 32547620531 and 'gh pr checks 78' still shows all five jobs failing in 1-4s. A HUMAN MUST FIX Settings > Billing & plans. Notified on the accuracy topic at high priority. Do NOT re-triage the block, do NOT re-run that workflow, do NOT trim the CI matrix. FOUR FINISHED ITEMS ARE QUEUED, ALL PUSHED, NONE MERGED, NONE TO BE REDONE OR RE-REVIEWED: (a) #77 -> PR #78 OPEN, reviewed clean (wf_d2272bef-33f: merge, zero findings); (b) #30 (M0.6 paired stats) at 3f569ee; (c) #33 (M0.9 ratchet) at 693d76e; (d) #29 (M0.5 honest denominators) at 4cd5099, reviewed merge-with-fixes (wf_25da8352-2ee) with its ONE should-fix APPLIED. THE ONLY THING ANY OF THEM NEEDS IS accuracy-pr-land. EXACT ORDER WHEN BILLING IS FIXED: (1) 'gh pr checks 78'; if green 'gh pr merge 78 --squash --delete-branch' then 'accuracy_board.py done 77'; (2) accuracy-pr-land {issue:30, branch:'feature/accuracy-30-paired-statistics-mcnemar-wilson', base:'develop'}; (3) same for #33, branch feature/accuracy-33-review-rate-as-a-two-part-ratchet-ci; (4) same for #29, branch feature/accuracy-29-honest-denominators-fix-d18-exclusion; (5) THEN #27 (M0.3 A/A floor) unblocks and MUST use '--cache-mode bypass', never 'refresh' (lemely/io/gemini.py:350-356 and :425 — bypass skips the cache read AND the write; refresh writes and would overwrite the shared cache on all ~10 repeats). REBASE HAZARD: #30/#33/#29 were all cut from origin/develop; #30 and #33 both touch lemely/eval/analyses.py, #29 touches lemely/accuracy/harness.py. Rebase and RE-GATE whichever lands later; never merge blind. MANDATORY AFTER #29 AND #33 BOTH LAND: #29 puts abstain/unmatched INTO the mark_accuracy denominator, invalidating #33's recorded baseline — recompute ALL THREE of BUILD/review-rate-baseline.json, lemely/runtime/config.py review_rate_last_merged=0.2903, and DA-M0.9. Posted on both issues. WHY I DID NOT START M1 THIS RUN, and why the next run should not either until M0 lands: #37, #38, #40, #41 and #58 all show NO dependencies, so they look eligible, but (i) section 3.2 orders M0 before M1 and M0 is not done, (ii) #37 (emit UNMATCHED with id provenance) COLLIDES DIRECTLY with the unmatched/excluded semantics #29 just rewrote in harness.py, so building it on a develop lacking #29 means solving the same problem twice, and (iii) decisively, M1 items CHANGE MARKING BEHAVIOUR and M1's acceptance is non-regression at alpha=0.05, which needs #30's paired stats and #29's honest baseline MERGED and ideally #27's A/A floor RUN — changing marking with no ability to measure the effect is precisely the failure this programme exists to prevent. #36 is separately blocked by #33. #39 is blocked by #32 (merged, so that one is fine). SWEEP COVERAGE IS NOW COMPLETE FOR #29: the 2026-08-22T15:53 sweep covered EXACTLY 4cd5099, #29's current tip, with a clean tree and pytest ABSENT from its failures — so #29's backend is genuinely green on its own tip and the 'newer than the swept sha' caveat from last run is CLOSED. Earlier sweeps likewise covered 3f569ee (#30's tip) and 693d76e (#33's tip), both with pytest absent. The 3 recurring failures (impeccable-detect, playwright-e2e, ui-thresholds) are the STANDING RED GATE, not accuracy-caused, do NOT re-triage; the lighthouse routes rotate between sweeps (student-correct 76-79, student-profile 54-58, sometimes student-landing/placement-test), consistent with noise around the 80 floor. WHERE THE BILLING ESCALATION LIVES: BUILD/BLOCKERS.md's billing section exists ONLY on the #77 branch (808 lines there vs 728 on origin/develop) — it was written there and did NOT survive the branch cut. That is FINE and I deliberately did not duplicate it here: #77 merges FIRST, so develop gets it then, and a duplicate append would only create a merge conflict. Do not 'fix' this by re-adding it. UNMEASURED SPEND, recorded not guessed: run-ef443fc2931e was a live run (cache_mode=read_write) but spend_usd is unchanged at 0.4026 and RunManifest carries NO cost field, so that run's cost is UNKNOWN. DA7 records this and proposes adding a per-run cost field. NO BUDGET SPENT in any of the last five runs. Precondition re-checked: origin/develop..origin/main = 0. Local develop is 1 ahead of origin/develop (2096e77, state bookkeeping only), left unpushed. WORKFLOW HAZARD SEEN EIGHT TIMES, twice committing the damage and once leaving a trailing space that made pre-commit FAIL at a branch tip: accuracy-issue-execute blanks this key and titles the commit 'clear in_the_middle_of after #N landed' when #N has NOT landed. Re-read and re-write this header after EVERY workflow, then re-run pre-commit. This is worth fixing at source in the workflow definition, but that is supervisor/human tooling and outside an accuracy diff's scope, so it is escalated rather than changed here. RE-RUN EVERY GATE YOURSELF; MUTATION-TEST EVERY NEW TEST INCLUDING YOUR OWN — two of mine were vacuous before I caught them, and an ImportError is NOT a falsification. STANDING RED GATE, do NOT re-triage: BUILD/BLOCKERS.md:666. ENV: jq NOT installed (use gh --jq); pre-commit needs .venv/bin on PATH; verify signing with 'git cat-file commit <sha> | grep -c gpgsig', NEVER %G?.
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
