# Phase 3 — Teacher + Parent Surfaces — Milestone Report

**Status:** ✅ Complete — every MISSION §4 Phase-3 acceptance criterion met. Three
limitations are reported honestly below (§7) rather than presented as passes.
**Branch:** `feature/phase-3-teacher-parent` (from `develop` @ `faef29c`) → merged to
`develop`; `develop → main` PR #3 updated (**not** merged).
**Date:** 2026-08-07.
**Baseline (`develop` @ Phase 2.5):** 609 passed / 85.54% coverage.
**After Phase 3:** **1939 tests — 1933 passed, 6 skipped, 0 failed — 89.42% coverage.**
All **13** quality gates green with **0 skipped**.
**Gemini spend: $0.1586 / $8.00** (2.0% of the cap; the only live calls this phase were
two mark-scheme parses and one real-paper accuracy run).

The six skips are environmental, not avoidance: four pre-existing live-Supabase-key tests
(`test_auth_live`, `test_seat_invite_live`, `test_storage_live` ×2) and two **new**
live-billed accuracy cases gated on `LEMELY_LIVE_ACCURACY=1` *and* a resolvable Gemini key,
so a bare `pytest` can never bill the cap.

---

## 1. What was built (task → outcome)

| # | Task | Outcome |
|---|------|---------|
| P3.1 | Real class model + teacher tenancy | `lemely/db/class_repo.py` (`ClassService`), migration `0004_class_model` (nullable `classes.school_id` for independent teachers, `classes.join_code`), `lemely/web/routers/classes.py` (CRUD/roster/enrol) + student join-by-code. The implicit "all students are one cohort" endpoints are gone. **Closes the cross-tenant leak D1.6 recorded as outstanding.** (D3.1) |
| P3.1b | Visual-baseline gate repair | All four UI runners hardcoded a committed phase report dir, so every `check.sh` run overwrote the baselines the "no unintended visual regression" gate compares against — the gate was **vacuous**. Now behind `LEMELY_REPORT_DIR`, defaulting to gitignored `reports/.scratch`; re-baselining is explicit and names its phase. (D3.2) |
| P3.2 | At-risk flagging engine | `lemely/core/at_risk.py` — pure, no I/O, injected clock. MISSION's three rules OR'd (declining trend N=3 with a 5pp floor / predicted ≥2 grades below target / ≥14 days inactive), each flag carrying reason + evidence. Replaced the old "grade in {D,E,U} or any negative delta" heuristic and reconciled `/api/teacher/overview` with `/api/classes/{id}`, which had diverged. (D3.3) |
| P3.3 | Teacher analytics (T-04/T-05/T-06) | `lemely/core/class_analytics.py` (pure): ranked topic weaknesses, topic×student heatmap, grade distribution, cohort trend, per-paper comparison, engagement. Three read-only routes, all scoped through one `_visible_students()` helper. **Closed the last cross-tenant leak** — `/api/teacher/overview` was still enumerating every student in the store. (D3.4) |
| P3.4 | Review queue override-and-annotate (T-07/T-08) | Migration `0005` adds teacher-override columns to `question_results` **without touching the AI's own `awarded_marks`**; `ReviewService` serves list/filter/detail/resolve/dismiss/bulk-approve. An integrity dismissal structurally never writes a `QuestionResult`, so no student-visible record can survive it. Follow-up fixed overrides leaving `weakness_records` at the AI's values. |
| P3.4b | At-risk acknowledge-with-a-note (T-06) | `flag_fingerprint()` canonicalises the *stable* part of each evidence type (notably `last_active_at`, never `days_inactive`, which would un-acknowledge an unresolved flag every 24h). Migration `0006` + `AtRiskAckService`. Acks are per-teacher and evidence-scoped; acknowledged flags are **tagged, never removed**. (D3.5) |
| P3.5 | Teacher quiz builder backend (T-09/T-10) | Eight chunks. `docs/quiz-model.md` (822 lines, D3.6) fixed the design first. Shipped: `lemely/core/difficulty.py`; migration `0007_quiz_model` (6 tables, 7 enums, `attempts.origin`); `question_bank_repo.py` + `lemely question-bank` CLI; `quiz_repo.py` + `/api/teacher/quizzes`; `quiz_taking_repo.py` + student take/submit (S-26); `quiz_marking_repo.py` reusing the **existing** `correct_paper` + `apply_integrity_checks` behind a single shared `AttemptRepository._persist`; `quiz_results_repo.py` + T-10 class results. (D3.6–D3.10) |
| P3.6 | Parent portal backend (P-01..P-04) | `parent_repo.py` (`ParentLinkService` — the ONE `parent_child_links` query), `routers/parent.py` (`/api/parent`, `require_role(Role.parent)`), the three student-side link routes, and notification preferences (migration `0008` + `/api/me/notification-preferences`). **Linking direction: the student invites by phone, and only an already-OTP-authenticated parent can be linked** — this deliberately does not mint a user from a student-supplied phone. (D3.11) |
| P3.7 | Teacher frontend T-01..T-06 | Dashboard, classes list, class detail roster, class analytics, student detail, at-risk list — all six on real data. Four chunks: additive DTO enrichment (D3.12), client API/types layer + T-01/T-02, T-03/T-04, T-05/T-06. Killed the sidebar's fabricated "Mr H. Sabry / Physics dept · CAIE" identity, the three fake `recentClasses`, and the hardcoded Grading `badge: "12"`. |
| P3.8 | Teacher frontend T-07/T-08, T-09/T-10, T-12 | Review queue + remark on P3.4's real API (replacing the P2 grading-console wiring), the six-step quiz builder, quiz class results, and the announcement composer — plus the announcements **backend**, which did not exist (the Phase-1 table was already the right shape, no migration). `portals/teacher/data.ts` is gone. (D3.14, D3.15) |
| P3.9 | Parent frontend G-05 + P-01..P-04 | `[data-portal="parent"]` token scope, parent shell, phone+OTP login, children list, child overview, subject detail, weaknesses, and the student-side parent-link management screen. Fixed a real defect: `TEACHER_ROLES` included `"parent"`, so a parent completing OTP **landed in the teacher portal** where every panel 403s. (D3.16) |
| P3.10 | Acceptance + the standing UI gate | Shared multi-role seed (`scripts/seed_e2e.py`), `audit.mjs` converted from a linear 506-line single-journey script into a **declarative 24-route / 34-state registry** with real console-error and responsive gates (D3.17), the teacher-portal token retrofit (D3.18), the Phase-3 re-baseline + first real cross-phase visual compare, and Vitest stood up for `web/` (D3.20). |
| P3.10-B3 | MCQ integrity guard | `apply_integrity_checks` now skips **both** the plagiarism and AI-detection checks for MCQ questions. Before this, `SequenceMatcher('C','C').ratio()` = 1.0 made every *correct* MCQ answer a plagiarism flag and a review-queue item while every wrong one stayed clean — the signal was exactly inverted. (D3.19, blocker B3) |
| INBOX-ACC | Real past-paper accuracy | Two genuine solved 0625 scripts run through the real ingest → OCR → mark → grade path against the official schemes. Both totals inside the pre-committed tolerance. (D3.21 — see §6) |
| P3.11 | This report | Phase report, contact sheet, `develop` merge, PR #3 update, ntfy. |

