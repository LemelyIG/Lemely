# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-72-evalrecords-are-discarded-the-run-id
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #72 IMPLEMENTED on feature/accuracy-72-evalrecords-are-discarded-the-run-id. NOT reviewed, NO PR open. NEXT: accuracy-review {issue:72, head:'feature/accuracy-72-evalrecords-are-discarded-the-run-id', base:'origin/develop'} — pass head and base EXPLICITLY — then accuracy-pr-land {issue:72, branch:same, base:'develop'}. accuracy-issue-execute run wf_f73ff647-3f0 returned ready_for_pr=FALSE with 2 blockers plus 1 SHOULD-FIX; I fixed ALL THREE myself and verified each. (1)+(2) THE WORKFLOW EMPTIED THIS in_the_middle_of KEY AGAIN — commit 98bcfb9 'clear in_the_middle_of after #72 implementation' — DESPITE an explicit dispatch constraint telling it not to. That left 'in_the_middle_of: ' with a TRAILING SPACE, which made pre-commit's trailing-whitespace hook rewrite the file, exit 1, and leave the tree dirty with an unamended auto-fix. Both blockers were the SAME root cause. Restoring a real value removes the trailing space and fixes both. LESSON, now twice burned: workflows clear this key when they checkpoint state; ALWAYS re-check it after any workflow writes state, and never trust 'gates green' from a run that touched this file. (3) SHOULD-FIX, a real weakness: the round-trip test's analysis assertion was VACUOUS — 'assertGreaterEqual(review_rate_total, 0.0)' and 'assertLessEqual(..., 1.0)' hold BY CONSTRUCTION and pass on an EMPTY record list, as does the all(...) generator, so a regression to eval_records=[] in BOTH memory and disk would have passed while destroying exactly what #72 delivers. Replaced with exact assertions: assertTrue(records), rate['n'] == len(records), review_rate_total == 0.0, review_rate_signal == 0.0. FALSIFIED PROPERLY: patching only save_result's JSON to [] fails at the pre-existing list-equality assert, but making measure_accuracy return eval_records=[] in memory too — the case the old test genuinely missed — now fails on the new assertTrue with 'eval_records round-tripped empty'. Fixture restored after each experiment. WHAT #72 DOES: AccuracyResult gains eval_records; save_result writes BOTH manifest (previously absent from the JSON entirely, despite being a field) and eval_records in round-trippable form; a test reconstructs records from saved JSON and runs lemely.eval.analyses.review_rate over them. The workflow's reviewer independently falsified all three new/edited tests against pre-fix harness.py, so they are not implementation-mirroring. NOTE the workflow ALSO ran the full 'pytest -q' suite despite being told not to — it happened to pass (exit 0, 91.55% coverage) but that is not a licence to repeat it; the full suite is the SUPERVISOR's job. My own targeted proof: tests/test_accuracy_harness.py + tests/eval/ all green, pre-commit green on the changed files with NO auto-fix, tree clean, commits signed. GATE HONESTY: the supervisor sweep at 2026-08-22T03:03 covered aa15278 (bookkeeping-only tip) with pytest ABSENT; it does NOT cover the implementation commits 5e12a9b onward — do not claim pytest green for this tip until the next sweep or CI says so. The 3 standing failures (impeccable-detect, playwright-e2e, ui-thresholds) are the escalation at BUILD/BLOCKERS.md:666 — NOT accuracy-caused, do NOT re-triage — but note the lighthouse set is DRIFTING WIDER, not static: student-profile 57, plus student-flashcard-review 63 and student-practice-generator 69 appearing in recent sweeps. Worth a human's attention as a widening signal, still not mine to fix. #72 IS THE LAST PREREQUISITE BEFORE THE BASELINE RUN. Once it merges the baseline is UNBLOCKED and the order becomes: baseline run, then #27 (M0.3 A/A floor), #28 (M0.4 ablation), #29 (M0.5). Measurement spends REAL MONEY and must go through accuracy-measure's costed preflight; 'not reportable, with reason' is a SUCCESSFUL outcome. That ordering is PROPOSED not decided, on #43 at https://github.com/LemelyIG/Lemely/issues/43#issuecomment-5375246756; ACCURACY-SPEC.md must NOT be edited until the human says. KNOWN LIMITATION from #73, check before trusting a per-call-bypass sweep: manifest.cache_mode reports only the CLIENT DEFAULT, so a per-call cache_mode='bypass' A/B sweep still stamps 'read_write'; no production call site can set default_cache_mode yet. Reviewer judged it M0.2's by strict ordering, but M0.3/M0.4 attribution depends on it. IF YOU ARE AN IMPLEMENTER AGENT: there is NO concurrent agent here; if you find a live process for this branch, check whether the agentId/PID is your OWN before refusing — that self-deadlock burned run wf_dba29fea-8af. BRANCH-CUT TRAP: 'start' does NOT create the branch, and cutting from origin/develop REVERTS this file to whatever rode in with the last squashed PR; re-check this header immediately after cutting any branch. After merging, local develop can DIVERGE from origin/develop via an unpushed state commit and 'git pull --ff-only' will refuse — inspect 'git log --oneline origin/develop..develop' and reset when the local-only commits are stale bookkeeping. BOARD: 'next' says 'nothing ready' because nothing sits in Ready and there is NO 'ready' subcommand — section 3.2 says YOU maintain it; select then call 'start'. M0 counts (11 total) EXCLUDE #72/#73 — their GitHub milestone is 'M0 — Instrument' and they are on project 'Lemely Progress' #1, but their PROJECT milestone field is unset. Remaining M0: #27, #28, #29, #30 (M0.6), #33 (M0.9); #30/#33 have no in-edges. Blocked: #57/#59 wait on #44, #36 waits on #33. CORPUS: 11 case dirs, 71 rows, 31 distinct leaves (DA6b). review_rate 19.1% is on the PRE-#32 denominator, deliberately NOT recomputed — recompute on the first post-merge measurement; ratchet unarmed. ENV: jq NOT installed; pre-commit needs .venv/bin on PATH; its auto-fix does NOT amend itself in — re-run and re-stage; verify signing with 'git cat-file commit <sha> | grep -c gpgsig', never %G?; squash is the merge convention; accuracy-pr-land's CI watch has capped short on 4 of 5 uses so expect to poll and merge by hand.
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
