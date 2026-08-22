# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-29-honest-denominators-fix-d18-exclusion
last_run_label: none
last_run_headline: none
review_rate: 29.03% (9/31 leaves, union numerator, on the #33 branch; NOT yet merged)
ratchet: unarmed; 29.03% recorded as a non-blocking M0 breach (#33 branch, unmerged)
spend_usd: 0.4026
in_the_middle_of: #29 (M0.5 honest denominators) is COMPLETE, REVIEWED AND LAND-READY on feature/accuracy-29-honest-denominators-fix-d18-exclusion, PUSHED, with NO PR because Actions is billing-blocked. DO NOT re-implement or re-review it. accuracy-review wf_25da8352-2ee returned recommendation=MERGE-WITH-FIXES with exactly ONE SHOULD-FIX, and I have FIXED IT — so #29 now needs only accuracy-pr-land once billing is fixed. ALL FOUR M0 CODE ITEMS ARE NOW DONE AND QUEUED; THERE IS NO REMAINING M0 WORK THAT CAN BE DONE WITHOUT MERGING. THE QUEUE, DO NOT REDO ANY OF IT: (a) #77 -> PR #78 OPEN, reviewed clean (wf_d2272bef-33f: merge, zero findings); (b) #30 (M0.6 paired stats) at 3f569ee, PUSHED, no PR; (c) #33 (M0.9 ratchet) at 693d76e, PUSHED, no PR; (d) #29 at the tip of its branch, PUSHED, no PR, reviewed merge-with-fixes and the fix applied. ORDER WHEN BILLING IS FIXED: (1) 'gh pr checks 78'; if green 'gh pr merge 78 --squash --delete-branch' then 'accuracy_board.py done 77'; (2) accuracy-pr-land {issue:30, branch:'feature/accuracy-30-paired-statistics-mcnemar-wilson', base:'develop'}; (3) same for #33; (4) same for #29; (5) THEN #27 (M0.3 A/A floor) is finally unblocked and MUST use '--cache-mode bypass', never 'refresh' (lemely/io/gemini.py:350-356 and :425 — bypass skips the cache read AND the write; refresh writes and would overwrite the shared cache on all ~10 repeats). REBASE HAZARD: #30/#33/#29 were ALL cut from origin/develop; #30 and #33 both touch lemely/eval/analyses.py, #29 touches lemely/accuracy/harness.py. Rebase and RE-GATE whichever lands later; never merge blind. MANDATORY AFTER #29 AND #33 BOTH LAND: #29 puts abstain/unmatched INTO the mark_accuracy denominator, which INVALIDATES #33's recorded baseline. Recompute ALL THREE of BUILD/review-rate-baseline.json, lemely/runtime/config.py review_rate_last_merged=0.2903, and DA-M0.9. Posted on both issues. THE SUPERVISOR SWEEP AT 2026-08-22T14:44 COVERED 7bf84c9, which was #29's tip AT THAT TIME, with pytest ABSENT from its failures — but I have committed the review fix SINCE, so the current tip is NEWER than the swept sha. Do NOT claim pytest green for the current tip; the next sweep will pick it up. The 3 sweep failures are the STANDING RED GATE, not accuracy-caused, do NOT re-triage. WHAT I VERIFIED MYSELF THIS RUN: the review's claim of 'no unreviewed dimension' is TRUE — I read the journal and all SIX dimension agents returned results (entries 2,4,6,8,10,12); the one agent error (parallel[1], StructuredOutput retry cap) was a per-finding SKEPTIC in the verify stage, not a dimension. Caveat recorded honestly: that means one finding lost a skeptic vote, so the review is clean but not perfectly complete. THE SHOULD-FIX WAS AGAINST MY OWN WORK and the reviewer was right: my comment claimed leaf '99' is 'never extracted' and was 'the case that drove extracted < matched', but with scan_path=None harness.py sets extracted_ids = set(case.ground_truth), so the fixture actually yields FunnelCounts(leaves=3, extracted=3, matched=2, marked=2) — extracted > matched. I had discovered those exact numbers myself when probing last run and still left the comment wrong. Corrected: the comment now states the real counts, explains oracle mode, and says plainly that this fixture does NOT reproduce the extracted < matched case, which is why the assertions are structural (exact stage list + 'extracted' absent) rather than monotonicity-only. Re-verified after the fix: 43/43 harness tests pass, pre-commit clean, mutation still bites ('extracted' unexpectedly found), and 'scripts/check.sh --fast tests/test_accuracy_harness.py' ran TO COMPLETION green. STILL OPEN ON #29, non-blocking, carry into the PR body: no test pins 'abstain' into the denominator (acceptance criterion 2 unverified); excluded rows hardcode id_match='unmatched'; the D18 regression test asserts only an inequality (pinning A=2/3 vs B=1/3 would be stronger); FunnelCounts is a SECOND funnel not unified with analyses.exclusion_funnel(), and 'funnel' is not serialised by save_result so 'extracted' is unrecoverable from saved runs; and no scan_path-backed fixture exercises extracted < matched. UNMEASURED SPEND, recorded not guessed: run-ef443fc2931e was live (cache_mode=read_write) but spend_usd is unchanged at 0.4026 and RunManifest carries NO cost field, so that run's cost is UNKNOWN. DA7 records this and proposes adding a per-run cost field. STILL HALTED: Actions is billing-blocked for LemelyIG — a human must fix Settings > Billing & plans. Re-verified THIS run: still no workflow run after 32547620531 (2026-08-22T02:56Z). Do NOT re-triage it, do NOT re-run that workflow, do NOT trim the CI matrix. IF BILLING IS STILL BLOCKED NEXT RUN there is genuinely nothing substantive left: #27/#28 need #77's cache_mode entrypoint ON DEVELOP plus real spend, and M1 depends on M0 closing. Say so plainly rather than manufacturing work or stacking a fifth branch. Precondition: origin/develop..origin/main = 0. Local develop is 1 ahead of origin/develop (2096e77, bookkeeping), unpushed. WORKFLOW HAZARD SEEN EIGHT TIMES: accuracy-issue-execute blanks this key and titles commits '#N landed' when nothing merged; once it left a trailing space that made pre-commit FAIL. Re-read and re-write this header after EVERY workflow, then re-run pre-commit. RE-RUN EVERY GATE YOURSELF; MUTATION-TEST EVERY NEW TEST INCLUDING YOUR OWN — two of mine were vacuous before I caught them. STANDING RED GATE, do NOT re-triage: BUILD/BLOCKERS.md:666. ENV: jq NOT installed (use gh --jq); pre-commit needs .venv/bin on PATH; verify signing with 'git cat-file commit <sha> | grep -c gpgsig', NEVER %G?.
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