## 2. Acceptance criteria (MISSION §4, Phase 3)

- ✅ **Teacher: class management, per-class and per-student analytics, aggregate weakness
  topics.** T-01..T-05, all on real data, all roster-scoped through one `ClassService`.
- ✅ **At-risk flagging with each flag labelled by reason.** `lemely/core/at_risk.py`, three
  rules, evidence-carrying. **One honest gap:** rule 2 (predicted ≥2 grades below target) is
  fully implemented and unit-tested but **cannot fire in production** — no target-grade
  column exists until P4's onboarding questionnaire. The engine reports it as *not
  evaluable*, never as a pass (D3.3). It is absent from the T-06 reason filter for the same
  reason.
- ✅ **Human-review queue with override-and-annotate; overrides feed back as recorded
  corrections.** P3.4 + T-07/T-08. The override recomputes `weakness_records` through the
  same `analytics.group_weak_areas` marking-time uses, so a restored question stops counting
  as "lost" on the student's weakness list and the T-04 heatmap.
- ✅ **Teacher quiz builder: difficulty targeting by expected grade, included-material
  selection, pool from generated or classified past-paper questions, assign to class,
  auto-marked, results feed analytics.** P3.5 + T-09/T-10. **One honest gap:** the
  past-paper half of the pool yields **zero** questions and always will — see §7 (i).
