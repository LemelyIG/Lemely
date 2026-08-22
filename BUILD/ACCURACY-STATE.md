# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-33-review-rate-as-a-two-part-ratchet-ci
last_run_label: none
last_run_headline: none
review_rate: 3.23% signal/total, 16.67% per_paper_p95 (n=31, dev split, 2026-08-22, DA-M0.9)
ratchet: unarmed; last_merged_review_rate=0.0323 (recomputed 2026-08-22, supersedes stale pre-#32 figure — see DA-M0.9)
spend_usd: 0.4668
in_the_middle_of: #33 (M0.9 ratchet) IMPLEMENTED on feature/accuracy-33-review-rate-as-a-two-part-ratchet-ci (2ea481c) but NOT PR-READY — accuracy-issue-execute wf_fa30d308-644 returned ready_for_pr=FALSE and the adversarial review returned BLOCKED. I verified BOTH blockers myself. NO PR is open for #33. BLOCKER A, now fixed by me: pre-commit FAILED at the branch tip because commit bdc9ecc blanked this very key leaving a TRAILING SPACE ('in_the_middle_of: ' — confirmed with 'git show HEAD:BUILD/ACCURACY-STATE.md | sed -n 11p | cat -A'), so the trailing-whitespace hook rewrote the file and dirtied the tree. That is the FIFTH time accuracy-issue-execute has destroyed this key and the second time it committed the damage. BLOCKER B, STILL OPEN, THIS IS THE REAL ONE — THE RECORDED 3.23% RATCHET BASELINE IS A LEAF-COLLAPSE ARTIFACT, NOT THE REVIEW BURDEN. I recomputed it independently over tests/golden/results/2026-08-22-f7be062.json and my numbers match the reviewer exactly: 71 question-level rows, 31 distinct leaves, 12 flagged rows (16.9%), and 9 OF 31 LEAVES (29.0%) carry at least one non-random_audit trigger — yet review_rate() reports 1/31 = 3.23%. ROOT CAUSE, which I confirmed at source and which is INHERITED, NOT INTRODUCED BY #33: review_rate already exists on origin/develop (lemely/eval/analyses.py:394), and _collapse_leaf_group (lines 73-90) is built for OUTCOME semantics — its docstring says a leaf is correct iff EVERY record is correct, and it picks a non-correct representative when any disagree. That is right for accuracy and WRONG FOR TRIGGERS: for a leaf whose records are unanimously correct in outcome, candidates is the whole group and min() picks an arbitrary representative, silently discarding triggers carried by the others. Confidence-driven reviews on CORRECT marks therefore vanish — 8 of the 9 flagged leaves are invisible to the gate. CONSEQUENCE: a run generating MORE reviews can score BETTER, which is the exact D18 perverse incentive this programme exists to prevent, and the gate does not bound the review queue as spec section 5 requires. MY ADJUDICATION, to be implemented: review_rate's NUMERATOR must be a UNION over each leaf's question-level records — a leaf counts as reviewed iff ANY of its records carries a non-random_audit trigger — while the DENOMINATOR stays distinct leaves. That keeps DA6's leaf-collapse discipline (needed for interval independence) without letting the representative-picker destroy trigger information. Expect ~29.0%. The representative-only numerator must NEVER be the value the ratchet arms on at M1. ALSO REQUIRED: delete the BUILD/DECISIONS.md claim that 3.23% is 'correctly-denominatored' and '6x smaller than the stale 19.1%' — the 6x IS the collapse artifact, and the row-level 16.9% is within noise of the old 19.1%, so that sentence is a flattering-number claim of exactly the kind D18 forbids. Publish the full funnel instead (71 rows -> 31 leaves; 12 flagged rows -> 9 flagged leaves -> 1 flagged representative). NOTE 3.23% is baked into THREE places: BUILD/review-rate-baseline.json, BUILD/DECISIONS.md, and lemely/runtime/config.py:162. HONEST CAVEAT to record with whatever number is chosen: the golden corpus replays each leaf as correct/partial/wrong variants, so the per-leaf union (29.0%) is an UPPER bound, the row-level (16.9%) weights synthetic variants as equally likely, and the representative-only (3.23%) is biased LOW; none is unambiguously 'the' review rate, so state which was chosen and why rather than presenting one as fact. FOUR SHOULD-FIXes to carry into the same pass: no dev-split assertion in cli.py:1058 (only check_review_rate_gate.py:38 asserts it); the semi-vacuous 'Targets missed' comprehension at tests/test_cli_review_rate_gate.py:112 filters on result.output not line; check_review_rate_gate.py:34 prefers a gitignored lexicographically-selected local run so local and CI can gate on DIFFERENT data; the baseline artifact carries no run_id/corpus_digest and nothing cross-checks it; also review_rate_last_merged rounds 0.03225806 UP to 0.0323 (loosening direction) and check.sh:126 hardcodes .venv/bin/python unlike neighbouring steps. WHAT IS GOOD AND SHOULD NOT BE REDONE: all four gate limbs plus the total==signal invariant are implemented with correct comparison directions and survived five reviewer mutations; the CLI tests were falsified BEHAVIOURALLY against origin/develop (not by ImportError); ci.yml is correctly written-only and NOT claimed CI-verified; no stale 19.1/13-of-68/11.5/30.0 figures appear in the new code or tests. TWO FINISHED BRANCHES QUEUED, DO NOT REDO: #77 -> PR #78 OPEN and reviewed clean, deliberately unmerged; #30 (M0.6) COMPLETE at 3f569ee, PUSHED to origin with NO PR (protective only; ci.yml triggers on pull_request so the push started no CI). The supervisor sweep at 2026-08-22T09:36 covered EXACTLY 3f569ee with pytest ABSENT from failures, so #30's backend is green on its own tip; its 3 failures are the STANDING RED GATE (impeccable-detect, playwright-e2e, ui-thresholds), not accuracy-caused, do NOT re-triage. ORDER WHEN BILLING IS FIXED: (1) 'gh pr checks 78', if green merge --squash --delete-branch then 'accuracy_board.py done 77'; (2) accuracy-pr-land for #30; (3) finish + land #33; (4) then #27 (M0.3), which MUST use '--cache-mode bypass' never 'refresh' (gemini.py:350-356, :425). STILL HALTED: Actions is billing-blocked for LemelyIG — a human must fix Settings > Billing & plans. Re-verified THIS run: no workflow run after 32547620531 (02:56Z); 'gh pr checks 78' still all five failing in 1-4s. Do NOT re-triage, re-run, or trim the CI matrix. spend_usd 0.4026 is a LOWER BOUND. NO BUDGET SPENT in the last three runs. Precondition re-checked: origin/develop..origin/main = 0. Local develop is 1 ahead of origin/develop (2096e77, bookkeeping), unpushed. RE-RUN EVERY GATE YOURSELF; MUTATION-TEST EVERY NEW TEST; an ImportError is NOT a falsification. ENV: jq NOT installed (use gh --jq); pre-commit needs .venv/bin on PATH; verify signing with 'git cat-file commit <sha> | grep -c gpgsig', NEVER %G?.
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
