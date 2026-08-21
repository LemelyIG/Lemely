# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-32-fixtures-carry-parent-id-and-is-excerpt
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #32 (M0.8) is STARTED but NOT IMPLEMENTED — board is In progress, branch feature/accuracy-32-fixtures-carry-parent-id-and-is-excerpt is cut from origin/develop and currently carries ONLY a bookkeeping commit (020d12c, the run-2026-08-21-a journal + state). No M0.8 code exists yet. NEXT ACTION: run accuracy-issue-execute {issue:32, root:'/home/sico/Lemely-worktrees/accuracy'} — it must reuse THIS branch, do not cut another; the branch name came from 'accuracy_board.py start 32' and must never be invented. #32 = fixtures carry parent_id and is_excerpt, plus a nested multi-part fixture. §8 CONSTRAINTS: M0.8 must land BEFORE M0.3 (A/A floor) and M0.4 (ablation), and before the ECF fix in M3/T1.5; and per §2 NO baseline run of any kind may happen until M0.8 is merged — #32 is the last fixture prerequisite. Also §8's caveat: do not start M1.4's paper-level-aggregate component until M0.8 lands, because it needs the is_excerpt marker. CONTEXT — this run landed TWO PRs, all verified directly rather than from workflow reports: #25 (M0.1) as PR #71 -> d5a8424, and #69 (supervisor state-set fix) as PR #70 -> 14cabfe. M0 is 4 of 11 Done (#56, #25, #26, #31). §4 precondition after both merges: origin/develop..origin/main = 0. TWO NEW UNSTARTED ISSUES filed this run, not yet on the board: #72 (AccuracyResult/save_result discard the per-record EvalRecord list, so the run_id->RunManifest join is unobservable outside measure_accuracy and the analyses cannot run over a real sweep) and #73 (_build_run_manifest hardcodes cache_mode='read_write' and split='dev' — land it BEFORE M0.3/M0.4 consume the manifest for attribution, or a bypassed run records itself as cached and a test-split run records itself as dev). DECISIONS DA6 + DA6a stand in BUILD/DECISIONS.md, flagged to the human; they may override DA6 with the design-effect alternative, which would be a NEW issue, never a reopen of #25. HARD-WON NOTES, all earned this session: 'jq' is NOT installed — use gh --jq and never pipe a poll loop through jq, because a missing binary reads as FALSE success; pre-commit's language:system hooks need .venv/bin on PATH or mypy/lint-imports falsely report 'Executable not found'; agent/workflow reports went FALSE-GREEN three times (pre-commit green on a tree whose auto-fix was never amended in, ruff clean with a live D205, and a report citing shas not on the branch) so RE-RUN EVERY GATE YOURSELF before believing any claim; and two agents once ran concurrently on this one worktree and one REWROTE branch history (§3.2 forbids it) — never dispatch an implementer while another is live. accuracy-pr-land's CI watch has capped short on 2 of 3 uses; a 'timeout' is neither pass nor fail, so be ready to merge by hand. Standing web-gate FAIL is escalated in BUILD/BLOCKERS.md awaiting a human — not accuracy-caused, not run by ci.yml, do NOT re-triage.
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