- ✅ **Parent portal: phone-OTP login (mock provider), linked children, performance +
  weakness views (read-only), notification preferences.** P3.6 + P3.9.
- ✅ **Every screen uses only Phase-2.5 tokens and components.** The teacher portal's
  arbitrary px/oklch literals — carried debt since P3.7 — were retrofitted in P3.10c
  (D3.18); the design-token invariants are now enforced by the `web-test` gate rather than
  by a bespoke script.
- ✅ **E2E per role (Playwright).** Green in the gate run, driven off the shared 5-role seed.
- ✅ **At-risk flags verified against seeded scenarios.** `scripts/seed_e2e.py` seeds
  `declining` / `inactive` / `control` / `correctedPaper` students; the real API was queried
  with the seeded tokens and reproduces exactly `declining→[declining_trend]`,
  `inactive→[inactive]`, `control→[]`, `correctedPaper→[]`.
- ✅ **Standing UI gate:** `BUILD/QUALITY-BAR.md` met; **zero axe violations at any
  severity** across all 34 audited states; Lighthouse accessibility ≥ 95 everywhere;
  screenshot corpus captured for every new screen × state × breakpoint; Impeccable audit
  clean (`npx impeccable detect` is a standing gate); the cross-phase compare shows **0
  removed and all 39 changed captures verified intended** (§5).

## 3. Test & coverage summary

```
$ pytest -q --tb=short
1939 tests — 1933 passed, 6 skipped, 0 failed
Required test coverage of 70% reached. Total coverage: 89.42%
```

| | Phase 2.5 (`develop`) | Phase 3 | Δ |
|---|---|---|---|
| Tests | 609 | **1939** | +1330 |
| Coverage | 85.54% | **89.42%** | +3.88pp |

Coverage never dropped below the previous `develop` value at any commit in this phase — each
chunk line in `BUILD/STATE.md` records its own before/after number.

> **A measurement note worth carrying forward.** `pytest -q` in this repo emits no
> `N passed` summary line (a reporter plugin eats it), so several early Phase-3 sessions
> *guessed* their test counts and the P3.1–P3.4b numbers in `STATE.md` are undercounts.
> Real counts come from the progress characters. The numbers in this report are measured,
> not carried forward.

## 4. Quality gates

```
$ ./scripts/check.sh
== Backend ==      PASS ruff-check · ruff-format · mypy · import-linter · pytest
== Web ==          PASS web-typecheck · web-lint · web-build · web-test · impeccable-detect
== Live-stack ==   PASS playwright-e2e · puppeteer-audit · ui-thresholds
── Summary ── All gates passed (0 skipped).
```

`alembic check` reports no drift. Five additive migrations landed this phase (`0004`
class model, `0005` review overrides, `0006` at-risk acknowledgements, `0007` quiz model,
`0008` notification preferences), each verified on the live stack in **both** directions
(`upgrade head → check → downgrade -1 → upgrade head → check`), per D1.2/D1.3's
additive-only rule.

## 5. Visual + accessibility evidence

Corpus: `reports/phase-3/screens/` — **131 PNGs** across **26 screen-id directories**
(the 2 loose files are the P2.10 captures carried in from Phase 2), at 380 / 768 / 1440.
Contact sheet: `reports/phase-3/contact-sheet.html`.

| Measure | Result |
|---|---|
| Routes audited | **24** (was 4 at phase start — D2.10 scoped `audit.mjs` to the student journey only) |
| States audited | **34** (default + empty / loading / error / offline / low-confidence / teacher-corrected) |
| axe violations | **0 at every severity** (critical / serious / moderate / minor) across all 34 |
| Lighthouse accessibility | **100 on 23 routes**, 96 on `teacher-review` — floor 96, clears the ≥95 bar |
| Console errors | **0** |
| Horizontal-scroll violations (≥320px) | **0** |
| Unreachable routes | **0** |
| Cross-phase compare | 39 changed / **0 removed** / 92 added — all 39 verified intended |

