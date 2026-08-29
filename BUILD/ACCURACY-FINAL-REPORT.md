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
| Review rate falls toward 10% | **It was never brought near the budget** — mean **32.58%** over 10 live repeats (range 29.03–41.94%), ~3.3× the 10% target. *No before/after trajectory exists*: the 19.1% start point was retracted by DA-M0.9 and ruling C16 deliberately left the mission without one, so "fell" and "rose" are both unsayable. |
| Wrong-mark catch rate doubles, 3/11 → ≥6/11 | **It fell.** `flag_recall` on the honest post-D18 run (`run-ef443fc2931e`) is **14.29%, n=71 rows** — against the 27.3% (3/11) the target was set from. The goal was ≥54.5%. |

**One moved the wrong way, one never approached its target, and the third cannot
be answered at all.** The catch rate is *below* the figure the target was set
from. The review rate sits ~3.3× over budget with **no trajectory available in
either direction** — ruling C16 deliberately removed the mission's start point
after DA-M0.9 retracted 19.1%, so "it fell" and "it rose" are both unsayable and
this report says neither. Neither number is a regression caused by this work: they
are what the figures look like once the denominators are honest, and the old 27.3%
and 19.1% were both measured before D18 was fixed.

> **The pattern is worth naming, because it recurs in everything below.** When
> `mark_accuracy` was restated post-D18 it moved *up* (83.8% → 90.1%) and was
> promptly relabelled "historical, superseded". `flag_recall` and
> `flag_precision_high` moved *down* in the very same run and kept their
> better-looking legacy numbers in `DELIVERY.md`, `CHANGELOG.md` and
> `docs/ACCURACY-STRATEGIES.md`. **Only the flattering restatement got
> published.** That is selective disclosure and the same family of defect as D18
> itself — caught and corrected during #29, and recorded rather than quietly
> fixed.

**What the programme did achieve is real, and it is not the objective:** it built
the instrument that makes those three statements sayable with numbers attached at
all. Before it, the honest answer to each was *"we don't know"*. It is now *"3.3×
over budget with no baseline to compare against, down from 27.3% to 14.29%, and
the third has no measurement — here are the n's"*. That is progress of a specific
and limited kind, and it is the only kind this report claims.

---

## The §13 clause walk at retirement

