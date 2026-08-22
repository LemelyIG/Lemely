# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: none (all four queued branches pushed; nothing in flight)
last_run_label: none
last_run_headline: none
review_rate: 29.03% (9/31 leaves, union numerator, on the #33 branch; NOT yet merged)
ratchet: unarmed; 29.03% recorded as a non-blocking M0 breach (#33 branch, unmerged)
spend_usd: 0.4026
in_the_middle_of: NOTHING IN FLIGHT. STILL FULLY HALTED ON THE EXTERNAL BILLING BLOCKER, and there is still no independent work left. Do NOT start a fifth branch and do NOT start M1. GitHub Actions has been billing-blocked for LemelyIG since 2026-08-22T02:56Z (~17h); re-verified AGAIN this run — no workflow run after 32547620531, PR #78 still shows its jobs failing in 1-4s (state=OPEN mergeable=MERGEABLE, so the ONLY thing missing is green CI). A HUMAN MUST FIX Settings > Billing & plans. Already notified at high priority on the accuracy topic last run; do NOT re-notify every run, it is the same unchanged fact. Do NOT re-triage the block, re-run that workflow, or trim the CI matrix. QUEUE VERIFIED INTACT ON ORIGIN THIS RUN (I checked git ls-remote, not memory): feature/accuracy-77-...=03639fa9 (PR #78 OPEN, reviewed clean wf_d2272bef-33f), feature/accuracy-30-paired-statistics-mcnemar-wilson=3f569ee0, feature/accuracy-33-review-rate-as-a-two-part-ratchet-ci=693d76ec, feature/accuracy-29-honest-denominators-fix-d18-exclusion=79fd9934 (reviewed merge-with-fixes wf_25da8352-2ee, its one should-fix APPLIED). Nothing has merged into origin/develop since the block began — its tip is still 5815b94 (#76). All four items need ONLY accuracy-pr-land. EXACT ORDER WHEN BILLING IS FIXED: (1) 'gh pr checks 78'; if green 'gh pr merge 78 --squash --delete-branch' then 'accuracy_board.py done 77'; (2) accuracy-pr-land {issue:30, branch:'feature/accuracy-30-paired-statistics-mcnemar-wilson', base:'develop'}; (3) same for #33; (4) same for #29; (5) THEN #27 (M0.3 A/A floor) unblocks and MUST use '--cache-mode bypass', never 'refresh' (lemely/io/gemini.py:350-356 and :425 — bypass skips the cache read AND the write; refresh writes and would overwrite the shared cache on all ~10 repeats). REBASE HAZARD: #30/#33/#29 were all cut from origin/develop; #30 and #33 both touch lemely/eval/analyses.py, #29 touches lemely/accuracy/harness.py. Rebase and RE-GATE whichever lands later; never merge blind. MANDATORY AFTER #29 AND #33 BOTH LAND: #29 puts abstain/unmatched INTO the mark_accuracy denominator, invalidating #33's recorded baseline — recompute ALL THREE of BUILD/review-rate-baseline.json, lemely/runtime/config.py review_rate_last_merged=0.2903, and DA-M0.9. Posted on both issues. TWO OTHER OPEN PRs EXIST AND ARE NOT OURS — DO NOT TOUCH, DO NOT MERGE, DO NOT COUNT THEM AS QUEUE ITEMS: #63 'feat(ci): staging/production CI/CD' and #64 'remove required files from .gitignore', both by Xart3mis and both based on MAIN. Merging to main is human-only (section 12.3). Note #64 would change .gitignore, which is worth a human's attention because tests/golden/results/*.json is currently gitignored and that is exactly why BUILD/review-rate-baseline.json has to exist as a committed summary — but it is still not ours to act on. WHY #28 (M0.4, the 2x2 ablation) STAYS UNSTARTED, checked independently this run rather than assumed: its three listed blockers (#56, #25, #32) are ALL Done, so it reads as eligible on the issue — but it is a LIVE measurement item, and #77 is precisely the defect that no entrypoint can set cache_mode, so a sweep run today would measure the cache and publish a meaningless 2x2. It is also Backlog not Ready (a human moves items to Ready), and the A/A churn floor (#27) must precede it or the four cells have no noise floor to be read against. Substantively blocked behind the SAME merge queue; do not start it. WHY M1 STAYS UNSTARTED: #37, #38, #40, #41, #58 list no dependencies and look eligible, but section 3.2 orders M0 before M1 and M0 is not done; #37 (emit UNMATCHED with id provenance) COLLIDES DIRECTLY with the unmatched/excluded semantics #29 rewrote in harness.py; and decisively, M1 items CHANGE MARKING BEHAVIOUR while M1's acceptance is non-regression at alpha=0.05, which needs #30's paired stats and #29's honest baseline MERGED and ideally #27's A/A floor RUN. Changing marking with no way to measure the effect is the failure this programme exists to prevent. #36 is blocked by #33; #39's blocker #32 is merged. SWEEP COVERAGE IS COMPLETE FOR EVERY QUEUED BRANCH, each with pytest ABSENT from failures: 3f569ee (#30's tip), 693d76e (#33's tip), 4cd5099 and now 1530b5d (#29's tip, including the halt commit). The 3 recurring failures (impeccable-detect, playwright-e2e, ui-thresholds) are the STANDING RED GATE, not accuracy-caused, do NOT re-triage; the lighthouse routes rotate between sweeps (student-correct 76-79, student-profile 54-58, occasionally student-landing/placement-test), consistent with noise around the 80 floor. WHERE THE BILLING ESCALATION LIVES: BUILD/BLOCKERS.md's billing section exists ONLY on the #77 branch (808 lines there vs 728 on origin/develop) — it did not survive the branch cut. That is FINE and deliberate: #77 merges FIRST so develop inherits it then, and a duplicate append would only create a merge conflict. Do NOT 're-add' it. UNMEASURED SPEND, recorded not guessed: run-ef443fc2931e was live (cache_mode=read_write) but spend_usd is unchanged at 0.4026 and RunManifest carries NO cost field, so that run's cost is UNKNOWN. DA7 records this and proposes adding a per-run cost field. NO BUDGET SPENT in any of the last six runs. Precondition re-checked: origin/develop..origin/main = 0. Local develop is 1 ahead of origin/develop (2096e77, state bookkeeping only), unpushed. WORKFLOW HAZARD SEEN EIGHT TIMES, twice committing the damage and once leaving a trailing space that made pre-commit FAIL at a branch tip: accuracy-issue-execute blanks this key and titles the commit 'clear in_the_middle_of after #N landed' when #N has NOT landed. Re-read and re-write this header after EVERY workflow, then re-run pre-commit. Worth fixing at source, but that is supervisor/human tooling and outside an accuracy diff's scope, so it is escalated not changed. RE-RUN EVERY GATE YOURSELF; MUTATION-TEST EVERY NEW TEST INCLUDING YOUR OWN — two of mine were vacuous before I caught them, and an ImportError is NOT a falsification. STANDING RED GATE, do NOT re-triage: BUILD/BLOCKERS.md:666. ENV: jq NOT installed (use gh --jq); pre-commit needs .venv/bin on PATH; verify signing with 'git cat-file commit <sha> | grep -c gpgsig', NEVER %G?.
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