The compare verdict was verified **visually on representative pairs**, not inferred from the
diffstat. Two of the 39 are worth naming because they are evidence, not noise:

1. `S-15/default--380` went 392×1446 → 380×1349. The **baseline** PNG was wider than its own
   viewport, because a full-page capture expands to `scrollWidth` — so the committed Phase-2.5
   baseline had been recording a header-overflow defect *as if it were the design*.
2. That same pair shows the five questions scored 1/1 losing their "Needs review" flag while
   the three 0/1 answers stay clean. That is **B3/D3.19's inverted MCQ plagiarism signal,
   photographed** — the first visual evidence the fix landed.

## 6. Real past-paper accuracy (INBOX directive, D3.21)

Two genuine solved 0625 scripts, run through the **real** ingest → OCR → mark → grade path
(not a mocked stub), against the official mark schemes. Tolerance was fixed at **±10% of
each paper's maximum before any result was seen**, justified by adjacent CAIE boundaries
sitting ~6–10% of max apart, so an error inside the band risks at most one grade band. The
two papers exercise different marking paths and are reported **separately, never averaged**.

| Paper | Path | Predicted | Ground truth | Error | Tolerance | Verdict |
|---|---|---|---|---|---|---|
| `0625_s23_qp_22` | MCQ, deterministic | 37 | 34 | **+3** | ±4 | ✅ within |
| `0625_w24_qp_41` | Theory, AI method marks | 63 | 66 | **−3** | ±8 | ✅ within |

**The finding that matters is not the error size but which paper flagged itself.** Paper 41
put 20 of 80 marks at medium confidence and returned `grade_confidence: low` — a teacher gets
pointed at the right quarter of the script. Paper 22 returned **all 40 marks at confidence
1.0, band high, zero review flags — and was still 3 marks wrong**. MCQ marking is
deterministic string comparison against the official key, so no marking-judgement error is
possible there: all 3 marks of error are *vision/transcription* error. **The confidence
number is measuring the marker while the mistake happened in the extractor.** Confidently
wrong, and invisible to every gate this build runs. Propagating extraction confidence into
per-question confidence on the deterministic MCQ path changes the marking contract and was
deliberately **not** patched as a phase-end drive-by; it belongs in DELIVERY.md and in a
scoped task.

Full numbers-only report: `reports/accuracy-real/REPORT.md`. The per-question JSON and the
rendered annotation overlay exist locally as the human's spot-check route (a correct total
made of two cancelling errors is a failure, and the total alone cannot tell you which you
have) but are **gitignored** alongside `tests/fixtures/real-papers/` — a minor's handwriting
and scan imagery stay out of git. No per-question ground truth was fabricated or
back-derived.

Three defects were found and fixed on the way to this number, each recorded in
`BUILD/BLOCKERS.md`: `tables.py` dropped every table after the first on a page (−9 marks,
B2); `rows.py` summed CAIE *compensatory* C-marks additively on top of the A-mark they
replace (+12, B2 — the two masked each other down to +3); and the MCQ plagiarism inversion
(B3/D3.19), which alone would have produced 34 false flags on paper 22 and poisoned the
confidence distribution.

## 7. Known limitations — reported, not resolved

These must survive into `DELIVERY.md`. None is a silent gap.

**(i) The question bank ships empty, and corpus growth cannot change that (D3.7).** The
mandated measurement came back zero and *that is the finding*: 122 leaf questions across the
entire 4-mark-scheme corpus, **0 with prompt text, 0 with a topic hint** — because a mark
scheme holds marking points and the question *stem* lives in the question paper, which this
codebase only ever consumes as a scanned student submission. There is no question-stem
extractor. The past-paper ingest therefore ships as a **reporting** function with no write
path, and a stem extractor is now a stated prerequisite of P4's "questions from the
past-paper corpus" work, not an assumption.

**(ii) Lighthouse performance on the teacher routes floors at 67** (`teacher-quiz-detail`).
MISSION §11 sets a ≥80 performance floor **on the student routes**, which is met (student
floor 82, parent floor 83). The teacher routes were never inside that floor's scope, so this
is **unmeasured debt now being measured and reported** — not a gate that passed.

