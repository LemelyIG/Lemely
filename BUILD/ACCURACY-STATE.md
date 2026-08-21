# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-19-g
worktree: /home/sico/Lemely-worktrees/accuracy
branch: fix/accuracy-pr-land-watch-cap-and-scratch
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #56 (M0.0) IS LANDED: PR #65 merged (squash) to develop as 4853f3a on 2026-08-21, CI green on all 5 checks (test 3.12/3.13/3.14 + pre-commit + web), board marked Done. Overprint fix + RunInkOverprintTests verified present in develop's tree post-squash. M0.0 no longer blocks baseline runs (spec §7). NOW: small tooling branch fix/accuracy-pr-land-watch-cap-and-scratch (2 commits, off develop, UNPUSHED, no PR yet) carrying two pr-land defects found while landing #56: 5fe9ce9 gitignores .pr-body-*.md (pr-land leaves it untracked and the supervisor auto-commits dirty trees), 4f3c8a4 makes the Watch cap literal 2700s with a 1800s floor (agent had chosen 600s vs ~17min test jobs). Next: PR that branch, then board 'next' = #26 (M0.2). Red web gates unchanged and unrelated: impeccable-detect, playwright-e2e (0625 mastery 88%), ui-thresholds (lighthouse student-profile 56 is the real one; the 79s vary run-to-run — 4 routes one sweep, 3 the next — so treat those as noise near the 80 floor). All in BLOCKERS.md; none run in CI.

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
