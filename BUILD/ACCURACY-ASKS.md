# ACCURACY-ASKS.md — the open human decisions, in one place

**Status 2026-08-27 (run 57): C8 and C10 are CLOSED and the queue is
UNBLOCKED.** The B1–B18 list was discharged at run 55; C1–C7 were taken the same
day; **C11–C14 were taken in a second interview on 2026-08-27** and are recorded
below as standing rulings, not open questions.

**C11 unblocked everything.** Ruling C6 (*"deterministic parsing for MCQ ONLY"*)
was **superseded**: det parses all mark schemes and marks MCQ; Gemini does all
extraction and marks non-MCQ — which is the architecture already in place. So
#112, #110, #136, #39, #41, #95, #127 and #38 are **live work again**, not dead,
and the $11.92–$28.02 migration costed on #151 **never arises**.

**What is actually open now: C9 (the four H issues), and #88.** Everything else
is agent work with a path.

Nothing here is a request for more investigation — each row is a decision only
you can make. Where I have a recommendation I give it, and where a
recommendation of mine would be self-serving (cheaper, or avoids a
measurement) I say so.

**How to answer.** Reply on the accuracy control topic
(`lemely-acc-ctl-bqlsqcY9FfbfQd` on `http://home-server:7532`), or append to
`BUILD/ACCURACY-INBOX.md`, naming the ask number and your choice — e.g.
`C15: (1)`. Partial answers are useful.

**If you answer only one: C15.** It is the only thing gating a measurement the
programme needs, and #57 → #47 → #51 → #55 all sit behind it.

---

# OPEN

## C15 — #88: the corpus parse sweep costs $13.31 and the ceiling is now $8.00

**Carried over unresolved, and C12 has made it harder rather than easier.**

#88's item-2 sweep — Gemini-parsing the **190 mark schemes the det parser fails
outright** — was authorised at a costed $7.26, then **measured at n=1, confirmed
at n=6, and aborted at 6 of 190** because the real figure is **$13.31** (1.83×).
Three causes, all structural: input 2.07× under (PDF via Files API, not billed
per page), output 1.35× under (~36% thinking tokens, which a det-JSON proxy
**cannot represent at any sample size**), and 1.33 calls per scheme, not 1.00.

**Ruling C12 made the committed $8.00 authoritative**, so from a ledger of
**$3.146479** the headroom is **$4.853521** — and $13.31 does not fit. It fitted
under the gitignored $25.00 that C12 removed.

**Why it matters, and it now matters more than before.** Ruling C11 says *"det
parses any & all mark-schemes"*. That is true of what det **can** parse — but
**190 of 479 source schemes have no parsed output at all**. This sweep is what
would make C11 literally true. It also populates DA1's **empty Gemini-path
strata**, which is what #57's split needs, which is what #47's labelling needs.

1. **Raise the committed ceiling and proceed at $13.31.** Ledger → ~$16.5. Needs
   a committed figure from you (C12 says raise the default, never re-add a
   gitignored override), and `per_run_token_ceiling` raised 5M → ~9M, since #88
   measured 7.25M against a 5M ceiling that would trip at roughly scheme 131.
2. **Proceed over a reduced set.** Note this changes DA1 stratum coverage, which
   is the entire justification for the spend — **not a free trim**.
3. **Do not proceed.** The nine Gemini-path strata stay empty, #57 keeps its
   parse-path axis unpopulated, and C11's *"any & all"* stays aspirational.

**No recommendation.** Option 1 spends your money on my say-so; option 3 is the
one that costs me nothing, which is exactly why I should not push it. **The 6
schemes already parsed cost $0.42 and are kept whichever way you go.**

## C9 — B14, still owed on the H issues

Unchanged, and not decisions I can make or work around (MISSION §3.5 — never
close one, never mark one done, never work around one):

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
