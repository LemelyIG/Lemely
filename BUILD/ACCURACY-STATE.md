# ACCURACY-STATE.md — resume pointer for the accuracy programme

run_pointer: run-2026-08-21-a
worktree: /home/sico/Lemely-worktrees/accuracy
branch: feature/accuracy-32-fixtures-carry-parent-id-and-is-excerpt
last_run_label: none
last_run_headline: none
review_rate: 19.1%
ratchet: unarmed (M0.9 / #33 open; starting value will be 19.1%)
spend_usd: 0.4026
in_the_middle_of: #32 (M0.8) IN PROGRESS on feature/accuracy-32-fixtures-carry-parent-id-and-is-excerpt at f44ea0e — do NOT open a PR. accuracy-issue-execute returned ready_for_pr=FALSE, review blocked, 5 items. FOUR ARE NOW FIXED BY ME, each verified: (a) E501 in the COMMITTED blob of tests/test_golden_corpus.py — wrapped and amended in; (b) dirty tree from the unamended auto-fix — committed; (c) an UNSIGNED commit — but NOT the one the workflow named. Its claim that 35dc283 was unsigned is FALSE: 35dc283 carries a gpgsig header; git only reported %G?=N because gpg.ssh.allowedSignersFile is unconfigured so SSH signatures cannot be VERIFIED locally ('cannot verify' != 'not signed'). The real unsigned commit was 020d12c, MY journal commit — 'git cherry-pick' drops the signature unless given -S, and I cherry-picked it last run. Whole chain re-signed via 'git rebase -S --force-rebase origin/develop'; all commits now show gpgsig=1. USE 'git cat-file commit <sha> | grep -c gpgsig' to check signing here, NOT %G?. (d) the vacuous is_excerpt test — fixed at f44ea0e and falsified: it built {c.paper_id: c.is_excerpt}, and because the three DA6 variants share one paper_id the dict kept only the last-sorted variant, so deleting case.json from two variants left the suite green; now keyed by case DIRECTORY with set(by_case_dir)==set(_EXPECTED_MAXIMUM_MARK) plus a variants-agree test, and removing case.json from a non-last variant now fails both by name. ONE MUST-FIX REMAINS — the reason #32 is not ready: the new 11th fixture tests/golden/0625_w21_qp_32_theory_nested does NOT exercise the PRIOR PART RESULTS chain it exists for. Verified at source: correction_ai.py:463-468 groups siblings by EXACT parent_id equality, and the fixture's only two leaves are 1a_i (parent_id='1a', marks=2) and 1b (parent_id='1', marks=3) — different parents, so sibling_prior is empty and prior_results=None. Acceptance criterion 'Test proving the PRIOR PART RESULTS block is actually emitted' is UNMET. THE FIX: split the 2-mark 1a_i into 1a_i=1 and a NEW sibling 1a_ii=1, both parent_id='1a', so leaf sum stays 2+3=5 and metadata.maximum_mark STAYS 5 — issue #32 forbids altering any maximum_mark, and this fixture is is_excerpt=false so its leaf sum must keep equalling its max mark. Then add an answers.json entry for 1a_ii, regenerate scan.pdf via scripts/regenerate_golden_fixtures.py render_handwritten_scan with its round-trip fidelity assertion, and add a test asserting correct_paper emits PRIOR PART RESULTS carrying 1a_i's awarded marks when marking 1a_ii. NOTE the issue's '(a)(i) -> (b)' wording can NEVER hold under exact parent_id equality — say so in the PR rather than pretending it was satisfied. ALSO NOTE: a genuine sibling-prior regression test already exists and is real (verified red on origin/develop). AC5 CLARIFIED: the workflow's plan text said the 0625_s20 family should be is_excerpt=true; that is a MISREADING of issue #32, which says SIX of ten fixtures are excerpts and lists 0625_s20 at 19 vs 19. The implementation's table (0580 True, 0606 True, 0625_m20 False, 0625_s20 False, nested False) is CORRECT — do not 'fix' it. SHOULD-FIX items for the PR body or a follow-up, from the review: the new fixture wears a real 0625 w21 identity with a fabricated maximum_mark=5; harness.py's is_excerpt parse is fail-open (bare except -> False, and bool() coerces the JSON string 'false' to True — worth hardening); 0625_s20 leaves 4a/5b/11b keep parent_id=null behind a hardcoded allowlist; _corpus_digest omits mark_scheme.json and the new marker, so a future parent_id/is_excerpt edit is invisible to M0.3/M0.4 attribution; and the distinct-leaf count becomes 30 (68->70 records), which means DECISIONS.md DA6's '28 leaves' text and the 19.1% review_rate denominator are now STALE and must be updated in this PR. §8: M0.8 blocks #27/#28, blocks #39, blocks the M3/T1.5 ECF fix, and §2 forbids any baseline run until it lands. AFTER the fix: re-run accuracy-review (the current verdict is spent), then accuracy-pr-land. ENV: jq NOT installed; pre-commit's language:system hooks need .venv/bin on PATH. Standing web-gate FAIL is escalated in BUILD/BLOCKERS.md — do not re-triage.
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
