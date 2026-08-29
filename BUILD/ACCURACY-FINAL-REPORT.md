# The Accuracy Programme — closing account

**Retired 2026-08-29 under human ruling C26. Decision record DA51.**
Twelve days, 24 issues closed at the end, $6.370451 spent of an $8.00 ceiling.

This is the last document the programme produces. It exists to be read by someone
who was not here, so it states what was achieved, what was not, and which of the
two each number belongs to.

---

## The verdict, first

The programme was **retired, not completed.** Its own Definition of Done
(`ACCURACY-MISSION.md` §13, eight clauses) is **not met**, and retiring it does not
make it met.

It set out to achieve one thing:

> **A wrong mark can be attributed to extractor or marker with published statistical
> backing, and the review rate falls toward the 10% budget while the wrong-mark catch
> rate at least doubles (from 3/11 toward ≥6/11) — the review rate must fall, never
> rise.**

**None of the three landed.**

| the objective | outcome |
|---|---|
| Attribute a wrong mark to extractor or marker | **No measurement exists.** The oracle-transcription 2×2 that would attribute it was never run; `ablation_2x2()` returns `b = c = n_pairs = 0` and the published verdict is `NOT_APPLICABLE`. |
| Review rate falls toward 10% | **It did not fall.** Measured mean **32.58%** over 10 live repeats (range 29.03–41.94%), ~3.3× the budget. |
| Wrong-mark catch rate doubles, 3/11 → ≥6/11 | **Never re-measured.** No catch-rate or flag-recall figure appears anywhere in `ACCURACY-REPORT.md`. |

**What it did achieve is real and is not the objective:** it built the instrument
that made these three statements sayable with numbers attached. Before this
programme the honest answer to all three was *"we don't know"*. It is now
*"no, no, and we still don't know — here is the n"*. That is progress of a
specific and limited kind, and it is the kind this report claims.

---

## The §13 clause walk at retirement

| # | clause | status |
|---|---|---|
| 1 | Every non-H sub-issue of #24/#35/#43 closed via merged PR | **NOT MET** — 8 open (#38, #39, #41, #58, #47, #57, #59, #88), plus 6 off-epic defect issues (#95, #110, #127, #136, #161, #166) |
| 2 | Baseline, A/A floor, funnel and ratchet published **and enforced in CI** | **PARTIAL** — all published; the gate runs on every test job, but `review_rate_ratchet_armed=False` (`config.py:190`), so it exits 0 on a breach. Observation, not enforcement. |
| 3 | The ablation 2×2 published, **or its absence** | **MET** — by publishing its absence. `NOT_APPLICABLE` with the reason. |
| 4 | ~300 labelled real leaves + published inter-rater agreement | **NOT MET** — **zero labels exist.** `eval/labels/` holds one file and it is `.gitkeep`. |
| 5 | Both paths measured in their own terms | **BOTH HALVES SHORT** — det parse coverage measured (393/1,130 = 34.8%); Gemini marking accuracy measured on 23 leaves against a clause asking for 10,314 answer points |
| 6 | Review rate at or below the ratchet, recall not below baseline | **NOT MET** — 32.58% against a 10% budget |
| 7 | develop→main PR open for human approval | **MET** — #159 open, green, 105 commits. Left open: merging to `main` is human-only (§12.3). |
| 8 | Open H issues cleanly documented as awaiting their human | **MET** — each carried a current statement when closed |

**One clause met on substance, one met by publishing an absence, one met by leaving
a PR open, five short.**

### M0 came closest, and "all sub-issues closed" was not acceptance

All 12 sub-issues of #24 are closed. That is **not** the same as M0's acceptance
being met, and the difference is the single most instructive thing in this report.

#24's acceptance **box 3** reads *"the honest baseline split into
extraction-attributable, marking-attributable and masked components"*. **That split
does not exist.** Its source, #28 (M0.4, the 2×2), is closed on GitHub with
`stateReason: COMPLETED` and **all four of its acceptance boxes unticked**:

```
- [ ] Both arms run over all fixtures
- [ ] ablation_2x2 cross-tabulates oracle+mark against extract+mark per question
- [ ] Four cells reported: both-correct; extraction-attributable; marking-attributable; masked
- [ ] Reported as a lower bound on extraction share …
```

Leaving them unticked was the honest record and was deliberate — §13 clause 3
exists to publish that absence. But the issue still closed as *completed*, and a
closed sub-issue is what a milestone count reads. **That is the mechanism by which
M0 came to look finished.** The oracle+mark arm produced zero records; the 2×2 was
deferred to #57's corpus expansion; #57 never completed.

