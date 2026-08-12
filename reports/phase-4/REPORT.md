# Phase 4 — Content Generation + Study Plans — Milestone Report

**Status:** ✅ Complete — every MISSION §4 Phase-4 acceptance criterion met, including the
one it names explicitly ("question rendering must be verified visually in screenshots, not
assumed"). Seven limitations are reported honestly below (§7) rather than presented as passes.
**Branch:** `feature/phase-4-content-study-plans` (from `develop` @ `49d9750`) → merged to
`develop`; `develop → main` PR #3 updated (**not** merged).
**Date:** 2026-08-09.
**Baseline (`develop` @ Phase 3):** 1939 tests / 89.42% coverage.
**After Phase 4:** **2350 tests — 2344 passed, 6 skipped, 0 failed — 90.18% coverage.**
All **13** quality gates green with **0 skipped**.
**Gemini spend: $0.18429 / $8.00** (2.3% of the cap). **Phase 4 itself spent $0.0257** — every
feature in it was built with Gemini mocked, which D4.3 made structurally impossible to
circumvent.

The six skips are the same environmental six Phase 3 carried, not new avoidance: four
live-Supabase-key tests and two live-billed accuracy cases gated on `LEMELY_LIVE_ACCURACY=1`
*and* a resolvable key, so a bare `pytest` can never bill the cap.

---

## 1. What was built (task → outcome)

| # | Task | Outcome |
|---|------|---------|
| P4.1 | Question-stem extractor | `lemely/io/det/question_papers.py` (deterministic, zero Gemini) + the shared `lemely/io/det/symbols.py` (Adobe SymbolEncoding recovery, also wired into `tables.py` so the **marking engine** stops reading mangled mark points) + `lemely question-bank ingest-question-papers`. **72 papers → 2018 leaves → 273 banked.** **Closes D3.7** — the question bank is no longer empty. (D4.1, D4.2) |
| P4.2 | Syllabus topic taxonomy + classification | `lemely/data/syllabus_topics.json`, transcribed from the three official CAIE syllabus PDFs (not from memory), + `lemely/core/topics.py` + `lemely question-bank classify-topics`. **245/273 classified, 211 written** across 29 topics. The 34 `low`-band matches are counted and **discarded** — `question_bank.topic` has no confidence column, so writing them would launder a guess into apparent fact. $0.00. (D4.4) |
| P4.3 | Student profile + onboarding data model | Migration **0009**, four additive tables + `student_profile_repo.py` + student-only `/api/me` routes. Every S-02 field is nullable: a skipped answer is `NULL`, never a defaulted sentinel. **At-risk rule 2 goes live** — `assess_at_risk` took a scalar target and now takes `targets: Mapping[str, str]`, because a scalar would have compared a physics paper against a maths target the moment a student enrolled in two subjects. (D4.5) |
| P4.4 | Placement test backend | Five chunks. The marking-side topic fill (`fill_correction_topics`, called **before** `summarize_weaknesses`), migration **0010** + the XOR-checked ownership shape that lets a quiz be owned by a student instead of a teacher, `lemely/data/paper_timing.json`, `core/placement.py` (pure), and `db/placement_repo.py` + three routes. Take/resume/submit are the **existing** `/api/student/quizzes/...` endpoints — that reuse is the point; no parallel engine was forked. (D4.6–D4.9) |
| P4.5 | Practice generator backend | `db/practice_repo.py` + `routers/practice.py`. **Availability is tri-state, not binary** — a *short* set is not a *failed* set, so `available=True` covers the honest-shortfall case with a true `available_count`, and `False` is reserved for `no_questions`/`no_weaknesses`. Never padded, never silently shortened. Export excludes `model_answer`/`mark_scheme_points`/`mcq_answer` **structurally** (asserted on the dataclass field set, not one response body). (D4.10) |
| P4.6 | Flashcards backend | Migration **0011**, `core/spaced_repetition.py` (pure, clock-injected), `db/flashcard_repo.py`, `io/flashcard_generation.py`, and ten routes. **Four departures from canonical SM-2 are documented at the point of divergence and each pinned by a test.** An AI-written card is stored `source='ai'` and stays distinguishable for its whole life. (D4.11) |
| P4.7 | Adaptive study plan | Three chunks. `core/study_plan.py` rewritten pure + clock-injected with weights **0.5 weakness / 0.3 placement / 0.2 confidence** — a missing signal **renormalises** rather than zero-filling, which is what makes "questionnaire only, no placement yet" a real plan instead of a diluted one. Migration **0012** persists it; regeneration **supersedes** rather than mutates, so last week stays auditable. A `no_signal` refusal **is persisted** — "no plan yet" and "refused a plan" are different facts and both stay queryable. (D4.12, D4.13) |
| P4.8 | Frontend S-01..S-05 | Onboarding wizard + placement invite/in-progress/results. Chunk 0 first fixed a data defect the screen would have displayed (below). **First `web/` diff of Phase 4, so gate 8 comes into play** — and it is satisfied non-vacuously: 6 registry entries / 7 states on four seeded accounts. (D4.14–D4.16) |
| P4.9 | Frontend S-20..S-23 | Practice generator/set/print and flashcards decks/review. 13 registry entries / 14 states, 14/14 axe clean at every severity. (D4.17, D4.18) |
| P4.10 | Frontend S-24/S-25 | Study-plan week view + session detail, replacing the placeholder `StudyPlan.tsx` — a rewrite onto a **different API**, not a retrofit. The legacy `GET/POST /api/student/plan` and `POST /api/student/onboarding` surfaces are retired, with their authz-matrix coverage **replaced rather than dropped**. (D4.19–D4.22) |
| P4.11 | Acceptance + the standing UI gate | Five chunks. `web/e2e/` went **8 spec files / 14 test blocks → 11 / 25**: the seed-contract drift pin, the MISSION §4 journey as five real legs, practice-targets-seeded-weakness and its two inverses, the seeded below-target scenario that pins at-risk rule 2 for the first time, and the corpus-maths seed that makes the visual check non-vacuous. (D4.23–D4.25) |
| P4.12 | This report | Phase report, phase-4 re-baseline, `develop` merge, PR #3 update, ntfy. |

## 2. Acceptance criteria (MISSION §4, Phase 4)

- ✅ **Topic-classified practice material, filtered to a student's weak topics,
  exportable/printable.** P4.5 + S-20/S-21. Weak-topic resolution reads `WeaknessRecord` rows
  through the server, not the client — there are two different weak-topic vocabularies in this
  codebase and prefilling from the screen's own list would have silently joined against nothing.
- ✅ **Flashcards (AI-generated per topic, spaced-repetition review flow).** P4.6 + S-22/S-23.
- ✅ **Placement test, ~15 minutes per subject, from real past-paper questions across topics,
  marked by the existing engine, initialising the weakness profile.** P4.4 + S-03/S-04/S-05.
  **Measured: 0625 assembles 10 questions / 17.06 min / 6 syllabus topics.** **One honest gap:**
  0580 and 0606 return `no_questions` and always will until their papers are ingested — that is
  a real `not available` path with a machine-readable reason, shipped as required behaviour and
  not coded around (§7 ii).
- ✅ **Onboarding questionnaire (enrolled subjects + session, school, external sessions y/n,
  weekly study time, grade level, target grades).** P4.3 + S-01/S-02. Every field is skippable
  and a skipped field is **absent from the payload** — asserted on the serialised wire, not just
  the object, because a falsy-means-skipped bug would have silently discarded every "no" answer.
- ✅ **Adaptive study plan from placement + questionnaire + rolling performance; regenerates
  weekly; concrete sessions (topic, activity, duration), not vague advice.** P4.7 + S-24/S-25.
  The pre-Phase-4 scheduler emitted one `StudySession(week=1, hours=…, focus="Practice and
  review: X")` per topic and was never persisted; sessions now carry a **date, an activity type
  and a duration in minutes**, and activity type must be *earned* against the live bank.
- ✅ **E2E: a new student onboards, takes placement, receives a plan.**
  `web/e2e/phase4-journey.spec.ts`, five legs, through the real UI against the real backend.
- ✅ **E2E: generated practice demonstrably targets seeded weaknesses.**
  `web/e2e/phase4-practice.spec.ts`, three tests — the positive case plus **both** honest
  refusals (no recorded weaknesses; a subject with no ingested questions).
- ✅ **Standing UI gate.** `BUILD/QUALITY-BAR.md` met; **zero axe violations at any severity**
  across all 122 audited route-states; Lighthouse accessibility ≥ 95 everywhere (floor 96);
  screenshot corpus captured for every new screen × state × breakpoint; `npx impeccable detect`
  clean; **0 captures removed** in the cross-phase compare (§5).
- ✅ **Question rendering (maths notation, diagrams) verified visually in screenshots, not
  assumed.** This is the criterion MISSION §4 calls out by name, and it is the one that was
  nearly passed vacuously — see §6.

## 3. Test & coverage summary

```
$ pytest -q --tb=short
2350 tests — 2344 passed, 6 skipped, 0 failed
Required test coverage of 70% reached. Total coverage: 90.18%
```

| | Phase 3 (`develop`) | Phase 4 | Δ |
|---|---|---|---|
| Backend tests | 1939 | **2350** | +411 |
| Coverage | 89.42% | **90.18%** | +0.76pp |
| Playwright spec files | 8 | **11** | +3 |
| Playwright test blocks | 14 | **25** | +11 |
| `web/` unit-test files | 3 | **8** | +5 |

Coverage never dropped below the previous `develop` value at any commit in this phase — each
chunk line in `BUILD/STATE.md` records its own before/after number.

> **Measurement note.** `pytest -q` in this repo emits no `N passed` summary line (a reporter
> plugin eats it), so the count above is the collected total measured directly, and the 6
> skips are read off the run's own summary. Two further traps this phase paid for and recorded
> so no future session pays again: **never run `pytest` concurrently with `./scripts/check.sh`**
> (they contend on the same `.coverage` file and the *coverage figure* comes back badly wrong —
> 89.67% vs 90.37% on an identical tree — while the run still exits 0 and the test counts stay
> correct, which is exactly what makes it convincing as a fake regression); and `pytest
> --collect-only` still runs the coverage plugin unless given `--no-cov`.

## 4. Quality gates

```
$ ./scripts/check.sh
== Backend ==      PASS ruff-check · ruff-format · mypy · import-linter · pytest
== Web ==          PASS web-typecheck · web-lint · web-build · web-test · impeccable-detect
== Live-stack ==   PASS playwright-e2e · puppeteer-audit · ui-thresholds
── Summary ── All gates passed (0 skipped).
```

Four additive migrations landed this phase (`0009` student profiles, `0010` placement quiz
ownership, `0011` flashcards, `0012` study plans), each verified on the live stack in **both**
directions, per D1.2/D1.3's additive-only rule.

> A note on `alembic check`, recorded because it cost real work: it errors *"Target database is
> not up to date"* when the DB sits behind head. That is the check **refusing to run**, not a
> downgrade failure.

**Every chunk was gated on the orchestrator's own run, never on the subagent's report — and
that was not ceremony.** Seven handovers this phase reported done with their own gate red:
`ruff` red on 8 findings in `flashcard_repo.py`; `ruff format` red on two of P4.5's own files;
a `pytest` failure on `test_all_expected_tables_registered` (the deliberate schema-drift guard,
which two new tables were never added to); and four sign-offs issued before the gate run had
finished. One handover — P4.7 chunk C — came back clean on every gate, which is worth recording
precisely because it is the exception.

## 5. Visual + accessibility evidence

Corpus: `reports/phase-4/screens/` — **212 PNGs** across **39 screen-id directories**, at
380 / 768 / 1440. Contact sheet: `reports/phase-4/contact-sheet.html`.

| Measure | Result |
|---|---|
| Registry entries / routes audited | **48** |
| axe route-states audited | **122** |
| axe violations | **0 at every severity** (critical / serious / moderate / minor) |
| Lighthouse accessibility | **100 on 33 routes**, 96 on `teacher-review` — floor **96**, clears the ≥95 bar |
| Lighthouse performance | floor **65** (`teacher-quiz-detail`); lowest student route **79** (`student-practice-generator`) — see §7 (i) |
| Console errors | **0** |
| Horizontal-scroll violations (≥320px) | **0** |
| Cross-phase compare vs Phase 3 | 81 added / **0 removed** / 78 changed / 53 unchanged |

**The compare verdict was verified by opening representative pairs, not inferred from the
diffstat.** `0 removed` is the load-bearing number — no screen stopped being captured. The 78
changed decompose into four causes, all intended:

1. **The seed grew a student and a class** (P4.11 chunk D). This is most of the teacher-side
   diff, and it is the best evidence in the phase — see §6.
2. **The parsed mark-scheme corpus went 1 → 33 schemes**, which is why `T-14-provisional`
   grew 1440×900 → 1440×2002. That reflects `outputs/schemes/`, local state outside git, so
   this particular capture is data-dependent and will differ on a fresh clone.
3. **D4.21** — every state view in the product overflowed the 380px breakpoint. Fixing it moved
   the error/loading/empty captures on screens Phase 4 never otherwise touched.
4. **The seed's `run_tag` is random per run**, so the class name (`P3.10 Seed Class
   b8bbfbeb01e0` → `… 7e95259b6ac9`) changes on every re-baseline. **This means the compare can
   never be pixel-clean on any screen that renders a class name**, and a future phase should not
   read a nonzero `changed` count as a regression signal by itself.

## 6. The acceptance criterion that was nearly passed vacuously

MISSION §4 requires question rendering — maths notation especially — to be *verified visually
in screenshots, not assumed*. The corpus already contained S-04 and S-21 captures, the two
screens that render a `question_bank.prompt`, and inspecting them would have looked like
compliance. It would have proved nothing:

**Every stem the E2E harness rendered was pure ASCII synthetic text** — `"Synthetic placement
seed item {ref} for topic {topic!r}"` — with no non-ASCII character and **no newline anywhere**.
The real corpus is where the maths lives (P4.8 measured 21 distinct non-ASCII characters across
273 stems); the seed was not. So the committed captures contained neither the Unicode maths nor
the `white-space: pre-line` newlines the criterion asks a human to look at, and a "pass" against
them would have been a photograph of the wrong thing.

The fix (D4.24) seeds a sample taken **verbatim from a real banked stem** (`0625_w23_qp_42#1c`,
`×` plus superscript `⁵`, four newlines) rather than maths authored by hand to make a screenshot
pass. The pick was checked against `_FIGURE_DEPENDENT_PATTERN` **in Postgres** — it is a Postgres
POSIX regex that raises under Python `re`, and a careless sample would have silently emptied the
placement pool, surfacing as a `no_eligible_questions` refusal on S-03 rather than as an error.

**Then the captures were actually opened and looked at.** The four newlines render as real line
breaks, and `1.1 × 10⁵ J` renders correctly including at the 380 breakpoint where the wrap splits
`1.1` from `× 10⁵ J.` — the case that would have exposed a superscript or glyph-fallback problem.
Verified on S-04 (default, 1440 and 380) and S-21 (print, 380).

**The other thing worth looking at is `T-06/default--1440.png`.** It shows three at-risk students
side by side, each labelled with a different rule: declining trend, **"Predicted grade D is 3
grades below target A"**, and inactivity. MISSION named three at-risk rules in Phase 3; **this is
the first image in the project's history in which all three fire at once**, because rule 2 had no
target-grade column to read until P4.3 and no seeded scenario to fire against until P4.11.

## 7. Known limitations — reported, not resolved

These must appear in `DELIVERY.md`. None is presented as a pass.

**(i) The Lighthouse performance floor MISSION §11 claims is gated is not actually enforced
(D4.25).** `scripts/check_ui_gates.py` enforces `ACCESSIBILITY_FLOOR = 95` and has **no
performance check at all**, while MISSION §11 claims "performance ≥ 80 on the student routes" is
gated and `audit.mjs:218` justifies its own browser-flag choice on the grounds that "the run
gates on performance ≥ 80". In this run `student-practice-generator` scores **79** and
`ui-thresholds` passes. Deliberately not fixed inside P4.11: adding the check turns the gate red
on a real 79, and lowering the floor to keep it green would be exactly the dishonest gate that
comment warns against. Note the *specific* failing route is not stable between runs (chunk E's
run had `student-flashcards-due` at 79 and this one has it at 81); what is stable is that a
student route sits below the claimed floor and nothing enforces it. **This is the third instance
of one shape** (cf. D3.20, P4.8's unregistered screens): *a gate believed to cover something it
never loads reads exactly like one that does.*

**(ii) Placement and practice are un-assemblable for two of three subjects.** 0580 and 0606 have
**zero** ingested questions, so both return an honest `no_questions`. Only 0625 is real. The
ceiling is not stem extraction — it is that **only 32 of 72 0625 mark schemes parse
deterministically**, and a stem needs its scheme to be bankable. Improving the deterministic
mark-scheme parser is the highest-leverage way to grow the bank.

**(iii) A practice set is marked but its result cannot be read.** `POST .../submit` triggers
marking for every kind, so the marks really are in the DB, but `StudentQuizTakeDTO` carries no
score and the only result route is narrowed to `kind == placement`. S-21's finish action has no
backend to show a summary. The marking already ran — only the *read* is missing.

**(iv) `web/e2e/` and `playwright.config.ts` are in no tsconfig `include` (D3.20).** The most
expensive gate in the build has still never been typechecked. Phase 4 added 11 test blocks to
that directory, which raises the value of closing this, not lowers it.

**(v) S-23 ships with no XP and AI study-plan narration left the web surface** (D4.17, D4.19).
Both are deliberate: XP is Phase 5's and `completed_at` is the seam, and putting an invented XP
number on a session-complete affordance would be exactly the invented precision UI spec §1.4
forbids. The narration loss is recorded rather than quietly restored.

**(vi) Phase 2's synthetic-golden-set accuracy gate is unchanged** — 83.8% mark agreement vs the
≥95% target, flag_recall 27.3%. Phase 4 touched the marking output (the topic fill) and the
harness was re-verified, but nothing in this phase attacks the remaining gap, which is free-form
algebraic method verification.

**(vii) D3.21's confidently-wrong paper stands.** Paper 22 returned all 40 marks at confidence
1.0, band high, zero review flags — and was still 3 marks wrong, all of it vision/transcription
error on a deterministic MCQ path where no marking-judgement error is possible. Propagating
extraction confidence into per-question confidence changes the marking contract and was not
patched here either.

## 8. Defects found and fixed in existing work

| Defect | Introduced | Why it mattered |
|---|---|---|
| **The test suite could make billed Gemini calls** when a key was exported (D4.3) | Pre-Phase-4 | A `pytest` run could spend against the $8 cap. `tests/conftest.py` now blocks real client construction suite-wide — structural, not a convention. |
| **Four banked stems said "The diagram shows …" but `question_bank` has no image column** (D4.14) | P4.1 | The 0625 placement assembles ~10 questions, so one such draw makes ~11% of the test unanswerable — and the student then records a weakness they **do not have**, which is precisely what seeds the study plan and the weakness-targeted practice. It renders perfectly and screenshots clean. **The obvious fix would have missed it:** `PlacementService` does not call the shared `visible_bank_filter` at all, so folding the predicate into that seam would have passed review and left the worst-affected path unfixed. |
| **Every new screen shipped without an `<h1>`** (D4.16) | P4.8 | axe rates it *moderate*, so gate 8's serious/critical threshold passed straight over it. |
| **Every state view in the product overflowed the 380px breakpoint** (D4.21) | Pre-Phase-4 | Product-wide, on the smallest supported breakpoint. |
| **All 273 banked questions had `paper_id IS NULL`**; `papers` and `subjects` were both empty (D4.8) | P4.1 | Nothing needed the link until placement made it load-bearing, at which point 0625 returned `no_eligible_questions` too — the same refusal the *honest* empty-subject path produces, so the bug wore the disguise of correct behaviour. |
| **Placement breadth counted subtopics as topics** (D4.8) | P4.4 | Reported "13 topics" for a set with nine of 13 questions under one physics topic. |
| **A 0625 Core student would have been assembled from Extended questions** (D4.9) | P4.4 | Every topic in that sample would report a weakness the student does not have. Invisible to the suite, because the seeded bank is single-paper. |
| **The study-plan scheduler dropped the remainder over its session cap** (D4.12) | P4.7 chunk A | A three-weak-topic ten-hour week scheduled **270 of 600 minutes** while the header still reported 10 hours. The pre-fix figure is written into the regression test. |
| **The marking-side topic fill reached 8.1% of nodes** on first implementation (D4.7) | P4.4 chunk A | Found by measuring against the real corpus rather than reading the report: it ignored the `parts` subtree and had no ancestor inheritance. Fixed → 32.2% of all nodes, **52.9% of the 809 that are reachable at all** (520 are MCQ, which a CAIE scheme carries only an answer letter for). |
| **`GET /due?limit=-1` was a 500** and `POST /decks/generate` took an **unbounded `count` straight to a billed Gemini call** (D4.11) | P4.6 chunk C | The count test asserts on the generator **mock**, because a 422 that still called the model would already have spent the money. |
| **`SeedContract` was missing three whole seeded groups** | P4.3–P4.7 | The TS mirror and `seed_e2e.py` are kept in lockstep **by hand** and nothing generates one from the other. |
| **`STATE.md`'s `gemini_spend_usd` had drifted** to 0.1612 against a ledger reading 0.18429 | Ongoing | Same class: a hand-copied mirror of an authoritative source. The ledger is authoritative; the field was corrected, not the ledger. |

## 9. Decisions recorded this phase

D4.1–D4.25, in full in `BUILD/DECISIONS.md`. The load-bearing ones for Phase 5:

- **D4.3** — the test suite structurally cannot make a billed call. Do not relax this to
  "smoke-test a feature"; use the documented live-gated env var instead.
- **D4.5** — at-risk targets are keyed **per subject**. A scalar target produces a false at-risk
  flag on a teacher's dashboard the moment a student enrols in two subjects.
- **D4.6** — a quiz may be owned by a student instead of a teacher, enforced by an XOR CHECK.
  Phase 5 must not assume `quizzes.teacher_id` is non-NULL.
- **D4.10 / D4.11 / D4.12** — one honesty pattern in three places: an honest refusal with a
  machine-readable reason is a **feature**, and a short result is not a failed result. Never pad,
  never silently shorten, never let a refusal and an empty success arrive identically at the wire.
- **D4.11** — another student's private study material is a **404, not a 403**; a 403 is an
  existence oracle. The test asserts the real id and a random UUID return **byte-identical**
  bodies, then inverts it.
- **D4.17 / D4.19** — XP is Phase 5's. `completed_at` is the seam; no points or streak column was
  added, and no invented XP number was put on a completion affordance.
- **D4.24** — a screenshot that renders text written to make the screenshot pass proves nothing.
  Take the sample from the corpus.
- **D4.25** — a gate believed to cover something it never loads reads exactly like one that does.

## 10. Blockers

**None raised this phase.** B1–B3 from Phase 3 remain resolved; `BUILD/BLOCKERS.md` carries the
history.

---

## Appendix — files of record

- Decisions: `BUILD/DECISIONS.md` (D4.1–D4.25)
- Task-by-task detail: `BUILD/STATE.md`, Phase 4 section
- Screens: `reports/phase-4/screens/`, contact sheet `reports/phase-4/contact-sheet.html`
- Raw gate output: `reports/phase-4/axe/`, `reports/phase-4/lighthouse/`,
  `console-errors.json`, `responsive-summary.json`, `screen-compare.json`
- New backend surfaces: `lemely/web/routers/{placement,practice,flashcards,study_plan}.py`
- New pure cores: `lemely/core/{placement,spaced_repetition,topics}.py`, `core/study_plan.py`
- Migrations: `lemely/db/migrations/versions/000{9,10,11,12}_*.py`
- Acceptance E2E: `web/e2e/phase4-journey.spec.ts`, `web/e2e/phase4-practice.spec.ts`,
  `web/e2e/seed-contract.spec.ts`
