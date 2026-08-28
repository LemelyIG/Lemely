# ACCURACY-ASKS.md — the open human decisions, in one place

**Status 2026-08-28 (run 58): C15 is CLOSED by ruling C20, C21 is executed,
and the queue is UNBLOCKED.** The B1–B18 list was discharged at run 55; C1–C7
were taken the same day; **C11–C14 were taken in a second interview on
2026-08-27** and are recorded below as standing rulings, not open questions.

**C11 unblocked everything.** Ruling C6 (*"deterministic parsing for MCQ ONLY"*)
was **superseded**: det parses all mark schemes and marks MCQ; Gemini does all
extraction and marks non-MCQ — which is the architecture already in place. So
#112, #110, #136, #39, #41, #95, #127 and #38 are **live work again**, not dead,
and the $11.92–$28.02 migration costed on #151 **never arises**.

**Status 2026-08-28 (run 59): #166, #52, #51 and #55 were put to the human in a
third interview and are answered as C22–C25 below. Nothing in the OPEN section
is now waiting on a human**, with one qualification: **C23 defers the #52
ruling behind agent work** (pull the concrete cases), so #52 comes back.

**What is actually open now: nothing that blocks.** #49 stays owed but is not a
gate on anything currently runnable — C25 ruled it out of #55 explicitly. C20
and C21 were executed on 2026-08-27; C15 below records what they measured.
Everything else is agent work with a path.

Nothing here is a request for more investigation — each row is a decision only
you can make. Where I have a recommendation I give it, and where a
recommendation of mine would be self-serving (cheaper, or avoids a
measurement) I say so.

**How to answer.** Reply on the accuracy control topic
(`lemely-acc-ctl-bqlsqcY9FfbfQd` on `http://home-server:7532`), or append to
`BUILD/ACCURACY-INBOX.md`, naming the ask number and your choice — e.g.
`C9: ...`. Partial answers are useful.

**#166 is ANSWERED (C22): diagnose one 0606 failure now, ~$0.15, hard stop at
$0.50.** It was the "answer only one" ask and it is taken.

---

# OPEN

## C23 — #52's three seed rulings, waiting on agent work, then on you again

**Not a live ask right now.** C23 ruled that the ECF / `oe`-alternatives /
list-rule-over-tariff rulings cannot be made in the abstract: the human requires
**3–5 concrete corpus instances per rule**, pulled zero-spend from `corpus/`, and
presented as cases rather than as recommendations. Until that pull lands, #52
stays open and the H8 log ships empty. **The mark-impact-only filter was offered
and declined** — pre-filtering would be the agent making the judgment the ruling
exists to capture.

## C9 — B14, what remains owed on the H issues

- **#49 (H4)** — split membership stays **NOT frozen**; sign-off still owed after
  #57 delivers. **C25 ruled it is not a gate on #55.** MISSION §3.5 still
  applies everywhere else: never close it, never mark it done, never work
  around it.
- **#51 (H7)** — identity settled (C14). **Onboarding still owed**, deferred by
  C24 until the first batch is ready; #47 is designed for two seats meanwhile.
- **#52 (H8)** — see C23 above.
- **#55 (H9)** — **conditionally authorised by C25**; fires on three named
  preconditions with no further interview.

---

# ANSWERED 2026-08-28 (run 59) — standing rulings, do not re-argue

| # | Subject | Ruling |
|---|---|---|
| **C22** | #166 / DA31 | **Diagnose one 0606 failure now, with logging — ~$0.15 authorised.** Ceiling NOT raised; C12 stands and the gitignored-override route stays closed. **Stopping rule: up to $0.50 total, then HARD STOP**, spent on ~3 repeats of the *same* scheme — the open question is intermittent vs systematic, which is what the failed-then-succeeded-unchanged probe raised. Breadth across syllabuses was offered and declined. At the cap, report even if inconclusive; a fourth run is a fresh ask. The 12 parsed schemes stay kept-but-not-stratum-coverage. |
| **C23** | #52 / H8 | **Not ruled — concrete cases first.** 3–5 clear instances per rule from `corpus/`, zero spend, presented as cases not recommendations. #52 returns to the human after. Mark-impact-only filtering **declined**. |
| **C24** | #51 / H7 | **Design #47 for two seats now; onboard Abdallah later**, when the first batch is ready. The co-author route (B shapes the protocol first) was offered and declined. Onboarding stays **owed** — #51 does not close. |
| **C25** | #55 / H9 | **Conditionally authorised, in writing.** The single run fires without further interview once **all three** hold: (1) #166 resolved or formally re-scoped; (2) costed preflight passes under #28 before any spend; (3) #47's two-seat protocol delivered. **And, ruled explicitly on a second asking: #49 is NOT a gate on #55.** The omission was put back to the human as a possible oversight and confirmed intentional — H9 may run on the split as it stands. A deliberate departure from the frozen-split framing, recorded as the human's call. #49 is not thereby closed. |

