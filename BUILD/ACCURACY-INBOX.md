# ACCURACY-INBOX.md — steering inbox for the accuracy programme

The contract, in full:

- The supervisor's control listener appends directives from the human as
  `- [ ] <timestamp> — <directive>` lines at the end of this file. Nothing else
  writes unchecked items.
- The orchestrator reads this file FIRST on every run, before touching the
  board or any code. Unchecked items are standing orders and take precedence
  over the mission's own queue.
- After acting on an item, the orchestrator flips it to `- [x]` and appends an
  indented one-line note on what it did (or why it could not act, in which case
  the item still gets checked and the problem goes to `BUILD/BLOCKERS.md` and
  the notify channel).
- Never delete an item and never reorder items — the history is the audit
  trail. Directives that are questions get their answer in the note.

Send items from your phone by publishing to the accuracy control topic
(`lemely-acc-ctl-bqlsqcY9FfbfQd` on `http://home-server:7532`), or locally by
appending a line in the format above.

---

(no items yet — seeded empty 2026-08-18)

- [x] 2026-08-19T00:25:42+03:00 — H4 (#49) decided — split rule approved, recorded as DA1 in BUILD/DECISIONS.md (uncommitted). Unit = the question (root parent, never divided; papers may span splits). Proportions 10/60/30 = ~30/180/90 leaves; dev deliberately below the n=219 McNemar floor, so improvement claims print as underpowered per M0.6. Strata = pre-label observables only (syllabus code x parse path x tariff band 1/2/3+); the labeller's type judgement is a REPORTING variable for M2.4's table, never an assignment variable. Assignment = bucket(sha256(salt || question_id)) within stratum, salt in the manifest — no RNG, no seeded shuffle. Amendments drop-only, never backfilled. Test-touch token gates EVALUATION JOINS only, not labelling reads. Binding constraints posted on #57 and #31 — read those before implementing either. #49 stays OPEN: box 2 (membership frozen) needs the real list from #57 after #44. Spec §4's stratification sentence is unsatisfiable as written (stratifies on an output of labelling that the freeze blocks); amendment proposed on #43 but the spec file is NOT edited — leave it alone until the human says.
  - Acknowledged; no change to the in-flight item (#56, M0.0) which the split rule does not touch. Committed the DA1 record so it is no longer uncommitted; left the spec file and #49 alone; the #57/#31 constraints will be read from those issues when either becomes the selected item.

- [x] 2026-08-19T01:05:22+03:00 — H7/H8/H9 (#51/#52/#55) decided — recorded as DA2-DA5 in BUILD/DECISIONS.md (uncommitted). #51: no longer self-agreement — a second named labeller B marks the 10% sample, so no delay; sample rule pre-committed in the manifest (lowest 10% by sha256(relabel_salt || question_id), per stratum) but membership computed only after #47 completes; B redoes transcription blind then marks against A's pass-1 text; B reads the full ruling log first; on disagreement A's label STANDS (B is measurement only, ground truth stays homogeneous); n stays ~30 and the Wilson interval (~+/-10pp) is published with it. #52: eval/rulings.jsonl at repo root, append-only + hash-chained, outside lemely/eval, published with the figures; every ruling carries a MACHINE-EVALUABLE scope predicate over label fields; rulings apply forward and ONE deferred sweep before the split freeze re-marks earlier in-scope leaves via supersede records; mid-session questions park as pending_ruling and the tail must hit zero before the freeze, unresolved leaves go in the M0.5 funnel; a ruling is never resolved by looking at pipeline output. #55: human picks the RC from dev-evaluated candidates, but candidates+dev figures get published, expected downward regression stated BEFORE the read, SHA recorded first; both McNemar arms run in the SAME authorised touch from one command; a disappointing number is published anyway and the split is spent. New ordering constraint DA5: #52's sweep before #51's sample — not in either issue, proposed as a §7 row on #43 together with a §6 rewrite. Issues updated: #51 retitled + effort corrected to 1-2h + new dependency, #52 and #55 acceptance boxes rewritten, #55 given the M4 milestone. Spec file NOT edited — §6/§7 amendments sit on #43 until the human says.
  - Acknowledged; DA2-DA5 committed so they are no longer uncommitted. No effect on the in-flight item (#56, M0.0), which none of #51/#52/#55 touch. The spec file is left alone as instructed; the §6/§7 amendments (including the new DA5 ordering row, #52's sweep before #51's sample) stay parked on #43 until the human says. #51/#52/#55 remain OPEN H issues — never closed or worked around here (§3.5); their constraints will be read from the issues when #47, #57 or #31 becomes the selected item.

- [x] 2026-08-23T12:33:25+03:00 — pus & PR #30 ignoring CI billing-blocked for this PR & future PRs
  - Done, and already in flight when this arrived (12:33; #30 landed 12:52) — the same authorisation had been given in code at 11:20 as commit 1289d8b, which added `allow_merge_without_ci` to accuracy-pr-land. Read as covering the whole queue, not just #30: all four landed under that waiver — #77/PR #78, #30/PR #79, #33/PR #80, #29/PR #81, develop now 465fe34, all four board items Done. "Future PRs" is taken as standing authorisation while the block holds, so no further inbox item is needed per PR; it lapses the moment Actions can provision a runner, which each PR comment says explicitly. What "ignoring CI" bought and cost, stated plainly rather than assumed harmless: ci_green was reported FALSE on every one of the four (never relabelled green), the deviation was posted to each PR before its merge, and NOT ONE CI STEP HAS EVER EXECUTED against any of them — the merges rest on local gates plus the supervisor's sweep alone. Two things this route caught that a blind merge would have shipped: the #29 x #33 semantic conflict (git merged the production code clean, but #29 makes `funnel` required on AccuracyResult while #33's fixture omitted it — five tests died with TypeError), and a DA7 decision-number collision between #29 and #30 (#30 keeps DA7, #29's became DA8). Still open and NOT covered by this directive: the billing block itself, and #27, which spends real money and needs its own authorisation.
