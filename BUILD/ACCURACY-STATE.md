# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-24-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-45-failure-reason-census-over-the-failing
last_run_label: ablation-2026-08-24-a
last_run_headline: NOT REPORTABLE as an ablation: the oracle+mark arm produced zero records (blocked on open #28 — measure_accuracy() picks the arm from case.scan_path and all 11 golden cases ship scan.pdf, so the oracle branch is dead code), so there is no A/B delta to test against the published 11.61% A/A floor and same_denominator_both_arms=false. What the run does support, descriptively and single-arm only: extract+mark leaf accuracy 77.4% (24/31 distinct leaves, Wilson 95% CI [60.2%, 88.6%]; det 8/8=100% CI [67.6%,100%] UNDERPOWERED, gemini 16/23=69.6% CI [49.1%,84.4%]), cache genuinely bypassed (0 hits), abstain/unmatched/under kept in the denominator, 0 excluded. Reportable finding in its own right: a real review-budget ratchet breach — review_rate_signal = review_rate_total = 29.03% (9/31 leaves; det 0/8, gemini 9/23=39.1%) against the 8%/10% ceilings, and per-paper p95 66.7% against 15% on only 5 papers (UNDERPOWERED as a percentile). It does NOT show that extraction helps or hurts marking, does NOT establish any delta, and n=31 is far below the MCNEMAR_IMPROVEMENT_N_FLOOR of 219 leaf-pairs. Note: the harness manifest's own mark_accuracy=0.9014 is over 71 pre-collapse rows and must not be cited as the leaf-level figure. *** CORRECTION 2026-08-25: the parenthetical above describes why THAT run failed and is accurate for it, but its blocker framing is now STALE TWICE OVER -- #28 is CLOSED, and the forcing mechanism it says is missing LANDED IN PR #87 (merged 2026-08-24T03:31Z, on develop): harness.py:705-710 makes `arm` override scan_path uniformly and cli.py:1013-1025 exposes --arm. No measured value in this headline is altered. The 2x2 STILL DOES NOT EXIST and M0.4 is closed with every acceptance box unticked; see BLOCKERS '#28' RESOLVED note and the 2026-08-25 comment on #28 for the (a)/(b)/(c) ruling that is required before any re-run.
review_rate: 29.03% single-repeat extract+mark, ablation-2026-08-24-a (9/31 leaves; det 0/8, gemini 9/23=39.1%; per-paper p95 66.7% on n=5 papers, UNDERPOWERED). Identical to last_merged_review_rate 29.03% (BUILD/review-rate-baseline.json, lemely/runtime/config.py:168) — same corpus, same computation. DA9a still binding: the aa-floor MEASURED MEAN over 10 live repeats was 32.58% (range 29.03-41.94%), so 29.03% is the BOTTOM of the range and arming min(10%, last_merged) against it gates on a figure unchanged code exceeds 7 times in 10 (#36).
ratchet: unarmed; ratchet constant remains 29.03% (config.py:168) and the M0 breach stays recorded-not-blocking. DO NOT arm against 29.03% — see review_rate above and DA9a: restate it distribution-aware first (#36).
spend_usd: 1.488057
in_the_middle_of: RUN 13 WITH NO HUMAN INPUT (14th consecutive). Inbox: no unchecked items. Board `next`: NOTHING READY. Tree clean; nothing in the background; supervisor sweep PASSED over f00dfb2 (my previous tip) so that commit IS gate-verified green -- it does NOT cover this run's commit. *** THIS RUN'S FINDING: THE #28 BLOCKER WAS STALE AND NOBODY NOTICED FOR A DAY. BLOCKERS said #28 was "Blocked on IMPLEMENTATION REQUIRED FIRST -- the oracle+mark arm is dead code -- do NOT re-run the sweep until a mechanism exists to force oracle+mark over cases that already have a scan_path". Verified at source that PR #87 (MERGED 2026-08-24T03:31Z, on develop, in this branch's history) supplies exactly that mechanism: harness.py:626 takes `arm`; harness.py:705-710 sets case_arm = arm UNIFORMLY, overriding the scan_path auto-selection, so the oracle bypass at :733 IS reachable; harness.py:678-684 raises up front if arm=extract+mark and any case lacks a scan_path (no silent fallback); cli.py:1013-1025 exposes --arm wired to measure_accuracy(arm=) at :1081. TESTED, not merely present: tests/test_accuracy_harness.py:313 and :352 test_both_arms_over_same_cases_produce_ablation_2x2_nonzero. The blocker's own release condition IS MET. BLOCKERS now carries a RESOLVED note; last_run_headline carries a CORRECTION suffix (no measured value altered). *** BUT DO NOT READ THAT AS "M0.4 IS DONE": #28 is CLOSED WITH EVERY ACCEPTANCE BOX UNTICKED, and the only ablation ever run (ablation-2026-08-24-a) is published NOT REPORTABLE -- zero oracle+mark records, no delta, same_denominator_both_arms=false. The issue was closed on PR #87, i.e. on the MECHANISM; M0.4's deliverable is the 2x2 ITSELF, which HAS NEVER BEEN PRODUCED. *** THE NEW ASK (#9), POSTED ON #28 AS (a)/(b)/(c): DOES A SPEND AUTHORISATION GRANTED WHILE AN ISSUE WAS OPEN SURVIVE THAT ISSUE BEING CLOSED? The 2026-08-24T01:14:03 directive authorised #28's sweep specifically (no per-item cap, costed preflight before spend, --cache-mode bypass NEVER refresh per E2, stop-and-ask at USD 20.00 of 25.00) and it is UNSPENT -- the ~USD 0.06 of ablation-2026-08-24-a went on the broken single-arm run. (a) authorisation stands: reopen #28 or open an M0.4-completion issue, run the two-arm ablation, publish the 2x2. (b) it lapsed with the close: M0.4 accepted complete-by-mechanism and the acceptance boxes + NOT REPORTABLE headline FORMALLY RETIRED as unmet in #40 bullet-4 style, NEVER silently ticked. (c) defer to a milestone close. RECOMMEND (a); NOT ACTED ON, because choosing the reading that unlocks spending is exactly the #27 rebuke. NOTE FOR THE NEXT RUN: re-running is NOT MISSION 12.9 significance-chasing -- that run was not underpowered, one arm of a two-arm experiment did not execute at all, so a re-run is the FIRST correct execution; no larger n is proposed; and the blocker text itself says "do NOT re-run UNTIL a mechanism exists". BOARD ITEM DELIBERATELY NOT FORCE-MOVED: it sits in Backlog while the issue is CLOSED (M0 shows 1 Backlog / 10 Done though all 11 M0 issues are CLOSED); which column is right depends on the ruling. *** THE ASKS NOW STAND AT NINE, ALL PURE DECISIONS: (1) #58 bullet 4 -- authorise ~USD 0.144 or RETIRE as #40's was; the ONLY thing between PR #90 (OPEN, MERGEABLE) and merge. (2) #88 q2 profiles.py:50. (3) #88 q1/q3 (H4/#49). (4) #45's 3-option design question. (5) #37 -- gate-9 sweep or explicit waiver. (6) #38 -- (a) land on the deterministic proof waiving a provably-blind gate 9, (b) regenerate golden mark_scheme.json through the det parser (MISSION 12.2/12.5, breaks comparability with every published figure), or (c) block until (b). (7) #38 bullet 2 needs RE-STATING -- measured harmful on 56% of affected papers (78 over-sum vs 75 under-sum + 24 exact/672 pts). (8) #39 bullet 4 NOT IMPLEMENTABLE as written -- is_excerpt landed only on harness.py:75, not on MarkSchemeMetadata; bullets 2 and 4 in direct tension. (9) #28 above. ALSO STANDING: #41 bullet 2 is a MISSION 12.7 human call on CAIE marking principles. *** EIGHT COMMITS UNPUSHED: origin/feature/accuracy-45-... at 8847f59; local ahead by 20908e1/377cb5f/5060a94/76f01a0/c617489/a253231/f00dfb2 + this one. Disk-only; not pushed per CLAUDE.md. *** NO SPEND THIS RUN; ledger unmoved at 1.488057.
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

**E5 — halt runs must now go QUIESCENT: make NO commit while the block holds.**
This is the rule, not a suggestion, and this entry is the last halt commit that
should exist until billing is fixed.

The record: ten consecutive runs each found the identical external block and
each answered it with a bookkeeping commit to `BUILD/ACCURACY-STATE.md`. Every
one of those commits is on the **#29 branch**, and E4 already established that
#29's PR squashes from **origin's** tip — so none of them reaches `develop`.
They are not saved work; they are additions to the pile that E4 schedules for a
hand-re-write onto develop once the queue drains. Each new one makes that
re-write bigger and buys nothing.

The two verdicts on 2026-08-23 (00:00:16 over `e3fdf3c`, 00:43:19 over
`0aa8438`, 39m each, 43m apart) show the supervisor sweeping back-to-back and
continuously. So a halt commit does **not** cost extra sweep time — that was
checked and is not the argument. The cost is churn and re-write debt only, and
the benefit of restating an unchanged fact is zero.

**What a halt run does instead:** re-read the inbox; re-verify the block from
the API (`gh api 'repos/LemelyIG/Lemely/actions/runs?per_page=3'`, then
`gh api 'repos/LemelyIG/Lemely/actions/runs/<id>/jobs'` — **only** jobs with
non-zero `steps` mean it is FIXED); re-read the queue with `git ls-remote`;
then **report in prose and stop with a clean tree.**

The "newer run id" half of that test was **falsified on 2026-08-23**: runs
`32631458524` (09:36Z), `32631767807` (09:42Z) and `32632548137` (10:00Z) are
all newer than `32547620531`, and every job in them still returned
`conclusion=failure` with `steps=0` in 2-4s. A newer run id proves only that
the queue accepted a trigger, not that a runner was provisioned. Use the
`steps` count and nothing else. No commit, no `state set`, no notify. The header is already
correct and complete; leaving it untouched is the accurate signal that nothing
happened. Resume committing the moment there is real work — i.e. the moment
billing is fixed and the five-step landing order in the header begins.

**Merge-conflict matrix** (measured with `git merge-tree`, all four branches ×
every pair, read-only): all four merge cleanly into develop; no production-code
conflict anywhere — `lemely/eval/analyses.py` (#30 × #33),
`lemely/accuracy/harness.py` (#29) and `lemely/app/cli.py` (#77 × #33) all
auto-merge. The earlier "both touch analyses.py" worry does not materialise
textually. Only `BUILD/ACCURACY-STATE.md` and `BUILD/DECISIONS.md` conflict.
Caveats are in the header: it is a pairwise proxy for squash-onto-moving-develop,
and it is blind to the #29/#33 semantic conflict.

## Current state (rewritten 2026-08-23, replacing the 2026-08-18 seed)

No live workflow runs. The four "Live workflow run" sections that stood here
for #72 and #73 were **deleted on 2026-08-23**: both issues are CLOSED and both
PRs merged (**#75** for #73 on 2026-08-21T23:20Z, **#76** for #72 on
2026-08-22T01:11Z). They had become actionable-but-wrong — each still told the
reader to "go straight to `accuracy-pr-land {issue:73…}`" for work that had
already landed. If a future run needs those transcripts they are still on disk
under `…/subagents/workflows/`; nothing about them belongs in the resume
pointer. **Do not re-add a workflow-run section unless the run is actually in
flight, and delete it the moment it is not.**

Everything the queue, the halt and the prohibitions require is in the
`in_the_middle_of` header line; the proofs are in the Evidence log above. This
section carries only what neither of those does:

## Landing run for #77 (added 2026-08-22)

`accuracy-pr-land` for **#77** is running as **`wf_f4d77849-0bd`** (transcript
under `…/subagents/workflows/wf_f4d77849-0bd/journal.jsonl`), base `develop`.

**Before launching anything for #77, run
`gh pr list --head feature/accuracy-77-no-entrypoint-can-set-cache-mode-an-a-a`
— do not open a second PR.** If its CI watch times out (4 of its first 5 uses
did), that is neither pass nor fail: poll `gh pr checks <pr>` and merge by hand
with `--squash`. Merge feature → `develop` only, never `main`.

`accuracy-review` `wf_d2272bef-33f` returned **`merge`**, zero findings, zero
unreviewed dimensions — and independently proved the two new tests fail on
de-wired code in detached worktrees (`KeyError: 'default_cache_mode'`,
`RunManifest cache_mode=None`), which answers the circularity worry about
patching `GeminiClient` with a MagicMock. Only CI green remains.

**After #77 merges, #27 (M0.3) can finally run** — with `--cache-mode bypass`.
It spends real money: use `accuracy-measure`'s costed preflight, and remember
"not reportable, with reason" is a successful outcome.

### Superseded — the #77 review run

## Review run for #77 (added 2026-08-22)

`accuracy-review` for **#77** is running as **`wf_d2272bef-33f`** (transcript
under `…/subagents/workflows/wf_d2272bef-33f/journal.jsonl`), over
`head=feature/accuracy-77-no-entrypoint-can-set-cache-mode-an-a-a`,
`base=origin/develop`, tip `372e483`. It only reads the diff, so it cannot
collide with the worktree. On a clean verdict go to `accuracy-pr-land`.

### Settled while it ran: #27 must use `--cache-mode bypass`, not `refresh`

Read at source in `lemely/io/gemini.py:350-356` and `:425`:

- `bypass` — skips the cache **read** and also skips the **write**, so the run
  is "fully side-effect-free with respect to the shared cache". The source
  comment names churn measurement as its purpose.
- `refresh` — skips the read but **does** write, overwriting the entry.

So the A/A floor (#27) uses **`bypass`**. `refresh` would give equally
independent API calls but would rewrite the shared cache on all ~10 repeats,
leaving the last run's responses behind for every later `read_write` caller —
a measurement silently mutating the thing later runs read.

## Current state (seeded 2026-08-18)

Nothing has been started. Five tracker issues are closed, all by the human or
with human verification: #34 (H1), #42 (M1.7), #48 (H2), #50 (H5), #60 (H10).
The board's Ready set is #56, #25, #26, #31, #32 — all M0 — and
`python scripts/accuracy_board.py next` currently selects #56 (M0.0, the
fixture-renderer repair).

`spend_usd` is what the ledger recorded (0.4026) under the stale
`_DEFAULT_PRICING` table, which understates real spend by 2-4x and never
counted thinking tokens; M0.2 (#26) corrects the table. Treat it as a **lower
bound**, and keep recording the ledger's own figure here so the series stays
consistent with itself rather than mixing two pricing bases.

`review_rate` is 29.03% (9/31, union numerator) measured on the **unmerged**
#33 branch, against a 10% budget. The M0.9 ratchet becomes
`min(10%, last_merged_review_rate)` once #33 lands. The header explains why
this number cannot honestly be recomputed offline once #29 lands (E1) — it is a
measurement item, not a bookkeeping chore.

Five tracker issues are closed by the human or with human verification: #34
(H1), #42 (M1.7), #48 (H2), #50 (H5), #60 (H10). Live board state is GitHub's
job, not this file's — read it with `scripts/accuracy_board.py`.
