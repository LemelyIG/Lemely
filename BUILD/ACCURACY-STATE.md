# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: none (all four queued branches pushed; nothing in flight)
last_run_label: none
last_run_headline: none
review_rate: 29.03% (9/31 leaves, union numerator, on the #33 branch; NOT yet merged)
ratchet: unarmed; 29.03% recorded as a non-blocking M0 breach (#33 branch, unmerged)
spend_usd: 0.4026
in_the_middle_of: NOTHING IN FLIGHT — FULLY HALTED ON THE EXTERNAL BILLING BLOCKER, and there is no independent work left. ONE HUMAN ACTION UNBLOCKS EVERYTHING: fix GitHub Settings > Billing & plans for LemelyIG. Actions has been billing-blocked since 2026-08-22T02:56Z, re-verified every run since — the latest run is STILL 32547620531 and its jobs have EMPTY steps arrays, i.e. they never provisioned a runner: billing, not a test failure, nothing in our code to fix. PR #78 is OPEN + MERGEABLE; green CI is the only thing missing. DO NOT: start a fifth branch; start M1; start #28; re-notify (already escalated at high priority, it is the same unchanged fact); re-triage the block; re-run that workflow; trim the CI matrix. QUEUE, verified on origin with git ls-remote and not from memory: #77=03639fa9 (PR #78, reviewed clean wf_d2272bef-33f), #30=3f569ee0, #33=693d76ec, #29=79fd9934 (reviewed merge-with-fixes wf_25da8352-2ee, its one should-fix APPLIED). origin/develop is still 5815b94; nothing has merged since the block began. All four need ONLY accuracy-pr-land. EXACT ORDER WHEN BILLING IS FIXED: (1) 'gh pr checks 78'; if green 'gh pr merge 78 --squash --delete-branch' then 'accuracy_board.py done 77'; (2) accuracy-pr-land {issue:30, branch:'feature/accuracy-30-paired-statistics-mcnemar-wilson', base:'develop'}; (3) same for #33; (4) same for #29; (5) THEN #27 (M0.3 A/A floor) unblocks and MUST use '--cache-mode bypass', NEVER 'refresh' — refresh writes and would overwrite the shared cache on all ~10 repeats, while bypass skips the cache read AND the write (verified in code end to end, Evidence log E2). REBASE: all four merge CLEANLY into develop today and there is NO production-code conflict; the ONLY textual conflicts are BUILD/ACCURACY-STATE.md (every pair, unavoidable) and BUILD/DECISIONS.md (#29x#30, #29x#33, #30x#33) — resolve those two by hand keeping BOTH sides' content. Re-check with merge-tree against the REAL develop tip immediately before EACH land, because develop moves and landings are squashes; and note merge-tree detects TEXTUAL overlap only and is BLIND to the semantic conflict that matters most — #29 puts abstain/unmatched INTO the mark_accuracy denominator, invalidating #33's recorded baseline WITHOUT touching a line #33 wrote. Rebase and RE-GATE whichever lands later; never merge blind. AFTER #29 AND #33 BOTH LAND, all three of BUILD/review-rate-baseline.json, lemely/runtime/config.py review_rate_last_merged=0.2903 and DA-M0.9 must be recomputed — but this CANNOT be done offline and is NOT a post-merge chore. It is a MEASUREMENT ITEM belonging AFTER #27, needing (a) #77 merged so the sweep can set --cache-mode, (b) explicit human SPEND authorisation, (c) #27's A/A churn floor run first so the new number has a noise floor. Re-deriving from the saved golden run would return the SAME 0.2903 out of the OLD denominator — a fake recompute, exactly the narrowed-denominator failure mode accuracy-reviewer exists to catch (Evidence log E1). DO NOT DO IT. Tell the human before spending. DO NOT PUSH the local halt/bookkeeping commits onto the #29 branch: its PR squashes from ORIGIN's tip, so this header's accumulated content will NOT reach develop when #29 lands — re-write it onto develop as its own chore commit after the queue drains (Evidence log E4). Pushing them instead would inject unrelated churn into a reviewed PR and invalidate the clean review. DO NOT TOUCH PRs #63/#64 (Xart3mis, based on MAIN, not ours; merging to main is human-only per section 12.3); #64 would change .gitignore, which matters because tests/golden/results/*.json is gitignored and that is exactly why BUILD/review-rate-baseline.json has to exist as a committed summary — still not ours to act on. DO NOT 're-add' the billing escalation to BUILD/BLOCKERS.md: it lives only on the #77 branch by design, develop inherits it when #77 merges first, and a duplicate append would only create a conflict. WHY M1 STAYS UNSTARTED: section 3.2 orders M0 before M1 and M0 is not done; #37 collides directly with the unmatched/excluded semantics #29 rewrote in harness.py; and M1 items CHANGE MARKING BEHAVIOUR while M1's acceptance is non-regression at alpha=0.05, which needs #30 and #29 MERGED and ideally #27 RUN — changing marking with no way to measure the effect is the failure this programme exists to prevent. #36 is blocked by #33; #39's blocker #32 is merged. WHY #28 STAYS UNSTARTED: its three blockers are all Done so it reads eligible, but it is a LIVE measurement, #77 is precisely the defect that no entrypoint can set cache_mode (so a sweep today would measure the cache and publish a meaningless 2x2), it is Backlog not Ready, and #27 must precede it. SPEND: 0.4026, unmoved for eight runs; run-ef443fc2931e was live (cache_mode=read_write) but RunManifest carries NO cost field so that run's cost is UNKNOWN (DA7 records this and proposes adding one). Golden-run artifacts are gitignored, untracked and single-copy, so 'git clean -xfd' would destroy the provenance of the committed baseline; copied with sha256sums to /home/sico/Lemely-accuracy-artifacts/, outside the worktree. STANDING RED GATE, do NOT re-triage: BUILD/BLOCKERS.md:666 — impeccable-detect, playwright-e2e, ui-thresholds, with pytest ABSENT from failures on every queued branch tip. Sweep coverage is complete for 3f569ee, 693d76e, 4cd5099, 1530b5d, f2e2c18 and 91ffe6d. Lighthouse is TWO phenomena and conflating them is a trap: student-correct/student-standings sit at 76-79 and rotate in and out of failure (noise), but student-profile is 54-58 EVERY sweep and never approaches 80 — a floor nudge or a re-run would silence the first two and do NOTHING for it, which needs a real performance fix (Evidence log E3). WORKFLOW HAZARD SEEN EIGHT TIMES: accuracy-issue-execute blanks this key and titles the commit 'clear in_the_middle_of after #N landed' when #N has NOT landed — twice committing the damage, once leaving a trailing space that made pre-commit FAIL at a branch tip. Re-read and re-write this header after EVERY workflow, then re-run pre-commit. RE-RUN EVERY GATE YOURSELF; MUTATION-TEST EVERY NEW TEST INCLUDING YOUR OWN (two of mine were vacuous before I caught them, and an ImportError is NOT a falsification). ENV: jq NOT installed (use gh --jq); pre-commit needs .venv/bin on PATH; verify signing with 'git cat-file commit <sha> | grep -c gpgsig', NEVER %G? — all four queued branches verified at 0 unsigned commits. Precondition re-checked: origin/develop..origin/main = 0; local develop is 1 ahead (2096e77, bookkeeping only), unpushed. PROOFS for E1-E4 are in the 'Evidence log' section in this file's body — read it before re-deriving any of them, and do not repeat the experiments they record.
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

## Evidence log — halt runs, 2026-08-22

Proofs behind the header's `E1`-`E4` references. These are **experiments that
were actually run**, not reasoning. Read this before re-deriving any of them;
repeating them costs a run and changes nothing.

**E1 — the #29 review_rate recompute cannot be done offline.** I opened the
exact artifact the committed baseline names as `source_run`
(`tests/golden/results/2026-08-22-f7be062.json`, untracked + gitignored but
still present locally). It holds 71 `eval_records` over 22 distinct
`question_id`s; `outcome` takes only `{correct:64, under:6, over:1}`, and
`id_match` is `exact` for all 71. There is **not one `abstain` and not one
`unmatched` record**, because the file predates #29's semantics. So
re-deriving `review_rate` from it returns the same 0.2903 — the old
denominator laundered through a new function. That is a fake recompute. The
real one needs a fresh live sweep; see the header for its three prerequisites.

**E2 — `--cache-mode bypass` is safe and sufficient; `refresh` is not.**
Verified in code end to end rather than trusted: #77 adds
`click.Choice(['read_write','bypass','refresh'])` wired to `default_cache_mode=`
on `GeminiClient` (`lemely/app/cli.py:1055`); `generate()` falls back to
`self.default_cache_mode` when the call site passes nothing
(`lemely/io/gemini.py:316-319`); **no production call site passes an explicit
`cache_mode`**, so nothing silently overrides the flag — the lone `cache_mode=`
in `lemely/accuracy/harness.py:486` only *reads* it off the client to stamp
`RunManifest` (#73's work). `bypass` then skips the cache read
(`gemini.py:357`, guard is `cache_mode == 'read_write'`) **and** the write
(`gemini.py:425`, guard is `cache_mode in ('read_write','refresh')`). So a
bypass sweep is genuinely side-effect-free on the shared cache, while `refresh`
would overwrite it on every one of #27's ~10 repeats.

**E3 — the lighthouse failures are two phenomena, not one.** Grounded by
opening `reports/.scratch/lighthouse/*.json` directly instead of trusting the
sweep's summary text; they matched it exactly (56 / 79 / 78).
`student-correct` and `student-standings` sit at 76-79, within a point or two
of the §11 floor, and rotate in and out of failure between sweeps — that is
noise. `student-profile` does not: 56, 57, 58, 57 in the four sweeps directly
observed and 54-58 across the earlier record, i.e. never once near 80. It is a
stable ~24pp deficit that will fail every future sweep. The two-phenomena model
then made a prediction and it held: the 2026-08-22T22:34 sweep brought a
*previously unseen* route into the noisy band (`student-study-plan-session`,
77) while `student-profile` stayed put at 57. Membership of the noisy set is
not fixed — expect further new names at 76-79 — and that churn is the
signature of routes sitting on the floor, not of a regression. Whoever owns this
should know a floor nudge or a re-run silences the first two and does nothing
for the third. Still not ours; recorded so it is not misdiagnosed as flakiness.

**E4 — signing is clean, and a bookkeeping-loss hazard exists.** Walked every
commit in `develop..<branch>` for all four queued branches with
`git cat-file commit <sha> | grep -c gpgsig` (never `%G?`): 0 unsigned out of
3 (#77), 7 (#30), 8 (#33) and 11 (#29). No signing surprise waits at land time.
Separately: this worktree's HEAD runs ahead of origin's #29 tip by the halt-run
chore commits, all signed, all touching only the `in_the_middle_of` line. #29's
PR squashes from **origin's** tip, so everything those commits recorded will
not reach develop when #29 lands. The fix is *not* to push them onto the
reviewed branch — it is to re-write the surviving content onto develop as its
own chore commit once the queue drains.

**Merge-conflict matrix** (measured with `git merge-tree`, all four branches ×
every pair, read-only): all four merge cleanly into develop; no production-code
conflict anywhere — `lemely/eval/analyses.py` (#30 × #33),
`lemely/accuracy/harness.py` (#29) and `lemely/app/cli.py` (#77 × #33) all
auto-merge. The earlier "both touch analyses.py" worry does not materialise
textually. Only `BUILD/ACCURACY-STATE.md` and `BUILD/DECISIONS.md` conflict.
Caveats are in the header: it is a pairwise proxy for squash-onto-moving-develop,
and it is blind to the #29/#33 semantic conflict.

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
