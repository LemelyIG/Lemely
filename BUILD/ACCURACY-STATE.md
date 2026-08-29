# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-29-f
worktree: /home/sico/Lemely-worktrees/accuracy
branch: none in flight — cut the next from origin/develop
last_run_label: gmp-injection-41-2026-08-29
last_run_headline: RUN 66 — #41's CODE HALF LANDED, ITS SWEEP COSTED AND NOT AUTHORISED. Zero spend. *** A13: the A-mark dependency comes from EACH PAPER'S OWN printed Generic Marking Principles, with strict M-then-A as FALLBACK ONLY. extract_gmp has always populated metadata.generic_marking_principles and correct_paper THREW IT AWAY. Now threaded through mark_question into the prompt. *** THE INJECTION NEEDED ONE MORE SENTENCE THAN THE OBVIOUS ONE: printing the principles is not enough, because the system prompt carried an UNCONDITIONAL 'do not award an A mark if its associated M mark was not earned' and a model reading both follows the general text. So they are injected WITH AN EXPLICIT PRECEDENCE STATEMENT and the hard-coded rule is now labelled FALLBACK ONLY. That is the difference between satisfying A13 and appearing to. *** INJECTED INTO THE USER PROMPT, NOT THE SYSTEM PROMPT, because the cache key is built from the user prompt (gemini.py:339) — two papers with different printed principles must not share a cached mark. A system-prompt injection would have been a silent cache-collision bug. *** VERSION 4 -> 5, which invalidates the whole cached golden corpus. Required, but it means EVERY subsequent marking run pays full price too, not just the sweep — recorded in the preflight so it is not discovered later. *** ON THE RECORD AGAINST MYSELF: my first version read ms.metadata... where the variable is . The  around ai.mark_question CAUGHT THE AttributeError, logged ai_marking_failed, AND AWARDED 0 TO EVERY QUESTION IN THE PAPER. No crash, no traceback — a paper that scored zero and a log line blaming the model. A CATCH THAT BROAD TURNS A PROGRAMMING ERROR INTO A PLAUSIBLE MARKING OUTCOME, and it is invisible because 'the AI failed to mark this question' genuinely happens. The tests caught it in seconds; a sweep would have cost 140 calls and read as a marking regression. NOT changed here — that is its own change with its own review — but anyone editing inside that try has the same trap waiting. *** BATCHING CONSTRAINT RE-CHECKED not assumed: #38 is provenance + an escalation flag, #39 was ruled parser-side and DA43 touched no prompt file. ONE VERSION bump is correct. If either later needs a prompt change it must be batched with a RE-RUN of this sweep. *** SWEEP PREFLIGHT: unit is ONE correction call per non-MCQ leaf; population 70 leaves per arm x 2 arms = 140 calls; 6 fixtures / 31 leaves have NO principles, which is exactly the population A13 requires covering. ~$0.18, ~$0.27 with headroom, against $1.629549 available. NOT AUTHORISED — needs an n=1 first-call check and a ledger bound, per DA26. DA44.
review_rate: RESTATED DISTRIBUTION-AWARE 2026-08-28 under C13 (#161, DA33). Published statistic is now an UPPER INTERVAL BOUND: review_rate_last_merged 0.2903 -> 0.4838 = the 95th percentile of the beta-binomial predictive for ONE new run (Jeffreys prior on the pooled 101/310 leaf-repeats of aa-floor-2026-08-23-a, 10 repeats x 31 leaves, cache_mode=bypass). Zero of the 10 observed repeats exceed it. PREDICTIVE, not a CI on the mean — the gate judges one run, and a CI narrows with n until it sits inside the spread unchanged code produces. CONSERVATIVE and not to be sold as tight: per-run counts are UNDER-dispersed vs binomial (sd 0.0415 vs 0.0842), so the bound is wider than the truth. *** 0.2903 was the MINIMUM of the ten, and truncated down, so ALL 10 of 10 unchanged repeats exceeded it — worse than DA9a's 7-in-10. *** THIS IS NOT A LOOSENING: the effective ceiling is min(0.10, last_merged) and is 0.10 before and after; TestC13RestatementDidNotLoosenTheGate pins it. *** The measured dev-split rate is unchanged at 29.03% (BUILD/review-rate-baseline.json); ablation-2026-08-24-a, 9/31 leaves, det 0/8, gemini 9/23=39.1%, per-paper p95 83.33%.
ratchet: STILL UNARMED, and #161 has now MEASURED why — it is NOT the statistic. Against the committed dev-split baseline ALL FOUR LIMBS FAIL: signal 0.2903 vs 0.08 (3.6x), total 0.2903 vs 0.10 (2.9x), p95 0.8333 vs 0.15 (5.6x), and the ratchet ceiling is min(0.10, last_merged) = 0.10. THREE of the four fail on ABSOLUTE targets that last_merged does not touch, and while the measured rate is above 10% the ratchet limb is PINNED by review_rate_total_target — NO value of last_merged can move it. #161's premise (that last_merged=0.2903 was the blocker) is FALSIFIED. *** ARMING NEEDS THE REVIEW RATE TO COME DOWN — M1 accuracy work — not a better statistic. DO NOT flip review_rate_ratchet_armed to finish the gate. DO NOT loosen the 0.08/0.10/0.15 targets to make arming comfortable (MISSION 14). The p95 limb missing by 5.6x is the honest measure of the distance. DA33, DA9a.
in_the_middle_of: NOTHING IN FLIGHT. The accuracy PR queue is EMPTY. EVERY REMAINING ITEM NEEDS THE HUMAN — either money or judgment. Cut the next branch from origin/develop; every accuracy PR appends to DECISIONS/JOURNAL and edits this header, so a branch cut before its predecessor squash-merges ALWAYS conflicts. Cherry-pick, never rebase; cherry-pick --continue does NOT re-sign (check: git cat-file commit HEAD | grep -c gpgsig). *** MERGED THIS SESSION: #167, #169 (#136), #171 (#161), #173 (C22-C25 + #166), #174 (#110+#112), #175 (C24), #176 (#110 phantoms), #177 (#95 re-probe), #178 (#39), #179 (figure fix), #180 (closeout), #181 (#41 code half). DA31-DA44. Spend $0.376981, ALL of it C22's authorised diagnosis. Ledger 6.370451, headroom $1.629549. *** DET PARSER, measured corpus-wide over 479 schemes: exact 289 -> 331; not exact 190 -> 148; overcount 845 -> 349 marks; leaves lost to id collapse 57 -> 25; schemes with dup ids 34 -> 15; phantom contentless leaves 58 -> 0. *** FIVE THINGS NEED YOU. (1) #41's SWEEP — $0.30 ledger-bounded, n=1 first-call check, preflight at BUILD/accuracy-runs/preflight-41-2026-08-29/. The CODE IS MERGED; only the before/after measurement is outstanding, and until it runs #41's bullet 4 is UNMET. (2) #166's FIX — not authorised; needs BOTH halves (set is_alternative on Gemini's alternative routes AND stop the empty {} objects in parts); one without the other moves the failure rate without closing the gap. C25 condition 1 says 'fixed or formally re-scoped' and that judgment is YOURS. (3) #52 — cases pulled and posted, H8 log stays empty until you rule. (4) H7's OVERLAP SHARE (DA40) — HAS A DEADLINE: it must change BEFORE #47 completes or the choice becomes visible to the sample it selects. (5) THE THREE UNARMED DETECTORS — escalate_on_defaulted_marks (#38, 44.4% of papers), escalate_on_duplicate_leaf_ids (#110, 15 schemes), escalate_on_primary_sum_breach (#39, 4 questions). All route to the same fallback DA35 measured failing ~50%, so DECIDE THEM TOGETHER. Plus #95's three options (DA42) — do NOT narrow it to the excerpted questions without a ruling. *** MISSION 13 CANNOT BE COMPLETED BY AN AGENT and this is structural, not a shortfall: it requires ~300 HUMAN-labelled leaves (#47), a FROZEN split (#49/#57), and a held-out measurement that follows both. Everything agent-ownable that could be measured without spending, has been. *** PR #159 (develop -> main) IS OPEN, body refreshed 2026-08-29 — DO NOT MERGE, MISSION 12.3 is human-only. *** ONE TRAP RECORDED IN DA44 FOR WHOEVER EDITS lemely/io/correction_ai.py: the broad 'except Exception' around ai.mark_question turns a PROGRAMMING error into 'ai_marking_failed' and awards 0 to every question in the paper — no crash, no traceback. A typo of mine did exactly that and only the tests caught it. *** LESSONS: MEASURE BEFORE IMPLEMENTING A GATE (#39 bullet 2 cannot fire; #38's could not stop firing; neither was visible from the code); re-run a feasibility probe before acting on its verdict; when the cheapest option is the one you want, that is the reason not to take it; widening a scope to unblock yourself is not an agent's call; when a fix removes a ONE-DIRECTIONAL error the metric it was inflating GETS WORSE first, so do not optimise it; read the fields the code already fills before spending to rediscover them; an ABORT IS NOT A PILOT; opposite-sign defects HIDE EACH OTHER; re-sum all four worktree ledgers every run.
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

## The `review_rate` figure in full (moved out of the header 2026-08-25)

The header key carries the number; the analysis behind it lives here. It was
moved because the supervisor pastes the header value **verbatim** into every
outbound notification's preamble, so a ~600-character paragraph there crowded
the actual alert payload out of every message the human receives. Nothing
in-repo parses this value: `lemely/eval/review_gate.py` takes
`last_merged_review_rate` as a function parameter sourced from
`BUILD/review-rate-baseline.json` and `lemely/runtime/config.py:168`, and the
header-shape fixture in `tests/test_accuracy_board_state.py:46` is
`"review_rate: 19.1%"`. **No measured value changed in this move.**

**29.03%**, single-repeat extract+mark, run `ablation-2026-08-24-a` — 9/31
leaves (det 0/8; gemini 9/23 = 39.1%). Per-paper p95 is 66.7% against a 15%
ceiling on only 5 papers, which is **UNDERPOWERED as a percentile**. It is
identical to `last_merged_review_rate` 29.03% (`BUILD/review-rate-baseline.json`,
`lemely/runtime/config.py:168`) because it is the same corpus under the same
computation.

**DA9a is still binding: do NOT arm the ratchet against 29.03%.** The A/A floor's
measured mean over 10 live repeats was **32.58%** (range 29.03–41.94%), so 29.03%
is the **bottom** of the observed range — arming `min(10%, last_merged)` against
it would gate on a figure that unchanged code exceeds 7 times in 10. Restate it
distribution-aware first (#161 — NOT #36, which is CLOSED and is M1.1 the confidence unit).

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