**(iii) Lighthouse runs on `default` states only; axe runs on all 34.** A deliberate
tradeoff (D3.17/e2a): axe is ~1s and empty/error states are exactly where violations hide
(the `page-has-heading-one` findings this phase were on empty screens), while Lighthouse is
~30s and its scores are a property of the route, not the state. Do not read the corpus as
"every state fully audited".

**(iv) `web/e2e/` and `playwright.config.ts` are in no tsconfig `include`,** so the
build's most expensive gate — the Playwright specs — has never been typechecked (D3.20).
Pulling them in would mix an unknown number of pre-existing type errors into a runner chunk;
recorded as measured debt.

**(v) Students cannot see announcements.** P3.8 ships compose / list / delete for teachers
only. There is no student-facing announcement surface and no notification send path —
MISSION §4 puts both in Phase 5, which also owns `notification_preferences` (written by P3.6
chunk b, read by nothing yet, including for the quiet-hours window).

**(vi) Two spec-vs-reality gaps rendered as absent rather than stubbed (D3.14).** T-08's
"student's actual scan crop side by side with the mark scheme extract" — **neither artefact
is persisted**; `studentAnswer` (what Lemely transcribed) + `matchedPointIds` +
`expectedAnswer` are the honest substitutes. T-12's "optional attachment" has no column and
no storage wiring, and is omitted entirely rather than shown as a disabled control. T-05's
integrity signals and "contact route if configured" get the same treatment.

**(vii) No class-level "average predicted grade", a knowing deviation from the spec's
wording (D3.12).** T-01 and T-02 both ask for one; averaging letter grades invents precision
the data does not support (UI spec §1.4). `ClassSummaryDTO.average` is the mean latest
*percentage*, rendered and labelled as exactly that.

**(viii) G-05's "no account found for this number" state is unreachable by construction**
(D3.11): `verify_otp` auto-creates the parent on first verify, so every verified phone gets
an account. Its honest equivalent is P-01's no-children-linked empty state. Documented as
absent, not faked.

**(ix) Carried forward from Phase 2, unchanged:** the accuracy gate on the *synthetic golden
set* is still not met (mark-level agreement 83.8% vs the ≥95% target; flag_recall 27.3%).
The remaining gap is free-form algebraic method-verification. Phase 3 did not touch it. The
new real-paper measurement in §6 is **added on top of** that gate, not a replacement for it.

**(x) PWA Lighthouse + camera capture** remain untested on real hardware (no Chromium camera
in this sandbox) — see `reports/phase-2/pwa-limitations.md`.

**(xi) Deliberately out of scope, so it is not quietly inferred later:** there is no
`school_admin` or co-teacher view into a quiz. `QuizService` is scoped strictly by
`teacher_id`, pinned by `test_school_admin_has_no_view_into_a_quizs_results`. Nothing in
`docs/quiz-model.md` supports one.

## 8. Defects found and fixed in existing work

Phase 3 was not additive-only. Per MISSION §4, defects in completed phases were fixed as
scoped tasks inside this phase rather than by reopening those phases.

