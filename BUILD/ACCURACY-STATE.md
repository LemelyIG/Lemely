# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-77-no-entrypoint-can-set-cache-mode-an-a-a
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #77 IMPLEMENTED at 13d5107 on feature/accuracy-77-no-entrypoint-can-set-cache-mode-an-a-a. NOT reviewed, NO PR open. NEXT: accuracy-review {issue:77, head:'feature/accuracy-77-no-entrypoint-can-set-cache-mode-an-a-a', base:'origin/develop'} — head and base EXPLICIT — then accuracy-pr-land {issue:77, branch:same, base:'develop'}. I implemented this one MYSELF rather than dispatching accuracy-issue-execute: it is a ~20-line change, and the workflows have twice cleared this state key and twice shipped vacuous tests, so direct implementation was cheaper and safer. WHY #77 EXISTS — THIS IS THE IMPORTANT PART. I began the costed preflight for #27 (M0.3 A/A churn floor) and found its acceptance criterion 1 ('N >= 10 repeats of the golden set with the cache bypassed') was UNACHIEVABLE, and that running it anyway would have been actively harmful. Verified across the whole repo: lemely/app/cli.py's measure_accuracy_cmd built GeminiClient(settings) with NO cache-mode argument and no flag; lemely/web/deps.py and scripts/run_real_paper_accuracy.py the same; lemely/runtime/config.py has no cache_mode field and no env var; and the ONLY 'default_cache_mode=' call site in the entire repo was tests/test_accuracy_harness.py:721. So the M0.2/#26 bypass seam existed at the client and was unreachable from anything that runs a sweep. Consequence: every repeat after the first would have replayed the first run's CACHED responses, and #27 would have published an A/A churn floor of EXACTLY 0.0. That is the worst failure mode available to this programme — not a crash, but a FLATTERING number that makes every later A/B delta read as 'above noise' no matter how small, which is the D18 shape section 2 exists to prevent. It would also have been compounded by #73: manifest.cache_mode would have honestly recorded 'read_write' while the report called the run a bypass sweep, so the instrument would have been lying in one artefact and truthful in the other. NO BUDGET WAS SPENT — spend_usd is unchanged at 0.4026 and the sweep was never started. Filed as #77 (milestoned 'M0 — Instrument', added to project 'Lemely Progress' #1) and disclosed on #27 at https://github.com/LemelyIG/Lemely/issues/27#issuecomment-5377239253. Kept SEPARATE from #27 deliberately: the #73 review judged this gap to belong to M0.2 by strict ordering, and a measurement issue carrying a production diff makes 'did the instrument change between runs?' harder to answer later. WHAT #77 DOES: adds --cache-mode [read_write|bypass|refresh] to measure-accuracy, DEFAULTING to read_write so every existing caller is byte-identical, and threads it into GeminiClient(settings, default_cache_mode=...) via the same cast(...) pattern cli.py already uses at lines 185-186. Two tests in tests/test_cli_new_commands.py: one asserts the flag reaches the SAVED MANIFEST (not merely the constructor — the manifest is what a later reader trusts about what a run was), one pins the unchanged default. FALSIFIED by unwiring the flag and watching the first go red. NOTE neither test asserts exit_code == 0: measure-accuracy exits NON-ZERO whenever a metric misses its configured target, which a one-question fixture always does, so coupling a plumbing test to the accuracy thresholds would be wrong — do not 'fix' that into an exit_code==0 assertion. My proof: tests/test_cli_new_commands.py + tests/test_accuracy_harness.py all green, pre-commit green on both changed files with NO auto-fix, tree clean, commit signed. GATE HONESTY: the supervisor sweep at 2026-08-22T04:56 covered 2096e77, which is on LOCAL develop and does NOT include 13d5107 — backend green is UNPROVEN for this tip until CI on the PR says so. SEQUENCING NOW: #77 -> #27 (M0.3 A/A floor) -> #28 (M0.4 ablation, which needs the SAME bypass for its 2x2) -> #29 (M0.5). Do NOT spend on any sweep until #77 merges. When #27 finally runs, use the accuracy-measure workflow's costed preflight; 'not reportable, with reason' is a SUCCESSFUL outcome, never a reason to retry for a nicer number. #27's stated blockers (#56, #26, #32, #34) are all closed — #77 is a FIFTH, found at preflight rather than declared upfront. THE FIRST MEASUREMENT MUST ALSO RECOMPUTE review_rate: the 19.1% in this header is on the PRE-#32 denominator (28 leaves); the corpus is now 11 case dirs / 71 rows / 31 distinct leaves (DA6b). And treat spend_usd 0.4026 as a LOWER BOUND — it was recorded under the stale _DEFAULT_PRICING table that understated spend 2-4x and ignored thinking tokens; M0.2 corrected it, so the series is NOT self-consistent across that boundary and reporting cumulative spend must say so. LOCAL DEVELOP DIVERGES from origin/develop by one bookkeeping commit (2096e77, state-file only, unpushed) — that is expected; 'git pull --ff-only' will refuse, so inspect 'git log --oneline origin/develop..develop' and reset when the local-only commits are stale bookkeeping. BRANCH-CUT TRAP, hit three times now: 'accuracy_board.py start' does NOT create the branch, and cutting from origin/develop REVERTS this file to whatever rode in with the last squashed PR — RE-CHECK this header immediately after cutting any branch. WORKFLOW HAZARDS, all live: accuracy-issue-execute CLEARS this in_the_middle_of key when it checkpoints (twice, once despite an explicit prohibition), leaving a trailing space that trips pre-commit; an implementer once found its OWN agent process and refused as if it were a rival; workflows have reported false green repeatedly; two workflow-authored tests were vacuous. RE-RUN EVERY GATE YOURSELF and TRY TO MAKE EVERY NEW TEST FAIL. accuracy-pr-land's CI watch capped short on 4 of its first 5 uses (the 5th settled) — a timeout is NEITHER pass NOR fail; poll 'gh pr checks <pr>' and merge by hand with --squash. STANDING RED GATE, do NOT re-triage: impeccable-detect, playwright-e2e, ui-thresholds, failing every sweep for ten sweeps, escalated at BUILD/BLOCKERS.md:666. NOT accuracy-caused. Flag for the human that the lighthouse set fluctuates in membership (student-profile 56-58 persistent; student-flashcard-review and student-practice-generator appearing in some sweeps and not others), which reads more like measurement variance near the floor than a single fixed regression. ENV: jq NOT installed (use gh --jq); pre-commit needs .venv/bin on PATH; verify signing with 'git cat-file commit <sha> | grep -c gpgsig', NEVER %G?.
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