So the milestone whose entire purpose was *attribution* closed without the
attribution measurement — and a sub-issue count says it finished.

(#24's box 5 is worse than unmet: it requires the ratchet to record *"19.1% as its
starting value"*, and 19.1% was **retracted** by DA-M0.9. The box could not be
ticked truthfully by the end, whatever was built.)

**The first draft of this report said "M0 completed in full."** It was corrected
after adversarial review of the retirement text itself. Counting closed
sub-issues and calling it done is exactly the move §14 names as programme
failure, and it was made while writing the document that retires the programme
for making moves like that.

---

## What was actually built and merged

The instrument is real, it is on `develop`, and it works. Every item below landed
through a reviewed PR:

| what | evidence |
|---|---|
| `lemely/eval` — `EvalRecord`, `RunManifest`, pure analyses (`ablation_2x2`, `mcnemar`, `wilson`, `risk_coverage`, `exclusion_funnel`, `review_rate`) | #25, PR #71 `d5a8424` |
| Determinism substrate — generation params, cache fingerprint | #26, PR #67 `49bc6cd` |
| `--cache-mode bypass` seam — the thing that makes an A/A run measure anything at all | #77, PR #78 `c66ef5b` |
| A/A churn floor, published with its n | #27, PR #82 `dc77784` |
| Honest denominators — D18 fixed, exclusion funnel, abstention as an outcome | #29, PR #81 `465fe34` |
| Paired statistics — McNemar, Wilson, n-floors | #30, PR #79 `199841b` |
| Frozen split mechanism + test-touch ledger + CI assertion | #31, PR #68 `47977cf` |
| Golden fixtures carry `parent_id` / `is_excerpt`; nested multi-part fixture | #32, PR #74 `1e18f05` |
| Review-rate ratchet as a CI gate (wired, running, unarmed) | #33, PR #80 `202702a` |
| Fixture renderer repaired, golden corpus regenerated | #56, PR #65 `4853f3a` |
| Coherence gate — awarded marks reconcile with matched point ids | #40 |
| Positional fallback deleted; `UNMATCHED` with id provenance | #37 |
| Corpus restored via PaperScraper, then expanded to 2010–2025 (1,130 schemes) | #44; #189 `fb80579` |
| Two-pass blind labeller, hash-chained rulings log, two-seat protocol | #46, #98 |
| CAIE Generic Marking Principles threaded into the marker prompt | #41 code half, PR #181 `81bf1eb` |

**The decision record is itself a deliverable**: `BUILD/DECISIONS.md`, 13,700 lines,
DA1–DA51 and rulings C1–C26. It records what was decided, why, and what was
rejected — including the reasoning that was later falsified.

---

## The numbers, each with its population

Every figure below carries the population it was measured on. That is not a
formality here: the headline det figure **halved** when the population changed,
and nothing about the parser changed with it.

### The instrument's own noise floor

| figure | value | n |
|---|---|---|
| Pairwise leaf-outcome churn | **11.61%** | 162/1,395 pair-leaf comparisons |
| Churn, `det` path | **0.00%** | 0/360 |
| Churn, `gemini` path | **15.65%** | 162/1,035 |

Run `aa-floor-2026-08-23-a`, `cache_mode=bypass`, ~740 real calls, $0.958711 (DA9).
**Any A/B delta on the gemini path below 11.6pp is noise.**

### Accuracy

| figure | value | n | population |
|---|---|---|---|
| Leaf accuracy, pooled | **75.8%** | 235/310 leaf-repeats | 31-leaf golden corpus |
| Marking accuracy, **gemini** path | **69.6%** | 23 leaves, Wilson 49.1–84.4% | same |
| Marking accuracy, **det** path | 100% | 8 leaves, Wilson **67.6**–100% | same |

**The headline blended a 100% path with a 70% path, weighted backwards.** MCQ
schemes carry **zero** answer points; the Gemini path carries **10,314 of 10,314**.
So the path responsible for every answer point in the corpus measures **69.6%**,
while the headline was pulled up by a path carrying none of them. det's 100% is 8
MCQ leaves from one paper with a Wilson lower bound of 67.6% — it is not evidence
that det is perfect.

### Review rate

| figure | value |
|---|---|
| Mean over 10 live repeats | **32.58%** (range 29.03–41.94%) |
| Budget | **10%** |
| Committed comparison constant, restated under C13 | **0.4838** |
| Ratchet | **never armed** |

