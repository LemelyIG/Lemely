# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-77-no-entrypoint-can-set-cache-mode-an-a-a
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: HALTED ON AN EXTERNAL BLOCKER — GITHUB ACTIONS IS BILLING-BLOCKED FOR THE LemelyIG ORG. NO feature -> develop PR CAN MERGE until a human fixes it: Settings > Billing & plans. Escalated in BUILD/BLOCKERS.md (section 'OPEN — 2026-08-22 — GitHub Actions is billing-blocked'), notified, and commented on the PR. THIS IS NOT AN ACCURACY FAILURE AND NOT A CODE FAILURE — do NOT re-triage it, do NOT re-run the workflow, do NOT trim the CI matrix to fit the billing constraint. PR #78 for #77 is OPEN, REVIEWED CLEAN (accuracy-review wf_d2272bef-33f: recommendation=merge, ZERO findings, ZERO unreviewed dimensions) and DELIBERATELY NOT MERGED. Board item #77 moved back to Backlog with the blocker logged. EVIDENCE I VERIFIED MYSELF, not from the workflow report: run 32547620531 has duration_ms=0 for ALL FIVE job_runs and total_ms=0 (zero compute allocated); all five jobs report steps=0 completing in 1-5s; the annotation on every job reads 'The job was not started because recent account payments have failed or your spending limit needs to be increased. Please check the Billing & plans section in your settings'; and it struck three Python versions AND the unrelated Node web job identically and instantly, which no dependency drift, version skew or stale cache can do. The triage also refuted the change-under-test by experiment: at PR head 03639fa in a clean detached worktree with fresh venv and fresh PRE_COMMIT_HOME, pre-commit run --all-files passed all 10 hooks. 'failing_job: pre-commit' is COLLATERAL — it is merely listed first. I CORRECTED ONE TRIAGE CLAIM: it cited run 32200705566 (2026-08-19) as a PRIOR billing block, but that run has 5 jobs WITH REAL STEP LISTS, so it actually executed and was a genuine failure of a different kind. This block is NEW. The six runs before it (all 2026-08-21) succeeded with real billable minutes, so the block began between 32541604166 (2026-08-22T00:50, success) and 32547620531 (2026-08-22T02:56, blocked). Do not describe this as recurring. UNMEASURABLE FROM HERE, recorded as an open question rather than guessed: whether the org's monthly consumption is also near its cap needs admin:org scope, which requires interactive human consent. WHY I DID NOT MERGE ANYWAY: section 7.1 requires CI green, and a billing block is not green. The supervisor's full-suite sweep at 2026-08-22T05:47 DID cover 372e483, which sits on top of #77's implementation commit 13d5107, with pytest ABSENT from its failures — so the code is genuinely verified — but merging on that basis would establish that CI is optional whenever it is inconvenient, which is exactly the kind of erosion this programme exists to prevent. If the human decides the supervisor sweep is sufficient warrant to merge #77 by hand, that is THEIR call to make explicitly, not mine to assume. WHEN BILLING IS FIXED, the path is short: poll 'gh pr checks 78'; if green, merge with 'gh pr merge 78 --squash --delete-branch', then 'accuracy_board.py done 77'. The review verdict is already clean and does NOT need re-running. Then #27 (M0.3 A/A churn floor) is finally unblocked. #27 MUST USE '--cache-mode bypass', NOT 'refresh' — settled at source (lemely/io/gemini.py:350-356 and :425): both skip the cache READ, but bypass also skips the WRITE and is documented as side-effect-free for churn measurement, whereas refresh WRITES and would overwrite the shared cache on all ~10 repeats, leaving the last run's responses behind for every later read_write caller. WHY #77 EXISTS AT ALL — the costed preflight for #27 found its acceptance criterion 1 unachievable: no entrypoint could set cache_mode (measure_accuracy_cmd built GeminiClient(settings) with no flag; web/deps.py and scripts/run_real_paper_accuracy.py the same; no settings field, no env var; the ONLY 'default_cache_mode=' call site in the repo was a unit test). Running #27 anyway would have replayed cached responses on every repeat and published an A/A churn floor of EXACTLY 0.0 — a flattering number that makes every later A/B delta read as 'above noise' regardless of size (the D18 shape section 2 exists to prevent), compounded by #73 recording manifest.cache_mode='read_write' truthfully while the report called it a bypass sweep. NO BUDGET WAS SPENT; spend_usd is unchanged at 0.4026. AFTER #27: #28 (M0.4 ablation, needs the same bypass for its 2x2), then #29 (M0.5). Measurement spends REAL MONEY via accuracy-measure's costed preflight, where 'not reportable, with reason' is a SUCCESSFUL outcome. THE FIRST MEASUREMENT MUST RECOMPUTE review_rate: 19.1% is on the PRE-#32 denominator (28 leaves); the corpus is now 11 case dirs / 71 rows / 31 distinct leaves (DA6b). Treat spend_usd 0.4026 as a LOWER BOUND — recorded under the stale _DEFAULT_PRICING table that understated spend 2-4x and ignored thinking tokens; M0.2 corrected it, so the series is NOT self-consistent across that boundary. OTHER WORK AVAILABLE IF THE HUMAN WANTS PROGRESS WITHOUT CI: #30 (M0.6 paired stats) and #33 (M0.9 ratchet) have NO in-edges — but note nothing can MERGE until billing is fixed, so any such work would stack up unmerged on branches. Blocked: #57/#59 wait on #44, #36 waits on #33. LOCAL develop diverges from origin/develop by one unpushed bookkeeping commit (2096e77, state-file only) — expected; 'git pull --ff-only' will refuse, so inspect 'git log --oneline origin/develop..develop' and reset when the local-only commits are stale bookkeeping. BRANCH-CUT TRAP, hit three times: 'start' does NOT create the branch, and cutting from origin/develop REVERTS this file to whatever rode in with the last squashed PR — re-check this header immediately after cutting any branch. WORKFLOW HAZARDS, all live: accuracy-issue-execute CLEARS this in_the_middle_of key when it checkpoints (twice, once despite an explicit prohibition), leaving a trailing space that trips pre-commit; an implementer once found its OWN agent process and refused as if it were a rival; workflows have reported false green repeatedly; two workflow-authored tests were vacuous. RE-RUN EVERY GATE YOURSELF and TRY TO MAKE EVERY NEW TEST FAIL. STANDING RED GATE, separate from this and also NOT accuracy-caused, do NOT re-triage: impeccable-detect, playwright-e2e, ui-thresholds, failing every sweep for ten sweeps, escalated at BUILD/BLOCKERS.md:666. ENV: jq NOT installed (use gh --jq); pre-commit needs .venv/bin on PATH; verify signing with 'git cat-file commit <sha> | grep -c gpgsig', NEVER %G?.
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
counted thinking tokens; M0.2 (#26) corrects the table. Treat the number as a
lower bound until then, and keep recording the ledger's figure here so the
series stays consistent with itself.

`review_rate` is the 19.1% baseline against the 10% budget. The M0.9 ratchet
(#33) is not built yet; once it lands, `ratchet` becomes the
`min(10%, last_merged_review_rate)` value CI enforces, seeded at 19.1% as a
recorded-but-non-blocking breach.
