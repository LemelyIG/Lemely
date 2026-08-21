# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-73-build-run-manifest-hardcodes-cache-mode
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #73 IMPLEMENTED on feature/accuracy-73-build-run-manifest-hardcodes-cache-mode at 69a07fb. NOT yet reviewed, NO PR open. NEXT: accuracy-review {issue:73, head:'feature/accuracy-73-build-run-manifest-hardcodes-cache-mode', base:'origin/develop'} — pass head and base EXPLICITLY (MISSION 7.1) — then accuracy-pr-land {issue:73, branch:same, base:'develop'}. accuracy-issue-execute run wf_ff14f7e7-9a0 returned ready_for_pr=FALSE with 5 blocking items; I fixed the two real MUST-FIX defects myself at 69a07fb and verified each at source rather than trusting the report. (1) THE M0.7a GATE FIRED TOO LATE — authorize_test_split_join sat inside _build_run_manifest, which measure_accuracy calls only in its final return, AFTER the per-case extract/correct loop. An unauthorised split='test' run therefore read the split and SPENT real budget before being refused. Confirmed structurally (gate at harness.py:448, loop at 540, manifest built at 624) and then FALSIFIED: restoring the late gate makes the new ordering assertion fail with 'Expected correct_paper to not have been called. Called 1 times.' — the unauthorised run really did mark a paper first. Fix: authorise at the TOP of measure_accuracy right after run_id; _build_run_manifest now trusts the already-authorised split and does NOT re-gate, so exactly one ledger entry per run. (2) THE UNIT TESTS WERE FORGING AUDIT HISTORY — the authorised-split test appended to the REAL reports/accuracy/test-touch-ledger.jsonl on every run; it held 11 entries, ALL 11 caller=measure_accuracy and all written by the buggy tests, i.e. 100% forged records of test-split touches that never happened. Fix: ledger_path threaded through measure_accuracy, test points at a tmp path and asserts EXACTLY ONE entry (which also pins the no-double-gate fix). I deleted that untracked polluted ledger — say so plainly in the PR; it is an append-only audit artefact and its removal must be disclosed, not silent. Verified afterwards that the suite no longer recreates it. THE OTHER 3 blocking items were gate/tree hygiene: pre-commit's trailing-whitespace hook had rewritten BUILD/ACCURACY-STATE.md leaving a dirty tree (now clean, pre-commit green on both changed files with NO auto-fix), and 'no full-suite verdict'. IGNORE that last one as written: the workflow's next_action says to background 'pytest -q' and wait ~20min, which DIRECTLY CONTRADICTS standing orders — the full suite is the SUPERVISOR's job, never mine, and every in-session attempt has been killed mid-wait (the workflow's own attempts died at exit 143). Targeted proof I ran in the foreground instead: tests/test_accuracy_harness.py 37 green, tests/eval/ green (includes test_test_touch_static_guard.py, so no second split=='test' comparison was introduced), ruff+ruff-format+mypy+import-linter green. SHOULD-FIX/NIT items still owed to the PR body, from the workflow's review: manifest.cache_mode reports only the CLIENT DEFAULT, so a per-call cache_mode='bypass' A/B sweep would still stamp 'read_write' — worth stating as a known limit since M0.3/M0.4 attribution depends on it; nothing in production (cli.py:1026, scripts/run_real_paper_accuracy.py:207, web/deps.py:92) can set default_cache_mode yet; the getattr(..., 'read_write') fallback manufactures provenance for clients lacking the attribute, including gemini_client=None and MagicMock doubles; and the caller string is hardcoded. WATCH OUT — THE WORKFLOW EMPTIED THIS in_the_middle_of KEY when it checkpointed state (its own review flagged it as a NIT). If a workflow checkpoints state, RE-CHECK this key afterwards and restore it; the resume pointer is not recoverable from the tracker. WHY #73 IS FIRST, ahead of section 4's next step: section 4's order is M0.0 -> M0.1/M0.2 -> M0.8 -> baseline -> M0.3/M0.4/M0.5, so with #32 merged the baseline is nominally next. DO NOT RUN IT YET. A baseline through the pre-fix manifest stamps FALSE provenance on every record and taints M0.3/#27 and M0.4/#28 irreversibly — the taint is in the attribution, not the figures. Then #72 (AccuracyResult/save_result discard the per-record EvalRecord list, so the run_id -> RunManifest join is unobservable outside measure_accuracy). ORDER: #73 -> #72 -> baseline -> #27/#28/#29. NOT in section 8's edge table; PROPOSED not decided on #43 at https://github.com/LemelyIG/Lemely/issues/43#issuecomment-5375246756 per the DA5 precedent; ACCURACY-SPEC.md NOT edited. IF YOU ARE AN IMPLEMENTER AGENT: there is NO concurrent agent here; if you find a live process for this branch, check whether the agentId/PID is your OWN before refusing — that exact self-deadlock burned run wf_dba29fea-8af, whose implementer found its own agentId af504b54bd135b41a and refused. #32 IS MERGED AND DONE (PR #74 squashed to 1e18f05, board Done, origin/develop..origin/main = 0); M0 is 6 of 11. Remaining M0: #27, #28, #29, #30 (M0.6), #33 (M0.9), plus #72/#73 which I milestoned to 'M0 — Instrument' and added to project 'Lemely Progress' #1 ('start' REFUSES non-board issues — 'gh project item-add 1 --owner LemelyIG --url <url>' first). #30/#33 have no in-edges. Blocked: #57/#59 wait on #44, #36 waits on #33. 'next' will keep saying 'nothing ready' — no 'ready' subcommand exists and section 3.2 says YOU maintain that column; select then call 'start'. CARRY-FORWARD from #32 for M3/T1.5: '(a)(i) -> (b)' cross-branch ECF is UNREACHABLE BY DESIGN (exact parent_id equality), covered as (a)(i) -> (a)(ii); disclosed at https://github.com/LemelyIG/Lemely/issues/32#issuecomment-5374580059. CORPUS: 11 case dirs, 71 rows, 31 distinct leaves (DA6b). review_rate 19.1% still on the PRE-#32 denominator, deliberately NOT recomputed. ENV: jq NOT installed; pre-commit needs .venv/bin on PATH and its auto-fix does NOT amend itself in; verify signing with 'git cat-file commit <sha> | grep -c gpgsig', never %G?; squash is the merge convention; accuracy-pr-land's CI watch has capped short on 3 of 4 uses.
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