The restatement (#161/DA33) moved the constant from 0.2903 to 0.4838 and
**did not unblock arming** — that was its finding. All four gate limbs fail, and
three fail on *absolute* targets (`signal` by 3.6×, `total` by 2.9×, `p95` by 5.6×)
that no value of `last_merged` can move. **Arming needs the review rate to come
down. It never did.**

### det parse coverage — the figure that halved

| population | schemes | exact | rate |
|---|---|---|---|
| 2019–2025 | 477 | 331 | 69.4% |
| 2010–2018 | 299 | 62 | 20.7% |
| **all canonical (2010–2025)** | **1,130** | **393** | **34.8%** |

The 2019–2025 row **reproduces the earlier 331 exactly**, which is what makes the
two populations comparable rather than merely different. **Nothing regressed. The
earlier figure was measured on the easy decade.**

### Cost

| | |
|---|---|
| Cumulative, four worktree ledgers, re-read at close | **$6.370451** |
| Committed ceiling | **$8.00** |
| Headroom never spent | **$1.629549** |

The ceiling was never breached, and no run was ever authorised without a costed
preflight.

---

## The five findings worth keeping

These outlive the programme. They are about the problem, not about the process.

**1. The det path's reach is bounded by CAIE's 2016/17 layout change, not by parser
quality.** Pre-2017 mark schemes have no ruled row separators, so pdfplumber returns
a whole page of questions as one 2-row table with the boundaries as newlines inside
cells. The table qualifier rejects them **correctly**. Supporting that layout is a
*second parsing strategy*, not a tweak. **Expanding the corpus backwards does not
expand det coverage** — for 2010–2016 the Gemini path is the only route, and DA35
measured it failing on ~50% of what det cannot parse. (DA50)

**2. A fix can be correct, necessary, and buy exactly zero coverage.** The pre-2017
cover-page fix cleared 411 of 438 parse failures — 93.8%, every affected session
2010–2016. `exact` stayed at **393**. All 84 newly-parsing schemes landed in
`not_exact`, and in production those escalate anyway. *"84 more schemes parse"*
would have been true and misleading. **It moved the diagnostic picture, not the
routing.** (DA50)

**3. An error message is the code's guess, not evidence.** The remaining parse
failures say *"No tables found — may be a scanned PDF"*, and a report was half
written saying older schemes are scans and structurally out of reach. They are not.
The errored 2010–16 papers carry **more** extractable text per page than the papers
that parse (872 chars vs 1,029; 1.30 tables vs 0.95). **A guess printed in a
traceback was about to be promoted to a finding.** One command falsified it. (DA50)

**4. Making a measurement honest usually makes the number worse, and that is the
measurement working.** det coverage 69.1% → 34.8% when the population stopped being
the easy decade. The 2010–2018 exact *rate* fell 28.8% → 20.7% because a fix grew
the denominator and not the numerator. Same shape as DA39. **A programme that only
accepts numbers that improve will select for dishonest denominators** — which is
what D18 was.

**5. Claims rot in place, and the controls do not catch it.** Five instances in the
programme's final days: the MISSION's stale coverage figure (DA45), a superseded
published figure (DA46), a CI comment asserting the gate did not run when it did
(DA48), and — found only by reading every line of the report to retire it — the
report still publishing *"clause 5 MET, 331 of 479"* the day DA50 falsified it, plus
a stale spend table sitting directly beneath a written rule against stale spend
tables (DA51). Each was accurate when written.

> **The rule that came out of it:** a restatement is finished when **every artifact
> that published the superseded figure** carries it — not when the decision record
> does. DA50's own commit is the counter-example: it landed in `DECISIONS.md`,
> `JOURNAL.md` and the state header, and never touched the file that publishes the
> figures.
>
> **And the harder half:** none of the five was caught by a gate, a test, or CI.
> They were caught by a person reading prose for another reason. **This programme's
> controls bind code and do not bind prose**, and it published its claims in prose.

---

## What was never done

| gap | what it would take |
|---|---|
| **Zero of ~300 human labels.** The two-pass blind labeller, the hash-chained rulings log, the pre-committed relabel rule and salt, the two-seat protocol — all built. `eval/labels/` holds only `.gitkeep`. | A human sitting down and labelling, plus a second labeller for the agreement figure. Not a technical blocker; it was never a technical blocker. |
| **The 2×2 attribution measurement.** The programme's stated reason for existing. | A corpus expansion (#57) that completed, then the oracle+mark arm actually run. |
| **The review-rate ratchet, unarmed.** | The review rate to fall from 32.58% toward 10% — i.e. real M1 accuracy work. **Not** a flag flip, and **not** a looser target. |
| **Three unarmed detectors** — #38's all-defaulted variant (3 papers), #110 (15 schemes), #39 (4 questions). | All three route to the same Gemini fallback that DA35 measured failing ~50%. One decision, not three. |
| **The pre-2017 parsing strategy.** | A second parsing strategy for the pre-2017 layout — a real piece of work, correctly refused as a tweak. |
| **#166**: the Gemini mark-scheme fallback — the route for every scheme det cannot handle — fails **12 of 24 attempted (50%)**, systematically by size (failed schemes average 10.0 pages / 11,637 chars vs 7.3 / 8,608 for successes), at **$0.2372 per success**, 3.39× the projection, because failures still cost money and return nothing. By syllabus: 0580 9/11, 0625 3/9, **0606 0 of 3** — and that last denominator is 3, not a rate. | **Diagnosed, never fixed.** DA35 traced it to Pydantic validation, with the reason logged all along. |

---

## What retirement did, and deliberately did not do

**Did:**
- Closed all **24** open accuracy issues — **1 as completed, 23 as _not planned_.**
  The single completed one is **#136**, the det mark-total fix: all six acceptance
  bullets, two merged PRs, the arithmetic closing exactly. *Not planned* here means
  **retired unfinished**, not delivered. Each issue carries a closing comment naming
  what landed, what did not, and the evidence for both.
- Added the four off-board issues (#127, #136, #161, #166) to the project **first**,
  so the board could be cleared completely rather than mostly.
- Moved every board item to **Done**, where Done now means *"no longer being
  worked"* — stated on the board, not left for a green column to imply.
- Corrected two stale figures in `ACCURACY-REPORT.md` and added the population
  banner DA50's own rule required.
- Banner-retired `ACCURACY-MISSION.md` so any orchestrator or supervisor that
  resumes reads **STOP** before it reads a queue.

**Deliberately did not:**
- **Merge PR #159 (develop → main).** §12.3 reserves merging to `main` for the
  human; asked directly, the human kept it that way. It is open, green, 105 commits
  ahead.
- **Close #10–#22.** Separate product work — sign-up flows, payments, hosting,
  CI/CD. Retiring this programme is not licence to clear someone else's board.
- **Merge any leftover branch.** Checked rather than assumed: every substantive
  artifact on the surviving branches is already in `develop`
  (`TestC13RestatementDidNotLoosenTheGate`, DA33/DA35–DA38, C22–C25, and every
  `BUILD/accuracy-runs/` directory). The two branches carrying genuinely unlanded
  work are orchestration tooling for a programme that no longer runs — and one of
  them adds *"allow merging without CI under an explicit, recorded waiver"*, which
  is not something to land unreviewed as a retirement tidy-up.
- **Mark unfinished work "completed"** to make the board look finished.

### One divergence resolved on the way out

**#49, #51, #52 and #55 read _Done_ on the project board while their issues were
OPEN and the human input they waited on had never arrived.** `accuracy_board.py
done` refuses H-numbered and `owner:human` issues, so the board status was set by
some path that bypassed that guard. **The issue state was the truth; the board was
the stale copy** — the same failure mode as the stale figures, in a different
tracker. Closing them under C26 made both say the same thing: closed, unanswered.

---

## If anyone picks this up again

1. **Read `BUILD/DECISIONS.md` before re-deriving anything.** DA1–DA51 record
   experiments that were actually run. The evidence log at the top of
   `ACCURACY-STATE.md` (E1–E4) exists specifically so they are not repeated.
2. **§14's anti-goals still bind**, whatever replaces this. Do not arm a gate by
   moving its target. Do not narrow a denominator to improve a figure. Do not
   report a diagnostic change as an improvement. Each was earned here.
3. **The labels are the bottleneck, and always were.** Every improvement claim in
   M1 and beyond waits on ~300 labelled real leaves. The machinery is built and
   tested. It has never had a labeller.
4. **The instrument is trustworthy and is on `develop`.** Whatever comes next can
   measure itself honestly from day one, which this programme could not.

---

*Recorded under ruling C26. Reasoning in `BUILD/DECISIONS.md` DA51; narrative in
`BUILD/JOURNAL.md` `run-2026-08-29-m`; figures in `BUILD/ACCURACY-REPORT.md`.*
