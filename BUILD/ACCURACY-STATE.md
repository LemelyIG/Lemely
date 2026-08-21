# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-25-lemely-eval-record-model-run-manifest
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #25 (M0.1) on feature/accuracy-25-lemely-eval-record-model-run-manifest at e21ca0e, REBASED onto the new origin/develop, UNPUSHED, no PR. accuracy-review is RUNNING on it now (run-2026-08-21-a); the earlier BLOCK verdict is SPENT — do not act on it. BOTH review MUST-FIXes are now addressed: (1) params_fingerprint fixed at c86068f — it hashed only temperature|top_p|seed|thinking_budget, omitting the MODEL, so two runs on different models hashed identically (demonstrated: both ce5aa7b9ccad), the false-zero-delta trap once M0.3's A/B reads it; now hashes sorted(models_by_task)|temperature|top_p|seed|thinking_budget|_MAX_OUTPUT_TOKENS, per-call schema hash deliberately excluded and said so in code; 3 tests, 2 fail against the old fingerprint. (2) SCOPE fixed — the supervisor-tooling fix was split to issue #69 / PR #70, PR #70 is MERGED to develop as 14cabfe and #69 is CLOSED; #25 was then rebased onto the new develop and commit 33f0f5b was DROPPED (git rebase --skip on its add/add conflict). VERIFIED AFTER REBASE: 'git diff --stat origin/develop...HEAD' lists NEITHER scripts/accuracy_board.py NOR tests/test_accuracy_board_state.py — net diff is now 11 files/1741 insertions, down from 13/1812. M0.1 content intact: the models fingerprint present, DA6 and DA6a both in DECISIONS.md, exactly one 'class RunManifest'. GATES RE-RUN ON THE REBASED TIP: ruff, ruff format, mypy 226 files, lint-imports 3/3, pre-commit --all-files all clean, and tests/eval + tests/test_accuracy_harness.py + tests/test_accuracy_board_state.py all green; tree clean. Pre-rebase backup branch was deleted after verification. NEXT: read the review verdict; if no blocker, accuracy-pr-land {issue:25, branch:that branch, base:'develop'}. If it died mid-review, that review is UN-RUN (MISSION §7) — re-run it, do not wait for a handle. DECISIONS DA6 + DA6a are recorded and flagged to the human; do not re-litigate; the human may override DA6 with the design-effect alternative. CARRY INTO THE PR BODY: the DA6/DA6a decisions and the override offer; that accuracy-issue-execute originally returned ready_for_pr=false; and that the first review returned BLOCK on two MUST-FIXes both since fixed. REVIEWER OBSERVATION worth wiring before it matters: _build_run_manifest hardcodes cache_mode='read_write' and split='dev' instead of reading them from settings / the M0.7a authorisation path — harmless today, dangerous once M0.7a-gated test-split reads or cache-bypass sweeps rely on the manifest being truthful. NON-BLOCKING FOLLOW-UP for its own issue after #25 lands: AccuracyResult exposes no EvalRecords and save_result discards records+manifest, so the run_id->RunManifest join is unobservable outside measure_accuracy. PROCESS HAZARD: earlier this session two agents ran concurrently on this single worktree and one rewrote branch history (§3.2 forbids it); benign only because content converged. Never dispatch an implementer while another is live. §4 precondition: origin/develop..origin/main = 0 (re-measure after any merge). ENV: jq NOT installed (use gh --jq); pre-commit's language:system hooks need .venv/bin on PATH. Standing web-gate FAIL is escalated in BUILD/BLOCKERS.md — do not re-triage.
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