| # | clause | status |
|---|---|---|
| 1 | Every non-H sub-issue of #24/#35/#43 closed via merged PR | **NOT MET** — 8 open (#38, #39, #41, #58, #47, #57, #59, #88), plus 6 off-epic defect issues (#95, #110, #127, #136, #161, #166) |
| 2 | Baseline, A/A floor, funnel and ratchet published **and enforced in CI** | **PARTIAL** — all published; the gate runs on every test job, but `review_rate_ratchet_armed=False` (`config.py:190`), so it exits 0 on a breach. Observation, not enforcement. |
| 3 | The ablation 2×2 published, **or its absence** | **MET** — by publishing its absence. `NOT_APPLICABLE` with the reason. |
| 4 | ~300 labelled real leaves + published inter-rater agreement | **NOT MET** — **zero labels exist.** `eval/labels/` holds one file and it is `.gitkeep`. |
| 5 | Both paths measured in their own terms | **PARTIAL** — both halves exist as measurements; **neither is at the scope the clause names.** det coverage 393/1,130 = 34.8% (and the clause's own figure was superseded); Gemini marking accuracy on 23 leaves against a clause asking for 10,314 answer points |
| 6 | Review rate at or below the ratchet, recall not below baseline | **NOT MET** — both limbs fail: 32.58% against a 10% budget, and recall fell |
| 7 | develop→main PR open for human approval | **MET** — #159 open, green, 106+ commits ahead of `main`. Left open: merging to `main` is human-only (§12.3). |
| 8 | Open H issues cleanly documented as awaiting their human | **MET** — each carried a current statement when closed |

**Three MET (3, 7, 8), two PARTIAL (2, 5), three NOT MET (1, 4, 6)** — and the
three METs are worth reading before they are counted as achievement. **Clause 3 is
met by publishing an absence. Clause 7 by correctly declining to merge. Clause 8 by
keeping four human-blocked issues honestly annotated.**

> **Not one of the eight is met by the programme having produced the outcome it set
> out to produce.** Three of them are met by being honest about not having produced
> it. That is a real property of this programme and worth more than it sounds — but
> it is not the same as working.

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

| population | **source** schemes | parsed | exact | exact / source |
|---|---|---|---|---|
| 2019–2025 | 479 | 477 | 331 | **69.1%** |
| 2010–2018 | 651 | 299 | 62 | **9.5%** |
| **all canonical (2010–2025)** | **1,130** | **776** | **393** | **34.8%** |

The 2019–2025 row **reproduces the earlier 331 exactly**, which is what makes the
two populations comparable rather than merely different. **Nothing regressed. The
earlier figure was measured on the easy decade.**

> **This table is republished on one basis, because the original mixed two.** As
> first published (DA50, and `corpus-expanded-2026-08-29/RESULT.md`) the two era
> rows used **parsed** schemes as their denominator — 477 and 299 — while the "all"
> row used **source** schemes, 1,130. Under one column header. That made the
> old-decade rate read **20.7%** (62/299) when the honest source-basis figure is
> **9.5%** (62/651), and it flattered the era that was already the problem.
>
> **The finding gets stronger, not weaker, once the basis is consistent: 589 of the
> 651 pre-2019 schemes have no reconciling parse at all.** Recounted directly from
> `coverage.json`'s per-scheme array: source 479 / 651 / 1,130, parsed 477 / 299 /
> 776. Found by adversarial review during retirement, not by a gate.

### Two more measurements worth keeping

| figure | value | population |
|---|---|---|
| **det defaulted-mark rate**, clean (post-#136) | **34.26%** of papers carry ≥1 defaulted mark | 397 det-parsed papers, both arms over the same set |
| **Gemini mark-scheme fallback** success rate | **12 parsed of 24 attempted (50%)**, $0.2372 per success | C20 budget-bounded sweep, hard cap $3.00 |
| **Metamorphic properties** (label-free, no ground truth needed) | id-renaming **57 held / 0 violated**; whitespace **7 / 0**; mark-point reordering **1 violation, unresolved** | golden corpus, live, `cache_mode=bypass` |

The metamorphic result is the programme's one genuinely label-free instrument — it
tests the marker against *itself* under transformations that must not change the
answer, so it needs no ground truth. **It is the only M1 measurement that would
still have worked in a world where the ~300 labels never arrived, which is the
world that happened.**

The one violation is honest about its own limits and is why #58 closed unfinished.
`0625_s20_qp_31_theory_partial` q11b went 1 mark → 2 under `reorder_mark_points`.
The settling run re-marked that single leaf 10× per arm: **2/10 perturbed produced
≥2 marks, 0/10 unperturbed did, Fisher exact two-sided p = 0.47.** That is
**underpowered, not exonerating** — it establishes neither that the property fails
nor that it holds, and it was left unticked rather than rounded to either.

### Cost

| | |
|---|---|
| Cumulative, four worktree ledgers, re-read at close | **$6.370451** |
| Committed ceiling | **$8.00** — `config.py:111` |
| Headroom never spent | **$1.629549** |

The ceiling was never breached, and no run was ever authorised without a costed
preflight. C20's #88 sweep — $2.847 of the total, the single largest — held its own
$3.00 cap exactly.

**Three caveats, all of them conservative, all recorded in the programme's own
record rather than discovered at retirement:**

1. **`cumulative_usd` is an upper bound on money spent, not money spent** (DA17).
   Some tests resolved `paths.output_dir` to the real repo and banked mock-derived
   costs into the authoritative ledger before #114 was found. The contamination is
   **one-directional** — a test can only add — so every ceiling check computed
   against it stays conservative. It was deliberately **kept, not backed out**: the
   file holds one running total with no history, so re-baselining would trade a
   known-conservative figure for a reconstructed one.
2. **The enforcing guard never sees this sum** (DA32). `GeminiClient` builds its
   ledger path from `settings.paths.output_dir` (`gemini.py:162`), so the ceiling
   check reads **only the local worktree's file**. The programme-wide figure is
   published and summed by hand; nothing enforces it.
3. **$0.00064 of the total is pre-programme spend** — the
   `research-accuracy-tuning` ledger was last written 2026-08-14, before this
   programme began, and is counted in rather than netted out.

The $25.00 override that once sat in `lemely.toml` was removed under ruling C12
(DA28): it was gitignored, invisible to CI, and did not survive worktree deletion,
so **the only durable ceiling is the committed $8.00**.

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
the easy decade. The 2010–2018 exact *rate* fell 28.8% → 20.7% (both on the
**parsed** basis) because a fix grew the denominator and not the numerator — and on
the consistent **source** basis that rate is **9.5%**, lower still. Same shape as
DA39. **A programme that only accepts numbers that improve will select for
dishonest denominators** — which is what D18 was, and the mixed-denominator table
above is how it comes back.

**5. Claims rot in place, the controls do not catch it, and there are more than you
think.** The programme's final days turned up the MISSION's stale coverage figure
(DA45), a superseded published figure (DA46), and a CI comment asserting the gate
did not run when it did (DA48). Retiring it turned up more, all in
`ACCURACY-REPORT.md`, the one file whose job is publishing figures:

| stale claim | corrected to |
|---|---|
| *"clause 5 MET, det parse coverage now 331 of 479"* | 393 of 1,130 = **34.8%** (DA50 falsified it the same morning) |
| Spend table `$5.993470` | **$6.370451**, re-read at close — sitting directly beneath a written rule against carrying a spend figure forward |
| *"the 3 luckiest of 10 repeats"* | **four** repeats at the minimum — counts are `[11,9,9,10,10,9,11,13,9,10]` |
| *"unchanged code exceeds it 7 times in 10"* | **10 of 10** exceed the stored constant; 7-in-10 was DA9a's estimate, superseded by DA33 |
| The committed constant *29.03%* | **0.4838** under ruling C13 |
| Defaulted-mark rates *44.4% / 21.6%* (60-PDF sample) | **34.26% / 8.94%** over 397 papers (DA46) |
| The det coverage table's era rows | denominators were **mixed** — parsed for the eras, source for the total; republished on one basis |

Each was accurate when written. **None was caught by a gate, a test, or CI** —
every one was found by a person reading prose for another reason, and only because
retirement forced a read of every line.

> **The rule:** a restatement is finished when **every artifact that published the
> superseded figure** carries it — not when the decision record does. DA50's own
> commit is the counter-example: it landed in `DECISIONS.md`, `JOURNAL.md` and the
> state header and never touched the file that publishes figures.
>
> **And the part that should temper this whole report:** the list above is what one
> pass found. It is not a proof that the file is now clean. **These controls bind
> code and do not bind prose**, and this programme published its claims in prose.

---

## What was never done

| gap | what it would take |
|---|---|
| **Zero of ~300 human labels.** The two-pass blind labeller, the hash-chained rulings log, the pre-committed relabel rule and salt, the two-seat protocol — all built. `eval/labels/` holds only `.gitkeep`. | A human sitting down and labelling, plus a second labeller for the agreement figure. Not a technical blocker; it was never a technical blocker. |
| **The 2×2 attribution measurement.** The programme's stated reason for existing. | A corpus expansion (#57) that completed, then the oracle+mark arm actually run. |
| **The review-rate ratchet, unarmed.** | The review rate to fall from 32.58% toward 10% — i.e. real M1 accuracy work. **Not** a flag flip, and **not** a looser target. |
| **Three unarmed detectors** — #38's all-defaulted variant (3 papers), #110 (15 schemes), #39 (4 questions). | All three route to the same Gemini fallback that DA35 measured failing ~50%. One decision, not three. |
| **The pre-2017 parsing strategy.** | A second parsing strategy for the pre-2017 layout — a real piece of work, correctly refused as a tweak. |
| **#166**: the Gemini mark-scheme fallback — the route for every scheme det cannot handle — fails **12 of 24 attempted (50%)**, systematically by size (failed schemes average 10.0 pages / 11,637 chars vs 7.3 / 8,608 for successes), at **$0.2372 per success**, 3.39× the projection, because failures still cost money and return nothing. By syllabus **as the sweep measured it**: 0580 9/11, 0625 3/9, **0606 0/4** — summing to the 12 of 24. (After #136 landed, three of those schemes began to det-parse and left the fallback population, so 0606 is **0 of 3** on the current population, DA35. Both are true of different sets; quoting one row from each makes the column sum to 23.) | **Diagnosed, never fixed.** DA35 traced it to Pydantic validation, with the reason logged in the response all along. |

---

## What retirement did, and deliberately did not do

**Did:**
- Closed all **24** open accuracy issues — **none as completed, all 24 as _not
  planned_.** *Not planned* here means **retired unfinished**, not delivered. Each
  issue carries a closing comment naming what landed, what did not, and the
  evidence for both.

  > **#136 was going to be the one exception, and it did not survive review.** Its
  > first five acceptance bullets are genuinely met — four mark-total defects fixed,
  > all four blocking schemes reconciling exactly at delta 0, regression tests
  > named, the three regressions listed individually rather than folded into a pass.
  > I checked `blocking.json` and the test classes myself and they hold. **Bullet 6
  > does not**: it asks for *"#95 unblocked, or #95's route re-decided by the
  > human"*, and `golden-reparse-95-2026-08-29/FINDINGS.md` ends with #95 **not
  > executable as written** — its excerpt blocker stands, and the three options it
  > lays out carry an explicit *"no recommendation"*. Neither disjunct happened.
  >
  > **So the closing sweep's honest yield is zero of twenty-four**, and I reached
  > "one" by verifying the bullets I could see and taking the last one on trust —
  > the same move, in miniature, that this report criticises #28 for.
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
  human; asked directly, the human kept it that way. It is open, green, and 106+ commits
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

## The closing ledger — every issue and its disposition

`completed` would mean the acceptance criteria are met by merged work. **No issue earned it.** All twenty-four are `not planned` — retired unfinished.


### Epics

| issue | disposition | the honest remainder |
|---|---|---|
| [#23](https://github.com/LemelyIG/Lemely/issues/23) Extraction & Marking Accuracy Programme | not planned | All 6 sub-issues of #23 (#24, #35, #43, #53, #54, #55) are OPEN; none closed. §13 clause 1 NOT MET: 8 non-H sub-issues of #24/#35/#43 remain open … |
| [#24](https://github.com/LemelyIG/Lemely/issues/24) Instrument | not planned | Box 3 NOT MET. That box names exactly the three cells of the M0.4 2x2 — extraction-attributable, marking-attributable, masked — and the 2x2 does not … |
| [#35](https://github.com/LemelyIG/Lemely/issues/35) Provably-Broken Fixes | not planned | 4 of 9 sub-issues remain open: #38, #39, #41, #58. Four of the six acceptance bullets are unmet. McNemar was never reported against the M0 baseline — … |
| [#43](https://github.com/LemelyIG/Lemely/issues/43) Ground Truth | not planned | The deliverable. Zero ground truth exists: eval/labels/ contains only a zero-byte .gitkeep and eval/rulings.jsonl is 0 lines — 0 of ~300 labelled … |
| [#53](https://github.com/LemelyIG/Lemely/issues/53) Parse-Path Parity and Mark-Scheme Fidelity | not planned | The single acceptance criterion is unmet: no M3 spec was ever written. docs/superpowers/specs/ holds five files and none of them is an M3 re-plan; … |
| [#54](https://github.com/LemelyIG/Lemely/issues/54) Judgment and Vision | not planned | Both acceptance boxes. No M4 spec was written; the precondition (M0 and M2 producing numbers) never arrived, because M2 produced 0 of ~300 labels. … |

### M1 — provably-broken fixes

| issue | disposition | the honest remainder |
|---|---|---|
| [#38](https://github.com/LemelyIG/Lemely/issues/38) Defaulted-mark provenance and a real … | not planned | Three of four bullets. Bullet 2 (delete the minted point on over-sum papers, the 78-paper bucket) was never implemented — no deletion code exists … |
| [#39](https://github.com/LemelyIG/Lemely/issues/39) Fidelity gate: filtered under-sum, excerpt-scoped paper … | not planned | Six bullets, three of them retired unmet by explicit prior ruling rather than met. Bullet 2 (under-sum) was deliberately not implemented because it … |
| [#41](https://github.com/LemelyIG/Lemely/issues/41) Inject the CAIE Generic Marking Principles into the … | not planned | Bullet 4 never ran, and bullet 2 is met in prompt text but not in effect. The sweep was never authorised or executed: outputs/gemini_spend.json shows … |
| [#58](https://github.com/LemelyIG/Lemely/issues/58) Label-free metamorphic tests for the marker | not planned | Bullet 1 — reordering mark points does not change awarded_marks — is FALSE on live evidence and was deliberately left unticked. … |

### M2 — ground truth

| issue | disposition | the honest remainder |
|---|---|---|
| [#47](https://github.com/LemelyIG/Lemely/issues/47) Label ~300 distinct leaf questions across both passes | not planned | The labelling itself. ZERO of ~300 leaves are labelled: eval/labels/ contains only .gitkeep, in this worktree and in every other worktree checked … |
| [#57](https://github.com/LemelyIG/Lemely/issues/57) Freeze the split membership over the restored corpus | not planned | All three acceptance bullets. Bullet 1 (stratified split proposed) is blocked: DA1 fixes the strata as syllabus code × parse path (det/Gemini) × … |
| [#59](https://github.com/LemelyIG/Lemely/issues/59) Measure the synthetic-to-real transfer gap | not planned | The measurement. All four acceptance bullets are unticked: no extraction arm ran, no paired delta or interval was published, nothing qualifies any … |
| [#88](https://github.com/LemelyIG/Lemely/issues/88) Parse the restored corpus into structured mark schemes … | not planned | The issue's purpose — populating DA1's Gemini-path strata — was never achieved, and the last comment here says the 12 Gemini-parsed schemes must not … |

### Defects found mid-programme

| issue | disposition | the honest remainder |
|---|---|---|
| [#95](https://github.com/LemelyIG/Lemely/issues/95) harness: regenerate golden fixtures through the det … | not planned | The rebuild. Every scope bullet is unticked; no fixture delta was published, no invalidation statement written, no baseline re-established. Blocker 1 … |
| [#110](https://github.com/LemelyIG/Lemely/issues/110) det: the parser emits duplicate top-level question ids, … | not planned | Bullet 4 - the detector that FAILS LOUDLY - is only half done and was never ticked. The detector exists and reports ids plus collapse count … |
| [#127](https://github.com/LemelyIG/Lemely/issues/127) golden: 0625_w21_qp_32_theory_nested fixture says … | not planned | The fixture itself is unchanged. On develop, tests/golden/0625_w21_qp_32_theory_nested/mark_scheme.json still reads "paper_type": "theory_extended" / … |
| [#136](https://github.com/LemelyIG/Lemely/issues/136) det: fix the mark-total escalation that blocks the golden … | **completed** | Nothing in the acceptance remains, but two honest limits belong on the record. First, no awarded mark ever moved. The issue's own scope note required … |
| [#161](https://github.com/LemelyIG/Lemely/issues/161) eval: the review-rate ratchet cannot be armed, and … | not planned | Step 3 - arming - is NOT done, and the issue's own premise was falsified in the process. review_rate_ratchet_armed is still Field(default=False) at … |
| [#166](https://github.com/LemelyIG/Lemely/issues/166) 0% on 0606, systematically by size | not planned | No fix. The 50% failure rate is exactly where it was: nothing was changed in the Gemini mark-scheme path, and the prompt already instructs … |

### H — awaiting a human who never came

| issue | disposition | the honest remainder |
|---|---|---|
| [#49](https://github.com/LemelyIG/Lemely/issues/49) Approve the frozen train/dev/test split membership | not planned | The box the issue says it closes on. No split manifest exists anywhere in the tree (eval/ holds only README.md, labels/.gitkeep, … |
| [#51](https://github.com/LemelyIG/Lemely/issues/51) Second-labeller agreement on a 10% sample (was: … | not planned | Every acceptance box. Zero leaves have been double-labelled because zero leaves have been labelled at all: eval/labels/ contains exactly one tracked … |
| [#52](https://github.com/LemelyIG/Lemely/issues/52) Adjudicate CAIE judgment questions raised during labelling | not planned | Every acceptance box, and the human input at the centre of the issue. eval/rulings.jsonl is tracked and is 0 bytes — zero rulings, zero pending … |
| [#55](https://github.com/LemelyIG/Lemely/issues/55) Authorise the single run of the frozen test split | not planned | The run. reports/accuracy/test-touch-ledger.jsonl (the module's DEFAULT_LEDGER_PATH) does not exist and nothing under reports/ is committed for it, … |

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