---

# OPEN (as of run 58 — retained for the record)

## C15 — RESOLVED by C20, and the answer falsified the question (#88 -> #166)

**Ruling C20 was "make the sweep cost < $3.00"** — option 2 of the fork below,
with the budget rather than the sample size made binding. It was executed on
2026-08-27. **The cap held: $2.8470 of $3.00, stopped before scheme 24 of 37.**

**The sweep is NOT REPORTABLE for its purpose.** 24 attempted, **12 parsed, 12
failed — 50%**. Four DA1 strata got **zero** successes (`0606/p1`, `0606/p2`,
`0625/p4`, `0625/p5`), so the stratum coverage the spend was justified by was not
delivered. Cost per *success* was **$0.2372** — **3.39x** the projection, which
extrapolates to **$45.08** for all 190.

**The real finding is not about cost.** The Gemini parse path — C11's designated
fallback for every scheme det cannot handle — fails on half of them and
systematically by size (**0580 82% / 0625 33% / 0606 0%**; failures average 10.0
pages and 11,637 chars against 7.3 and 8,608). Truncation is ruled out by
measurement (65,536 limit, largest success 26,571), and it is not fully
deterministic — the probe failed, then succeeded unchanged. **This was invisible
because the 2026-08-26 run aborted at 6 of 190 on cost, and all 6 happened to
succeed.**

Recorded as **DA31**. Opened as **#166 (`owner:human`)**, which now carries the
one remaining decision: diagnosing a single 0606 failure with logging costs
**~$0.15 of the $2.01 headroom** left against the $8.00 ceiling. I did not spend
it. **The 12 parsed schemes are kept, and must not be used as stratum coverage.**

**Ledger: 3.146479 -> 5.993470. Headroom: $2.01.**

**Also ruled and executed: C21 — no hard token ceiling.**
`per_run_token_ceiling` is `None`; the committed **$8.00 `total_usd_ceiling` is
the sole guard** (DA32). The gitignored 5M override was removed, as C12 required
for the dollar ceiling.

## C9 — B14, as it stood at run 58 (SUPERSEDED by C22–C25 above for #51/#52/#55)

Kept verbatim so the run-58 state is readable. **Do not act on this copy** —
#51 is governed by C24, #52 by C23, #55 by C25. Only the #49 bullet still
stands as written, and C25 removed it as a gate on #55.

- **#49 (H4)** — split membership stays **NOT frozen** until #57 delivers and you
  sign off. **Correction:** #57's bullet 1 (propose the split) is agent work and
  does **not** need #49 — it is blocked on **#88 / C15**, whose sweep would
  populate DA1's empty Gemini-path strata. C11 removed the other blocker
  (#151 would have collapsed the parse-path stratum axis; it no longer can).
- **#51 (H7)** — **identity ANSWERED (C14): labeller B is Abdallah ElGammal,
  co-founder.** So H7 is genuine **inter-rater** agreement, not self-agreement,
  and may be published as such. **Onboarding is still owed**, and #47's
  labelling protocol must be designed for **two seats from the outset** —
  retrofitting later may mean re-labelling, not just labelling more.
- **#52 (H8)** — the three seed rulings themselves (ECF, `oe` alternatives, list
  rule over-tariff). The machinery is built and the log ships empty; the rulings
  are examiner judgment and I will not draft them.
- **#55 (H9)** — authorisation for the single run of the frozen test split.

---

# ANSWERED 2026-08-27 (run 57) — standing rulings, do not re-argue

