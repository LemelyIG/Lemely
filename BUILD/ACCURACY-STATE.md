# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: none
last_run_label: aa-floor-2026-08-23-a
last_run_headline: A/A churn floor candidate (M0.3/#27): 11.6% of leaf outcomes flip between two identical-config repeats (162/1395 pair-leaf comparisons over C(10,2)=45 pairs; per-pair range 0.0-19.4%); 9 of 31 distinct leaves ever churned, Wilson [16.1%, 46.6%]. All churn is gemini-path (15.7%, 162/1035); det path is exactly 0.0 (0/360). Pooled leaf accuracy 75.8% (235/310 leaf-repeats), 0 excluded, 0 abstentions. Does NOT show any A/B effect: single-arm, cache bypassed, n=31 leaves vs the 219-leaf McNemar floor, split=dev (pre-M0.7a). Separately reportable: review_rate_total 32.6% (per-repeat 29.0-41.9%) and per-paper p95 82.1% breach the min(10%, 29.03%) ceiling and 15% p95 target in every repeat (ratchet unarmed at M0).
review_rate: 32.58% MEASURED MEAN of 10 live repeats (aa-floor-2026-08-23-a, range 29.03-41.94%, n=31, post-#29) — NOT THE RATCHET CONSTANT. last_merged_review_rate is still 29.03% (BUILD/review-rate-baseline.json, lemely/runtime/config.py:168) and 29.03% is the BOTTOM of the measured range, so arming min(10%, last_merged) against it gates on a figure unchanged code exceeds 7 times in 10 (DA9a; binding on #36).
ratchet: unarmed; ratchet constant remains 29.03% (config.py:168) and the M0 breach stays recorded-not-blocking. DO NOT arm against 29.03% — see review_rate above and DA9a: restate it distribution-aware first (#36).
spend_usd: 1.425511
in_the_middle_of: NOTHING IN FLIGHT — HALTED. Every open item now waits on a HUMAN DECISION; there is no agent-startable work left that does not need one. *** #44 (M2.1) IS DONE AND MERGED — PR #84 squashed to develop 5f7cde7 on genuinely green CI (all 5 jobs, run 32663320054), issue CLOSED/COMPLETED, board M2 Done=1. Corpus 648 -> 1488 docs, 1 permanent failure ('Motion 5 QP.pdf', null-filled upstream, pmt has no failover, survived a retry — NEVER 'fix' it with --no-verify). Committed artifact BUILD/corpus/corpus-manifest-2026-08-23.json + scripts/build_corpus_manifest.py (read-only). DO NOT RE-FETCH and do NOT run even a --dry-run: a dry-run writes 'pending' rows and corrupts the counts the manifest pins. *** #57 (M0.7b) IS BLOCKED AND I DID NOT START IT — BLOCKERS.md section E. #44 delivered 1488 PDFs but ZERO parsed mark schemes (find /home/sico/PaperScraper/papers -name '*.json' minus the catalogue = 0). #57's strata need syllabus code x parse path x TARIFF BAND, all properties of a PARSED scheme; a PDF supplies none. Available: 11 tests/golden mark_scheme.json = 71 leaves, against a ~300-leaf target (10/60/30 = 30/180/90). I deliberately did NOT freeze over the 71: the constraints do say splits may land under target, but they ALSO say amendments are drop-only and membership is FROZEN, so freezing over 71 while 1488 unparsed papers sit on disk is IRREVERSIBLE BY RULE and would permanently cap the labelling corpus at a quarter of its intended size. The drop-only rule exists to stop backfilling AFTER a principled freeze, not to license freezing early and booking the gap as a shortfall. THE UNLISTED PREREQUISITE between #44 and #57: parse the restored corpus into structured schemes — det handles MCQ free, THEORY NEEDS GEMINI = SPEND = unauthorised. Unblock via (A) authorise a costed parsing pass to ~300 leaves, (B) rule that #57 may freeze over a smaller corpus with the n accepted as permanent, or (C) scope parsing as its own issue (likely overlaps #45/M2.2, which also needs parsed schemes). *** #59 (M2.5) is a MEASUREMENT ('measure the synthetic-to-real transfer gap') so it needs a sweep = authorisation; not started. *** #36 and #40 STILL PARKED on unanswered human decisions — BLOCKERS.md sections B and C. #40's PR #83 is OPEN, green, complete at 1022036 with a DO-NOT-MERGE comment; #36's branch is complete at 2cae804 with no PR. Local branches feature/accuracy-36-... and feature/accuracy-40-... are INTACT — verified this run. Do not restart either from scratch. #28 (M0.4) STILL NOT AUTHORISED, not even its costed preflight. BLOCKERS.md section D: every remaining M1 item needs a measurement number to merge under MISSION 9 gate 9, so M1 is gated on authorisation, not engineering. *** SO THE HUMAN HAS FIVE OPEN DECISIONS: #36 bullets 1/2/7 conflict (B), #40 unmeasured review-rate rise (C), M1 measurement gating (D), #57 parsing spend (E), and #28 ablation spend. Authorising measurement/parsing spend is the single thing that would unblock the most. *** GIT HAZARD HIT AND FIXED THIS RUN: BLOCKERS.md section C had been written while on the UNMERGED #40 branch, so it never reached develop even though B and D did, leaving D's cross-reference to 'section C' dangling. Recovered by extracting it from the branch and re-inserting it in order. RULE: write BUILD/ docs on DEVELOP, never on a feature branch that may not merge (E4 again). Local develop was reset to origin/develop after the squash — verified first that the only differences were the 4 #44 files (gained) and one stale state line. *** ENV/TOOL TRAPS unchanged: pre-commit not on PATH, use 'PATH=$PWD/.venv/bin:$PATH .venv/bin/pre-commit run --all-files', always --all-files. 'accuracy_board.py block' WRITES TO BLOCKERS.md as a side effect and dirties the tree mid-checkout. 'git cherry-pick' has NO -q flag. 'git rebase' silently drops signatures — check 'git cat-file commit HEAD | grep -c gpgsig', never 'git log --show-signature'. accuracy-pr-land needs a DURABLE review verdict passed in its args; CI matrix jobs run SERIALLY ~10-16 min each so a short watch window times out legitimately, and TIMEOUT is UNKNOWN, never a pass. 'accuracy_board.py done' can exit 1 harmlessly when the squash already auto-closed the issue — exit 2 is the H-issue refusal, exit 1 here is not.
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