| Defect | Where it came from | Why it mattered |
|---|---|---|
| Every **correct** MCQ answer flagged as plagiarism | P2.4 | The signal was exactly inverted — a 40/40 paper generated 40 flags, a 0/40 paper none. It accused honest students by default and would have poisoned the accuracy measurement in §6. (B3/D3.19) |
| The visual-regression gate overwrote its own baselines | P2.5.5 | The "no unintended visual regression" gate was **vacuous** — it compared against baselines the same run had just rewritten. (D3.2) |
| `/api/teacher/overview` enumerated every student in the store | P2 | Cross-tenant data exposure; the last of the two leaks D1.6 recorded. Now roster-scoped and pinned by a two-teacher disjoint-class regression. (D3.4) |
| `AtRiskAcknowledgement.reason` bound the enum's `.name`, not its `.value` | P3.4b | Every acknowledge call 500'd against any real Alembic-migrated stack. **Neither `pytest` nor `alembic check` can see this class of bug**, and a `create_all()`-based fixture actively hides it — the schema it builds is derived from the same wrong declaration, so it is self-consistently wrong. Now closed structurally by a metadata test that audits all 25 enums. (D3.13) |
| `request()` swallowed every backend error's real `detail` | P2.6 | Silently, across every screen's `error.message`. Also `res.json()` on a 204 made every successful DELETE surface a fake error. |
| A parent logging in landed in the teacher portal | P2.6 | `TEACHER_ROLES` included `"parent"`; every panel 403s there. |
| Two mark-scheme extraction defects (−9 and +12 marks) | Pre-Phase-0 `lemely/io/det/` | They masked each other down to a +3 reconciliation failure that looked like a rounding concern. Fixing them also repaired `s20_ms_31`, which had been failing at 38/80 — and established that **a cached `.json` sibling is not evidence a PDF parses today**. (B2) |
| `HistoryStore` claimed a pre-versioning file was v2 | P0 | The bump to `HISTORY_SCHEMA_VERSION` 2 destroyed the "detect an older file" signal the field exists for. |
| The student sidebar's hardcoded "Maya Rahman" identity | P2.6 | The same fiction P3.7 removed from the teacher sidebar, never done for the student side. |

## 9. Decisions recorded this phase

D3.1–D3.21, in full in `BUILD/DECISIONS.md`. The load-bearing ones for later phases:

- **D3.3** — at-risk rule 2 cannot fire until P4 supplies target grades; it reports as *not
  evaluable*, never as a pass.
- **D3.6 / `docs/quiz-model.md`** — the quiz model is designed and fixed. P4 implements
  against it; it does not redesign it.
- **D3.7** — the question-stem extractor is a P4 prerequisite, not an assumption.
- **D3.9** — three predicates, not one: `is_grade_bearing` (grade claims), `is_paper`
  (counts that say *papers*), and unfiltered (topic/weakness/streak surfaces). Every
  grade-or-percentage claim in the web layer filters; topic aggregation deliberately does
  not.
- **D3.11** — the student invites the parent, by phone, and only a phone-proven parent can be
  linked. The student owns the consent on both ends.
- **D3.13** — "unit tests pass against a `create_all()` schema" is **no evidence at all**
  that a column works against the migrated database.
- **D3.20** — `web/` tests run in Node with no jsdom and no component-rendering stack;
  Playwright owns component behaviour against a real browser. A second lower-fidelity stack
  would be the D3.13 mistake in a new place.
- **D3.21** — the confidence number can measure the marker while the mistake happened in the
  extractor.

## 10. Blockers raised and resolved

All three raised this phase are **resolved**; `BUILD/BLOCKERS.md` carries the full history.

| | Blocker | Resolution |
|---|---|---|
| B1 | The two official mark schemes were not in the repo and no code path could obtain them | Resolved by the human installing the `paperscraper` skill — unblock route 3, "authorise fetching from a named source". The schemes were **not** reconstructed, LLM-generated, or back-derived from the known totals. |
| B2 | `0625_w24_ms_41` failed reconciliation at 83 vs 80 under **both** parsers | Two real extraction defects, not a reconciliation-rule problem. `mark_reconcile_tolerance` stays **0** — raising it to 3 would have silenced a real signal across every scheme the product ever parses, to unblock one fixture. |
| B3 | Every correct MCQ answer flagged as plagiarism | Type guard on `question.type == MCQ`, covering AI-detection too. `plagiarism_threshold` was not touched. |

---

## Appendix — files of record

- Decisions: `BUILD/DECISIONS.md` (D3.1–D3.21)
- Blockers: `BUILD/BLOCKERS.md` (B1, B2, B3 — all resolved)
- Task-by-task detail: `BUILD/STATE.md`, Phase 3 section
- Quiz model design: `docs/quiz-model.md`
- Accuracy: `reports/accuracy-real/REPORT.md`
- Screens: `reports/phase-3/screens/`, contact sheet `reports/phase-3/contact-sheet.html`
- Raw gate output: `reports/phase-3/axe/`, `reports/phase-3/lighthouse/`,
  `console-errors.json`, `responsive-summary.json`, `screen-compare.json`