| # | Subject | Ruling |
|---|---|---|
| **C11** | #151 / C6 | **C6 SUPERSEDED.** *"det parses any & all mark-schemes, as well as MCQ correction. Gemini handles ALL question paper extraction & the marking of non-MCQ papers."* Verified at source, then **confirmed rather than assumed**, as the architecture already in place. **Nothing migrates**; the $11.92–$28.02 never arises; #112/#110/#136/#39/#41/#95/#127/#38 are live work again; **#53 (M3) is not voided**; DA1's parse-path axis survives. #151 CLOSED. **DA27.** |
| **C12** | the ceiling | **The COMMITTED $8.00 is authoritative** (`config.py:111`). The gitignored $25.00 has been **removed** from `lemely.toml` with a comment saying why — it did not survive worktree deletion, CI could not see it, and the report was publishing it as real headroom. Headroom is now **$4.853521**. Raise the committed default; never re-add a gitignored override. **DA28.** |
| **C13** | #161 / ratchet | **Publish an UPPER interval bound of the measured distribution and arm against that.** Not the mean (≈half of no-op diffs would fail) and never 29.03% (the bottom of the range; unchanged code exceeds it 7 times in 10). Do not re-run the A/A floor for a tighter number (§12.9); do not loosen the 0.10 target (§14). **DA29.** |
| **C14** | #51 / H7 | **Labeller B is Abdallah ElGammal, co-founder.** Named by explicit choice after being offered a role-only record. H7 is therefore **inter-rater**, not self-agreement. #47 must be designed for two seats from the outset. **DA30.** |

**RESOLVED without a ruling:** **C10** (B17's `comment` half) — implemented and merged as **#153**; `accuracy_board.py comment` now works off-board, and the `done`-refuses / `comment`-allows asymmetry is pinned by test.

---

# ANSWERED 2026-08-27 (run 55) — standing rulings, do not re-argue

| # | Issue | Ruling |
|---|---|---|
| **C1** | #112, #110, #136-fix | Marking sweep **WAIVED** on the instrument-blindness ground #38 got under A6(a) and #93 under B2 — `load_golden_cases` (`harness.py:130`) never invokes the det parser, so both arms are identical inputs. In its place: a **zero-spend deterministic before/after re-parse** of the 289 schemes under `corpus/` (`parser_sha 8758dba`), checked against #112's pre-stated prediction of strict deflation (77–246 marks). B15 is **not** reopened. |
| **C2** | #38 b2+3 | **Defer behind #136's fix, then re-measure.** The 44.4%-of-papers / 21.6%-of-points defaulted rate is contaminated by DA21 mechanism (B). Bullets stay **open and unticked** — nothing closed on a falsified premise. |
| **C3** | #39 | **Same waiver as C1**, with a zero-spend deterministic before/after over `corpus/` standing in — measuring how many schemes the gate **reroutes**, not what Gemini then marks. Caveat attached by the human: #39 is **cost-changing**, so the reroute count is itself the number to watch. Bullet 9's zero-false-positive requirement **holds**. |
| **C4** | #58 | **~14 calls / ~$0.01 AUTHORISED** to close bullet 3 on live evidence (the offline "7 held" must not stand in for it). **No new issue** for q11b — it stays recorded on #58 as reproduced-but-not-significant (Fisher p = 0.4737). §12.9 still forbids re-running at higher n. |
| **C5** | #127 | **Fold into #95.** One corpus-membership restatement instead of two. Chain: #151 → #136 fix → #95 → this. |
| **C6** | #41 → programme-wide | **Deterministic parsing for MCQ ONLY.** Asked twice; the broad reading was confirmed against an option stating it "largely moots #112, #110, #136 and #39". **Now costed and forked as C8 / #151** — it is not executable as ruled without a ceiling decision. |
| **C7** | #59 | **Both blockers authorised** — commit the handwritten CAIE renders (MISSION §12.7 granted, scoped to #59) and run the measurement (costed preflight first, per #28). The public-repo irreversibility point was flagged once and the ruling reaffirmed with it in view. |

**Carried forward from the B list, still binding:** B3 (0.99 is INHERITED-NOT-MEASURED, no follow-up issue), B5 (whitespace fixtures are ordinary golden cases; their consequence — restating every figure against the new membership — is **unspent, not skipped**), B12 (per-mark-point is the published H7 figure; `mark_point_verdicts` still declared and never read), B15 (fix all three sub-defects — the *what*; only its sweep clause was superseded by C1), B16 (`cumulative_usd` is a known-contaminated **upper bound**; re-sum every run, never carry the header forward).

**Sequencing as it now stands (rewritten after C11):** **#88 (C15)** is the only
gate on the measurement chain — #88 → #57 → #49 → #47 → #51 → #55. Everything
else is agent work with a path: **#136's fix** → #95 → #127, and #38's
re-measurement; **#112 + #110 jointly** under C1's waiver; **#39** under C3's;
**#41** under B1. **#161** is now actionable under C13. #59's measurement is
authorised with a $4.00 cap but is n≤2 and needs its synthetic counterpart arm
built first.
