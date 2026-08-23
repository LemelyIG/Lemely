# Decisions log
(orchestrator records every non-trivial decision here: what, why, alternatives)

## Phase 4

### D4.7 — The marking-side topic fill lands, and its honest reach is 52.9% of the questions that *can* be classified (P4.4 chunk A)

D4.4 §6 left the marking side of the topic vocabulary open: `CorrectedQuestion.topic` comes
from `topic_hint`, measured `None` on all 637 questions across the 33 deterministically-parsed
0625 schemes, so `summarize_weaknesses` grouped every real-paper question under `"unknown"`.
`fill_correction_topics` (`lemely/db/attempt_repo.py`) closes it by running the *same* P4.2
deterministic classifier the bank side uses against the mark scheme's own prose. $0.00, zero
Gemini.

**Where it is called, and why not at persist time.** Both marking paths — `grade_paper`
(past paper) and `QuizMarkingService.mark_submission` (quiz) — call it immediately after
`apply_integrity_checks` and **before** `summarize_weaknesses`. This is the trap the P4.4
chunk plan flagged: both paths compute the `WeaknessReport` *before* calling
`persist_*_correction`, so filling the topic inside `AttemptRepository._persist` would have
fixed the `QuestionResult.topic` column while leaving the weakness **grouping** on
`"unknown"` — and the grouping is the whole point, since P4.5's practice-targets-weakness
joins on it.

**Two structural rules, both measured rather than assumed** (1329 marked nodes; `correct_paper`
iterates `all_questions_flat`, so it marks parents *and* leaves, and the fill must resolve the
same set):

| rule | nodes filled | of all 1329 | of the 809 non-MCQ |
|---|---|---|---|
| node's own fields only (first implementation) | 108 | 8.1% | 13.3% |
| + classify from the node's whole **subtree** | 198 | 14.9% | 24.5% |
| + inherit the **nearest ancestor's** label | 428 | 32.2% | **52.9%** |

Rule 1 exists because a parent node carries almost no prose of its own — the marking content
hangs off its `parts`, which the first implementation ignored. Rule 2 is inheritance, not
guesswork: `3(b)(ii)` whose own mark points read "correct substitution" *is structurally part
of* question 3, and the ancestor's evidence is a superset of the child's. Both stay gated by
`is_writable`, so a `low`-band match is still discarded (D4.4 §5 — there is no per-question
topic-confidence column, so writing a guess would launder it into apparent fact), and a real
`topic_hint` is never overwritten. Result: **428 nodes across 26 distinct topics spanning all
six 0625 syllabus topics.**

**The ceiling is structural and is recorded so it is not later mistaken for a defect.**
520 of the 1329 nodes are MCQ, and a CAIE MCQ mark scheme carries exactly one datum — the
answer letter. There is no text to classify at any depth, so those nodes are unclassifiable
*from a mark scheme* by construction; their stems live in the question paper. That is D3.7's
wall, the same one P4.1's stem extractor exists to climb, and closing it here would mean
joining marked questions back to banked stems — a larger change than this chunk, deliberately
not attempted. **The reachable population is the 809 non-MCQ nodes, and the fill reaches 52.9%
of them.**

Each rule was verified by inversion, not assumed: disabling inheritance fails
`test_fill_correction_topics_inherits_the_nearest_ancestors_label`, disabling subtree
recursion fails `test_fill_correction_topics_classifies_a_parent_from_its_parts`, and both
pass restored. The MCQ ceiling is pinned by its own test so a future reader sees it as
intended behaviour.

**Layering:** the function lives in `lemely.db`, which is outside the import-linter
`app > io > core` contract (`exhaustive = false`), because it must compose `lemely.core.topics`
(pure classifier) with `lemely.io.syllabus_topics` (taxonomy loader); `core.correction` can
reach neither without a signature change through every marking caller or a layering violation.

### D4.3 — The test suite could make billed Gemini calls; now it structurally cannot (P4.1)

**Found by running the gates, not by looking for it.** `./scripts/check.sh` failed on
`test_plan_post_narrate_without_key_is_503_not_500` (`assert 200 == 503`), and the captured
log showed a real `POST generativelanguage.googleapis.com/.../gemini-2.5-flash` in the
middle of the suite. MISSION §8 requires every automated test to mock Gemini; nothing
enforced it.

**Three separate defects, all real:**

1. **`tests/conftest.py` neutralises `.env` but deliberately not `os.environ`** ("exactly
   as in CI"). Sound for env isolation, but STATE.md's own documented way to run the gates
   is `set -a && . ./.env && set +a` — which exports `GEMINI_API_KEY`. So the "no key" test
   ran *with* a key, took the narrate path, and spent money against the hard $8 cap.
2. **`Settings.model_validate(dict)` re-runs the pydantic-settings sources.** The obvious
   fix — build a settings copy with `gemini_api_key=None` — silently gets the env key
   reinstated during validation. `model_copy(update=...)` is the form that actually works.
   Worth not re-deriving: the sibling `_settings_with_key` helper appeared to work only
   because *any* key satisfies it.
3. **The first accidental call poisoned the disk cache**, so subsequent runs took a
   `gemini_cache_hit` and the test kept failing with no network call at all — the symptom
   outlived its cause and looked like a code bug.

**Fix, in enforcement order.** A session-scoped autouse fixture in `tests/conftest.py`
raises if anything constructs a real `google-genai` client during the suite. Guarding at
*client construction* rather than at the key is the decision: tests that legitimately
exercise "a key is configured" inject `_genai_client=` or a `MagicMock` and never reach
the guard, so nothing had to change for them; only a genuinely unmocked path trips it, and
it trips loudly instead of spending. The narrate test then injects the absent key via
`app.dependency_overrides[get_settings]` rather than hoping the environment is clean.
**Verified by inversion**, not assumed: a throwaway test constructing a real client raises
`RuntimeError`, and one passing `_genai_client=<sentinel>` still gets its sentinel back.

**Cost of the leak: $0.0026** (cumulative $0.1586 → **$0.1612** / $8.00). Small, and now
bounded — but it was unbounded before, and it was a full test-suite run away from being
much larger.

### D4.2 — All five P4.1 content defects closed; the yield *fell* to 273 and that is the honest number (P4.1)

**Context.** D4.1 closed P4.1 structurally but recorded four content defects (plus a
CLI no-op) found only by reading banked rows back out of Postgres. This is the fix,
re-measured the same way.

**Measured, before → after** (`/tmp/p41_quality.py` over the 0625 bank, full purge +
re-ingest each time, not an incremental run):

| defect | before | after |
|---|---|---|
| prompts with private-use-area glyphs | 16 | **0** |
| MCQ option sets with PUA glyphs | 17 | **0** |
| mark-point sets with PUA glyphs | 34 | **0** |
| prompts with `© UCLES` / copyright bleed | 30 | **0** |
| MCQ rows with a blank (diagram-only) option | 3 | **0** |
| prompts with a flattened exponent | 4 | **0** (1 residual hit is a verified false positive — "1050 J") |

**Decisions.**

1. **Symbol-glyph recovery is a shared det module, not a question-paper concern.**
   `lemely/io/det/symbols.py` holds the Adobe SymbolEncoding table and `desymbolize()`;
   `tables.py` now runs every qualifying mark-scheme cell through it at selection time.
   That placement is the decision: the 34 mangled mark-point sets were *not* a P4.1 bug,
   they were the **marking engine** reading the same garbage since Phase 2 — fixing it in
   the extractor would have cleaned the bank and left the marker broken. Fixed once,
   upstream, so every consumer benefits.
2. **Five delimiter codepoints added to the table** (`[ ] { | }`). A corpus scan found
   113 PUA glyph occurrences in mark points, of which exactly 6 were unmappable — all
   `0xF07B`/`0xF07D`, SymbolEncoding braceleft/braceright, an identity mapping at their
   ASCII positions. Adding them takes unmappable to **zero** on this corpus, so nothing
   is silently dropped from a marking point.
3. **The end-of-paper block terminates extraction; "BLANK PAGE" does not.** The copyright
   bleed was not the running footer (already filtered) but the *last page's* notice being
   appended wholesale to the final question. Anchoring the terminator on "BLANK PAGE" was
   rejected: CAIE also inserts blank pages **mid-paper** between sections, so that would
   silently truncate a paper — a failure that looks exactly like a short paper. Pinned by
   `test_mid_paper_blank_page_does_not_truncate_extraction`.
4. **A missing `--schemes-dir` now raises instead of reporting zero.** Previously every
   paper fell through to `papers_no_scheme` and the run printed "0 banked" and exited 0 —
   indistinguishable from a real finding about the corpus. `click.Path(exists=True)` on
   the flag plus a `FileNotFoundError` in `ingest_question_papers_dir` for both directories.

**The yield went down, 298 → 273, and the report says so.** Leaves whose text contains a
glyph this module cannot confidently map are now excluded rather than banked with garbage
in them — the same policy already applied to figure-dependent stems (UI spec §1.4). 25
questions moved from "banked, subtly corrupt" to "not banked". That is the right
direction and the number should not be quoted as a regression.

**Known limitation, not fixed:** 7 of 273 prompts (2.6%) contain an orphaned
symbol-only line — a raised `°` that pdfplumber bands as its own text line, so
"100 °C" extracts as "°\n...100  C". The text is correct and readable, the line
break is wrong. Merging vertically-overlapping line bands risks over-merging real
lines; deferred and recorded rather than guessed at. Relevant to P4.11's
"maths notation verified visually in screenshots, not assumed".

**Environment fact worth not re-deriving:** the paperscraper corpus (648 PDFs across
0580/0606/0625) lives **outside this repo** at
`/home/sico/PaperScraper/papers/CAIE/igcse/<subject>-<code>/<year>/<session>/`. Nothing
under `Sources/` holds question papers.

### D4.1 — The question-stem extractor closes D3.7, and the honest yield is about a third of the corpus (P4.1)

**Context.** D3.7 established that `question_bank` ships empty for a *structural*
reason, not a corpus-size one: a CAIE mark scheme carries marking points but no
question **stem**, the stem lives in the question paper, and no question-paper
extractor existed. Phase 4's placement test (S-04) and practice generator (S-20)
are both meaningless against an empty bank, so this was the first task of the phase.

**Decisions.**

1. **Deterministic, zero-Gemini extraction.** `lemely/io/det/question_papers.py`
   uses pdfplumber only, mirroring the existing `lemely/io/det/` mark-scheme parser's
   structure and config conventions. Rejected the obvious alternative (Gemini vision
   per question) on budget grounds that are not close: the hard cap is $8.00 with
   $0.1586 spent, and per-question LLM extraction over 312 papers would exhaust it
   many times over. A deterministic path also re-runs free, which matters because
   ingestion will be re-run every time the extractor improves.

2. **A stem that depends on an unextractable figure is not banked.** 651 of the 2090
   leaves examined in the 0625 corpus were excluded on this rule. This is the
   expensive decision and it is deliberate: text-extracting "Which diagram shows the
   rod in equilibrium?" and banking it without the four diagrams produces a question
   no student can answer, which is inventing precision (UI spec §1.4). The ingest
   reports every exclusion **by reason** rather than reporting a yield.

3. **No marking points, no bank row.** The bank feeds a marking engine, so a stem
   with no matching mark-scheme entry cannot be marked and is skipped, not banked
   with an empty scheme.

4. **Topic stays `NULL` here.** Deriving a topic from the extractor would be a guess;
   classification is P4.2 and is done against a real syllabus taxonomy.

**Measured yield over the real 0625 corpus** (orchestrator-run, not taken from the
subagent's report): 72 papers → 2090 leaves → **298 banked** (206 MCQ, 92 theory),
651 figure-excluded, re-ingest idempotent. So roughly a third of the corpus is
bankable today, and the report says so rather than rounding it up.

**The binding upstream constraint, worth not re-deriving.** Only **32 of 72** 0625
mark schemes parse deterministically at strict tolerance (`--on-error continue`
reports 40 failures, mostly `mark_total_mismatch`). Since a stem needs its scheme to
be bank-eligible, **mark-scheme parse coverage — not stem extraction — is what caps
the bank size.** Improving the det mark-scheme parser is the highest-leverage way to
grow the bank; B2's two fixes are precedent that these failures are real extraction
defects, not a tolerance to relax.

**Verification found four defects the subagent's own tests missed**, all in the
*content* rather than the structure, and all found only by reading the banked rows
back out of Postgres: Adobe Symbol-font characters arriving as U+E000–F8FF private-use
garbage (Δ, × unreadable) in 16 prompts / 34 mark-point sets / 17 option sets; `© UCLES`
page footers bleeding into 30 stems; 3 diagram-only MCQ questions banked with empty
option strings (the `has_figure` guard checked the stem but not the *options*); and
flattened superscripts turning `1.3 × 10⁷ m/s` into `1.3 × 107 m/s`, which does not
look broken and silently asks a different question. **How to apply:** structural tests
passing over synthetic PDFs says nothing about extraction fidelity on real documents —
read the persisted rows back and grep them for corruption before believing a yield.

## Phase 3

### D3.21 — Real past-paper accuracy: both totals land inside tolerance, and the MCQ paper is the worrying one (INBOX-2026-08-07-ACC)

**Context.** The human's INBOX directive supplied two genuine solved CAIE 0625
scripts (`0625_s23_qp_22`, 34/40, MCQ; `0625_w24_qp_41`, 66/80, theory with
method marks) and asked for a real end-to-end accuracy measurement — ingest →
OCR → mark → grade, no mocked Gemini, no reconstructed scheme. B1 (missing
official mark schemes) and B2 (the w24 scheme reconciling 83/80) were both
resolved first; nothing here was measured against a scheme this build invented.

**Decisions, all fixed before any result was seen so none can be tuned to the
outcome.**

1. **Tolerance is ±10% of each paper's own maximum** (±4 on 40, ±8 on 80),
   implemented in `lemely/accuracy/real_papers.py::tolerance_marks`. Justified
   by adjacent CAIE boundaries on these papers sitting ~6–10% of max apart: an
   error inside the band risks at most one grade band.
2. **The two papers are reported separately and never averaged** (directive
   item 5). Their signed errors are +3 and −3; averaging them would manufacture
   a "no systematic bias" claim out of two unrelated failures in opposite
   directions. `test_fixtures_are_declared_as_two_separate_cases` pins the
   shape structurally.
3. **The live run is gated on `LEMELY_LIVE_ACCURACY=1` plus a resolvable Gemini
   key**, and caches to `run_summary.json` so re-runs replay for $0 and the
   committed report stays reproducible. A bare `pytest` never bills the cap.
4. **Confidence distribution is weighted by marks, not by question count** — a
   1-mark MCQ marked high and an 8-mark method question marked low are not the
   same quantity of confidence.
5. **Only a numbers-only `REPORT.md` is committed.** `per_question.json`,
   `raw_run.json` and `annotation_overlay.pdf` carry a minor's transcribed
   handwriting and scan imagery; `reports/accuracy-real/*/` is gitignored,
   extending the judgment already applied to the fixture PDFs. That gitignore
   entry doubles as directive item 7's dataset/export exclusion list.

**Result.** Both papers are within tolerance, so the tests are green honestly —
nothing was loosened. Paper 22: predicted 37 vs 34, signed +3. Paper 41:
predicted 63 vs 66, signed −3.

**The finding that matters is not the error size — it is which paper flagged
itself.** Paper 41 (AI marking) assigned medium confidence to 20 of its 80
marks and returned paper-level `grade_confidence: low`; a teacher is pointed at
the right quarter of the script. Paper 22 (MCQ) returned **all 40 marks at
confidence 1.0 / band high and zero review flags** — and was still 3 marks
wrong. MCQ marking is deterministic string comparison against the official key,
so *no marking-judgement error is possible on that path*: all 3 marks of error
are vision/transcription error, and the confidence signal is measuring the
marker while the mistake happened in the extractor. The system was maximally
confident precisely where it had no basis to be. That is a direct violation of
the "visible confidence" principle (UI spec §1.4) in the failure direction that
matters, and it is invisible to every gate this build currently runs.

**Not fixed here, deliberately.** Propagating extraction confidence into the
per-question confidence on the deterministic MCQ path is a change to the
marking contract; it is recorded as a known limitation for DELIVERY.md rather
than patched unattended at the end of Phase 3.

**Also honest about what the totals cannot show.** Ground truth is the paper
total only. A correct-looking total can be two cancelling errors, and nothing
in this exercise can distinguish that case — which is why the per-question JSON
and rendered annotation overlay exist as the human's local spot-check route.
No per-question ground truth was fabricated or back-derived from the pipeline's
own output (directive item 2).

**Cost.** $0.021 for this run (2 vision extractions + 43 correction calls);
cumulative Gemini spend **$0.1586 / $8.00**.

### D3.20 — `web/` gets Vitest, in Node, with no component-rendering stack (P3.10 chunk e3)

**Context.** MISSION §6 gate 3 requires "frontend unit tests green". For the whole
build there has been no frontend test runner at all, so that gate has been
*vacuously* satisfied — it passed by having nothing to run. P3.7 chunk b recorded
this and explicitly warned against briefing a chunk to "add the missing frontend
unit tests" before a runner existed; P3.10 carried it as open item (c).

**Decision, three parts.**

1. **Vitest, not Jest.** Vite is already the build tool; Vitest reuses its
   resolver and transform pipeline, so a test imports `@/lib/utils` under the same
   rules the app does. Jest would mean a second, differently-configured transform
   chain that can disagree with the build — framework drift for no gain. One
   devDependency (`vitest`), no babel config, no transformer config.

2. **`environment: "node"`, and no jsdom / no @testing-library.** This is the part
   worth arguing. The obvious next step from "we have a runner" is to render
   components into jsdom, and that is deliberately *not* taken. Component and
   screen behaviour is already covered by the Playwright suite, which drives the
   real Chromium against the real backend and the real Alembic-migrated database.
   A jsdom-based component stack would be a second, lower-fidelity account of the
   same behaviour — and D3.13 is this build's own hard evidence about what happens
   when a lower-fidelity fixture (`create_all()` instead of the migration) is
   trusted: it was self-consistently wrong against itself for four chunks while
   every gate stayed green. jsdom stands in the same relation to a browser. So the
   runner's remit is the two things Playwright genuinely cannot see: pure logic,
   and repo-wide invariants over source text.

   Consequence accepted honestly: there is still no unit-level coverage of React
   components, and the phase report says so rather than implying a runner means
   the frontend is unit-tested. Revisit only if a component grows logic worth
   testing away from a browser — and then argue the case, don't assume it.

3. **`check-design-tokens.mjs` is deleted, its two invariants moved into
   `web/tests/unit/design-tokens.test.ts` verbatim.** That script existed only
   because no runner did, and its own header instructed exactly this migration. In
   `check.sh` the `design-tokens` gate becomes `web-test`, so the gate count is
   unchanged at 13 and no invariant is lost in the move. Both were re-verified by
   inversion after the move, not assumed: unregistering `"metadata"` from
   `CUSTOM_FONT_SIZE_CLASSES` fails the utils.ts↔index.css drift check, and
   pasting a raw `#ff00aa` into a teacher screen fails the literal scan.

**Also fixed here.** `tests/` gets its own `tsconfig.test.json`, referenced from
the root `tsconfig.json`, so `npm run typecheck` covers the tests. **Note the gap
this exposes and does not close:** `web/e2e/` and `playwright.config.ts` are in no
tsconfig `include` either, so the Playwright specs — the build's most expensive
gate — have never been typechecked. Left alone in this chunk (pulling them in
would mix an unknown number of pre-existing type errors into a runner chunk);
recorded in the phase report as measured debt.

**Two vacuity guards in the moved suite, deliberately.** Both invariants iterate a
list derived from source (`it.each(registered)`, `it.each(files)`). An empty list
makes `it.each` register zero cases and the suite reports green — the exact
failure mode where a mistyped path or a renamed constant silently disables the
check. Each block therefore asserts its list is non-empty first. Do not remove
those as trivial.

### D3.19 — B3's MCQ integrity guard is on question *type*, and it exempts AI-detection too

**Context.** B3 (`BUILD/BLOCKERS.md`): `apply_integrity_checks` ran the plagiarism
similarity check on any question with both a student answer and an expected answer.
For an MCQ both are the same single letter, so `SequenceMatcher.ratio()` is exactly
1.0 on every *correct* answer and 0.0 on every wrong one. A 40/40 paper produced 40
plagiarism flags and 40 review-queue items; a 0/40 paper produced none. Found by the
P3.10 chunk-e1 subagent, re-verified independently before acting.

**Decision, and the three sub-choices that were not forced by the blocker.**

1. **Guard on `question.type == QuestionType.MCQ`, not on answer length.** Length is
   the tempting proxy — it needs no mark-scheme lookup — but it would exempt a
   one-character *free-text* answer, which is a genuinely checkable case. The
   mark-scheme lookup already existed inside the AI-detection branch; it was hoisted
   to the top of the loop, so the type is now resolved once and shared, not twice.
2. **A question absent from the mark scheme keeps being checked.** It cannot be
   classified, and the two failure directions are not symmetric: wrongly exempting
   silently disables a real integrity check, wrongly checking produces a visible
   advisory flag a teacher can dismiss. Default to checking.
3. **AI-detection is skipped for MCQ as well** — wider than B3's stated fix, and
   deliberate. The same type confusion applies (single-letter authorship is not a
   meaningful question), and there is a budget argument the correctness one does not
   carry: with `ai_detection_enabled=True` the INBOX accuracy fixture's 40-question
   MCQ paper would spend 40 Gemini calls classifying 40 letters against a hard $8
   cap. `ai_detection_enabled` defaults to False, so this changes no current
   behaviour — it removes a live foot-gun before P4 turns the setting on.

**Rejected:** raising `plagiarism_threshold`. Nothing above 1.0 is reachable, and
desensitising a real check to hide a type-confusion bug is the same class of act B2
explicitly ruled out for `mark_reconcile_tolerance`.

**Verified by inversion, not assumed.** Forcing the guard to `False` fails the three
MCQ tests (including `[True, True] == [False, False]` on the whole-correct-paper
case); restoring it passes all 21 in `tests/test_integrity.py`. The two
"still checked" tests deliberately pass either way — they are regression guards
against a future over-broad exemption, not evidence for this fix.

**One pre-existing test was pinning the defect, and that is the real lesson here.**
`tests/test_integrity.py` passing is not the whole story: the fix was left uncommitted
with the *suite* red. `tests/test_student_correct.py::
test_upload_then_correct_persists_attempt` — the end-to-end upload→correct→persist
test, i.e. the one place the real path was exercised — asserted **2** review-queue
rows, and its comment justified the second one in the defect's own terms ("q1's
deterministic MCQ answer ('A') is verbatim-identical to the expected answer ('A'), so
the … plagiarism checker also flags it"). B3 shipped in P2.4 and survived to P3.10
behind a green suite *because* that assertion had been written to match the observed
output. Corrected to 1 row (`low_confidence`), with the history kept inline so it is
not silently re-flipped; MISSION §5's "if the test is genuinely wrong, document why"
is the governing rule, and this is the genuine case, not a convenience.

The other 20+ `plagiarism_flagged` assertions across `test_web_review.py`,
`test_review_repo.py`, `test_attempt_repo.py` and `test_web_app.py` set the flag
directly on a `CorrectedQuestion` and never call `apply_integrity_checks`, so none of
them constrained the fix — a fact worth knowing before anyone reads "23 tests mention
plagiarism" as coverage of this behaviour. **Generalisable:** a test comment that
works hard to explain why a surprising assertion is correct is a good place to look
for a defect.

**Consequence for the INBOX accuracy task.** Its paper 22 (`0625_s23_qp_22`, MCQ,
ground truth 34/40) would have generated 34 false plagiarism flags, so the
confidence distribution directive item 3 asks for would have been measuring this
defect. That contamination is now gone; the task can report on the marking itself.

### D3.18 — The token retrofit: the inherited premise was wrong, D2.9's workaround was half-applied, and the type scale had a hole (P3.10 chunk c)

**Context.** P3.7 chunk b handed forward carried item (b): "the teacher portal's five
screens use arbitrary px/oklch literals instead of the DESIGN.md token scale (P2.5.3
retrofitted only the student screens). Decide: retrofit them, or record it as accepted
debt." Chunk c measured that premise before acting on it. Two of its three claims are
false:

- It is not five screens. It is **18 teacher files carrying 482 `text-[Npx]` literals**,
  57 arbitrary radii and 34 raw `oklch()` colours.
- The **parent portal was already clean** — zero font-size, radius or colour literals.
  So was `portals/auth/`. Nothing to retrofit there; the "teacher + parent" scoping in
  the chunk title is satisfied by the teacher half alone.
- The student portal was **partly** unretrofitted, and the shared `components/` C-*
  library carried literals of its own. Measured per file rather than in aggregate, the
  split is exact and exonerates P2.5.3: every student screen that was *in scope then* is
  clean (`Overview`, `CorrectPaper`, `PaperResult`, and P3.9's `Parents` — 0 literals
  each). All 141 remaining literals sit in `Subject` (37) plus the five P4/P5 mock
  surfaces `Landing` (30), `Directions` (19), `StudyPlan` (15), `Standings` (14) and
  `Onboarding` (13) — which is precisely the set chunk b kept out of the audit registry.
  So P2.5's acceptance criterion held for its own scope; the aggregate count is
  misleading and an earlier draft of this entry read it as a P2.5 failure, which it is
  not.

**What was done.** The teacher portal, the shared `components/` library and the student
*shell* (`portals/student/index.tsx`, which wraps all four in-gate student routes) are
retrofitted — 598 literals replaced, leaving zero in all three.

**What is left, and why.** 141 literals in six student screens. Five are P4/P5 mock-data
surfaces; retrofitting unbuilt work is the same mistake as gating it, so they wait for
the phase that builds them. The sixth, **`Subject.tsx` (37 literals), is the one genuine
gap** — a real, API-backed P2 screen (`useSubject`) that P2.5.3 did not reach and that
chunk b excluded from the registry as "real but P2's". It is not fixed here because it
is outside both the chunk's stated scope and the audit gate that would prove the fix
safe; it is named so the phase report can carry it as debt with a number attached rather
than as a vague "some screens".

**The three findings behind the mechanical work.**

1. **D2.9's workaround was only ever half-applied, and the other half was live.** D2.9
   found that a `text-`-prefixed custom class falls into tailwind-merge's `text-color`
   group, so `cn()` silently drops either it or the colour beside it, and fixed it by
   renaming the button rungs to `.btn-text*`. The *composite type-scale* classes
   (`.text-display-*`, `.text-body-*`, `.text-label-sm`, `.text-metadata`) were left in
   the trap. Verified empirically this chunk: `twMerge("text-display-md text-t1")`
   returned `"text-t1"` — the font-size, family and line-height dropped entirely. **Five
   shared C-* components hit exactly that shape** (`trend-sparkline` twice,
   `boundary-bar`, `confidence-indicator`, `paper-identity`), so the defect shipped on
   every student and parent screen composing them. It is invisible to every gate the
   build has: a dropped type class degrades to *inherited* type, which is not a type
   error, a lint error, a console error, an axe violation or a layout overflow.

   Fixed at the source instead of by renaming again: `lib/utils.ts` now builds `cn()`
   from `extendTailwindMerge` with every custom `text-*` class declared as a font-size.
   D2.9's "never name a custom class `text-anything`" rule is superseded — the correct
   rule is **"register it"**, which also lets rungs be named for what they are.
   `.btn-text*` keep their names (load-bearing in `button.tsx`'s cva variants).

2. **DESIGN.md's type scale has a hole between 15px and 30px.** Its `typography:` table
   jumps straight from `body-lg` (15px) to `display-md` (30px), so every dense-dashboard
   serif heading had nowhere on-scale to land — which is precisely why the teacher portal
   invented 19/20/22/24/26/34px ad hoc across 18 screens. Two rungs were added,
   `--fs-display-sm: 24px` and `--fs-display-xs: 19px`. These are not invented brand
   values: they continue the table's own ~1.25 ratio (30/24 = 1.25, 24/19 = 1.26,
   19/15 = 1.27). The ad-hoc sizes collapse onto the scale as 34→display-md,
   26/24/22→display-sm, 20/19→display-xs.

   Three size-only "dense" rungs (13.5/13/12.5px) were also added, aliasing the existing
   `--fs-button-text*` raw values. The numbers were already tokenized, but only as
   *composite* `.btn-text*` classes that also set weight 500 and line-height 1 — unusable
   for the 240 table cells and captions that need the size alone. Same for `--text-md`
   (15px), needed because `.text-body-lg` would have overridden `font-mono` on Grading's
   two readouts.

3. **The raw `oklch()` literals in the teacher portal were the *student* palette.** All
   34 were hue 78/60/68 warm-terracotta values hardcoded from the pre-DESIGN.md mock,
   surviving into a portal whose accent is teal. They are now semantic tokens, so they
   follow `[data-portal]` like everything else. One genuine gap was filled to do it
   honestly: `--accent-subtle-on`, defined per portal
   (`--md-on-{primary,tertiary,secondary}-fixed`), for the badges that sat on
   `bg-accent-subtle` with a hand-picked foreground and no defined on-colour.

**Deliberate consequence, not an oversight.** Adopting a composite type class means
adopting its line-height: the class is unlayered CSS and so beats any `leading-*` utility
beside it. Rather than preserve ad-hoc `leading-none`/`leading-[1.08]` overrides that
could not win anyway, the conversion drops them — size and leading travel together, which
is what a type scale is for. The 21-route audit gate is what proves nothing broke.

**Testing.** `web/` still has no unit-test runner (that decision belongs to chunk e), and
both invariants here fail *silently*, so `web/scripts/check-design-tokens.mjs` is a
standalone guard wired into `scripts/check.sh`: it asserts every registered custom class
survives `cn()` beside a colour in both orders, that two sizes still collapse, that
`lib/utils.ts` and `index.css` agree in **both** directions, and that no arbitrary
font-size/radius/colour literal has reappeared in the retrofitted paths. Verified by
inversion — it fails against the unregistered class and against a reintroduced
`text-[13px]`. If a real runner lands, these checks move into it verbatim.

**Also removed here (carried item (d), plus two of the same class found beside it).** The
student sidebar's hardcoded "Maya Rahman / Year 11 - Helwan Science Centre" and "MR"
initials — the twin of the teacher fiction P3.7 chunk b deleted — now render the real
caller via `useProfile()`. The header's fabricated `<span>`-as-search-box (no handler, no
search endpoint anywhere in the API) and its "24 day streak" pill are gone. The streak was
**not** wired to real data on purpose: the only streak-shaped field in the API is
`StandingsDTO.streakDays`, which is `len({distinct dates in history})` — a count of active
days, not consecutive ones. Wiring it would have swapped a hardcoded lie for a mislabelled
one. Streaks are Phase 5's to build; the misnomer is flagged there.

### D3.17 — The UI gate stops being a 4-route gate: a 21-route registry, real console/responsive gates, and an unreachable route is a failure (P3.10 chunk b)

**Context.** D2.10 fixed `web/scripts/audit.mjs` at exactly four student routes, and
`audit.mjs` was a 506-line linear journey rather than a route table, so every screen
built in P3.7–P3.9 sat outside the axe/Lighthouse/screenshot gate. That gate therefore
passed by never looking — evidenced three separate times (P3.8c's `text-t3` contrast
finding, and two serious axe violations P3.9 could only find by hand).

**The decisions.**

1. **`ROUTE_REGISTRY` is a declarative table of 21 routes**, replacing the hardcoded
   journey. The four D2.10 routes stay in `runStudentMainJourney()` because they are
   genuinely a stateful sequence (sign up → log in → upload a real scan → get a real
   `paperId`); the other 17 are data, visited by one generic `visitRoute()`.

2. **Exclusion criterion changed from "no *populated* fixture" to "the seed cannot
   reach the route at all."** An empty state is a state, and it is exactly where a
   violation hides — `/teacher/grading` and `/teacher/schemes` are audited empty, and
   that is precisely how their missing `<h1>` was found. Only
   `/teacher/review/:itemId` and `/teacher/quizzes/:quizId` (+ its results route)
   remain out: the seed creates no review item and no quiz, so both would 404 rather
   than render anything. The P4/P5 mock-data screens stay out deliberately — gating
   unbuilt work is not coverage.

3. **Authenticated routes inject a real seeded session rather than re-driving four
   login UIs**, and **each session key gets its own incognito browser context, not
   just its own page.** `localStorage` is per-origin: sharing one context made
   `/login/parent` redirect to `/student` (correctly — `LoginRoute` navigates an
   authenticated visitor away from every login route), so the "unauthenticated" route
   was not unauthenticated. Isolated contexts are what make the registry independent
   of route ordering.

4. **A registry route that cannot be reached fails the gate, and the run continues.**
   One dead route must not hide the other twenty; failures are collected and the run
   exits non-zero at the end. This is strictly stricter, never more permissive — a
   failed route contributes no axe/Lighthouse row, and `check_ui_gates.py` can only
   check rows that exist, so without this a broken route would have read as silence.

5. **Console errors and horizontal scroll are now real gates**, not numbers a human
   reads: `check_ui_gates.py` reads `console-errors.json` and
   `responsive-summary.json`, and treats a *missing* file as "not checked" (a
   failure), never as "clean". A responsive violation now also names the offending
   elements, widest-overhang first — the difference between a fixable report and
   "something on this page is 10px too wide".

6. **`--t3` is fixed at the token, not per-screen.** The mix moved from
   `outline 65% / on-surface-variant 35%` (#76615e) to `35% / 65%` (#67534f). A
   per-screen retrofit would have to be repeated on every future screen that reaches
   for caption text; one token change fixes every screen at once, and `--t3` is still
   visibly the most muted of the three text tokens.

**The honest part of (6).** P3.8c reported axe measuring `text-t3` at **4.36:1**. That
is below the hand-calculated ratio against *every* base surface token (4.48–5.77:1),
so whatever axe sampled was composited over a background darker than any of them — a
chip, hover or overlay background, not `--surface`. **The exact element was never
root-caused**, and the earlier claim in `index.css` that the gap was axe accounting for
glyph rasterization was simply wrong (axe computes contrast from computed colours; the
same two colours always give the same ratio, so a divergence means the background
differed, never the maths). The comment has been corrected to say so. What *is*
independently established is that the old value failed AA at 4.48:1 against
`--md-surface-container-highest` regardless, and that the new value clears AA by at
least 1.08 on all six surface tokens.

**Alternatives rejected.** (a) *Per-screen `text-t3` → `text-t2` retrofit* — fixes the
screens that exist and none of the ones P4/P5 will add. (b) *Fail fast on the first
unreachable route* — costs one ~11-minute run per broken route; the aggregate report
found T-02's wrong readiness predicate and the console-error artifact in a single pass.
(c) *Swallowing the `about:blank` `SecurityError` in a bare try/catch* — that would
also silence a genuine storage failure on a real origin; the injection skips opaque
origins explicitly instead.

### D3.16 — G-05's developer OTP affordance is gated on the *provider's* capability, not on an environment string (P3.9 chunk a)

**Context.** `docs/LEMELY_UI_SPEC.md` §G-05 mandates a "clearly-marked developer
affordance that shows the code on screen in non-production environments, so this is
testable without a real SMS provider." Today the code exists only in a log line
(`MockSmsProvider.send_code`), and `OtpRequestResponseDTO`'s docstring records a
deliberate prior decision that the acknowledgement "never carries the code" —
`AuthService.request_otp` returns `None` on purpose. Satisfying the spec means
reversing that, so the reversal has to be narrower than the guarantee it replaces.

**The decision.** `SmsProvider` gains a `delivers_out_of_band: bool` capability.
`MockSmsProvider` sets it **False** (it logs; nothing reaches the parent's handset).
A real gateway sets it True. `AuthService.request_otp` returns `str | None` — the code
**iff `not provider.delivers_out_of_band`** — and the route surfaces it as
`OtpRequestResponseDTO.devCode`, which the UI renders in an explicitly-labelled
developer panel. There is no settings flag and no environment check anywhere in the
path.

**Why the capability and not an env var.** "Is this production?" is a string a
misconfiguration can get wrong while the system keeps working; "does this provider
actually deliver the code to the user by another channel?" is a property of the code
that is running. Gated on the capability, the only way to leak a live OTP over the API
is to ship a provider that both fails to deliver and claims it does — at which point
the OTP is unusable anyway. Gated on an env var, one wrong deploy value leaks every
live code. This is the same structural-exclusion shape D3.8 used for answer leakage
(the guard is the absent capability, not a remembered conditional).

**Alternatives rejected.** (a) *A dev-only route that reads the last issued code* —
a second, separately-gated surface whose whole purpose is to disclose a secret; strictly
more attack surface than a field on the response that already exists. (b) *Leave it in
the log and have the UI say "check the server console"* — does not satisfy the spec's
"shows the code on screen", and makes the Playwright OTP flow in P3.10 depend on
scraping backend logs. (c) *A settings boolean* — see above.

**What this does not change.** The code is still never returned when a real provider is
configured, the resend cooldown (429) and attempt counter are untouched, and nothing
about `verify_otp` changes.

### D3.15 — T-09's six steps do not map 1:1 onto the quiz data model, and two of the spec's step-1 fields belong to the assignment (P3.8 chunk c)

**Context.** UI-spec §T-09 specifies a six-step flow whose step 1 is "basics — title,
subject, class, due date, optional time limit". The quiz data model
(`docs/quiz-model.md` §1.4/§1.6, built in P3.5 and fixed by D3.6) has **no `class_id`,
`due_at` or `closes_at` column on `quizzes`** — all three live on `quiz_assignments`,
because §1.6's whole point is that one quiz can be assigned to several classes with
different due dates. So the spec's step 1 asks the builder to collect two fields the
draft row cannot store.

**Decision.** Collect `class` + `due date` (+ `closes at`) at **step 6 (assign)**, where
they become a real `quiz_assignments` row, not at step 1. Step 1 collects
title + subject code + optional time limit — exactly the fields the draft row has.
The other five steps map 1:1: 2 → `included_topics`, 3 → `target_grade`,
4 → `pool_source` + `GET /pool-count`, 5 → `POST /questions/generate` +
`DELETE /questions/{ref}`, 6 → `POST /assignments`.

**Why not the alternatives.**
- *Collect class/due at step 1 and hold them in client state until step 6.* "Draft saving
  throughout" is a named T-09 state; a teacher who fills step 1, leaves, and resumes would
  silently lose two of the four fields they entered — the draft would be visibly
  lying about what it saved. Worse than moving the fields.
- *Add `class_id`/`due_at` columns to `quizzes`.* Directly contradicts §1.6 and D3.6, and
  would create a second, conflicting answer to "when is this quiz due" for a quiz assigned
  to two classes. The schema is right; the spec's step-1 list was written before it.

**Two related calls made in the same chunk.**
1. **Topic source for step 2 is free-text entry plus suggestions from the teacher's own
   classes** (`ClassSummary.topWeakness`, already fetched for step 6's class picker and
   already roster-scoped). Deliberately **not** `GET /api/quizzes/topics` — that P2-era
   route folds *every student in the history store* into one aggregate, i.e. it is the
   same cross-tenant enumeration P3.3 removed from `/api/teacher/overview`. Wiring a new
   screen to it would reintroduce the leak on a different surface.
2. **The mock's "Predicted class average" panel is deleted, not ported.** It is invented
   precision (UI-spec §1.4) with no data source: nothing predicts a class's score on an
   unwritten quiz. Same treatment as D3.12's refused class-level average predicted grade.

**Consequence to report, not to paper over.** Because `question_bank` ships empty (D3.7),
a first-time teacher's step 4 count is genuinely 0 for `past_paper` and step 5 generates
nothing. The builder renders the backend's own `message`/`shortfall` verbatim and names
which constraint to loosen; it never shows a plausible number and never invents questions.

### D3.14 — P3.8's three spec-vs-reality gaps: what T-08 and T-12 can honestly show

**Context.** P3.8 builds the last five teacher screens. Three things the UI spec asks for
have no data behind them, and each has a tempting fake.

**1. T-08's "student's actual scan crop, side by side with the mark scheme extract."**
Neither is persisted. `QuestionResult` stores the *transcription* of what the student wrote
and the ids of the mark-scheme points the marker matched — not pixels, and not the scheme
text. `ReviewItemDetailDTO`'s docstring already recorded this at P3.4; P3.8 is where it
becomes visible, because this is the screen that was supposed to show them.
**Decision: render `studentAnswer` (labelled as Lemely's transcription, not as the scan),
`expectedAnswer`, and `matchedPointIds`, and state plainly on the screen that the original
scan crop is not stored.** Rejected: a placeholder image frame (implies a missing asset
rather than an absent capability), and reconstructing a "mark scheme extract" from the
matched point ids (that is inventing precision — UI-spec §1.4 — since the ids are
identifiers, not the scheme's prose). The teacher is deciding whether the AI misread a
student; telling them they are looking at a transcription rather than the paper is
load-bearing information, not a caveat to bury.

**2. T-12's "optional attachment."** No attachment column on `announcements`, no storage
wiring for anything but student paper uploads. **Decision: omit the control entirely**,
the same treatment T-05's absent integrity signals and "contact route if configured" got in
P3.7 chunk d. Rejected: a visibly-disabled upload button — "Coming soon" was right for T-08
"assign practice" because that feature is scheduled (P4); an attachment is not scheduled
anywhere, so the tag would be a promise nobody has made.

**3. T-12's audience selector wants "several classes"; `announcements.class_id` is a single
nullable FK.** Additive-only (D1.2/D1.3) means no join table without a strong reason.
**Decision: one row per selected class, all written in one request and reported back as a
group.** A whole-school announcement is the existing `school_id`-set/`class_id`-NULL shape.
Rejected: an `announcement_audiences` join table (a new table to model a fan-out that the
existing row shape already expresses); rejected: a comma-joined `class_id` string (unindexable,
breaks the FK). Consequence to accept, not hide: editing or deleting a multi-class
announcement acts per class row.

**4. Nothing delivers these to students.** There is no student announcement surface, no
notification send path, and `notification_preferences` (P3.6 chunk b) is written but never
read. MISSION §4 puts announcement delivery and the student calendar in **Phase 5**.
**P3.8 ships compose/list/delete only, and the phase report must say students cannot see
them yet** rather than letting a working composer imply a working feature. The composer's
mandated "preview of how it appears to a student" is honest — it is explicitly a preview.

### D3.13 — A whole class of DB bug that neither `pytest` nor `alembic check` can see (P3.7 chunk d)

**What happened.** Every `POST`/`DELETE /api/teacher/at-risk/{id}/acknowledge` call 500'd against
any real, Alembic-migrated stack, and the entire 12-gate suite was green throughout.

`AtRiskAcknowledgement.reason` was declared `sa.Enum(AtRiskReason, name="atriskreason")`.
SQLAlchemy's default enum binding converts a Python enum member to its DB string using
**`.name`, not `.value`**. Migration `0006` creates the Postgres type with the lowercase
*values* (`declining_trend`, `below_target`, `inactive`), so every query bound
`"DECLINING_TREND"` and Postgres answered `DataError: invalid input value for enum
atriskreason`.

**Why 25 other enum columns are fine, and why that is exactly the trap.** Every enum mirrored
in `lemely/db/models/enums.py` is declared with lowercase member names equal to their values
(`low_confidence = "low_confidence"`), so `.name == .value` and the default binding *happens*
to be right. `AtRiskReason` (`lemely/core/at_risk.py`) is the one DB-backed enum reused
straight from `lemely.core` rather than mirrored under that convention, and it uses ordinary
`SCREAMING_SNAKE_CASE` members. Verified by enumerating all 25: it is the only DB-column enum
whose `.name != .value`. The convention was load-bearing safety nobody had written down.

**Why every gate missed it.** `tests/test_at_risk_repo.py` builds its schema with
`Base.metadata.create_all()`, which derives the enum's DDL labels from *the same buggy
declaration* — so the test database's type accepted `DECLINING_TREND` and the tests were
self-consistently wrong. `alembic check`'s comparator does not diff enum labels either, so the
drift between the model and migration `0006` was invisible to it too. Only a real E2E run
against the migrated stack could surface this, and T-06 was the first screen to exercise the
write path.

**The standing rule this leaves.** For any `sa.Enum(SomePythonEnum, ...)` column, either the
enum's member names must equal its values, or the column must pass
`values_callable=lambda enum_cls: [e.value for e in enum_cls]`. Neither `pytest` nor
`alembic check` will tell you; a `create_all()`-based test fixture actively hides it. Treat
"the unit tests pass against a `create_all()` schema" as **no evidence at all** that a column
works against the migrated database.

### D3.12 — Close the T-01/T-02/T-03 spec-vs-DTO gaps with additive fields, but do not invent a class-level predicted grade (P3.7)

**The decision.** Before building any teacher screen, three of them were checked against the
DTOs that would feed them, and three gaps were found where `docs/LEMELY_UI_SPEC.md` §4.7
names contents no field carries:

- **T-01 item 4** — "Recent activity: submissions across their classes." `OverviewDTO` has
  `stats`, `atRisk` and a structurally-empty `retention`. Nothing else.
- **T-01 item 3 / T-02** — class summary cards want the class's top weakness and activity
  level; the T-02 table additionally wants last activity and an at-risk count.
  `ClassSummaryDTO` carries `id`/`label`/`studentCount`/`average`/`subjectCode`/`schoolId`/
  `joinCode` and none of those four.
- **T-03** — the roster table wants papers submitted, last active, and "at-risk flag **with
  reason**" (the spec is emphatic: "Reasons must be shown, not just a red dot").
  `StudentRowDTO` has a bare `gradeAtRisk: bool` — a red dot and nothing else.

P3.7 adds these as **additive DTO fields** (chunk a), every one derived from data the route
already loads: the overview route already holds every visible student's full history, and
`/teacher/classes` already walks each class's roster. No new query, no N+1, no new engine —
`assess_at_risk` (D3.3) and `lemely.core.history`'s D3.9 predicates are reused as-is.

**The alternatives, and why they lose.** (a) *Omit the columns.* Ships a roster with a red
dot and no reason — a direct violation of the spec line above and of principle §1.4
(flags are signals with evidence, never unexplained verdicts). (b) *Derive them
client-side.* The client would have to fetch every student's detail to compute one class's
at-risk count — an N+1 over HTTP to recompute something the server already has in memory.
(c) *A new endpoint per gap.* Three extra round trips on first paint for fields that fall
out of a loop the route already runs.

**What is deliberately NOT added: a class-level "average predicted grade."** T-01 and T-02
both use that phrase. Averaging letter grades is invented precision — the ladder is ordinal,
the gap between C and D is not the gap between A and A\*, and a "class average of B−" would
be a number the data cannot support. `ClassSummaryDTO.average` (mean latest percentage,
already filtered to grade-bearing records per D3.9) is rendered and **labelled as exactly
that**. This is a knowing, reported deviation from the spec's wording in favour of its §1.4
principle ("never invent precision"), which the authority order in MISSION §10 puts above
the screen-contents prose. It must appear in the phase report as a deviation, not be
quietly "corrected" by a later session inventing the mean grade.

**Honest consequence.** `recentActivity` spans papers *and* quizzes, because the spec says
"submissions", not "papers". A quiz attempt has a percentage but deliberately never a grade
(D3.9/chunk F1), so its `grade` is null on the wire and the UI must render the absence
rather than substitute the student's last paper grade.

### D3.11 — Parent links: the student invites, and only a phone-proven parent can be linked (P3.6)

**The decision.** `parent_child_links` is created by the **student**, naming a parent by
phone number, and the link succeeds only if a `role=parent` user with that phone **already
exists** — i.e. that parent has already completed a phone-OTP verification. If no such user
exists the student gets a clean 404 ("ask them to log in first, then invite again"), never a
created account. `DELETE /api/student/parent-links/{parent_id}` revokes. There is no pending
state and no approval step.

**Why.** `AuthService.verify_otp` already mints a `role=parent` user on first verify, keyed
by phone. The tempting shortcut — let the student's invite mint that user too — turns a
student-supplied string into an account-creation primitive: a bored student could mass-create
parent rows for arbitrary phone numbers, and a single typo would hand a stranger read access
to a child's grades the moment they happened to log in with that number. Requiring the parent
to have proven control of the phone first costs one ordering step (which P-01's empty state
already has to explain anyway, per the UI spec) and removes the vector entirely. The student
is the right initiator because the data being shared is *theirs*; consent on the parent side
is inherent in choosing to authenticate. Revocation keeps it reversible, which is the
MISSION §1 tie-breaker.

**Alternatives rejected.** (a) *Parent requests, student approves* — matches G-11's "pending
parent-link request" chip, but needs an additive status column, a second route pair, and a
notification to be useful; deferred, not precluded (the columns stay addable). (b) *Link via
the school* — the UI spec names it, but no school-side child-registry surface exists yet and
inventing one is Phase-4-shaped speculative work. (c) *Student-generated link code* — a third
code vocabulary beside `classes.join_code` for no gain over a phone number the parent must
already own.

**Scope note.** Linking is not named in MISSION §4's parent bullet or the P3.6 task line.
It is included because without it no `parent_child_links` row can be created outside a seed
script, which would make the entire portal untestable end-to-end in P3.10 and unusable in
production — a read surface with no way to grant it is not a delivered feature.

**Two things this decision refuses to fake.** P-02 asks for predicted grade *against target
grade*: no target-grade column exists until P4's onboarding questionnaire, so `target` ships
`null` and the UI must say "no target set" — the same *not evaluable* honesty D3.3 applied to
at-risk rule 2, not a defaulted target that would make every child look on track. P-04's
"what the child is doing about it" has no data source beyond the existing study plan, so it
reports the plan or nothing.

### D3.10 — T-10 scopes every panel to the live roster, and *reports* the off-roster remainder (P3.5 chunk F2)

`docs/quiz-model.md` §4.6 rule (c) fixes the completion denominator as the **live**
`ClassService` roster, because submissions are created lazily and a snapshotted denominator
drifts the moment a student joins or leaves. It does not say what the *numerator* does when
a student submits and is then removed from the class — and that case is not hypothetical:
`ClassService.remove_student` exists, and enrolment is mutable by design.

Taken literally ("count(status in (submitted, marked))" over all submissions, divided by the
live roster) the rate can exceed 100%: five submissions, four students. Three options were
on the table:

1. **Roster-scope the numerator only.** Simple, never exceeds 1.0, but a departed
   student's marks vanish from the class average, the score distribution and the
   per-question analysis with no trace — a teacher who remembers marking that work sees it
   silently gone and has no way to tell whether it was dropped or never existed.
2. **Include off-roster submissions everywhere.** Keeps the marks, but breaks rule (c)'s
   denominator: the completion rate stops being a rate, and "per-student results" grows
   rows for students the teacher can no longer open (`ClassService.roster` is also the
   tenancy seam — a removed student is out of scope, so showing their name here would be a
   small tenancy regression, not just a display oddity).
3. **Chosen: scope every panel to the live roster, and surface the excluded count** as
   `CompletionStats.off_roster_submission_count` (`offRosterSubmissionCount` on the wire).

Option 3 keeps rule (c) exactly as written, keeps the tenancy seam single (nothing is read
for a student outside `roster()`), and refuses to make a silent omission look like an
absence — which is the same "never invent precision / never hide what you dropped"
discipline D3.7's zero-row measurement and D3.9's `is_paper` split were decided under. The
cost is one extra integer on the DTO and a number the frontend must actually render;
`tests/test_quiz_results.py::test_off_roster_submission_is_excluded_but_reported` pins both
halves (excluded from the aggregates *and* counted).

Not a workaround for a missing feature: there is deliberately no "results for a student who
left" view. If that is ever wanted it is a separate surface with its own scope decision, not
a quiet widening of this one.

### D3.9 — Three predicates, not one: `is_paper` beside `is_grade_bearing` at the web layer (P3.5 chunk F1)

`docs/quiz-model.md` §5 fixes the grade-bearing / topic-bearing split for `lemely/core/`,
and chunk G wired it there. Chunk G also handed chunk F a list of web-layer sites that
derive a grade or percentage straight off `history.records` — harmless until a quiz
attempt exists, live corruption the moment F1 starts writing them. Applying the filter to
those sites turned up a third category the §5 table does not have a row for.

**The problem.** Three surfaces report a *count* that calls itself papers: the teacher
overview's "Papers graded" stat card, T-05's `engagement.totalPapers`, and the student
standings' `paperCount` / per-subject `papers`. Neither existing option is right for them.
Leaving them unfiltered counts a quiz as a paper. Filtering them on `is_grade_bearing`
also drops a *real past paper whose grade came back unreadable* — a paper the student
demonstrably sat and a teacher demonstrably marked — from a count that has nothing to do
with grades. Chunk G hit the same edge from the other side and recorded it: it kept
`grade_distribution` on "latest paper, skipped if its grade is unreadable" rather than
letting an unreadable grade silently promote an older, better one.

**Decision.** Split the predicate in two in `lemely/core/history.py`:

* `is_paper(record)` — origin only. For counting claims that say "papers".
* `is_grade_bearing(record)` — `is_paper(record) and record.grade in GRADE_ORDER`,
  unchanged in meaning and now defined in terms of the narrower one. For anything
  reporting a grade, a percentage, or a paper comparison.

Plus two list helpers, `grade_bearing()` and `latest_grade_bearing()`, because ~15 call
sites needed "the latest grade-bearing record" and inlining that comprehension at each is
how one of them eventually gets forgotten.

**Rejected: filter everything on `is_grade_bearing`.** Simpler, one predicate, and wrong
in the direction that matters — it makes a student's paper count silently disagree with
the paper list beside it whenever a grade fails to parse.

**Rejected: rename the cards** ("Work marked" instead of "Papers graded"). The labels come
from `docs/LEMELY_UI_SPEC.md`, which outranks a backend convenience (MISSION §10 authority
order), and a copy change is not the right fix for a counting bug.

**Third category, applied consistently: activity.** `streakDays`, `lastActiveAt`, and
`daysSinceLastSubmission` take **all** records, quizzes included — matching
`at_risk._check_inactivity`, which §5 already puts in the all-records column. This
deliberately makes T-05 report `totalPapers=1` beside `lastActiveAt` pointing at a quiz.
That is not an inconsistency: a screen telling a teacher a student had been silent for
20 days, next to an at-risk badge that saw them yesterday, would be describing a different
student than the badge next to it.

**Consequences a caller must handle.** A student whose only activity is quizzes now has no
grade anywhere: `StudentRowDTO.grade`, `AtRiskStudentDTO.grade` and `AtRiskListEntryDTO.grade`
report `""`. That is the same "no grade" value `DbHistoryStore` already produces for an
attempt with a NULL grade, so it is not a new state for the frontend — no DTO was made
nullable for this. The roster row itself is *kept* (they are enrolled and they have done
work); what is dropped is the grade claim, not the student. `GET /student/subject/{code}`
404s for a subject the student has only quizzed, because every number on that screen is
paper-derived; the quiz's evidence still appears on the Overview weak threads and in the
topic map of any subject they have also papered.

**Not filtered, deliberately:** `aggregate_weaknesses_from_history` and every topic map,
weakness list, and weak-thread anywhere. A weakness is a weakness whatever revealed it,
and a topic quiz is precisely the evidence those surfaces exist to show. Pinned by
`tests/test_web_quiz_origin_filtering.py`, which asserts both halves on the same seeded
history — 16 of its 18 tests fail against the pre-filter routers, verified by reverting
them.

### D3.8 — Quiz "open" has no column: closed vs overdue, and the unassign guard (P3.5 chunk E)

`docs/quiz-model.md` §1.6 gives `quiz_assignments` a `due_at` and a `closes_at` but **no
`opens_at`**, while UI-spec S-26 lists "not yet open" as one of its four states. Rather than
invent a column (additive-only is cheap, but a column nothing sets is worse than no column),
chunk E resolves the three states off what exists:

- **closed** = the quiz's own status is `closed`/`archived` **OR** `closes_at` has passed. A
  closed assignment cannot be started, saved to, or submitted, and `get_take` returns it
  read-only *without* lazily creating a submission row — otherwise merely looking at an
  expired quiz would mint an `in_progress` row that inflates the teacher's counts forever.
- **overdue** = `due_at` has passed and the assignment is not closed. Overdue is a **flag,
  not a block** (UI-spec §1.4: flags are signals, not verdicts) — a late-but-not-yet-closed
  submission is accepted and simply carries the flag. A teacher who wants a hard cutoff sets
  `closes_at`; that is what it is for.
- **"not yet open"** has no backing state at all: an assignment does not exist until the
  teacher creates it, so there is nothing to be not-yet-open *of*. The UI state is reachable
  purely from a 404. Do not add a column for this later without a product reason.

**The unassign guard, stated honestly.** `quiz_submissions` cascades from
`quiz_assignments`, so deleting an assignment would silently destroy student answers.
`delete_assignment` refuses (422) if any submission has a status other than `not_started`.
Because submissions are created lazily *already* `in_progress` (§1.7 — nothing ever writes
`not_started`; it is the table default and the "no row" sentinel the DTO reports), this is in
practice **"refuse if any submission row exists at all"**. The finer-grained wording is
future-proofing for a state nothing currently produces — not a distinction that fires today.

**Two seams, not one service.** Quiz *building* is scoped by `teacher_id` ownership; quiz
*taking* is scoped by class **enrolment** — a different tenancy axis, so
`QuizTakingService` (`lemely/db/quiz_taking_repo.py`) is separate from `QuizService` rather
than a flag on every method. Its single scoping seam is the new
`ClassService.enrolled_class_ids` (modelled on `member_school_ids`); no second
`ClassEnrollment` query exists for that purpose. `QuizService.create_assignment` /
`list_assignments` gained a `caller_role` parameter — needed only to call the role-scoped
`ClassService.get_class`/`roster`; quiz ownership itself stays strictly `teacher_id`-scoped,
with still no `school_admin`/co-teacher view (D3.6 §1.5's standing exclusion).

**Answer leakage is excluded structurally, not by remembering.** `QuizTakeQuestionRow` has
no `model_answer`, `mark_scheme_points`, or `mcq_answer` field *at all* — it is a strict
subset of `QuizQuestionRow`, so there is nothing at the DTO layer to forget to omit. Pinned
from both directions: a repo test asserts those attributes do not exist on the dataclass, and
a web test asserts the response body contains neither the key names nor sentinel secret
values seeded into the quiz.

### D3.7 — The past-paper question ingest yields zero questions, and always will (P3.5 chunk B)

`docs/quiz-model.md` §2 required chunk B to begin with a measurement of how much usable
question text comes out of the parsed mark schemes, and predicted "expect a non-trivial
fraction" to be skipped for a missing prompt. **The measured fraction is 100%, and the
cause is structural, not a data-quality gap.**

Measurement over the entire parsed corpus (4 mark schemes — 0580_s23_ms_22, 0606_s23_ms_12,
0625_m20_ms_12, 0625_s20_ms_31 — the only parsed mark schemes that exist; the `mark_schemes`
table in the live stack holds **0 rows**):

| | leaf questions | with prompt text | with `topic_hint` | with `question_command` |
|---|---|---|---|---|
| all four papers | **122** | **0** | **0** | 1 |

Inferred difficulty bands would be foundation 70 / standard 45 / challenge 7, so
`infer_difficulty` works fine — there is simply nothing to attach it to.

**Why it can never improve by re-parsing.** `lemely.core.loose_schemas.Question` has no
question-stem field *at all* — not an unpopulated one, an absent one. That is correct
modelling: a CAIE mark scheme document contains marking points, not the question text; the
stem lives in the question paper (`qp_*.pdf`), which this codebase only ever consumes as a
student's scanned submission and never parses into structure. `lemely/io/integrity.py:113`
already records the same fact in a comment ("the mark-scheme model has no verbatim
question-stem") and works around it with a best-effort proxy. So no amount of re-ingesting,
re-parsing, or corpus growth changes this number: **mark schemes are not a question source.**

**Decision — do not persist prompt-less questions**, departing from §2's "create the row with
`is_active = false`". §2 prescribed that for a *sometimes*-missing stem, where a dormant row
becomes live once the text arrives. Here the row can never become live from this source, and
`question_bank.prompt` is `NOT NULL` — so persisting 122 rows would require inventing a
placeholder prompt, which is fabricating content into the exact column a teacher reads. That
violates "never invent precision" (UI-spec §1.4). The ingest is still built, is still
idempotent on `uq_question_bank_paper_question`, and still reports rows-produced /
rows-skipped; it simply reports 0/122 against today's corpus and skips rather than writes.

**Follows from that: the past-paper ingest is built as a *survey*, not a writer.** If every
question is skipped and the skip is structural, a persist branch behind
`if prompt is not None:` is unreachable code that can only be "tested" by stubbing a field
the schema does not have — dead code dressed as a feature, and a coverage hole either way.
So chunk B ships `survey_past_paper_questions()`, which walks the parsed payloads and
reports produced / skipped-for-no-prompt / topic coverage, with a docstring naming the
missing stem extractor as the blocker. The real writer lands with the extractor, not before.
`uq_question_bank_paper_question` stays in the schema — it is what will make that writer
idempotent, and dropping and re-adding it later is pure churn.

**Consequences that must be carried forward, not quietly forgotten:**
- The `past_paper` pool count is genuinely **0 for every subject**, and T-09 (chunk D) must
  say so in the §2 words — "no past-paper questions indexed for <subject> yet; use generated
  questions" — never a plausible-looking number.
- The on-disk `GeneratedQuiz` import is likewise **0 rows today**: `outputs/questions/` does
  not exist, so there are no files to import. The importer is still built, because chunk D
  moves `/quizzes/pools` off that directory and onto the bank.
- **Therefore the bank ships empty, and the only path that fills it is `/quizzes/generate`
  writing bank rows (chunk D).** T-09's live count is honest but will read 0 until a teacher
  generates questions. This is the §2 "honest degraded behaviour" outcome, reached in full,
  and it must appear in the Phase-3 report and DELIVERY.md rather than being presented as a
  populated question bank.
- Making past papers a real question source requires parsing question papers into structured
  stems — a new extractor, not a fix. That is out of Phase-3 scope; it is the natural home of
  P4's "questions from the ingested past-paper corpus" work, which now inherits it as a
  prerequisite rather than an assumption.

### D3.6 — Quiz model: a real question bank, a difficulty *mix* (not a band), and one marking road

Full design in **`docs/quiz-model.md`** (822 lines — schema table-by-table, the mapping
functions, the marking sequence, rejected alternatives). Recorded here is what a future
session must not re-litigate:

- **A queryable `question_bank` table is required, and is in scope.** T-09 step 4 promises
  a *live count* of matching questions; no arrangement of on-disk JSON answers a count
  query. Today's `_existing_questions()` disk scan is additionally a tenancy hole — a
  process-global path, so every teacher sees every other teacher's generated questions.
  Past-paper rows are ingested from `mark_schemes.parsed_payload`. **Honest degradation,
  chosen deliberately:** until ingest has run for a subject, that pool's count is genuinely
  0 and T-09 says so in words. We do not fake a pool.
- **Difficulty targeting is a *mix*, not a single band.** `lemely/core/difficulty.py`
  (pure): `DIFFICULTY_MIX` maps a target grade to proportions across
  foundation/standard/challenge, and `allocate_difficulty(grade, count)` does the
  largest-remainder rounding, so the count endpoint and the builder cannot disagree. A
  single-band quiz discriminates nothing *within* a grade. **The mix has no empirical
  backing — it is a product judgement, must say so in its docstring, and must never be
  called "calibrated" in the UI** (spec §1.4: never invent precision). Past-paper questions
  carry no difficulty label at all; they get `infer_difficulty(marks, question_type)`,
  recorded as `difficulty_source=inferred_from_marks` and surfaced to teachers as
  "estimated from mark allocation". Gemini labelling rejected on cost.
- **One marking road, not two.** Quiz questions are adapted into core `Question`s and run
  through the *existing* `correct_paper` (deterministic MCQ + `AICorrector`, with its
  existing confidence escalation and `REVIEW_CONFIDENCE_THRESHOLD`), and persist as
  ordinary `Attempt`/`QuestionResult`/`WeaknessRecord` rows tagged `origin='quiz'` via a
  shared `_persist` both writers call. So T-10 and the class weakness analytics read what
  they already read, low-confidence quiz answers land in the same P3.4 review queue, and
  T-11's custom mark scheme enters the same call with no adapter. A parallel quiz-results
  aggregation path is exactly the divergence D3.3/D3.4/D3.5 each had to fix once.
- **Four risks the architect flagged, each of which must be honoured by the build:**
  1. Chunk B (past-paper ingest) gates T-09's core promise and must *begin with a
     measurement* — rows produced, rows skipped for missing prompt text, topic coverage —
     before anything is persisted. A poor yield is an acceptable answer; discovering it in
     chunk D is not.
  2. `ReviewService._recompute_attempt_totals` (shipped in P3.4) assigns `grade` and
     `boundary_source` unconditionally. Left unguarded, **the first teacher override on a
     quiz invents a grade the marking path deliberately never wrote.** Needs an explicit
     guard and its own test.
  3. The `is_grade_bearing` split (chunk G) must land *before* quiz marking. It is a no-op
     today; after the first quiz attempt it becomes a data-corruption fix.
  4. `ExamMetadata` forces a synthetic paper_number/variant/session for the marking call.
     Those must never be persisted — an implementer copying `persist_correction` will get
     this wrong by default.
- **Sequence: C → A → G → B → D → E → F** (see `docs/quiz-model.md` §6 for the table).

### D3.5 — Acknowledging an at-risk flag: evidence-scoped, per-teacher, never suppressed from the API

- **What:** the UI spec's T-06 line "Dismiss/acknowledge a flag with a note" is the last
  piece of P3.4's scope, and STATE recorded it as "needs a backing table (none exists)".
  It does — but the shape is not obvious, because **at-risk flags are derived, not
  stored**: `assess_at_risk` recomputes them from history on every request, so there is
  no flag row to mark dismissed. Decided design:
  - New table `at_risk_acknowledgements` keyed `(teacher_id, student_id, reason)` unique,
    carrying `evidence_fingerprint`, an optional teacher-facing `note`, and who/when.
  - **Acknowledgement is scoped to the evidence it was made against.** A flag renders as
    acknowledged only when a stored ack exists *and* its fingerprint equals the current
    flag's fingerprint. New evidence re-raises the flag. `flag_fingerprint()` lives in
    `lemely.core.at_risk` (pure, single-sourced) and is deliberately built from the
    *stable* part of each evidence type: the percentage series for declining-trend, the
    target/predicted pair for below-target, and **`last_active_at` only** for inactivity —
    never `days_inactive`, which increments every day and would re-raise an acknowledged
    inactivity flag every 24 hours.
  - **Acknowledged flags are still returned by the API**, tagged with `acknowledged`
    (by/at/note); hiding them is a client-side filter (`?acknowledged=` on T-06).
  - **Per-teacher, not global**: teacher A acknowledging must not blind teacher B, who
    carries their own responsibility for that student. That is what the composite key
    encodes.
  - The ack note is **teacher-facing and never student-visible** — unlike the T-08
    override note, which is explicitly a note *to* the student.
- **Why:** spec §1.4 says flags are signals, not verdicts. A dismissal that deleted the
  signal from the API would convert the teacher's "I've seen this" into "this never
  happened", destroying the evidence the next teacher (or the same teacher next term)
  needs. Evidence-scoping is the difference between "acknowledged" and "permanently
  muted": a student who declines *further* after a teacher acknowledged the decline is a
  genuinely new signal and must surface again.
- **Alternatives rejected:** (a) permanent ack per (teacher, student, reason) — silently
  hides re-fires, the failure mode above; (b) time-boxed snooze — arbitrary duration with
  no relationship to whether anything actually changed; (c) materialising flags into rows
  so an ack can reference a flag id — a large write path and a cache-invalidation problem
  in exchange for nothing the fingerprint does not already give us.
- **How to apply:** anything added later that renders an at-risk flag for a teacher
  (T-01 overview, T-05 student detail, T-06 list) must populate `acknowledged` through
  the same shared helper. A flag that reads acknowledged on one screen and unacknowledged
  on another is the exact divergence D3.3 fixed for "at risk" itself and D3.4's
  weakness-record follow-up fixed for weaknesses.

### D3.4 — Teacher analytics: the last cross-tenant leak, and calling the 403/404 oracle what it is

- **What:** P3.3 built `lemely/core/class_analytics.py` (pure, injected-clock cohort
  analytics) plus three read-only routes — `GET /api/classes/{id}/analytics` (T-04),
  `GET /api/teacher/students/{id}` (T-05), `GET /api/teacher/at-risk` (T-06) — all
  scoped through a single `_visible_students()` helper (the union of every roster the
  caller may see, delegating entirely to `ClassService`).

- **The leak P3.1 missed.** `GET /api/teacher/overview` still called
  `history_store.list_students()` — *every student in the store, regardless of owner* —
  and labelled at-risk rows with the raw `history.student_id` uuid. P3.1 closed D1.6 on
  `/teacher/classes` and `/classes/{id}` and the phase was recorded as done, but this
  third route was never audited because it did not *look* class-shaped. **Lesson for
  future tenancy work: enumerate the routes that read student data and check each one,
  rather than checking the routes whose names contain the resource you just fixed.**
  Now scoped + named from `RosterEntry.display_name`, pinned by a two-teacher
  disjoint-class regression test.

- **The 403/404 existence oracle — decided, not overlooked.** Both P3.1 and P3.3 return
  403 for "exists but out of your scope" and 404 for "no such id anywhere". Four
  docstrings across `classes.py`, `teacher.py` and `class_repo.py` simultaneously
  described that split *and* claimed it was "never a 404-vs-403 existence oracle" —
  a security claim flatly contradicted by the code beneath it. The behaviour is
  correct and stays (it matches the brief and P3.1's precedent); the **claim** was
  wrong and is now replaced everywhere with an honest statement: this leaks exactly
  one bit (does this uuid belong to a real user/class?) to an already-authenticated
  staff caller, no data, and is accepted because ids are random 122-bit UUIDs.
  `ClassService.user_exists()` is the method that makes it possible and is documented
  as deliberately never returning anything *about* the user.
  **Alternative rejected:** collapsing both to 404 (textbook advice). It would make a
  genuine "you can't see this" indistinguishable from a typo'd id for a legitimate
  teacher, and buys nothing real against unguessable UUIDs.
  **How to apply:** never let a docstring assert a security property the function does
  not have — an inaccurate reassurance is worse than no comment, because it stops the
  next reviewer from looking.

- **Honest gaps, deliberately not papered over.** (a) Heatmap cells for a student with
  no data on a ranked topic are `None`, never 0% — persisted `weak_areas` drop
  zero-loss topics upstream, so a perfect scorer and a non-attempter are
  indistinguishable in the data; guessing either way would invent precision
  (UI-spec §1.4). (b) T-05 integrity signals are **omitted as a field**, not stubbed
  empty: persisted `PaperRecord`s carry no per-question answers for the
  plagiarism/AI checks to run on. (c) T-06's dismiss/acknowledge-a-flag action is a
  mutation with no backing table — deferred to P3.4.

- **Found and deferred, not fixed here:** `_count_review_papers()` (the "Need your eyes"
  stat on `/teacher/overview`) counts the *entire* in-process `papers_store` with no
  owner filter, so every teacher sees a global review count. The store is the P2-legacy
  teacher-upload store with no owner column at all, so scoping it is a store change,
  not a query change — it belongs to P3.4 (review queue), which owns that surface.

### D3.3 — At-risk flagging: the three MISSION rules, their open parameters resolved, and the one rule that cannot fire until Phase 4
- **What:** `lemely/core/at_risk.py` — a pure rules module (bottom layer, no I/O, no DB,
  no clock of its own) that takes a `StudentHistory` plus an injected `now` and an
  optional target grade, and returns every flag that fires, each carrying its **reason
  and its evidence**. MISSION §4 fixes the three rules and that they combine with OR;
  D2.10 recorded the trend-window and recalc-cadence detail as the open questions. They
  are resolved here.
- **Rule 1 — declining trend. Window N = 3, with a 5-percentage-point floor.** Two
  papers is a single delta, not a trend; three is the smallest window in which "declining"
  is a shape rather than one bad day. The rule fires when the last 3 papers are strictly
  decreasing **and** the total drop across the window is ≥ 5pp. The floor exists because
  strict monotonicity alone would flag 71.2% → 71.1% → 71.0% — technically declining,
  meaningless to a teacher, and exactly the kind of false alarm that trains people to
  ignore the flag. Evidence carried: the three percentages, so the UI can show
  "72% → 65% → 58%" rather than an unexplained badge (spec §1.4: flags are signals, not
  verdicts — a teacher must be able to judge the signal themselves).
- **Rule 2 — predicted ≥2 grades below target. Implemented and fully tested, but it
  cannot fire in Phase 3, and that is recorded as an honest limitation rather than
  hidden.** There is no target grade anywhere in the schema: MISSION §4 puts target
  grades in the Phase-4 onboarding questionnaire. So the rule takes the target as a
  **parameter**, which the unit tests supply directly (the logic is therefore genuinely
  proven), while production has nothing to pass yet. Deliberately **not** adding a
  `users.target_grade` column now — that is P4's data-collection scope and MISSION §8b
  forbids speculative work outside the current phase. The assessment distinguishes
  "rule evaluated and did not fire" from "rule not evaluable (no target recorded)" so a
  missing target never masquerades as a passing check. Distance is measured on the
  ladder `A* A B C D E U`, so "2 boundaries below" is 2 positions, e.g. target A → C.
- **Rule 3 — inactivity.** ≥ 14 days since the most recent `recorded_at`, per MISSION.
  A student with no papers at all is **not** flagged inactive — that is a student who has
  not started, not one who has stopped, and conflating them would flag every new
  enrolment on day 15. Evidence carried: the day count and the last-active date.
- **Recalc cadence: computed on read, no background job.** There is no scheduler in the
  stack and adding one for this is disproportionate; the inputs are a short history list
  and a clock, so the computation is cheap and always current by construction (a nightly
  job would instead serve stale flags all day). Reversible: if the teacher dashboard ever
  needs to rank thousands of students at once, this becomes a cached column fed by the
  same pure function. Cheapest and most reversible per MISSION §1.
- **`GRADE_ORDER` moves into `lemely/core/`** and the web layer aliases it, rather than
  keeping the existing private copy in `lemely/web/routers/teacher.py:119`. Same
  anti-drift discipline D2.2 applied to `REVIEW_CONFIDENCE_THRESHOLD`: a grade ladder
  duplicated across layers is a silent-divergence bug waiting to happen.
- **Supersedes** the crude heuristic in `teacher.py::_at_risk` (latest grade in
  {D,E,U} OR any negative delta), which matched none of the three specified rules,
  carried no reason label, and would flag a straight-A student after one 1pp dip.
- **Two things were both called "At risk"; they now mean one thing.** Rewiring the
  overview onto the engine left `/api/classes/{id}`'s "At risk" stat card still counting
  `grade in {D,E,U}` — so the same label showed a different number on two screens, with
  no way for a teacher to reconcile them. The class-detail card now runs the same engine.
  The per-row `gradeAtRisk` **badge** deliberately stays the grade test: "this grade is
  low right now" is a genuinely different signal from "this student is on a declining
  trajectory", it is differently named on the wire, and collapsing the two would lose
  information. Pinned by two tests (a steady, active D is *not* at risk but *does* carry
  the badge; an inactive A-grade student *is* at risk and does *not*).
- **Honest consequence of the narrowing:** a consistently-failing but active and stable
  student no longer appears in the at-risk list. That is what MISSION §4's three rules
  say, and their low grade is still visible via the badge, the grade distribution, and
  the class average — but it is a real behavioural change from Phase 2, not a silent
  equivalence, so it belongs in the phase report.

### D3.2 — The visual-baseline gate was self-defeating: routine gate runs overwrote the baselines they compare against
- **What:** `web/scripts/audit.mjs` (`REPORTS_DIR`), `web/e2e/screenshots.spec.ts` and
  `web/e2e/correct-paper.spec.ts` (`SCREENS_DIR`) all hardcoded a committed phase
  report directory (`reports/phase-2.5/`, and `reports/phase-2/` for the last),
  and `scripts/check_ui_gates.py` read its thresholds from the same place. So every
  `./scripts/check.sh` invocation **rewrote the Phase-2/2.5 baselines in place**.
- **Why that is a real defect, not cosmetics:** MISSION §11 says "Commit baselines.
  Compare against them each phase; an unintended diff is a blocker." A gate that
  destroys its own reference can never report a regression — after any run, the
  baseline *is* the current render by construction, so the comparison is vacuous.
  It also poisons every diff: P3.1 is a backend-only change (zero files under
  `web/src/`) and still produced a 53-file dirty tree of re-rendered PNGs, ±1
  Lighthouse performance jitter, and a fresh random paper-UUID in the axe summary.
  Committing that would have buried any genuine future visual change in noise and
  made "no visual regression" unfalsifiable for the rest of the build.
- **Fix:** one env seam, `LEMELY_REPORT_DIR` (repo-relative or absolute), defaulting
  to the gitignored `reports/.scratch`. Routine gate runs write there; the committed
  baselines are never touched. Re-baselining becomes an explicit, reviewable act that
  names its phase — `LEMELY_REPORT_DIR=reports/phase-3 npm run audit`. The two
  Playwright specs share `web/e2e/report-dir.ts`; `audit.mjs` and `check_ui_gates.py`
  each carry the same default with a comment pointing at the others, because if the
  three ever disagree the threshold gate silently reads output the audit runner never
  wrote (a false PASS — the failure mode worth guarding hardest).
- **Verified:** full `./scripts/check.sh` green on all 12 gates with the working tree
  showing only the intended source edits afterwards; `reports/.scratch/` populated by
  both runners (screens from Playwright *and* the audit runner's G-04, axe summary
  zero violations) and confirmed ignored by git.
- **Alternatives rejected:** `git checkout -- reports/` after each run (rejected — hides
  the problem behind a ritual every future session must remember, and one forgotten
  revert silently re-baselines); committing the regenerated artifacts each time
  (rejected — that *is* the vacuous-comparison bug, just accepted); dropping the
  screenshot corpus from `check.sh` (rejected — MISSION §11 wants it run often, and
  it caught two real regressions in Phase 2.5 per D2.12).
- **Applies to:** every later phase's UI gate (P3.10, P4, P5, P6's full sweep). When a
  phase legitimately changes a screen, re-baseline explicitly and note it in that
  phase's report, exactly as MISSION §11 prescribes.

### D3.1 — Real class model: nullable `school_id` for independent teachers, join codes, and the ownership rule that lands D1.6
- **What:** P3.1 replaces the two implicit-class endpoints
  (`lemely/web/routers/teacher.py::list_classes` / `get_class`, which treated *every*
  student with history as one cohort keyed `"all"`) with the DB-backed `classes` /
  `class_enrollments` tables from P1.3, behind a new `lemely/db/class_repo.py`
  (`ClassService`) modelled directly on `SeatService` (D1.10): pure ownership/CRUD
  logic over a `sessionmaker`, domain errors mapped to status codes by a thin HTTP
  layer, testable against Postgres with no GoTrue dependency.
- **`classes.school_id` becomes NULLABLE — the one schema relaxation, and it is
  required by the product model, not convenience.** MISSION §1 states "a teacher can
  be independent, belong to a school, or both." P1.3 shipped `classes.school_id` as
  `NOT NULL`, which makes an independent teacher's class unrepresentable. The
  alternatives were worse: minting a synthetic one-teacher `School` row per
  independent teacher (pollutes the seat/quota/membership model with rows that are
  not schools, and `SeatService.list_admin_schools` would start returning them), or
  blocking independent teachers entirely (contradicts the MISSION). Dropping a
  `NOT NULL` is a *relaxation*: it invalidates no existing row, needs no data
  backfill, and is reversible by re-adding the constraint once every row has a
  school. It is not literally additive, so it is recorded here as a deliberate,
  scoped exception to D1.2's additive-only guarantee rather than slipped in silently.
- **Ownership rule (this is D1.6's deferred row-level tenancy, now landed):**
  - `teacher` → sees and mutates **only** classes where `classes.teacher_id ==
    auth.user_id`. Any other class id is a **403, never a 404-vs-403 oracle and
    never data**.
  - `school_admin` → sees classes whose `school_id` is a school they hold a
    `school_admin` `SchoolMembership` for (read + roster management), mirroring how
    `SeatService` scopes every mutation to an admin's own schools.
  - `platform_admin` → **no classes**. Consistent with D1.6/D1.10's no-super-role
    rule; a platform admin reaching class data comes via a dedicated admin surface
    (X-01..X-03, unbuilt), not by inheriting the teacher router's role gate.
  The router-level `require_role(teacher, school_admin, platform_admin)` guard stays
  as the 401-then-403 outer boundary; the ownership check is the inner one.
- **Two enrolment paths, matching MISSION §4 P3.1 ("invite code / school seat"):**
  1. **Join code** — additive `classes.join_code` column (unique, indexed,
     server-generated at create). A student self-enrols by posting the code. This is
     the path an independent teacher (no school, no seats) must have.
  2. **Direct add** — a teacher/school_admin enrols an existing student who holds a
     non-revoked `Seat` in the same school as the class. Gated on the class having a
     `school_id`; an independent teacher's class has no seat pool, so this path 403s
     for them by construction rather than by a special case.
  A student may be in many classes; `uq_class_enrollments_class_id_student_id`
  already makes re-enrolment idempotent rather than duplicated.
- **Roster identity comes from `users.display_name`, falling back to `email`.** The
  old `StudentRowDTO.name` carried the raw history key (a UUID string) because there
  was no user join. With a real roster there is one, so the DTO now carries a real
  name plus the student id as a separate field — the frontend (P3.7) needs the id to
  link through to the student detail screen and must not parse it out of a label.
- **DTO shapes extend, never break.** `ClassSummaryDTO`/`ClassDetailDTO` keep every
  existing field so `web/` keeps building through P3.1–P3.6 (the teacher frontend is
  P3.7/P3.8); new fields are added optional-with-default.
- **Alternatives rejected:** keeping the implicit `"all"` cohort alongside the real
  model (rejected — two sources of truth for "who is in this class", and the implicit
  one is exactly the cross-tenant leak D1.6 recorded as outstanding); enforcing
  ownership in the router instead of the service (rejected — D1.10 already proved the
  service-layer placement is the testable one, and it keeps the guarantee in one
  place for the P3.3/P3.4/P3.5 surfaces that will reuse it).

## Phase 2.5

### D2.12 — P2.5.5 kickoff: E2E harness had a silent PATH blocker; fixed in-repo, and its first real run caught two P2.5.3/4 regressions
- **What:** `web/playwright.config.ts` resolves local-stack keys via
  `execSync("supabase status -o json")`, which depends on the invoking shell's PATH
  containing the Supabase CLI. In this sandbox the CLI lives at `~/.local/bin/supabase`,
  but neither non-interactive nor login `bash` invocations put it on PATH — `~/.bashrc`
  never adds it, and `~/.bash_profile` (which takes precedence over `~/.profile` for
  login shells, and only sources `~/.bashrc`) means `~/.profile`'s `~/.local/bin` PATH
  line is dead code for this account. This is a host/account quirk, not a repo bug, so
  fixed it inside `playwright.config.ts` (`env: { PATH: "$HOME/.local/bin:$PATH" }` on
  that one `execSync` call) rather than editing dotfiles outside the repo (MISSION §5:
  never touch anything outside the project directory).
- **Consequence:** the P2.10 E2E suite had therefore not actually executed at any point
  since Phase 2.5 began — P2.5.1-4 all verified via tsc/build/oxlint only, never
  Playwright. Once unblocked, `correct-paper.spec.ts` immediately failed and a browser
  console error surfaced on every question row:
  1. The spec's marks/grade/question-id assertions depended on Phase-2-era DOM structure
     (a "Marks" label div + sibling value div; bare `div.font-mono.font-medium` question
     cells) that P2.5.3/4's retrofit onto `MarkDisplay`/`GradeBadge`/`QuestionRow`
     replaced. Not a product bug — rewrote the assertions against the new components'
     `aria-label`s/accessible names, which is also more robust going forward.
  2. `QuestionRow` (C-6) nested the `ConfidenceIndicator` (C-4) chip's own tap-to-expand
     `<button>` inside the row's own toggle `<button>` — invalid HTML, logged as a React
     console error on every row. This is a real defect in the component library shipped
     by P2.5.2/retrofitted-onto by P2.5.3, exactly the class of thing QUALITY-BAR.md's
     "zero console errors" gate and the P2.5.6 axe pass exist to catch, and neither the
     Impeccable audit (static, no runtime rendering) nor tsc/oxlint (not an HTML-validity
     checker) could have caught it. Fixed by splitting the row into two sibling
     interactive regions instead of nesting them (`web/src/components/ui/question-row.tsx`).
- **Why fixed now, not deferred:** MISSION §5: "If you find a defect in [prior, completed]
  work, fix it as a scoped task inside the current phase — do not reopen a completed
  phase." P2.5.3/4 aren't a completed *phase* (still Phase 2.5, still open), and this is
  squarely a P2.5.5 blocker — the screenshot harness can't produce clean, warning-free
  captures of a screen that logs a console error on render. Fixed, not just documented.
- **Verified:** tsc/build/oxlint clean; `pre-commit run --files <the 3 changed files>`
  clean; full existing suite (`_smoke` + `correct-paper`) green, zero console errors.
  Committed (2148e41) ahead of the P2.5.5 screenshot-harness work proper.

### D2.11 — Installed Impeccable v4.0.4 has no `normalize` command; P2.5.4 runs audit → polish instead
- **What:** MISSION §10 and STATE.md's P2.5.4 line specify `/impeccable audit` →
  `/impeccable normalize` → `/impeccable polish` for the retrofit pass. The installed
  skill (`.claude/skills/impeccable/SKILL.md`, v4.0.4) has no `normalize` command in its
  command table — only `audit`, `critique`, `polish`, and other named commands exist.
- **Why:** genuinely undecidable fork per MISSION §1 (skill version drift, not a design
  choice) — proceeding without stalling per protocol. `audit`'s dimension 3 (Theming)
  explicitly checks token conformance/hard-coded colors/dark-mode drift, and `polish`'s
  step-1 triage explicitly classifies and fixes "missing token" and "one-off
  implementation" drift against DESIGN.md and shared components. Together they cover
  everything `normalize` (align with our tokens) would have done; `critique` (UX
  heuristic scoring against intent) is skipped because it targets new-work concept
  evaluation, not a retrofit of already-shipped, already-speced screens, and the
  original P2.5.3/STATE.md line for this task only ever named audit→normalize→polish,
  never critique.
- **Alternatives rejected:** stall and wait for human (violates "never stop" rule);
  hand-roll a bespoke "normalize" pass duplicating what audit/polish already cover
  (wasteful, diverges from the maintained skill).
- **Applies to:** P2.5.4 only, and any later phase's UI retrofit/build pass that cites
  the same three-command sequence — use audit → polish (+ critique only for genuinely
  new surfaces per the skill's own routing.md) until/unless a skill update reintroduces
  `normalize`.

### D2.10 — UI spec read in full; Phase 2.5 scope fixed to tokens + C-1..C-13 + retrofit of the 6 shipped Phase-2 screens only
- **What:** `docs/LEMELY_UI_SPEC.md` defines **71 screens** across 6 portals (Global,
  Student S-01..S-31, Teacher T-01..T-12, Parent P-01..P-04, School Admin K-01..K-04,
  Platform Admin X-01..X-03) and **13 cross-cutting components** (C-1 grade badge, C-2
  mark display, C-3 boundary bar, C-4 confidence indicator, C-5 weakness chip, C-6
  question row, C-7 paper identity line, C-8 trend sparkline, C-9 XP/streak, C-10
  processing state, C-11 empty/error/offline family, C-12 role switcher, C-13 navigation
  shells). Phase 2.5 per MISSION §4 builds the token system and all 13 components with
  every state, then retrofits only the screens Phase 2 already shipped (student home,
  upload flow, scanner, marking progress, results, question detail — S-06/S-10..S-17
  roughly). Building or wiring the remaining ~60 screens (teacher, parent, admin, quiz,
  flashcards, study plan, leaderboards, etc.) is explicitly Phase 3/4/5 scope per the
  roadmap, not Phase 2.5, even though the component library and tokens they need are
  being built now.
- **Why:** the spec is a product/UI spec, not a build-order spec — reading it in full
  (per §4 Phase 2.5's "read docs/LEMELY_UI_SPEC.md first" instruction) surfaced its full
  71-screen scope, which if taken as this phase's literal to-do list would blow the phase
  wide open. MISSION §4 is explicit that Phase 2.5 is tokens+components+retrofit only;
  the other screens are sequenced into Phases 3-5 where their own acceptance criteria
  (at-risk flags, XP economics, study plan generation, etc.) already live. Confirmed by
  MISSION.md §4 phase roadmap, not overridden by anything in the spec.
- **Five non-negotiable product principles reconfirmed** (spec §1.4, verbatim-near):
  (1) the system says when it isn't sure — every mark carries confidence, low-confidence
  flagged to student + routed to teacher review, never shown confidently when it isn't;
  (2) flags are signals not verdicts — plagiarism/AI-detection are teacher-only advisory,
  students never see them, never auto-penalized; (3) grades private, effort public —
  leaderboards are XP-only, marks visible only to the student + their parents + their
  teachers; (4) teacher has final authority — any mark is overridable with a note, shown
  to the student as an attributed correction; (5) never invent precision — predicted
  boundaries from real data are plain, boundaries from insufficient data are visibly
  labelled "estimated" every time. These gate every component this phase builds,
  especially C-3 (boundary bar) and C-4 (confidence indicator).
- **Deferred spec ambiguities, not blocking this phase, to be resolved when their owning
  phase starts** (do not re-derive — reference this entry): study-plan session-selection
  algorithm (S-24, Phase 4), placement-test question-selection/weighting (S-04, Phase 4),
  XP earning rules + level curve + streak-freeze economics (C-9/S-31, Phase 5), at-risk
  flag AND/OR combination + trend window + recalc cadence (T-01/T-06, Phase 3 — note
  MISSION §4 already specifies OR across the three conditions, so the open question is
  only the trend-window and recalc-cadence detail), confidence-threshold-to-tier mapping
  and mark-scheme-copying detection method (C-4/T-07/T-08, Phase 3), role-switcher (C-12)
  placement/trigger UI, teacher-override visual encoding on S-17 (Phase 3), offline
  cache-invalidation policy for G-15 (Phase 2.5/3 boundary — build C-11's offline state
  visually now, defer the caching policy itself).
- **No conflict found** between the spec and what Phase 2 already shipped structurally
  (screen purposes match the shipped files' evident intent by name); the gap is entirely
  "spec asks for more states/fidelity than a Phase-2-speed build would have had time for"
  (e.g. S-14 marking-progress wants honest per-stage/per-question detail, not a spinner;
  S-11 scanner wants edge-detection + real-time guidance copy) — these become the audit
  findings the retrofit step (Impeccable audit → normalize → polish) is expected to
  surface and fix, not a pre-emptive rewrite here.
- **Alternatives considered:** treat the full 71-screen inventory as this phase's target
  (rejected — directly contradicts MISSION §4's explicit phase boundaries and would
  multiply this phase's size ~10x); skip reading the full spec and work from the MISSION
  §4 paragraph alone (rejected — MISSION §4 itself mandates reading the spec first, and
  the components list here is more complete/precise than the paragraph summary).

## Phase 1

### D1.12 — Teacher paper upload drops the caller-supplied `student_id` (cross-tenant write kill)
- **What:** `POST /api/papers/upload` (`lemely/web/routers/teacher.py::upload_paper`) no longer
  accepts a `student_id` form field. The interim paper bucket is keyed solely on the
  server-generated `paper_id` (`resolved_student = paper_id`). Found by the Phase-1 acceptance
  adversarial review as finding **H2**.
- **Why:** The old code did `resolved_student = student_id.strip() or paper_id`, trusting a
  caller-supplied identity to decide whose history a graded paper is written into. With the
  teacher→class↔student ownership model still deferred (D1.6), no teacher can be *authorized* to
  write into a specific student's bucket, so honoring a supplied id is an unauthenticated
  cross-tenant write vector (a teacher — or a smuggled value — could target any student key).
  Removing the field makes the contract honest: the upload lands in its own paper-keyed bucket
  and nothing is attributed to a real student account until verified ownership exists.
- **Association deferred, not lost:** binding a graded paper to a real student account lands with
  the DB-backed class model (Phase 2/3), gated on a verified teacher→student ownership check —
  the same boundary D1.6 records as deferred. This is the correct place for it; faking it now
  would re-introduce the IDOR D1.6 closed on the student routes.
- **Blast radius:** existing `test_web_teacher.py` uploads still send `student_id` in the form
  body; FastAPI ignores undeclared form fields (no 422) and those tests only assert on
  `paper_id`/job status/sandbox containment, so they stay green. No DTO/JSON contract changed.
- **Alternatives:** keep the field but ignore it server-side (rejected: a trusted-looking field
  silently dropped is a footgun — the same reasoning that removed `studentId` from the student
  DTOs in D1.6); gate it behind a teacher→student ownership check now (rejected: the class model
  it needs does not exist until Phase 2/3 — this is deferral, not a shortcut).

### D1.11 — Device/session registry: sid-claim + sid-gated DB liveness check (immediate eviction)
- **What:** Max **3** concurrent devices per account. Each real login (email/password,
  parent OTP, and self-service signup) registers a `Device` row and embeds its id in the
  minted access token as a top-level `session_id` claim. `get_auth_context` decodes the
  token offline as before, then — **only when a `session_id` claim is present** — performs a
  single indexed DB read to confirm that device row is not revoked; an evicted/unknown
  session → **401**. Tokens without a `session_id` (hermetic tests, seat-invite signup with
  no device context) skip the check entirely, preserving the offline path.
- **Device identity (the client-vs-server fork):** the client sends an optional stable opaque
  `deviceId` (the SPA mints one once and keeps it in localStorage) plus its `User-Agent`. If a
  non-revoked device row matches `(user_id, client_device_id)`, that row is **reused** — a
  re-login on the same device is NOT a new slot; its `last_seen_at` is refreshed. If no
  `deviceId` is supplied, every login mints a fresh device (a distinct session).
- **Eviction:** after registering, if the user holds > 3 non-revoked devices, the **oldest by
  `last_seen_at`** (tie-break `created_at`) is revoked (`revoked_at = now()`) until 3 remain.
  Because eviction sets `revoked_at`, the evicted session's next request fails the liveness
  check → immediate, real invalidation (faithful to "silently invalidates the oldest session").
- **Enforcement fork resolution — chose (a) request-time DB check, scoped:** the STATE fork
  weighed (a) a per-request DB lookup vs (b) refresh-boundary-only revocation with a short TTL.
  Chose (a). D1.5's rejected cost was an **external** JWKS network hop + kid-rotation dependency
  in the token hot path; a `session_id` liveness lookup is one indexed read against Postgres,
  already a hard runtime dependency of every data-serving route — so it does NOT reintroduce the
  dependency class D1.5 avoided, and it delivers immediate invalidation that (b) cannot (no
  refresh flow exists yet, so under (b) an evicted token would stay valid up to its 3600s TTL).
  Scoping the check to sid-bearing tokens keeps the hermetic auth-dependency suite offline.
- **Schema:** additive migration `0003_device_client_id` adds `devices.client_device_id`
  (nullable String) + index `ix_devices_user_id_client_device_id`. Additive-only per D1.2; the
  STATE note "no migration needed" assumed the friendly `device_label`/`user_agent` columns
  sufficed, but a stable client fingerprint needs its own column so "same device" dedupe does
  not collide with the human label. `refresh_token_id` stays reserved for the future refresh flow.
- **last_seen_at semantics:** refreshed only at login (register), not on every request — keeping
  the per-request path a single read, no write. Eviction by login-recency is the correct
  "concurrent devices" notion; a Phase-5 device-management UI can later add explicit sign-out.
- **Alternatives:** (b) refresh-boundary revocation (rejected: weak/eventual invalidation, and
  no refresh flow exists to trigger it); reuse `refresh_token_id`/`device_label` for the client
  id (rejected: conflates distinct concerns, blocks the future refresh flow / friendly label).

### D1.6 — RBAC model: least-privilege role gating + token-derived ownership; teacher tenancy deferred
- **What:** Authorization is enforced by a `require_role(*roles)` dependency factory
  (`lemely/web/deps.py`) layered on `get_auth_context`. It authenticates first (401 on
  missing/invalid token) then 403s any caller whose `AuthContext.role` is not in the allowed
  set. Application: (a) every **student** route depends on `require_role(Role.student)` and
  keys all data off `auth.user_id` (a student can only ever read/write their own history
  bucket); (b) the **teacher** router is gated at the router level with
  `require_role(Role.teacher, Role.school_admin, Role.platform_admin)` so every current and
  future teacher route inherits the staff guard; (c) `/api/health` and the `/api/auth/*`
  routes stay public by design.
- **IDOR kill:** POST /student/plan and POST /student/onboarding previously trusted a
  caller-supplied `studentId` (any caller could act as any student). Both now require a
  student token and derive identity from `auth.user_id`; `studentId` was **removed** from
  `StudyPlanRequest`/`OnboardingRequest`, so under `extra="forbid"` a smuggled id is a 422,
  not an impersonation. Covered by tests/test_authz_matrix.py.
- **Least privilege, no super-role:** each portal names exactly the roles allowed; there is
  no implicit "admin sees all" bypass at the route layer (a platform_admin reaching student
  data will come via dedicated admin surfaces later, not by hitting /student/*). This keeps
  the authz matrix explicit and testable.
- **Teacher per-tenant ownership DEFERRED (honest limitation):** "a teacher sees only their
  own classes/students" cannot be enforced yet because the teacher routes still read the
  shared single-bucket interim `HistoryStore` (no class↔teacher / student↔teacher mapping is
  wired to routes). P1.6 enforces the *role* boundary (students/parents are fully locked out
  of teacher routes); row-level teacher→class ownership lands when these routes move onto the
  DB-backed class model (Phase 2/3). Recorded so this is not mistaken for complete tenancy.
- **Alternatives:** per-route `Depends` on every teacher handler (rejected: 15 signatures to
  touch, easy to forget one; router-level guard is defense-in-depth and future-proof);
  keeping `studentId` in the body but ignoring it (rejected: a trusted-looking field that is
  silently dropped is a footgun — removing it makes the contract honest).

### D1.5 — Backend is the sole token issuer to clients (HS256 self-signed), revising D1.4
- **What:** The FastAPI backend mints **every** access token it hands to a client, self-signed
  HS256 with the shared `SupabaseSettings.jwt_secret`, in the GoTrue claim shape (`sub`,
  `aud="authenticated"`, `role="authenticated"`, `exp`, `app_metadata.role`, `phone`/`email`).
  This applies to BOTH email/password login and parent phone-OTP. GoTrue is still the identity +
  password-hashing + account-lifecycle authority: `AuthService.signup` admin-creates the user in
  GoTrue and `login` calls the GoTrue password grant to **verify the password** — but GoTrue's own
  access token is discarded, not forwarded. `decode_token` stays HS256-only (one validation path).
- **Why (evidence, not assumption):** The live integration test (`test_auth_live.py`) caught that
  the local Supabase stack's GoTrue signs access tokens with **ES256** (asymmetric, JWKS + `kid`
  header: `{'alg':'ES256','kid':'b812…','typ':'JWT'}`), NOT the shared HS256 secret that D1.4
  assumed. This is the current Supabase CLI default (asymmetric JWT signing keys). D1.4's premise
  — "both token kinds validate identically under the shared HS256 secret" — was therefore false in
  reality; the hermetic `FakeGoTrueBackend` had signed HS256 and masked the gap.
- **Fork + tiebreaker:** Two viable fixes: (A) validate real ES256 GoTrue tokens via the JWKS
  endpoint (canonical, but adds a networked fetch+cache+kid-rotation path to token validation AND
  still needs HS256 for the self-signed OTP tokens → two validation paths); (B) have the backend
  re-mint all client tokens as HS256. Because our SPA only ever talks to FastAPI (never GoTrue
  directly), FastAPI is already both issuer-proxy and validator, so re-minting is transparent.
  MISSION's undecidable-fork rule (simplest, cheapest, most reversible) selects **B**: one uniform,
  fully-offline-verifiable token path; no JWKS network dependency in the hot path; version-
  independent of the Supabase CLI's key management (survives `supabase db reset`).
- **Phase-2 compatibility:** Supabase Storage/PostgREST still accept HS256 tokens signed with the
  shared `jwt_secret` (the anon/service keys are themselves such tokens), so direct SPA→Storage
  uploads in Phase 2 keep working with our minted token (`aud=authenticated`, `role=authenticated`).
- **Reversible:** to adopt GoTrue's ES256 tokens later, add JWKS/ES256 validation to `decode_token`
  and stop re-minting in `AuthService`; nothing else changes because the claim shape is identical.
- **Supersedes:** D1.4's statement that email/password uses GoTrue's token and only OTP is
  self-signed. Everything else in D1.4 (GoTrue for password/identity, `SmsProvider` seam, in-memory
  OTP store, mirroring to `public.users`, deps) stands.

### D1.4 — Auth backend split: GoTrue for email/password, self-signed HS256 for mock parent OTP
- **What:** A new `lemely/auth/` package owns identity. Email/password signup+login go
  through Supabase **GoTrue** (local stack): admin-create the user (service-role key,
  email pre-confirmed for dev, `role` in `user_metadata`) and password grant for login;
  every GoTrue user is mirrored 1:1 into `public.users` (id = `auth.users.id`, per D1.1)
  with role/email/phone. Parent **phone-OTP** runs behind an `SmsProvider` protocol whose
  `MockSmsProvider` logs the code; `AuthService` owns the OTP challenge lifecycle (generate
  → store → deliver → verify) and, on successful verify, **mints a Supabase-compatible
  access token self-signed with the shared HS256 `jwt_secret`** carrying the same claims
  GoTrue issues (`sub`, `aud="authenticated"`, `role="authenticated"`, `exp`,
  `app_metadata.role`, `phone`). Both token kinds therefore validate identically under the
  (next task) JWT middleware.
- **Why:** GoTrue's native phone OTP requires a real SMS provider (Twilio/etc.); the MISSION
  mandates a MOCK provider now with "one config switch to a real provider later." Owning the
  OTP challenge ourselves keeps the mock fully functional and testable offline, while the
  `SmsProvider` seam is the exact switch point. Self-signing the OTP session token with the
  same secret + claim shape GoTrue uses means the downstream validator needs no special case
  — email/password and OTP tokens are indistinguishable to RBAC. We already hold the local
  secret in `SupabaseSettings.jwt_secret`; this is a local-dev convenience, not a production
  key-management pattern (a real deploy switches parent OTP to GoTrue+real SMS and drops the
  self-signer).
- **OTP challenge store is in-memory (TTL, default 300s, max 5 attempts), NOT a DB table:**
  OTP challenges are ephemeral; adding a table would be a non-additive schema change outside
  the P1.3 schema and buys nothing (a single-process dev/test server). Recorded so a later
  multi-worker deploy knows to move it to Redis/DB. Deterministic in tests via injected
  clock + RNG.
- **Deps:** `httpx` added to the `web` extra (GoTrue REST client; already installed,
  matches the async-free sync-httpx call style); `pyjwt[crypto]` stays in the `db` extra and
  CI's test job now installs `db` too (needed to import `lemely.db`/`lemely.auth` at all).
- **Testing:** hermetic unit tests use a `FakeAuthBackend` + `MockSmsProvider` + injected
  clock/RNG and never touch the network; a live integration test hits the real local GoTrue
  + Postgres and **skips cleanly when either is unreachable** (mirrors `test_db_schema.py`),
  so CI stays green until a Supabase service block is added before the E2E acceptance task.
- **Alternatives:** GoTrue admin `generate_link` magic-link exchange for the OTP session
  (rejected: convoluted for phone, still needs an SMS-less verify hack, more moving parts);
  a real DB OTP table (rejected: non-additive, unnecessary for single-process dev);
  self-signing ALL tokens incl. email/password (rejected: throws away GoTrue's real
  password hashing, refresh-token rotation, and account lifecycle we get for free).

### D1.1 — Auth identity mapping: `public.users.id` == Supabase `auth.users.id`, no cross-schema FK
- **What:** Our application-owned `public.users` table uses a `UUID` primary key
  that is set to the Supabase GoTrue user id (`auth.users.id`) at signup time.
  We do NOT declare a SQL foreign key from `public.users.id` to `auth.users.id`.
  GoTrue owns the `auth` schema; our Alembic migrations own `public`. Role, active
  flag, and profile fields live on `public.users`.
- **Why:** Supabase manages the `auth` schema out-of-band (its own migrations); a
  cross-schema FK into a table Alembic doesn't control is fragile (reset/upgrade
  ordering, `supabase db reset` wipes auth) and is the officially discouraged
  pattern. Mirroring the id gives a stable 1:1 join without coupling migration
  ownership. Every other table FKs to `public.users.id` (which we own), so
  referential integrity across the app schema is fully enforced.
- **Alternatives:** Real FK to `auth.users` (rejected: brittle across resets, and
  Alembic autogenerate would try to manage a table it must not touch); a separate
  `profiles` table keyed by auth id (deferred — Phase-4 onboarding fields are
  additive columns; one `users` table is simpler now).

### D1.2 — Schema conventions (additive-only guarantee for Phases 2-5)
- **What:** (a) UUID primary keys everywhere via server default `gen_random_uuid()`;
  (b) all timestamps `TIMESTAMP(timezone=True)` with `created_at`/`updated_at`
  server-defaulted to `now()`; (c) role/enumerations as Postgres `ENUM` types
  (extended later with `ALTER TYPE ... ADD VALUE`, which is additive); (d) money as
  integer minor units + ISO currency code (never float); (e) confidence persisted
  as BOTH a band enum and a float score, mirroring `core.schemas`; method-mark
  breakdown persisted as JSONB; (f) sync SQLAlchemy 2.0 `Mapped`/`mapped_column`
  matching the sync engine in `lemely/db/session.py`.
- **Why:** Phases 2-5 must need only additive migrations (MISSION §4). UUIDs are
  merge/import-safe and let us mirror auth ids; timezone-aware timestamps avoid the
  classic naive-datetime trap; ENUM-add and column-add are additive whereas type
  changes are not; integer money avoids rounding drift in billing.

### D1.3 — Enum `server_default`s rendered with an explicit `::type` cast
- **What:** ENUM-typed columns that carry a server default (e.g. `subjects.board`,
  `seats.status`, `subscriptions.status`, `uploads.status`, `review_queue.status`)
  set it as `sa.text("'value'::enumname")` in BOTH the ORM model and the migration,
  rather than a bare `sa.literal("value")`.
- **Why:** With a bare string literal the model renders the default as `'value'`
  while Postgres stores it as `'value'::enumname`. `alembic check`/autogenerate then
  compares them by running `SELECT 'value'::enumname = 'value'::VARCHAR`, which errors
  (`no operator matches ... enum = varchar`) and, worse, produces a spurious drift
  diff on every future autogenerate — directly threatening the additive-only guarantee
  (D1.2). The explicit cast makes model and DB defaults render identically, so
  `alembic check` reports "No new upgrade operations detected". Verified live against
  the local Supabase Postgres.
- **Also fixed here:** the model modules imported `uuid`/`datetime`/`date` only under
  `TYPE_CHECKING`, but SQLAlchemy 2.0 resolves `Mapped[...]` annotations at runtime, so
  every model failed to configure (`MappedAnnotationError: Could not resolve ...
  Mapped[uuid.UUID]`). Those types are now imported at runtime; a scoped
  `per-file-ignores` entry (`lemely/db/models/** = TC001/TC002/TC003`) stops ruff from
  moving them back — mirroring the existing exemption for the pydantic web DTOs.

## Phase 0

### D0.1 — Single lockfile: keep `uv.lock`, delete `requirements.lock`
- **What:** Standardise on `uv.lock` (uv's native universal lockfile) as the one
  dependency lock. Deleted `requirements.lock`. `Makefile` `lock` target changed
  from `pip freeze --exclude-editable > requirements.lock` to `uv lock`.
- **Why:** The two lockfiles drifted (audit §1): `requirements.lock` was compiled
  via `uv pip compile ... --extra ui --extra dev` (missing the `web` extra) while
  the Makefile regenerated it via `pip freeze` — a different mechanism. `uv` is
  installed (0.11.29) and `uv.lock` already resolves all extras (ui+web+dev).
  CI installs from `pyproject.toml` (not a lockfile), so removing the pip-format
  lock costs nothing operationally while killing the drift.
- **Alternatives:** Keep only `requirements.lock` (rejected: pip-freeze output is
  environment-specific and lossy); keep both (rejected: guaranteed drift).

### D0.2 — GEMINI_API_KEY env-mapping trap fix (validation_alias + populate_by_name)
- **What:** `Settings.gemini_api_key` now uses
  `validation_alias=AliasChoices("LEMELY_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")`
  and the model enables `populate_by_name=True`.
- **Why:** Audit blocker #11: an unprefixed `GEMINI_API_KEY` authenticated the
  CLI/Gradio (google-genai SDK env fallback) but left the web portal degraded/503
  because web AI gates read `settings.gemini_api_key`, which only
  `LEMELY_GEMINI_API_KEY` populated. Now one env var works everywhere.
  `populate_by_name=True` is required so `Settings.model_validate(model_dump())`
  round-trips (test fixtures rebuild Settings from a dump) don't reject the
  field-name key under `extra="forbid"`.
- **Alternatives:** Custom env source override (rejected: more code, less idiomatic);
  reading the SDK vars manually in each gate (rejected: scattered, error-prone).

### D0.3 — Test hermeticity against a developer's repo `.env`
- **What:** Added `tests/conftest.py` (session autouse) that disables `.env` file
  discovery in `Settings.model_config` for the test session; hardened
  `_IsolatedEnv` in `test_runtime_config.py` to also clear the unprefixed keys and
  chdir into a temp dir.
- **Why:** `Settings(env_file=".env")` reads a repo-root `.env` at every
  instantiation. A developer keeping a real `.env` (with a Gemini key) for local
  runs flipped 3 "without key" assertions (doctor, config defaults, web plan 503).
  CI has no `.env` and always passed; this makes the suite green everywhere so the
  unattended `pytest` gate is trustworthy. No `os.environ` mutation, no assertion
  weakened — only the stray file source is neutralised.

### D0.4 — CI now installs the `web` extra and adds a `web` job
- **What:** Test job installs `.[dev,ui,web]` (was `.[dev,ui]`); new `web` CI job
  runs `npm ci`, `typecheck`, `oxlint`, `build` for the SPA.
- **Why:** The FastAPI tests import `fastapi` (web extra) — CI omitting it was a
  latent failure once CI got past the (previously red) ruff-format step. Audit §9
  flagged the SPA has zero CI coverage.

### D0.5 — DET parser: wire the modular `lemely/io/det/`, delete the monolith `parsers_det.py`
- **What:** Adopt the staged modular package `lemely/io/det/` as the one
  `DeterministicMarkSchemeParser`; delete `lemely/io/parsers_det.py`; rewire the
  3 call sites (cli, gradio, teacher router) and rewrite the parser test suite to
  target the modular package. Both expose the same
  `DeterministicMarkSchemeParser.__call__(pdf_path) -> MarkScheme`; the modular one
  additionally takes `cfg: DetParserSettings | None`.
- **Why (evidence, not assumption):** Ran BOTH parsers head-to-head on the 4 real
  Physics mark-scheme PDFs in `Sources/`:
  - MCQ (`0625_m20_ms_12`) and alternative-practical (`0625_m21_ms_62`): identical,
    correct output — leaf-mark total == `maximum_mark` (40 == 40) for both parsers.
  - Theory (`0625_s19_ms_43`, `0625_s20_ms_31`): the **monolith silently returns
    wrong totals** (88 and 76 vs the stated 80) with no error — audit blocker #10,
    the exact "silent mis-parse" that poisons marking accuracy. The **modular parser
    runs its Stage-4 reconciler**, detects the mismatch, and raises `ParseError` so
    `ChainedMarkSchemeParser` routes the paper to Gemini instead of persisting
    garbage. It also honors `DetParserSettings` (the monolith ignores it entirely).
  - The modular package is already `mypy --strict` clean.
- **Consequence (recorded honestly):** With the modular parser, theory papers can
  no longer be "deterministically parsed" into a (wrong) scheme — they escalate to
  Gemini via the chain. On the raw no-Gemini path (`parse-mark-schemes` without
  `--use-gemini`) a theory paper now raises `ParseError` (fail-loud) instead of
  writing a silently-wrong JSON. For an accuracy-first product this is the correct
  trade: MCQ/practical stay fully deterministic; complex theory uses Gemini (the
  intended chain design) rather than emitting numbers that don't sum to the max.
- **Alternatives:** Keep the monolith and bolt reconciliation onto it (rejected:
  duplicates work the modular package already does cleanly, and the monolith still
  ignores `DetParserSettings`); keep both (rejected: MISSION requires picking one).

### D0.6 — Gemini cost cap: persistent file-backed USD ledger, $8 hard ceiling
- **What:** New `lemely/io/cost_ledger.py` (`CostLedger`) persists cumulative USD to
  `{output_dir}/gemini_spend.json` (atomic write, survives process restarts).
  Renamed `GeminiSettings.monthly_usd_ceiling` → `total_usd_ceiling` (default now
  **8.0**, active); added `usd_warning_thresholds=[4.0, 6.0]`. `GeminiClient` checks
  the ledger total before/after calls and publishes `BUDGET_WARNING`/`BUDGET_EXCEEDED`
  bus events on threshold crossings (each fires once, tracked in the ledger).
  `lemely/runtime/notify.py` (`post_ntfy`, stdlib urllib, no-op unless
  `LEMELY_NTFY_TOPIC` set) + `budget_notify.register_budget_ntfy()` (idempotent)
  deliver those events to ntfy, registered from the CLI and web entrypoints.
- **Why:** Audit blocker #5 — `monthly_usd_ceiling` reset every process, so there was
  no real cross-run cap. Verified fix with two separate OS processes sharing one
  ledger file: proc2 reads proc1's spend; $4/$6 warnings fire exactly once across
  the boundary. `lemely.runtime` stays free of domain imports (notify uses only
  stdlib) so the import-linter contract holds.
- **Test hermeticity:** `tests/conftest.py` now also neutralises ambient `lemely.toml`
  discovery (repo-root + ~/.config/lemely), needed because the rename would make a
  developer's local `monthly_usd_ceiling` key an `extra=forbid` error. Explicit
  `toml_path`/temp-cwd discovery still works.

### D0.7 — `lemely doctor` real Gemini reachability (acceptance criterion)
- **What:** Added `GeminiClient.check_reachable()` — a zero-token `models.list()`
  round-trip that raises `ExternalServiceError` on missing key / auth failure /
  network error. `doctor` (without `--no-network`) now calls it and reports the
  actual result, replacing the hardcoded `gemini_reachable=False` "not yet
  implemented" stub (audit §6/§10 #15). `--no-network` still skips it.
- **Why:** Phase 0 acceptance requires "`lemely doctor` reports the real Gemini
  reachability." `models.list()` validates credentials + connectivity without
  generation, so it costs nothing against the $8 ledger.
- **Tests:** live-ping reachable→all_passed; unreachable→exit 3 + gemini_reachable
  false (both mock `check_reachable`, no real network in the suite).

### D1.7 — Adversarial auth-surface hardening (signup RBAC, OTP resend cooldown, history-key guard)
- **What:** Three defensive fixes to the Phase-1 auth surface, found by an
  adversarial review pass:
  1. **Self-service signup is student-only.** `POST /api/auth/signup` now 403s any
     role other than `student` (`_SELF_SERVICE_SIGNUP_ROLES = {student}`). Elevated
     roles (teacher/school_admin/platform_admin) are minted only by an authenticated
     admin via the seat/invite flow (later task), never by an anonymous caller.
  2. **OTP resend cooldown.** `OtpStore.issue` raises `OtpRateLimitError` if a *live*
     challenge for the same phone was issued < `otp_min_resend_seconds` (default 30)
     ago; the router maps it to **429**. Without this, a caller could reset the
     `max_attempts` brute-force counter by re-requesting before lockout.
  3. **History-store key guard.** `HistoryStore` runs every `student_id` through
     `_safe_key`, rejecting path separators, `.`/`..` segments, and NUL bytes before
     it becomes a `{root}/{id}.json` path — closing a traversal vector for the
     request-supplied ids some callers pass.
- **Why:** All three are unauthenticated/low-privilege escalation or abuse vectors on
  routes that are now publicly reachable. Cheapest correct fix at each layer; no schema
  or API-shape change (signup DTO unchanged — the 403 is behavioural).
- **Tests:** `test_signup_elevated_role_forbidden` (3 roles → 403) + student→200;
  `test_resend_within_cooldown_is_rate_limited` / `_allowed_after_cooldown` /
  `_once_prior_challenge_expired` + router `test_otp_resend_within_cooldown_returns_429`;
  `test_unsafe_student_id_rejected` (7 hostile keys) + a dotted-id allow test.
- **Alternatives:** Map the resend cooldown to 401 (rejected: 429 is the correct
  semantic and lets clients back off); allow-list roles at the DTO layer (rejected: the
  behavioural 403 keeps one signup DTO and a clear audit log line).

### D1.8 — HistoryStore → Postgres via an interface-preserving repository
- **What:** `lemely/db/history_repo.py` (`DbHistoryStore`) replaces the JSON
  `HistoryStore` behind the *same* surface (`load(user_id) -> StudentHistory`,
  `append(user_id, record)`, `list_students()`), so all downstream analytics that
  consume `StudentHistory`/`PaperRecord` are untouched. A `PaperRecord` maps to one
  `Attempt` row (+ its `WeaknessRecord` rows from `weak_areas`); `load` reconstructs
  `PaperRecord`s from those rows.
- **Impedance mismatches resolved (recorded honestly):**
  1. `student_id` (free-form str) → `Attempt.user_id` (UUID FK → `users.id`). The repo
     requires a real user row (post-P1.4 every authed caller is mirrored into
     `public.users`, so `auth.user_id` is a valid UUID). Legacy non-UUID JSON keys
     (e.g. "anonymous") cannot be migrated and are reported/skipped, not forced.
  2. `ExamMetadata.session_month` ("May/June"…) ↔ `SessionMonth` enum via the inverse
     of `SESSION_MONTH_LABELS`.
  3. `recorded_at` ISO **string** ↔ tz-aware `DateTime`: parsed on write, `isoformat()`
     on read. Canonical UTC strings (`now_iso()`) round-trip exactly.
  4. `PaperRecord` carries **no** per-question data, so migrated attempts have zero
     `question_results` (those come from the live marking pipeline, not history).
- **Ordering (intentional improvement over the JSON store):** `load` returns records
  in `recorded_at` order (JSON preserved append order); `weak_areas` within a record are
  sorted by `topic`. Both are deterministic and semantically correct for trend/aggregation
  code; parity tests normalise on the same keys.
- **Migration:** `migrate_json_history(json_store, db_store)` walks every JSON student
  file and re-appends each record through the repo; returns a per-key result so unmigratable
  legacy keys are surfaced. `outputs/history/` is currently EMPTY (the interim store was only
  dev/test-written), so there is no production data at risk.
- **Rollout:** additive first (repo + parity tests, routers untouched, JSON store intact),
  then swap `get_history_store` → DB repo + relocate `now_iso` + delete `io/history_store.py`.
- **Alternatives:** async SQLAlchemy (rejected: whole stack is sync, D-session.py); a new
  wire/DTO shape for history (rejected: preserving `PaperRecord` keeps the blast radius to
  the storage layer only).

### D1.9 — Web/product history moves to Postgres; CLI + Gradio keep the JSON store
- **What:** `get_history_store` (the web dependency) now returns `DbHistoryStore`
  (D1.8), so every FastAPI route and the web grading service persist/read student
  history in Postgres. `now_iso()` and a structural `HistoryStoreProtocol`
  (`load`/`append`/`list_students`) move to `lemely/core/history.py`; routers and the
  grading service are annotated against the Protocol so both stores satisfy them.
- **Deviation from the STATE task, recorded honestly:** the task said "delete the JSON
  store after parity proven." The audit assumed the web routers were its only consumers —
  they are NOT: `app/cli.py` and `app/gradio_app.py`/`gradio_callbacks.py` also use the
  JSON `HistoryStore`. The CLI and Gradio are local, single-process, **unauthenticated**
  tools with no tenancy and no UUID user ids; forcing a Supabase-Postgres round-trip on
  them is heavy, out of the task's "web routers" scope, and less reversible.
- **Decision (simplest / cheapest / most reversible per MISSION):** migrate only the
  web/product surface to the DB now; **retain `lemely/io/history_store.py` for the CLI +
  Gradio internal tools.** Full deletion of the JSON store is DEFERRED until those tools are
  either retired or given their own migration — a separate, explicit scope decision, not a
  silent side effect of the web migration. Parity between the two stores is already proven
  (D1.8), so a future switch is low-risk.
- **Consequences:** web tests are unaffected (they override `get_history_store` with an
  in-tmp JSON store as a hermetic test double at runtime — the DB is never touched in the
  web suite). `test_history_store.py` stays valid (the JSON store still ships). No web route
  reads history without an override, so no web test silently starts requiring Postgres.

### D1.10 — Seat model: on-demand allocation, locked quota check, membership-based ownership
- **What:** `lemely/db/seat_repo.py` (`SeatService`) owns seat allocation. A school buys a
  fixed `seat_quota`; each occupied slot is a non-revoked `Seat` row. Seats are allocated
  **on demand** — there is no pre-provisioning step: `invite_student` creates a student
  account and, in the same locked transaction, inserts an `assigned` seat *iff* the school
  has headroom. `revoke_seat` flips a seat to `revoked` (freeing quota) without deleting the
  student's account (idempotent). Introspection: `list_admin_schools` / `seat_usage`. The
  HTTP surface is `lemely/web/routers/school.py` under `/api/school/seats` (list / invite /
  {id}/revoke), gated at the router level to `school_admin` alone.
- **TOCTOU-safe quota:** `invite_student` locks the school row `FOR UPDATE` for the duration,
  so two concurrent invites serialise — the second sees the first's committed seat and is
  rejected once the quota is full, instead of both slipping past a stale count. Ownership and
  quota are checked *before* account creation, so a rejected invite never leaves an orphaned
  account (proven by `test_invite_beyond_quota_is_rejected_without_creating_account`).
- **Ownership is membership-based, no super-role (mirrors D1.6):** every mutating call
  re-verifies the caller holds a `school_admin` `SchoolMembership` for the target school (or
  the seat's school); anyone else gets a `SeatOwnershipError` → 403, never data or a
  mutation. Even `platform_admin` is 403 on this surface (dedicated admin surface later).
- **Account-creation seam:** `StudentAccountCreator` is a Protocol so the pure seat/quota/
  ownership logic is Postgres-testable without the live GoTrue stack. The real adapter
  (`AuthServiceStudentCreator`, in `web/deps.py` — the one layer that already imports both
  `lemely.auth` and `lemely.db`, keeping the import graph acyclic) wraps `AuthService.signup`
  pinned to `Role.student`; the invite route generates a one-time temporary password when the
  admin omits one and returns it once (no student email provider in v1, exactly as the mock
  SMS provider surfaces the parent OTP).
- **Personal subscription coexists:** a seated student may *also* hold a personal
  `Subscription` — the schema enforces no exclusivity and the seat service touches neither
  table (proven by `test_seated_student_may_also_hold_a_personal_subscription`), satisfying
  the MISSION §4 requirement.
- **Alternatives:** pre-provision N empty seats at school creation then claim them (rejected:
  an extra lifecycle state and migration for no gain — an occupied-seat count against the
  quota is the same invariant with less machinery); advisory application-level locking instead
  of `FOR UPDATE` (rejected: the row lock is the simplest correct serialisation and needs no
  external coordinator).

### D2.1 — Grade-boundary data stays JSON-file-based, not a new DB table
- **What:** P2.2 (real per-paper-variant CAIE grade-threshold ingestion) populates
  `lemely/data/grade_boundaries.json` with scraped official data and replaces the
  hardcoded `_defaults` guesses with **real per-subject historical averages** computed
  from the scraped exact entries. `GradeBoundaryStore` (`lemely/io/grade_boundaries.py`)
  and its `resolve()` fallback chain (exact → subject_default → global_default) are
  **unchanged** — only the data backing it changes from guessed to real+provenanced.
- **Why not a DB table:** the `papers` table (P1.3) could host boundaries, but
  `GradeBoundaryStore` is used by three surfaces — the web API, the CLI, and Gradio
  (`app/cli.py`, `app/gradio_app.py`) — and only the web surface has a DB session (CLI/
  Gradio are the same local/unauthenticated tools D1.9 kept off Postgres). Moving
  boundaries into the DB would mean either giving CLI/Gradio a DB dependency they don't
  otherwise need, or forking the resolver into DB-backed (web) and file-backed (CLI/
  Gradio) implementations that must be kept in sync — both more machinery for no
  behavioural gain over the existing file-backed resolver, which is already
  injectable/testable (`GradeBoundaryStore(data_path)`) and consistent with how the
  mark-scheme corpus is stored (files, not DB rows).
- **Provenance:** each scraped exact entry's source document URL is recorded in a
  sibling `lemely/data/grade_boundaries_provenance.json` keyed by the same boundary key,
  so the JSON data file itself stays a clean grade→percentage map (matching the existing
  reader) while still giving full traceability to the official CAIE document each number
  came from.
- **"Estimated" flag:** `boundary_source` already encodes this — `"exact"` vs
  `"subject_default"`/`"global_default"` — and the student-facing integrity copy in
  `lemely/web/routers/student.py::_integrity_summary` already reads as an estimate
  disclosure for the non-exact cases. No new field was needed; the existing Literal is
  the "estimated" flag the MISSION §4 P2.2 acceptance asks for.
- **Source: official cambridgeinternational.org, NOT the three mirrors MISSION §4 named
  — recorded deviation.** Before scraping, checked all three: `gceguide.com` now
  resolves to an unrelated Indonesian gambling-slot site (the domain has been squatted
  since the mission was written — confirmed via `curl`, page title/meta is
  "AGUNG11 - Situs Slot..."), so it is unusable and was NOT fetched again beyond that one
  identifying request. `papacambridge.com` and `xtremepape.rs` both resolved to their
  expected past-papers content and were viable, but Cambridge International's own site
  (`cambridgeinternational.org/.../grade-threshold-tables`) publishes the same official
  per-subject grade-threshold PDFs directly, with a predictable per-session index page —
  strictly better provenance (primary source, not a re-host) for the same data, so that
  was used instead of the fan mirrors. Flagging the squatted domain here so no future
  session wastes a request on it or, worse, trusts its content.
- **No workflow/subagent fan-out — direct script instead, recorded deviation from the
  MISSION §5 "use a workflow for boundary-document scraping/parsing" guidance.** That
  guidance was written before reconnaissance; once the actual page/PDF structure was
  known (one small index page per session, one PDF per subject, a clean fixed-width
  table per PDF), the task is fully deterministic pattern-matching, not judgment work —
  spinning up agents to read PDF text and transcribe numbers would be slower, costlier,
  and less accurate than a parser regex. Wrote `scripts/ingest_grade_boundaries.py`
  instead: discovers the published session list, finds each subject's PDF per session,
  downloads, and parses the per-component threshold table with `pdfplumber`. Simpler,
  cheaper, and fully reversible/rerunnable — the reversible-fork tiebreaker in MISSION §1.
- **Scope of "all available sessions":** Cambridge's own grade-threshold-tables index
  currently lists exactly 13 published sessions: March/June/November 2022 through 2025,
  plus March 2026 (results not yet published for these 3 subjects as of ingestion, so it
  contributed 0 entries). That is the full available history on the authoritative source
  — not an arbitrary cutoff. The script fetched all 13 for all 3 subjects (39 candidate
  documents; 36 existed and parsed, 3 were not-yet-published), yielding 347 real
  per-component exact entries, from which `_defaults` (per-subject historical averages)
  are now genuinely computed rather than guessed. Extending coverage later is additive:
  re-running the script picks up newly published sessions automatically (it derives the
  session list from the live index each run) and merges into the same JSON + provenance
  files without touching existing keys.

### D2.2 — One review threshold at 0.90 (provisional, Physics-only); confidence alone provably cannot satisfy the §4 flag gate
- **What:** The three coincidentally-equal confidence thresholds are collapsed to **two
  semantically distinct knobs**:
  1. `GeminiSettings.escalation_confidence_threshold` (`lemely/runtime/config.py:46`,
     unchanged at **0.80**) stays a *budget* knob only: `AICorrector.mark_question`
     (`lemely/io/correction_ai.py:75,97`) spends a thinking retry then a Pro call to try to
     **improve** a mark before it is final. Raising it costs Gemini dollars.
  2. **`REVIEW_CONFIDENCE_THRESHOLD = 0.90`, defined once** in `lemely/core/schemas.py`
     (immediately below `confidence_band_for_score`), is the *human-review* gate: a final
     mark may reach a student unreviewed only if confidence ≥ this. Raising it costs teacher
     time. It is now read by all three sites that previously carried their own literal:
     `lemely/io/correction_ai.py::_build_ai_corrected` (was a hardcoded `0.80` — the
     duplicate), `lemely/db/attempt_repo.py` (was its own `REVIEW_CONFIDENCE_THRESHOLD =
     0.90`, now a re-export so the module's public name is preserved), and
     `lemely/web/routers/teacher.py:119` (`_REVIEW_CONFIDENCE`, now an alias — a **fourth**
     copy the STATE note had not counted).
- **Why one constant and NOT a `lemely.toml` field (deviation from the STATE task's
  "e.g. `review_flag_confidence_threshold`" suggestion):** the value must be byte-identical
  in the marking layer (`io`), the persistence layer (`db`) and the web layer, and those three
  do not share a `Settings` injection path — `AttemptRepository` takes only a `sessionmaker`,
  and giving it a settings dependency to carry one float is more machinery than the problem.
  Worse, a per-machine TOML override of an *accuracy-gate* invariant would silently invalidate
  the harness numbers that justify it (the same class of footgun D0.3 closed for `.env`).
  Promoting the constant to config later is additive and touches one import. Its value
  coincides with the `ConfidenceBand.HIGH` cut-off, so the invariant states in one sentence:
  **only HIGH-confidence marks are auto-graded.**
- **Should (A) and (B) be allowed to diverge? Yes, and they now do — the coupling was the
  bug.** They answer different questions ("is it worth more money to re-ask?" vs "is it safe
  to show a student?"), and the correct ordering is escalate-low ≤ review-high: escalating at
  <0.90 would have fired on 5 of the 21 theory questions in the calibration batch and burned
  budget on questions the model was already right about, while flagging at <0.80 fired on
  exactly 1 of 21. Wiring (B) to (A) would have permanently welded a cost knob to a safety
  knob; a second config field would have kept the drift risk with extra surface. One shared
  domain constant kills the drift outright.
- **(B)'s old 0.80 was strictly dead in production, and that made the harness lie —
  the most important thing this decision fixes.** Because (C) was 0.90 and the persist gate
  is `needs_teacher_review OR confidence < (C)` (`lemely/db/attempt_repo.py:122`), a 0.80
  flag could never add a review item that 0.90 did not already add. Its only independent
  effects were the teacher UI badge and — critically — the accuracy harness, whose
  `flag_recall`/`flag_precision_HIGH` read `cq.needs_teacher_review`
  (`lemely/accuracy/harness.py:187,288`). So the 2026-08-04 batch reported **flag_recall
  0.0%** while the code that actually routes work to a human would have caught 1 of the 3
  disagreements. The harness was measuring a gate that does not exist. Post-change the harness
  measures exactly the production gate: same batch → **flag_recall 33.3%** (1/3),
  **flag_precision_HIGH 91.7%** (22/24, up from 89.3%). Answering the STATE question directly:
  **yes — MISSION §4's "review threshold" criterion is evaluated against this one constant
  from now on, and it is the same number (B) and (C) both use, so the distinction that made
  the question necessary no longer exists.**
- **Why 0.90 and not higher — the step function (this is the evidence, and it is robust to
  n=29):** the 21 theory confidences in `tests/golden/results/2026-08-04-2a9af42.json` take
  only six distinct values — 0.65 ×1, 0.85 ×4, 0.90 ×1, 0.95 ×1, 0.96 ×1, **0.98 ×13** — with
  the 3 disagreements at 0.98, 0.85, 0.98. Sweeping the threshold over that distribution:

  | threshold | theory questions flagged | disagreements caught |
  |---|---|---|
  | 0.80 (old (B)) | 1 / 21 | 0 / 3 |
  | **0.90 (chosen)** | **5 / 21** | **1 / 3** |
  | 0.91 – 0.98 | 6 → 8 / 21 | 1 / 3 |
  | 0.99 | 21 / 21 | 3 / 3 |

  Every value in (0.90, 0.98] buys **zero** additional recall for strictly more teacher work,
  and `flag_precision_HIGH` actively *degrades* across that range (0.9167 at 0.90 → 0.9130 at
  0.91 → 0.9091 at 0.96 → 0.9048 at 0.97) because raising the bar removes correct answers from
  the auto-graded set while both 0.98 errors stay in it. Strictly dominated on both metrics, so
  "tune it up a bit" is not an option that exists here. The only value
  that satisfies MISSION's literal "100% of disagreements carry confidence below the review
  threshold" is >0.98, which flags **every AI-marked question** and reduces the product to
  "auto-marks MCQs only". That is a degenerate pass, not a pass. 0.90 is the Pareto-optimal
  point on the frontier and is independently anchored (HIGH band, and the value (C) already
  shipped with in P2.1). The finding driving this is *where the probability mass sits* — 62%
  of theory marks report the identical 0.98 — not a fine boundary estimated from 3 points, so
  a bigger corpus can move the optimum but is unlikely to invert the ordering.
- **Answering "is a single global threshold sufficient?" — No, provably not, and the honest
  reason is that the fix does not live in the flagging layer.** Decomposing
  `mark_accuracy_theory` 85.7% by *ground-truth* mark shape: **15/15 (100%)** on
  all-or-nothing answers (7 full-credit + 7 zero-credit + one 1-mark question) but **3/6
  (50%)** on genuinely partial-credit answers. All 3 errors are the identical failure:
  the method (M) marks were correctly identified and the **accuracy (A) mark was awarded even
  though the final numeric value was wrong** (1b: 89 vs 8.9; 5b: 3.33 vs 3.0 N, also missing
  M3; 12c: 9 vs 4.5 mg). The model is not mis-reporting its confidence about a thing it
  half-knows — it is confidently failing to re-check arithmetic. Method-mark partial credit is
  exactly the capability MISSION §1 sells, and it is at 50%.
- **The proposed secondary signal (`awarded_marks != question.marks` + high confidence) was
  evaluated and REJECTED on the data — recorded so it is not re-proposed blind.** Neither
  direction of a mark-value rule separates these cases:
  - "flag when `0 < awarded < max`" (predicted partial credit): flags 4/21 theory, catches
    **1/3** — identical recall to the 0.90 threshold already achieved, for 4 extra flags.
  - "flag when `awarded == max` on a multi-mark question": flags 8/21, catches 2/3 — but 6 of
    those 8 flags are correct full-credit answers, i.e. it mostly penalises good students.
  - the union (≡ "flag any non-zero award") flags 14/21 for 3/3: flag-everything again.
  The reason it cannot work: 2 of the 3 errors awarded **full** marks and 1 awarded **partial**,
  so the observable award value is anti-correlated with itself across the failure set. Adding
  an unvalidated heuristic here would trade a measurable miss for an unmeasurable one.
- **What WAS added instead — a zero-false-positive structural signal.**
  `_build_ai_corrected` now flags on `mark.awarded_marks != clamp(mark.awarded_marks)`
  **independently of confidence**: a marker asking for 4 marks on a 3-mark question has
  misread the mark scheme, and the pre-existing `max(0, min(...))` clamp was silently
  repairing that and shipping it as a confident mark. It fires zero times on the current
  corpus (no over-award occurred), so it adds no review load, and it can only fire when the
  model is objectively wrong. `_build_ai_corrected` also now sets a human-readable
  `review_reason` (previously `None` for every AI-flagged question, so the teacher queue and
  `question_results.review_reason` showed a flag with no stated cause).
- **Numbers are PROVISIONAL — Physics-only, n=29 (8 MCQ + 21 theory), 3 disagreements, one
  paper (0625 s20 qp31 + m20 qp12), one session, all disagreements the same failure mode.**
  Recorded in the constant's docstring too, so nobody reads 0.90 as calibrated across boards
  or subjects.
- **Step-7 sequencing decision (0580/0606 fixtures): ship the threshold now, source the
  fixtures next, revisit the number once — do NOT block on broader evidence.** Three reasons:
  (a) the step-function above shows broader fixtures cannot change the *direction* of this
  call unless the confidence distribution itself changes shape across subjects; (b) the change
  is one constant plus one import per call site — the cheapest, most reversible option MISSION
  §1 asks for; (c) the actual blocker is `mark_accuracy_theory` 85.7% vs the ≥95% gate, which
  is a marking-quality defect that more fixtures will *measure*, not fix. Sourcing 0580/0606
  remains a required step, for **statistical power**: with only 24 auto-graded questions, a
  single wrong mark caps `flag_precision_HIGH` at 95.8%, so the §4 ≥99% target is
  **arithmetically unreachable at this corpus size regardless of the threshold** — the gate is
  currently unmeasurable, not merely unmet. Mandatory revisit trigger: the first harness run
  that includes 0580 or 0606 fixtures re-runs the threshold sweep above and amends this entry.
- **Flagged risks / follow-ups (accuracy constraint, MISSION §4):**
  1. **Phase-2 gate is still failing and this decision does not fix it:** `mark_accuracy`
     89.7% (<95%), `mark_accuracy_theory` 85.7% (<95%), `flag_recall` 33.3% (<85%),
     `flag_precision_HIGH` 91.7% (<99%). Only `id_match_rate` (100%) passes. The remaining
     work is a **marking** task, not a thresholds task: the marker must verify the final
     numeric value before awarding an A mark (a deterministic re-computation, or a cheap
     second-pass "recheck the final value only" call). That is the correct next accuracy task
     and is where the 50%-on-partial-credit number gets moved.
  2. `AccuracyEvalSettings.flag_recall_target` (`lemely/runtime/config.py`) is **0.85**, but
     MISSION §4 says *100%* of disagreements must fall below the review threshold. The config
     is the weaker of the two; the MISSION text is what gates the phase. Left unchanged
     (out of scope), flagged so the discrepancy is not read as a passing gate later.
  3. Calibration is measurably overconfident, not just noisy: the 0.90–1.00 bucket's actual
     accuracy is 87.5% (gap −0.075) and 0.80–0.90's is 75% (gap −0.10). Any future work that
     wants a *finer* threshold must first make the marker emit a spread of confidences at all
     — 62% of theory marks currently report the same 0.98.
- **Test changes (documented per MISSION §5, not weakened):** `tests/test_correction_ai.py`
  `ThresholdTests` previously asserted `test_review_false_at_0_80` — it encoded the old
  literal, so it necessarily fails under the new threshold. Replaced with tests written
  against the shared constant (`test_review_fires_just_below_threshold`,
  `test_review_false_at_threshold`), plus `test_old_0_80_threshold_now_flags` as an explicit
  regression guard for the behaviour change, and two clamp tests
  (`test_out_of_range_award_flags_despite_full_confidence`,
  `test_in_range_award_at_full_confidence_is_auto_graded`). No assertion was loosened; the
  boundary is pinned as inclusive-at-threshold (0.90 auto-grades, 0.899 flags).
- **Blast radius:** no schema change, no migration, no API/DTO shape change. Behavioural:
  marks with confidence in [0.80, 0.90) now carry `needs_teacher_review=True` (previously
  `False`) — this is a *widening* of the flag that the DB gate was already applying, so the
  review queue's contents are unchanged; what changes is that the per-question flag, the
  paper-level aggregate, the teacher badge and the harness metric finally agree with it.
- **Alternatives considered:** (i) wire (B) to `escalation_confidence_threshold` (rejected:
  welds a cost knob to a safety knob; also *lowers* the effective review bar to 0.80 in the
  UI/harness while the DB uses 0.90 — the drift stays); (ii) a new
  `review_flag_confidence_threshold` TOML field (rejected: three layers with no shared
  Settings path, and an operator-tunable accuracy-gate invariant is a footgun — see above);
  (iii) raise the threshold to 0.99 to make the §4 gate literally pass (rejected: flags 100%
  of AI-marked questions — a gate satisfied by deleting the feature is a faked pass, which
  MISSION §5 forbids); (iv) leave 0.90 and add the `awarded != max` heuristic (rejected on
  the data, quantified above); (v) block the decision on 0580/0606 fixtures (rejected: the
  step function makes the call insensitive to them, and this is the reversible option).

### D2.3 — 0580/0606 fixtures landed; mandatory D2.2 revisit confirms the gate is a marking-quality problem, not a threshold problem — 0.90 kept unchanged
- **What:** P2.3 step 7 completed. Verified and committed the two `data-engineer` outputs
  dispatched in the prior (crashed) session: real Cambridge IGCSE Mathematics 0580/22
  (May/June 2023) and Additional Mathematics 0606/12 (May/June 2023) mark schemes + question
  papers under `Sources/{Mathematics,AdditionalMathematics}/` (gitignored, consistent with
  `Sources/` policy), and 6 new committed golden fixtures mirroring the 0625 pattern exactly:
  `tests/golden/0580_s23_qp_22_theory_{correct,partial,wrong}` (7 questions each) and
  `tests/golden/0606_s23_qp_12_theory_{correct,partial,wrong}` (6 questions each). Also fixed
  a real latent bug the dispatch surfaced: `lemely/io/det/profiles.py` registered a 0606
  profile but never a 0580 one, so `get_profile("0580")` fell through to `_DEFAULT_PROFILE`,
  which maps paper 1 → MCQ — wrong for 0580 (no MCQ component at all; papers 1/3 are
  non-calculator/calculator Core, 2/4 are non-calculator/calculator Extended). Added
  `_MATHEMATICS_PROFILE` with the correct 1/2/3/4 → Core/Extended/Core/Extended mapping and
  corrected a comment on the 0606 profile that had incorrectly asserted "0580 paper 1 is MCQ".
- **Verification performed (not just trusting the subagents' prior claims, per MISSION §5):**
  read page 1 of all 4 sourced PDFs via `pdfplumber` — genuine Cambridge headers/watermarks
  confirm `MATHEMATICS 0580/22 Paper 2 (Extended) May/June 2023` and `ADDITIONAL MATHEMATICS
  0606/12 Paper 1 May/June 2023`, not fabricated; validated all 6 `mark_scheme.json` files
  against `lemely.core.loose_schemas.MarkScheme` (all pass); spot-checked answer points against
  the real mark scheme text (e.g. 0580 Q1 answer point "−13" matches "−5 − 8 = −13" in the
  `correct` fixture; Q12a point "53" matches the fixture's derivation) and confirmed the
  `wrong`/`partial` variants carry genuinely altered student answers and reduced
  `awarded_marks`, not copies. Ran full §6-relevant gates: ruff/ruff-format/mypy(115
  files)/lint-imports clean; pytest 100% pass (0 failures; the usual Postgres/live-auth skips —
  local Supabase stack could not be started this session, see Blast radius below, this is an
  environment gap not a regression). Gemini spend delta: **+$0.0150** (cumulative
  $0.0502 of the $8.00 ceiling) for the live `measure-accuracy` run below — sane and
  nowhere near budget pressure.
- **Mandatory revisit executed (D2.2's own trigger: "the first harness run that includes 0580
  or 0606 fixtures re-runs the threshold sweep and amends this entry").** Ran
  `lemely measure-accuracy` across all 10 committed fixtures (0625 MCQ + 3×0625 theory +
  3×0580 theory + 3×0606 theory), n=68 questions (60 theory, 8 MCQ) — saved to
  `tests/golden/results/2026-08-04-2473205.json` (gitignored, regenerable, cache-hits are free
  per the usual pattern).
  - **Metrics got materially worse, not better, with more data — this is signal, not noise:**
    `mark_accuracy` 89.7%→**80.9%**, `mark_accuracy_theory` 85.7%→**78.3%**, `id_match_rate`
    unchanged at 100%, `flag_precision_HIGH` 91.7%→**82.5%**, `flag_recall` 33.3%→**23.1%**.
    Theory disagreements went from 3 (one paper) to **13** (three papers, two subjects): a
    21.7% theory error rate on the broader corpus vs 14.3% on Physics alone.
  - **Threshold sweep at n=68 (vs D2.2's n=29) — the honest re-run of D2.2's own table:**

    | threshold | theory questions flagged (of 60) | disagreements caught (of 13) |
    |---|---|---|
    | 0.80 | 5 | 1 |
    | 0.85 | 5 | 1 |
    | **0.90 (current)** | **11** | **3 (23%)** |
    | 0.95 | 16 | 7 (54%) |
    | 0.96–0.98 | 30–35 | 9 (69%) |
    | 0.99 | 59 | 13 (100%) |

    At n=29 (D2.2), 0.90 already looked weak (1/3 caught) but was read as a thin-sample
    artifact possibly fixable by more data. At n=68 it is now unambiguous: **no threshold
    below 0.99 gets anywhere close to the MISSION §4 "100% of disagreements below threshold"
    requirement**, and 0.99 remains the same degenerate "flag 98% of theory questions" case
    D2.2 already rejected as a faked pass (MISSION §5). The broader corpus did not change the
    *direction* of D2.2's call (predicted correctly: no non-degenerate threshold clears the
    gate) but it does sharpen the diagnosis: this is not a calibration problem that more data
    fixes, it is a **structural ceiling** — confidence and correctness are close to
    independent on this task as currently implemented.
  - **Calibration confirms systemic, worsening overconfidence:** the 0.90–1.00 confidence
    bucket (49 of 68 predictions) is only 79.6% actually correct (gap **−0.154**, vs D2.2's
    thinner −0.075 reading); 0.80–0.90 is 66.7% correct (gap −0.183). The model states high
    confidence at roughly the same rate whether it is right or wrong.
- **Decision: `REVIEW_CONFIDENCE_THRESHOLD` stays at 0.90, unchanged.** The sweep above proves
  raising it further only trades teacher-review load for marginal recall while the honest
  ceiling (0.99 = flag-everything) is still off the table for the reasons D2.2 already gave.
  Moving it would be re-litigating an already-answered question with data that confirms the
  original answer more strongly, not new evidence against it.
- **P2.3's accuracy gate remains unmet, now with statistically adequate evidence (n=68, 3
  papers, 2 subjects) instead of D2.2's provisional n=29/1-subject caveat — the "sourcing
  0580/0606 gets us to a measurable gate" reasoning is now resolved: the gate is measurable
  and it fails.** The path to closing it is unchanged from D2.2's diagnosis and is now the
  clear next P2.3 step: a marking-quality fix that verifies the final numeric/algebraic value
  before awarding the accuracy (A) mark on partial-credit questions, not further threshold or
  fixture work. Recorded as the explicit next action in `BUILD/STATE.md` (P2.3 step 8).
- **Blast radius:** fixtures + one profile registry entry + one comment fix; no schema,
  migration, or API change. `REVIEW_CONFIDENCE_THRESHOLD` numerically unchanged, so no
  behavioural change to what reaches the review queue. Local Supabase stack was down this
  session (stale root-owned files under `supabase/.temp/start-secrets/` from a prior crashed
  container, not removable without root — outside this session's write access) so
  Postgres-backed integration tests skipped as usual; this is an environment gap, not
  introduced by this change, and does not affect the accuracy-harness work (no DB dependency).
  Flagged here so a future session with shell/root access cleans it up rather than
  re-diagnosing it.

### D2.4 — Deterministic calculated-answer verification (P2.3 step 8, the marking-quality fix)

- **What:** `lemely/io/correction_ai.py` gained a deterministic backstop that runs after
  every AI marking call, independent of stated confidence (D2.3 proved confidence cannot
  substitute for this). For every point the AI claims was matched, if the mark scheme
  attaches a `calculated_answer.value` to that point (a specific numerical result is
  required, any M/A/B/C code), the point — and its marks — are rejected unless that value
  is actually present in the student's text. `needs_teacher_review` gets a third
  independent trigger (`value_mismatch`) alongside D2.2's existing two (low confidence,
  out-of-range award).
- **Resumed on a dirty tree:** this session inherited an untracked, uncommitted WIP diff to
  `lemely/io/correction_ai.py` implementing the first version of this idea. Verified before
  trusting (MISSION §5): static gates had one lint issue (fixed); no tests existed for the
  new logic at all — added 20 unit tests before treating any of this as done.
- **Design iterated three times against the real golden corpus, not just unit tests — each
  iteration caught by a live `measure-accuracy` re-run, not by inspection:**
  1. First cut: extract every number (decimals + naive `a/b` fractions) from
     `student_answer + " " + student_working` concatenated, check for a match. Net effect on
     the 10-fixture corpus: **zero** — it fixed 2 of the known D2.2/D2.3 disagreements
     (0625 `1b`, `12c`) but broke 2 previously-*correct* answers (0606 `q1`, both variants),
     because the student wrote `b = 3/8` and the naive extractor never evaluates fractions.
     `mark_accuracy` was unchanged at 80.9% — fixes and regressions cancelled exactly.
  2. Added fraction evaluation, but the regex still matched *any* `a/b` substring anywhere in
     the combined text, including intermediate division shown as working. Re-running
     surfaced a worse bug: `148 / 16.6 = 89` (mark scheme expects `8.9`, student's decimal-slip
     wrong-answer is `89`) — the fix evaluated `148/16.6 ≈ 8.9` itself and "corrected" the
     student's arithmetic, validating a wrong answer as if the fraction were the stated value.
     Same for `36 / 8 = 9` (expects `4.5`). This is worse than doing nothing: it launders
     exactly the failure class D2.3 was written to catch. Full re-run reverted to the
     pre-fix baseline exactly (0 diffs vs the original bug) because the false-accept on
     `1b`/`12c` cancelled the true-reject that was working before.
  3. Final design: (a) fraction *evaluation* is applied ONLY to `student_answer` — never to
     `student_working` — because working legitimately contains a division whose correct
     result differs from what the student actually wrote as their final answer; evaluating it
     ourselves re-does their arithmetic instead of checking their claim. (b) fraction operands
     must be plain integers not adjacent to a decimal point (blocks `148/16.6`) and not
     immediately followed by `= <number>` (blocks `36/8 = 9`, a division-with-shown-result).
     (c) plain-decimal *matching* (no evaluation, pure string search) is safe and IS applied to
     both `student_answer` and `student_working` combined, because extraction commonly splits
     a question's final requested value into `answer` while an intermediate quantity that
     still carries its own mark-scheme point (e.g. a B-mark checkpoint like `AC = 28.89` inside
     a shaded-area question) lands in `working` — restricting the first (broken) iteration's
     "answer-only, fall back to working only if answer is empty" idea to decimals-only fixed a
     third regression (0606 `4b`) that the answer-only restriction had introduced.
- **Final verification (live, real Gemini, cached from the D2.3 run — near-zero incremental
  cost since only the deterministic post-processing changed, not the marking prompt):** full
  10-fixture re-run, n=68. `mark_accuracy` 80.9%→**83.8%**, `mark_accuracy_theory`
  78.3%→**81.7%**, `flag_precision_HIGH` 82.5%→**85.5%**, `flag_recall` 23.1%→**27.3%**.
  Diffed every one of the 68 question results against the D2.3 baseline: **exactly 2 changed,
  both fixes (0625 `1b` and `12c`, wrong→correct), zero regressions.** Gemini spend delta
  ~$0.006 (cumulative $0.058 of the $8.00 ceiling) — a few live calls during interactive
  debugging of the intermediate broken iterations, not from the harness re-runs themselves
  (those were cache hits).
- **Honest limitation, not fixed by this change:** 0625 `5b` (the third original D2.2/D2.3
  disagreement) is still wrong and still unflagged. Root cause differs from the other two:
  Gemini's marker credits point `p3` (a *method* point — "F = (200-20)/60 OR 180/60", the
  student instead wrote `F = 200/60`, omitting the −20 step) despite the shown method being
  wrong; `p3` carries no `calculated_answer`, so this backstop has nothing to check. Verifying
  *method* correctness (did the student's working match the mark scheme's required algebraic
  form, not just produce a number) is a materially harder problem — comparing free-form
  algebra against a mark-scheme pattern, not a numeric-tolerance check — and is explicitly out
  of scope for this deterministic pass. Recorded here rather than silently left for a future
  session to rediscover from scratch.
- **P2.3's §4 accuracy gate (`>95%` mark-level, `100%` of disagreements below the review
  threshold) is still NOT met** — 83.8% and partial flag coverage are real improvement, not a
  pass. Whether to pursue the harder method-verification problem, accept a documented
  deviation on this gate, or find another lever is the next P2.3 judgment call, not resolved
  by this entry.
- **Blast radius:** `lemely/io/correction_ai.py` (new functions + `_build_ai_corrected` wiring)
  and `tests/test_correction_ai.py` (+20 tests: 3 baseline-behavior classes reused, 6 new
  calculated-answer-verification cases including the 3 regression guards that pin the
  iteration-2/3 bugs described above so they cannot silently reappear). No schema, API, or
  migration change — `matched_point_ids`/`awarded_marks`/`needs_teacher_review`/`review_reason`
  are all pre-existing `CorrectedQuestion` fields. Full suite green (0 failures, cov 81.95%,
  ruff/format/mypy/lint-imports clean).

### D2.5 — P2.3 accepted with a documented, unresolved §4 accuracy-gate deviation; proceeding to P2.4

- **What:** Closing P2.3 (accuracy harness + golden fixtures) and moving to P2.4 without the
  MISSION §4 gate (`≥95% mark-level`, `100% of disagreements below the review threshold`)
  being met. Current measured state: `mark_accuracy` 83.8%, `flag_recall` 27.3% (D2.4).
- **Why this is a genuinely undecidable fork, not a corner being cut:** the two approaches
  available at this point are (a) a second-pass Gemini "verify final value/method" call gated
  behind the escalation budget, or (b) accept the current state as documented and move on.
  Neither is obviously correct, so per MISSION §1 ("pick the option that is simplest, cheapest,
  and most reversible... and continue — never stop to wait for a human"), this records the
  choice rather than leaving it silently undecided or blocking the build indefinitely.
- **Reasoning for (b) over (a):**
  - Threshold tuning is exhausted (D2.3: no non-degenerate threshold clears the gate).
  - The deterministic value-check backstop (D2.4) has closed every case it structurally can —
    the one remaining known disagreement (0625 `5b`) fails because the AI credits a *method*
    point that carries no `calculated_answer`, not because a stated numeric value is wrong.
    Catching it needs judging whether free-form algebraic working matches a mark scheme's
    required method shape — a materially different, harder problem than a numeric-tolerance
    check.
  - A second Gemini self-review call is not obviously going to fix that: D2.3 already found
    "confidence and correctness are close to independent" for this model on this task — i.e.
    the model's own self-assessment is not reliably calibrated, which is exactly the capability
    a second self-review pass would need to lean on. There's no evidence a second pass avoids
    the same miscalibration as the first, only a hope.
  - Accuracy work here is genuinely open-ended (this could easily become an entire second
    workstream — prompt engineering, per-subject calibration, structured method-matching
    against parsed mark-scheme algebra), which is a different shape of problem than "build the
    core loop" (MISSION §1's framing for Phase 2). Continuing to sink unbounded effort into one
    accuracy percentage point risks starving the rest of Phase 2 (P2.4–P2.10) and the phases
    behind it of any session time at all.
  - This is reversible: nothing about (b) forecloses (a). A future session (or a dedicated
    accuracy-improvement pass, potentially after the DB-backed review queue from P2.1 has
    accumulated real teacher corrections to learn from) can pick the second-pass idea back up
    with no rework of what D2.4 already built.
- **What "accepted" means concretely:** the §4 gate is NOT silently marked as passing anywhere.
  `REVIEW_CONFIDENCE_THRESHOLD` and the calculated-answer backstop stay exactly as D2.4 left
  them — no threshold was raised to fake a pass, no fixture was altered or dropped to change
  the measured rate. This gap must be carried into `DELIVERY.md` at Phase-2 acceptance (P2.10)
  as an explicit, honest limitation: current measured accuracy (83.8% mark-level; the numbers
  from whatever the last `measure-accuracy` run before P2.10 shows) vs the §4 target, with the
  method-verification gap named as the reason, not glossed over as "in progress."
- **Blast radius:** documentation only — no code change. `BUILD/STATE.md`'s P2.3 checklist
  entries are marked done with this deviation noted; P2.4 begins next.

### D2.6 — P2.5 scoped to backend Supabase Storage wiring only; camera-capture UI + client-side PDF assembly deferred to P2.7/P2.9

- **What:** MISSION §4's P2.5 line item reads "Upload path: plain file upload (25MB cap kept)
  + PWA camera capture → client-side multi-page PDF assembly → Supabase Storage → backend
  job," which reads as one task spanning both the frontend camera/PDF-assembly UI and the
  backend Storage wiring. This session scopes P2.5 to the backend half only: migrate the
  existing (working, tested) local-disk student upload path to real Supabase Storage
  (bucket, signed access, backend pipeline reads the stored object), keep the 25MB cap.
  The camera-capture UI component and client-side multi-page PDF assembly library land
  with the screen-by-screen frontend wiring already scoped to P2.7 (whose checklist entry
  explicitly lists "CorrectPaper (real SSE upload→correct, kill setTimeout theatre)" as the
  screen that owns this upload flow), with PWA installability/manifest/service-worker polish
  around it staying in P2.9 as already scoped.
- **Why this is a genuinely undecidable fork, not a corner being cut:** building camera-capture
  UI now would require either (a) wiring it against `web/lib/api.ts`, which does not exist yet
  as a real client (P2.6, not done) — meaning the component would ship against a mock and need
  rework once P2.6 lands, or (b) building the API client scaffolding early, out of order,
  duplicating what P2.6 is explicitly scoped to do properly (react-query, typed hooks, auth
  bearer wiring). Both are worse than doing backend Storage now (independently testable, no
  frontend dependency) and the camera UI once P2.6's real client exists to wire it against.
- **Reasoning:** P2.5's backend half is self-contained and matches the existing P2.1/P2.4
  pattern (repo/router/DTO changes with hermetic + live-skip tests) with no cross-phase
  ordering problem. Splitting also keeps each unit small and independently verifiable, per
  MISSION §5's "small, committed, checkpointed units."
- **What "backend-only" means concretely:** `StudentUploadRepository`/`student_upload`
  endpoint/`run()` correction closure move from local-disk paths to a `StorageBackend`
  Protocol (Storage object key stored in `Upload.storage_path`, same column, new semantics);
  teacher.py's own upload usage (mark-scheme uploads in the grading console) is explicitly
  OUT of scope for P2.5 — it stays on local disk since MISSION's P2.5 wording only mentions
  the student self-mark path, and touching it would widen blast radius for no phase-checklist
  benefit. This exclusion is deliberate, not an oversight, and can be revisited if a later
  phase needs teacher uploads on Storage too.
- **Testing reality carried forward, not new:** the local Supabase stack is still down this
  session (root-owned dirs from a prior crashed container, needs sudo — see the recurring
  environment note in STATE.md), and CI's Postgres-only service (`.github/workflows/ci.yml`)
  does not run the Storage API either — this mirrors the EXISTING GoTrue precedent
  (`HttpGoTrueBackend` is only exercised by a live-skip test; hermetic tests use a
  `Protocol`-conforming fake). The new `HttpStorageBackend` follows the identical pattern:
  real HTTP client tested live-only (skips everywhere until Storage is reachable), business
  logic tested via a `FakeStorageBackend` double. Not a new gap — the same one Phase 1 already
  accepted for auth, applied consistently to storage.
- **Blast radius:** `lemely/io/storage.py` (new), `lemely/web/deps.py` (new singleton +
  reset), `lemely/web/routers/student.py` (upload + correct endpoints), `lemely/runtime/
  config.py` (new `StorageSettings`), tests for all of the above. No DB migration (the
  `storage_path` column already exists from P1.3 and is repurposed, not renamed, to avoid an
  unnecessary migration for a semantic-only change).
- **Completion note (same session, resumed on the WIP described above):** the PLAN as recorded
  had `StorageSettings`/`HttpStorageBackend`/`FakeStorageBackend`/`get_storage_backend`
  already implemented and dirty on disk (steps 1–3) — verified correct before trusting (matches
  the recorded design exactly, gates were not yet run). Completed steps 4–6: wired
  `student_upload` to `storage_backend.upload` (object key
  `uploads/{user_id}/{paperId}/{filename}`, `storage_path` now stores that key) and
  `student_correct`'s `run()` closure to `storage_backend.download` into a
  `tempfile.TemporaryDirectory` (not the PLAN's literal `NamedTemporaryFile` — deviation
  explained below). **Deviation from the literal PLAN text:** the PLAN only described
  downloading the scan; it didn't address the optional sibling `mark_scheme.pdf` that
  `student_upload` has always accepted and `resolve_mark_scheme` looks for next to the scan on
  disk. Downloading only the scan would have silently regressed that existing, tested feature
  (a student-supplied mark scheme would stop being found, always falling back to corpus lookup
  or `None`) — not acceptable for a "no behavior change beyond storage location" migration. Added
  `StorageObjectNotFoundError` (moved from being test-local in `tests/storage_fakes.py` into
  `lemely/io/storage.py` so production code and the fake raise the identical type;
  `HttpStorageBackend.download` now raises it on HTTP 404, `ExternalServiceError` on other
  non-2xx) so `run()` can distinguish "no sibling scheme" (expected, silently skipped) from a
  genuine Storage failure, and download the sibling into the same temp directory under the
  original `mark_scheme.pdf` name so `resolve_mark_scheme`'s sibling-file check keeps working
  unchanged. Also added `tests/test_storage_live.py` (live-skip, mirrors `test_auth_live.py`'s
  skip condition) rather than a `httpx.MockTransport` hermetic test for `HttpStorageBackend` —
  the PLAN's step 6 asked to match "whatever pattern test_gotrue.py/similar already uses," but
  no such file/pattern exists: `HttpGoTrueBackend` itself has zero hermetic unit tests, only
  live-skip integration coverage (confirmed via grep). Matched that actual precedent instead of
  the PLAN's untested assumption. Updated `tests/test_student_correct.py`: `client` fixture now
  overrides `get_storage_backend` with one shared `FakeStorageBackend()` instance (a fresh
  instance per lambda call would have broken the upload→correct flow across requests);
  `test_upload_sets_status_and_writes_file` now asserts against the fake store instead of a
  local disk path; added `test_upload_over_size_cap_is_413` for the new `check_upload_cap` call
  site (the equivalent gap already existed pre-P2.5 for `write_upload_capped`, tracked as
  non-blocking debt in STATE.md — this closes it for the new call site only, not retroactively).
  Gates green (see STATE.md Next-action entry for numbers); Postgres-backed tests skip locally
  (Supabase stack still down, same root-owned-dir issue, sudo unavailable in this session too —
  unchanged from the dispatch session, CI unaffected).

### D2.7 — P2.7 result delivery: SSE `complete` frame carries full per-question data; two small additive backend DTO changes precede the frontend wiring

- **What:** Before wiring the student screens, two small additive backend changes:
  1. `PaperHistoryRowDTO` (`lemely/web/schemas_student.py`) gains an `id: str` field — the
     forward-position index into `history.records` (same addressing scheme
     `GET /student/result/{paper_id}` already uses). Populated in `student_subject()`
     (`lemely/web/routers/student.py`) by enumerating `records` *before* reversing for display
     order (the current code does `for record in reversed(records)` with no index tracked).
  2. The `complete`-phase `MARKING_PROGRESS` event published at the end of `student_correct`'s
     `run()` gains a `questions` key: `[question_to_dto(q).model_dump(by_alias=True) for q in
     report.correction.questions]`, reusing the existing `question_to_dto` converter from
     `lemely/web/schemas.py`. Bus event payloads are free-form dicts (no schema), so this is a
     non-breaking additive key.
- **Why:** Two gaps surfaced while planning the frontend wiring, both would have made honest
  wiring impossible without a backend touch: (1) `PaperHistoryRowDTO` had no addressable id, so
  Subject's paper-history table (real, data-backed rows) had nothing to link to a result page
  with — a UI dead end, not a frontend bug. (2) `ResultDTO.theory`/`.integrity` are
  **documented as structurally empty** when served via the index-based
  `GET /student/result/{paper_id}` route (history records persist totals + weak-areas only, not
  per-question theory/mark-points/integrity flags — see that endpoint's docstring). The *only*
  place the full per-question `CorrectionResult` exists is inside `student_correct`'s live SSE
  closure, and it was being discarded after computing scalar totals for the `complete` frame.
  Without forwarding it, the flagship "just corrected a paper, see the real marks/method-marks/
  weaknesses" moment (P2.10's literal E2E acceptance wording) would be unbuildable — the richest
  screen in the product would only ever be able to show structurally-empty theory data.
- **Design:** CorrectPaper consumes the `complete` frame's `questions` (+ existing scalars) and
  assembles a client-side `ResultData`-shaped object, navigating to `/student/result/:paperId`
  via React Router state (`navigate(path, { state })`) rather than triggering a second fetch.
  PaperResult prefers `location.state` when present (the "just corrected" case, full theory/
  integrity) and falls back to `GET /student/result/:paperId` otherwise (browsing an older paper
  from Subject's history table via its new `id` — still honestly structurally-empty for
  theory/integrity, unchanged, already-documented behavior, not a regression). This avoids
  widening `HistoryStoreProtocol`/`DbHistoryStore` to persist and re-serve full per-question
  detail, which is out of scope for a frontend-wiring phase task.
- **Alternatives rejected:** (a) Have `GET /student/result/{id}` return full theory data by
  querying `QuestionResult` rows directly (they exist in Postgres from P2.1) instead of going
  through the reduced `HistoryStoreProtocol` abstraction — rejected as a larger, riskier change
  (bypassing the interim history abstraction entirely) for a phase whose task list says
  "screen-by-screen wiring," not "redesign the result-retrieval data path"; worth revisiting in
  a later phase once `HistoryStoreProtocol` itself is reconsidered. (b) Re-fetch
  `GET /student/subject/{code}` after correction completes and infer the new paper's index —
  rejected: fragile (race with the row actually landing, ordering assumptions) versus the SSE
  frame already holding the exact data needed.
- **Blast radius:** `lemely/web/schemas_student.py` (1 field), `lemely/web/routers/student.py`
  (`student_subject`'s history-row loop + `student_correct`'s `complete` publish call) — both
  additive, no field removed/renamed. Existing tests asserting on `PaperHistoryRowDTO`/the SSE
  `complete` frame shape need their expected-shape assertions extended, not rewritten.

**Addendum (P2.7 step 5 planning) — header fields on the complete frame, and a deliberate
per-question rendering simplification:**

- **Gap found while planning CorrectPaper/PaperResult:** the `complete` frame (as landed in
  step 1) carries only `awarded`/`max_marks`/`grade`/`confidence`/`needs_review`/`questions` —
  no exam metadata (subject/paper/session) and no grade-boundary rail data (`railLeft`/
  `railFoot`/`boundaryYear`), both of which `ResultDTO`'s header needs and both of which
  `GET /student/result/{id}` computes from a `PaperRecord.metadata` that doesn't exist yet at
  SSE-completion time (the record is written *by* `attempt_repo.persist_correction`, from
  inputs the router already has in scope — nothing new to fetch).
- **Decision:** extract a small shared helper, `_result_header_fields(metadata: ExamMetadata,
  awarded: int, maximum: int) -> dict`, computing code/paper/session/boundaryYear/railLeft/
  railFoot exactly as `student_result` already does (same boundary-store call, same format
  strings) — refactor `student_result` to call it too, so the two paths are provably
  consistent rather than duplicated. `student_correct`'s `run()` calls it with
  `mark_scheme.metadata` (the resolved scheme's own metadata — reliable whenever a scheme was
  successfully resolved, unlike the separately-detected `metadata` variable which can be
  `None` when a student supplies their own scheme and Gemini extraction is skipped/unavailable)
  and adds the resulting fields as new top-level SSE kwargs, plus `pct=round(report
  .grade_prediction.percentage)`. `markerLabel`/`summary`/`railNote` are deliberately left
  unpopulated ("") on BOTH paths, matching the existing GET-path convention — this keeps
  fresh-correction and history-browsing visually consistent (no path looks "more narrated"
  than the other) rather than inventing generated copy for one path only.
- **`QuestionResultDTO` gains `topic: str | None`:** `CorrectedQuestion` (core schema) already
  carries `topic`, it just was never surfaced on the DTO. Free, additive, zero new logic —
  add it and populate it in `question_to_dto`.
- **Deliberate scope cut — NOT building `TheoryQuestionDTO`-shaped fresh data:** the mock's
  `TheoryQuestion` shape needs a per-point `text`/`got` breakdown (`MarkPointDTO[]`), which
  requires resolving `matched_point_ids` against the full `MarkScheme`'s `answer_points` per
  question — a real, non-trivial new converter, not a screen-wiring task. Building it now would
  expand this phase task ("wire screens to already-designed DTOs") into "design and implement a
  new per-question-detail data path." Decision: PaperResult's per-question section renders the
  flatter `QuestionResult` list (id/awarded/max/markerSource/confidence/feedback/topic/
  matchedPointIds-as-a-count-not-a-breakdown/reviewReason/flags) directly — a simpler list/row
  layout, not the mock's split MCQ-grid-vs-theory-points-cards UI (which also assumed two
  separate fixed papers via a tab switcher; a real result is one paper, so the tab switcher and
  its `resultP1`/`resultP3`/`mcq`/`dropped`/`theory`/`theoryWeak`/`paperTabs` mock data are
  dropped entirely, not adapted). This is honest given the real data available, and the richer
  per-point UI can be built in a later phase once/if a converter for it is scoped. History-
  browsed results (no `questions` available, GET-only) render the header with an explicit "per-
  question detail is only available right after a paper is corrected" note instead of an empty
  section that looks broken.
- **Blast radius (addendum):** `lemely/web/schemas.py` (1 field), `lemely/web/routers/
  student.py` (new shared helper + both call sites), tests extended for the new frame/DTO
  fields.

### D2.8 — Fix for the long-standing "Supabase stack down" environment blocker (root-owned start-secrets)

- **What:** Every prior session since Phase 1 (many sessions, see STATE.md's repeated
  "environment note" entries) reported `supabase start` failing with
  `EACCES: permission denied, rm '.../supabase/.temp/start-secrets/supabase_db_Lemely'` and
  worked around it by leaving DB-integration tests skipped locally (CI unaffected — it
  provisions Postgres independently). `sudo` is unavailable in every sandbox session tried so
  far (the harness itself denies `sudo` invocations, confirmed again this session — it's not a
  Linux permission issue, the tool call is refused before it reaches the shell).
- **Root cause:** the Supabase CLI stages per-container secret files under
  `supabase/.temp/start-secrets/<container>/` by bind-mounting that host directory into a
  short-lived setup container that runs as root; files/dirs it creates are root-owned on the
  host. On the *next* `supabase start`, the CLI (running as the unprivileged host user) tries to
  `rm -rf` that same directory to re-stage it and fails with EACCES, since deleting requires
  write access to the root-owned directory, not just its parent.
- **Fix (this session):** the sandbox user (`sico`) is a member of the `docker` group, which is
  root-equivalent for file operations reachable via container bind-mounts. Deleting the
  root-owned directory through a throwaway container sidesteps the missing host `sudo` entirely:
  ```
  docker run --rm -v /home/sico/Lemely/supabase/.temp:/mnt alpine rm -rf /mnt/start-secrets
  supabase start
  ```
  This worked cleanly — full stack came up healthy (db/auth/storage/kong/rest/realtime/studio;
  `imgproxy`/`pooler` reported "stopped" by `supabase status` but neither is used by this app,
  not investigated further). `alembic upgrade head` applied 0001->0002->0003 against the live DB
  with no errors.
- **Why this matters / how to apply:** this was blocking more than convenience — P2.10's
  acceptance task requires a live Playwright E2E run against a real backend+DB+Storage+Auth
  stack, which was previously impossible in this environment. Any future session that hits the
  same `EACCES ... start-secrets` error should run the two commands above (adjust the path) BEFORE
  concluding the stack is unusable and falling back to the skip-and-document pattern. If the
  `alpine` image can't be pulled (offline sandbox variant), fall back to any other locally
  cached image capable of `rm -rf` bind-mounted paths — the trick only needs a container with a
  shell and the mount, not `alpine` specifically.
- **Residual risk:** this is a workaround for a CLI bug in how it stages/cleans up secrets, not
  a permanent fix upstream. If the CLI changes its staging layout in a future version, the exact
  directory name may change (`supabase_db_Lemely` is derived from the project's docker-compose
  naming) — the general pattern (bind-mount + rm via docker) still applies, just confirm the
  actual failing path from the CLI's own error message first.

### D2.9 — Two real bugs surfaced by D2.8's live-stack fix, both fixed

The Supabase stack being live for the first time (D2.8) immediately exposed two real
defects that had been invisible for the whole build because the tests that would have
caught them were always skipping.

**Bug 1 — duplicate/mislabeled `low_confidence` review-queue rows.** `AttemptRepository.
persist_correction` (`lemely/db/attempt_repo.py`) queued a `ReviewReason.low_confidence`
row whenever `qr.needs_teacher_review` was true, OR the confidence score was below
threshold. But `apply_integrity_checks` (`lemely/io/integrity.py`, P2.4) also forces
`needs_teacher_review=True` on any plagiarism/AI-detection flag — a case that already gets
its own specific `plagiarism_flag`/`ai_detection_flag` row. A fully-confident (1.0),
in-range question flagged only for plagiarism was getting a THIRD, spurious, mislabeled
`low_confidence` row alongside its correct one. `tests/test_student_correct.py::
test_upload_then_correct_persists_attempt` (real-PG, previously always skipped) caught this
immediately once it could actually run: expected 2 review rows, got 3. A companion test,
`tests/test_attempt_repo.py::test_review_queue_includes_integrity_flag_rows`, had encoded
the BUG as intentional behavior in its own assertion (`reasons == {low_confidence,
plagiarism_flag, ai_detection_flag}`) — both tests were written in the same P2.4 session but
never reconciled against each other, since only the attempt_repo one could ever run
(the student_correct one needs live PG). Fixed: the low_confidence branch now only fires
when the MARKING side (real low confidence, or the D2.4 structural out-of-range/
value-mismatch signal) is why review is needed, not when `needs_teacher_review` was flipped
purely by an integrity flag that already has its own row. Corrected the
`test_attempt_repo.py` assertion (was asserting the bug) and added
`test_review_queue_low_confidence_row_survives_alongside_integrity_flags` to prove a
*genuinely* low-confidence, *also* plagiarism-flagged question still correctly gets both
rows — the fix must not suppress a real low-confidence signal when the two coincide.

**Bug 2 — `HttpStorageBackend.download()` never actually detected a missing object.** The
local/self-hosted Supabase Storage API answers a missing object with HTTP **400** (not 404)
and a body like `{"statusCode": "404", "error": "not_found", "code": "NoSuchKey"}` —
confirmed against the live stack via `curl`. `download()`'s `response.status_code == 404`
check therefore never fired against the real API; every "no such object" case fell through
to the generic `ExternalServiceError` branch instead of `StorageObjectNotFoundError`. This
matters because `student.py`'s `run()` closure (P2.5) relies on catching
`StorageObjectNotFoundError` specifically to distinguish "student didn't supply a mark-scheme
sibling" (expected, handled) from a genuine Storage failure — meaning every paper corrected
WITHOUT a student-supplied scheme would have hit an unhandled `ExternalServiceError` against
a real backend, a P2.5-flagship-feature-breaking bug that no test had ever exercised live.
Fixed: `_is_missing_key()` in `lemely/io/storage.py` inspects the response body's `code`
field (`"NoSuchKey"` specifically, not `"NoSuchBucket"` — a real misconfiguration that should
still surface as `ExternalServiceError`, not be silently treated as "not found"). Added
`tests/test_storage.py` — this class had ZERO hermetic tests before (only the live-skip
test, matching the `HttpGoTrueBackend` precedent), which is exactly how this shipped
unnoticed; 4 new hermetic tests (`httpx.get` monkeypatched to return the exact real response
shapes) pin: the NoSuchKey case, a literal-404 fallback, the NoSuchBucket
non-suppression, and a plain success path.

**Also:** the `uploads` Storage bucket did not exist in a fresh local stack — declared it in
`supabase/config.toml`'s `[storage.buckets.uploads]` for future fresh inits, AND created it
directly via the Storage API this session (`POST /storage/v1/bucket`) since the config.toml
declaration did not retroactively materialize it against the existing initialized volume on
a plain `supabase stop && supabase start` (only appears to apply on first-time volume
creation / `db reset` — not confirmed further, out of scope to dig into the CLI's own
behavior here). A future session hitting "Bucket not found" against an existing volume
should create it via the API the same way rather than assuming the config.toml declaration
alone is sufficient.

**Verification:** full suite green against the live stack (D2.8): 86.38% coverage (up from
81.47% with DB tests skipped — genuine new coverage from tests that can now actually run,
not a regression), 0 failed. `ruff`/`ruff format`/`mypy`/`lint-imports`/`pre-commit
--all-files` all clean.

### D2.13 — `ruff check .`/`ruff format --check .` were silently scanning vendored `.claude/skills/` content; excluded

Building `scripts/check.sh` for P2.5.7 (the Phase-0-mandated "one gate command" that,
per JOURNAL.md 2026-08-04, had never actually been created — a gap carried since Phase 0)
surfaced that plain `ruff check .` from repo root — exactly what `.github/workflows/ci.yml`
runs — reports **329 errors**, 328 of them inside `.claude/skills/ui-ux-pro-max/scripts/`
(a vendored third-party Python search-engine script bundled with the design skill pack,
added whole in d83aa67 "design stack + phase 2.5 build kit"). `pyproject.toml`'s
`[tool.ruff] extend-exclude` had no entry for `.claude`, unlike D2.11's already-documented
fix for `pre-commit run --all-files` doing the same thing to the same directory — the two
gaps were never connected because nobody had run plain `ruff check .` against this branch
since the skill pack landed. **This means CI's `ruff check .` step has very likely been red
on this branch since d83aa67**, independent of anything this session touched; not confirmed
against the actual GitHub Actions run (this sandbox has no path to that), but reproduced
locally with the exact command CI uses.

**Fix:** added `".claude"` to `extend-exclude` alongside the existing
`lemely/db/migrations/versions` entry — same reasoning, vendored/generated content we don't
own and don't want linted, not a project source directory. This is a `pyproject.toml`
config change, so it fixes CI's `ruff check .` step too without touching `ci.yml`.
One real, unrelated finding surviving in `scripts/check_ui_gates.py` itself (a D205
docstring-formatting issue, ruff's own fix) was also cleaned up in the same pass — not
excluded, actually fixed.

**Why this matters / how to apply:** any future session that adds a new top-level vendored
or generated directory (another skill pack, a generated SDK, etc.) should add it to this
same `extend-exclude` list immediately, and should not assume "CI is green" from STATE.md
history without accounting for what's changed on disk since the last time the exact gate
command was actually run — `git log --oneline` showing recent unrelated commits is not
evidence a given check still passes.

### D2.14 — Custom Tailwind utility classes named `text-*` silently break `tailwind-merge`

Discovered during P2.5.8's QUALITY-BAR grep sweep (a `designer` agent's own verification
pass caught it before reporting done — recorded here so no future session repeats it).
Promoting `button.tsx`'s bare `text-[12.5px] font-medium` / `text-[13.5px] font-medium`
size variants to reusable composite classes, the first attempt named them
`.text-button-text-sm` / `.text-button-text-lg` (bundling font-size + weight +
line-height + family, the same pattern already used for `.text-display-md` etc.
elsewhere in `index.css`). This silently broke color: `cn()` (this project's
`clsx` + `tailwind-merge` wrapper) merges `text-accent-on text-button-text-lg` down to
just `text-button-text-lg` — **no color class survives** — because tailwind-merge
recognizes the `text-` prefix and buckets *any* unrecognized suffix into its default
"text color" conflict group, so the later `text-*`-prefixed class always wins and evicts
the real color utility, even though the two classes have nothing to do with each other
semantically. Confirmed empirically: `twMerge('text-accent-on text-button-text-lg')` →
`'text-button-text-lg'`.

This is invisible in isolation (the button still renders, just with browser-default black
text merged away silently — no build error, no lint error, no TypeScript error) and only
surfaced because `npm run audit`'s axe pass caught a genuinely new serious color-contrast
violation on Login's submit button (white-on-dark became near-black-on-dark, 1.3:1) during
the same session that introduced it — if that re-verification step hadn't run, this would
have shipped as a silent, undetected accessibility regression.

**Fix:** renamed to `.btn-text` / `.btn-text-sm` / `.btn-text-lg` — anything NOT prefixed
with a tailwind-merge-recognized group prefix (`text-`, `bg-`, `border-`, `p-`, `m-`, `w-`,
`h-`, `gap-`, `rounded-`, ...) is safe from this class of collision.

**How to apply:** any future custom composite utility class in `index.css` must NOT start
with a string tailwind-merge treats as a real Tailwind prefix unless it IS that exact
utility (e.g. a real color/spacing value) — a font-size-bundling class must not be named
`text-anything`, a spacing-bundling class must not be named `p-anything`/`gap-anything`,
etc. When in doubt, verify empirically before shipping:
`node -e "console.log(require('tailwind-merge').twMerge('<class A> <candidate class>'))"`
from `web/` and confirm both classes survive in the output.

### D4.4 — Syllabus topic taxonomy: transcribed from source, and the write policy that follows from measuring it

**P4.2.** `question_bank.topic` was NULL on all 273 past-paper rows (D4.1 §4 left it
that way deliberately rather than guessing). This is what closed it, and the parts
worth not re-deriving.

**1. The taxonomy is transcribed, not remembered.** The first instinct was to author
the topic lists from model knowledge of the CAIE syllabuses. That would have been
invented precision at the root of the whole phase: CAIE renumbers topics between
syllabus cycles, and every label Phase 4 emits is only meaningful against a stated
version. No syllabus PDF was in the repo or in the PaperScraper corpus (which holds
question papers and mark schemes only), so the three official PDFs were fetched from
cambridgeinternational.org — the same domain Phase 2 already scrapes for grade
boundaries (D2.1), so no new source authorisation was involved — and the topic and
subtopic **codes and names** extracted from their §3 Subject content sections:

| Subject | Syllabus | Structure |
|---|---|---|
| 0625 Physics | 2023–2025 (`595430`) | 6 topics, 21 named subtopics |
| 0580 Mathematics | 2025–2027 (`662466`) | 9 topics, 59 named subtopics |
| 0606 Additional Mathematics | 2025–2027 (`662470`) | 14 topics, **no** named subtopics |

0606's asymmetry is real, not an omission: that syllabus numbers *learning objectives*
under each topic rather than naming subtopics, so the classifier can never emit a 0606
subtopic label. Pinned by `test_0606_is_topic_level_only` so a future session does not
"fix" it by inventing fourteen subtopic names.

The `strong`/`keywords` arrays in `lemely/data/syllabus_topics.json` are **not** from
the syllabus — they are Lemely's authored matching vocabulary, and the file says so in
its own `note` field so the two are never conflated when the file is read back.

**2. Label format is `"<code> <name>"`** — `"4.3 Electric circuits"`, `"14 Calculus"`.
Self-describing in a UI chip, parseable back to a code, sorts in syllabus order, and
hierarchically related to its parent by code prefix. Subject scoping comes from the
row, not the label, so the "Trigonometry" that exists in both 0580 and 0606 is never
ambiguous — every bank query and every weakness report is already per-subject.

**3. Two defects the real corpus found that no synthetic test would have.**
- *Hyphens never matched.* CAIE prints `double-insulated` in one paper and `double
  insulated` in the next. `_normalise` now folds hyphens and all five unicode dashes
  to spaces, on **both** sides — taxonomy terms are normalised by a pydantic validator
  at construction, so the invariant holds for hand-built nodes in tests too.
- *MCQ options carry the signal.* An MCQ stem is deliberately terse ("Which planet is
  classed as a rocky planet?") and the discriminating vocabulary often lives entirely
  in the four options, which `question_bank.mcq_options` already stores (197/273 rows).
  Including them moved coverage **78.8% → 89.4%**. They are part of the question.

**4. Two scoring defects found by writing the tests, fixed in the code not the test.**
- A tie between two subtopics *of the same parent* was being resolved by file order and
  reported as a finding. It now falls through to the topic-level label: right topic,
  undetermined subtopic, which is the true statement. A tie across *different* parents
  still abstains entirely.
- `_band` ignored whether anything else claimed the question. "Define specific heat
  capacity" scores one strong hit and **nothing else in the syllabus scores at all** —
  thin, but uncontested. An uncontested single strong hit is now `medium`; a contested
  one at the same raw score stays `low`. The discriminator is competition, not the
  total, so this is not simply lowering the bar. Verified on the 13 rows it promotes:
  12 correct on inspection.

**5. The write policy — only `high` and `medium` are persisted (the honest bit).**
Measured on the real 273-row 0625 bank: scoring produces a match for **245/273 (89.7%)**,
but a hand-checked orchestrator sample of ~47 classified rows put label accuracy at
roughly 84%, with errors heavily concentrated in the `low` band — which contained
outright nonsense, e.g. a question about alpha, beta and gamma emission from radioactive
nuclei labelled `4.2 Electrical quantities`.

The decisive argument is **not** the error rate. It is that there is nowhere to put the
caveat: `question_bank.topic` is a bare string with no companion confidence column, so a
low-confidence label is indistinguishable downstream from a certain one. Writing it
would launder a guess into apparent fact and silently point a student's practice at the
wrong syllabus material (UI spec §1.4). So `low` is counted and discarded.

**Final measured yield: 211/273 (77.3%) of past-paper rows carry a topic** — 108 high,
103 medium — spanning **29 distinct topics across all six** physics topics. 34 rows were
classified but discarded as low-confidence; 28 had no confident match at all. D3.7's
empty-topic gap is closed. `TopicClassificationReport` keeps those two rejection buckets
separate on purpose: they are different failures, and the 34 is exactly what a future
`topic_confidence` column would reclaim.

**6. Scope boundary — the marking side is NOT wired up, and P4.4 must do it.**
`CorrectedQuestion.topic` comes from `topic_hint` on the parsed mark scheme, which is
`None` on **all 637 questions across all 33** deterministically-parsed 0625 schemes in
`outputs/schemes/` (measured, not assumed). So the weakness engine currently reports no
topics at all for real papers, and **practice-targets-weakness (P4.5) does not join up
until both sides speak this vocabulary.** It was not done here because
`lemely.core.topics` is in `core` and the taxonomy loader is in `io`: `core.correction`
cannot reach it without either a signature change through every marking caller or a
layering violation. The fill belongs at the db/io boundary where a `CorrectionResult` is
persisted and the loader is reachable. P4.4 owns it.

**7. Cost: $0.00.** Deterministic keyword scoring, no Gemini call, no new dependency.
Re-run any time with `lemely question-bank classify-topics [--subject X] [--reclassify]
[--dry-run]`; `--reclassify` is the one to use after editing the vocabulary, and it can
*remove* a label the new vocabulary no longer supports, not only add.

---

## D4.5 — Student profile + onboarding data model, and how target grades activate at-risk rule 2 (P4.3)

**Four additive tables (migration 0009), not one.** D1.2/D1.3's additive-only rule holds:
no existing column is touched.

1. `student_profiles` — one row per student user (`user_id` PK/FK). The whole-person
   facts S-02 collects: qualification level, grade level, school name, external-lessons
   flag, weekly study hours, and `onboarding_completed_at`.
2. `student_subject_enrolments` — one row per (student, subject). Carries the **target
   grade** and the exam session being targeted (S-01). Unique on (`user_id`,
   `subject_code`).
3. `student_enrolment_papers` — the papers a student will actually sit for an enrolment
   (0580 P2 + P4). A separate table rather than an array column so a paper is a row a
   later phase can join practice/plan material against.
4. `student_confidence_ratings` — one row per (enrolment, topic) self-assessment slider,
   keyed on the **P4.2 topic label vocabulary** (`"4.3 Electric circuits"`), so the
   questionnaire, the bank, and the weakness engine speak one language rather than three.

**Everything the spec calls skippable is nullable.** S-02 says "allow *skip for now* on
everything non-essential", and the study plan must be able to say "we do not know your
weekly study time" rather than invent a default that then looks like an answer the
student gave (spec §1.4). A skipped field is `NULL`, never a sentinel or a zero.

**Target grades activate at-risk rule 2 — via a subject-keyed mapping, not a scalar.**
This is the substantive design call. `assess_at_risk` took `target_grade: str | None`,
one grade for a whole student. That is wrong now that targets are real: a target grade is
per *subject*, and `StudentHistory` interleaves subjects. Passing a single grade would
compare a physics paper against a maths target the moment a student enrols in two
subjects — a false at-risk flag on a teacher's dashboard, which is the exact failure
D3.3's tri-state was built to prevent.

So the parameter becomes `targets: Mapping[str, str] | None` (subject code → grade) and
`_check_below_target` resolves the target for the subject of the **latest grade-bearing
record** — the same record the rule already compares. One resolution site, inside the
pure rules engine, so the nine call sites cannot each drift their own way (the D3.5
shared-helper discipline).

**The tri-state gets sharper, not looser.** `NOT_EVALUABLE` now means either "no targets
supplied" *or* "targets supplied but none for this student's subject". Both are honestly
"we did not check", and neither may collapse into `NOT_FIRED`. A student who has enrolled
in physics but set no target there is still not-evaluable, not cleared.

**The T-06 reason filter gains `below_target`** (`web/src/portals/teacher/screens/AtRiskList.tsx`),
whose omission was explicitly conditional on the rule being unfirable. It is firable now.

**Implementation note (added after P4.3 landed).** Two things worth not re-deriving:

- `assess_at_risk`'s `targets` mapping is resolved against the **latest grade-bearing** record,
  not the latest record of any kind. A quiz carries no grade (`docs/quiz-model.md` §5), so it can
  never be the record that decides which subject's target applies.
- The multi-student routes (teacher overview, at-risk list, class detail, parent children) use
  `StudentProfileService.target_grades_for_many`, added for this. Calling the single-student
  `target_grades_for` inside those loops would have made every teacher dashboard N+1 — the
  cheapest possible way to turn a correctness fix into a performance regression.

**Measured, not claimed:** no-targets, empty-mapping and wrong-subject-target all resolve to
`not_evaluable`; a matching subject target 2 grades above the predicted grade `fired`; 1 grade
above `not_fired`. Verified by the orchestrator running the engine directly rather than from the
implementing subagent's report (MISSION §5).

---

## D4.6 — Placement tests reuse the quiz engine: NULL-owner rows, an XOR-checked ownership shape, and a marks-derived duration budget (P4.4)

**The obstruction.** MISSION §4 / STATE's Phase-4 header: *"The placement test and
practice sets are quiz-shaped: reuse that engine, do not fork it."* Two columns block
that literally — `quizzes.teacher_id` NOT NULL and `quiz_assignments.class_id` NOT NULL.
A placement test has neither: it is assembled by the platform and self-assigned by a
student during onboarding (S-03/S-04). Everything downstream of those two columns —
`QuizQuestion`'s frozen snapshot, `QuizSubmission`'s lifecycle, `QuizAnswer`,
`QuizTakingService`, `QuizMarkingService` → `correct_paper` → `summarize_weaknesses` →
`persist_quiz_correction` — is already student-shaped and needs no structural change.

### 1. Schema: relax the two NOT NULLs, add a typed second owner, enforce the shape with XOR CHECKs

**Chosen.** Migration 0010, board-agnostic, no data backfill:

```sql
CREATE TYPE quizkind AS ENUM ('teacher', 'placement', 'practice', 'study_plan');

ALTER TABLE quizzes ALTER COLUMN teacher_id DROP NOT NULL;
ALTER TABLE quizzes ADD COLUMN student_id uuid
    REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE quizzes ADD COLUMN kind quizkind NOT NULL
    DEFAULT 'teacher'::quizkind;              -- D1.3 cast, in model AND migration
ALTER TABLE quizzes ADD CONSTRAINT ck_quizzes_owner_xor
    CHECK ((teacher_id IS NULL) <> (student_id IS NULL));
ALTER TABLE quizzes ADD CONSTRAINT ck_quizzes_kind_owner
    CHECK ((kind = 'teacher') = (teacher_id IS NOT NULL));
CREATE INDEX ix_quizzes_student_kind ON quizzes (student_id, kind, created_at DESC);

ALTER TABLE quiz_assignments ALTER COLUMN class_id DROP NOT NULL;
ALTER TABLE quiz_assignments ADD COLUMN student_id uuid
    REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE quiz_assignments ADD CONSTRAINT ck_quiz_assignments_target_xor
    CHECK ((class_id IS NULL) <> (student_id IS NULL));
CREATE UNIQUE INDEX uq_quiz_assignments_student
    ON quiz_assignments (quiz_id, student_id) WHERE student_id IS NOT NULL;
CREATE INDEX ix_quiz_assignments_student ON quiz_assignments (student_id, assigned_at DESC);
```

Nothing else changes. `assigned_by` stays NOT NULL and holds the student's own id for a
self-assignment — "who assigned this" is answered truthfully, not with a sentinel.
`time_limit_minutes` stays NULL for placement (see §4). `quizzes.school_id` stays NULL
for placement: a placement result is a personal baseline, not school analytics material,
and adding it later is additive if a school_admin surface ever wants it.

**Two owner columns rather than one polymorphic `owner_id` + `owner_type`.** A
polymorphic id cannot carry a foreign key, so it cannot carry `ON DELETE CASCADE`
either — deleting a student would leave orphaned quizzes holding their answers. Two
typed FKs plus an XOR CHECK is the boring, referentially-correct version of the same
idea, and it makes "exactly one owner, always" a database invariant instead of a
convention.

**Rejected (b), the `self_assessments` side-table.** It was rejected on its own terms,
before the synthetic-user problem: without a fake `users` row there is no legal value
for `quizzes.teacher_id`, so (b) *cannot* be built without exactly the sentinel D4.5
refused. Even granting a way around it, it splits "who owns this attempt" across two
tables, so every ownership check becomes a join that a future caller can forget — the
opposite of the fail-closed property §2 buys.

**Rejected (c), the full fork.** Duplicates take/resume/autosave/submit/mark, and with
it the answer-leak discipline `QuizTakeQuestionRow` encodes (D3.8 — `model_answer`,
`mark_scheme_points`, `mcq_answer` are excluded *structurally*). A second copy is a
second place to get that wrong. MISSION forbids it, and MISSION is right.

**Rejected (d), a `quiz_owners` join table.** Correct and general; buys nothing three
kinds of owner do not, and makes the common teacher query a join.

### 2. The additive-only rule is amended here, deliberately

D1.2 promised Phases 2–5 need only additive migrations. Two `DROP NOT NULL`s break the
letter of that. **The amended rule, which future phases follow:**

> Migrations may add columns, add ENUM values, add indexes/constraints, and **relax a
> constraint** (`DROP NOT NULL`, widening a CHECK). They may not drop or rename a
> column, narrow a type, or tighten a constraint on a populated table without an
> explicit decision entry.

The justification is that a relaxation is exactly as reversible as an addition and
strictly safer than the alternative: `DROP NOT NULL` rewrites no rows, takes a brief
`ACCESS EXCLUSIVE` lock on catalog only, breaks no existing reader (every current row
still satisfies the old constraint), and is undone by `SET NOT NULL` as long as no NULL
row has been written. The intent D1.2 was actually protecting — "no migration rewrites
or invalidates existing data" — is fully preserved. What it costs: `alembic check` drift
discipline (D1.3) now has to cover nullability as well as defaults, and the down-migration
is only valid before the first placement row exists, which is why 0010 must ship *before*
any placement route does.

### 3. How the discriminator propagates — ownership is the filter, `kind` is only a label

**The rule.** *A query is scoped by an owner/target predicate, never by `kind`.* Teacher
surfaces scope on `teacher_id = :caller`; class surfaces scope on `class_id IN
(:enrolled)`; student-owned surfaces scope on `student_id = :caller`. `kind` may only
*narrow* a query that is already owner-scoped ("list my practice sets"), and must be used
as a positive allowlist (`kind IN (...)`) — never `kind != 'teacher'`, which fails open
the day a fifth kind is added.

**This fails closed with no code change at six of the eight enumerated sites,** because
SQL three-valued logic already excludes a NULL owner from an equality or `IN`:

| Site | Predicate | Effect on a placement row |
|---|---|---|
| `lemely/db/quiz_repo.py:254` (`list_quizzes`) | `Quiz.teacher_id == teacher_uuid` | NULL ≠ uuid → excluded. **No change.** |
| `lemely/db/quiz_repo.py:756` (`_load_owned`, ORM-side `quiz.teacher_id != teacher_uuid`) — gates `get_quiz`:268, `patch_draft`:316, `set_status`:354, `generate_questions`:404, `remove_question`:471, `create_assignment`:587, `list_assignments`:676, `delete_assignment`:737 | `None != uuid` → True | raises `QuizOwnershipError` (403). **No change.** |
| `lemely/db/quiz_repo.py:612` (assignment uniqueness) | `quiz_id AND class_id ==` | teacher path only. **No change.** |
| `lemely/db/quiz_results_repo.py:228` (`assignment_results`) | delegates to `get_quiz(teacher_id, …)` | 403 before any read. **No change.** |
| `lemely/db/quiz_taking_repo.py:232-241` (`list_assigned`) | `QuizAssignment.class_id.in_(class_ids)` | `NULL IN (…)` → NULL → excluded. **No change in P4.4** — which is exactly right: a placement test is not "an assigned quiz" in S-25/S-26. P4.5/P4.7 add a second, explicitly `kind`-allowlisted branch for practice/study-plan sets. |
| `lemely/db/quiz_marking_repo.py:220,230` | keyed on `submission_id`/`quiz_id` only | no tenancy predicate to get wrong; reached only via a submission the taking service already authorised. **No change.** |

**Two sites genuinely change**, both in `lemely/db/quiz_taking_repo.py`:

- `_load_enrolled`:524 — see §4 below; renamed `_load_permitted`.
- `get_take`:293-296 — `session.get(SchoolClass, assignment.class_id)` and
  `session.get(User, quiz.teacher_id)` are called with what is now possibly `None`, which
  raises inside SQLAlchemy. Both become conditional, and `QuizTakeHeader.class_name` /
  `.teacher_name` (and the same two fields on `AssignedQuizRow`) become `str | None`.
  A placement test has no teacher and no class; S-04 must render that absence, not the
  empty string that `_display_name` currently returns for a missing user.

**Do not add `AttemptOrigin.placement`.** A placement mark is persisted by
`persist_quiz_correction` as `origin=quiz`, unchanged. `lemely/db/review_repo.py:540`
tests `attempt.origin != AttemptOrigin.quiz` — negative polarity — so a new member would
fail *open* there and let the first teacher override on a placement attempt invent a grade
the marking path deliberately never wrote, which is the precise failure that guard exists
to prevent. (`lemely/core/history.py:69` `is_grade_bearing` is positive-polarity and would
have been safe; the codebase is mixed, so the safe move is to add no member.) "This attempt
was a placement test" is recoverable exactly where it belongs:
`quiz_submissions.attempt_id → quiz_assignments → quizzes.kind = 'placement'`.

### 4. RBAC: the ownership predicate for a class-less assignment

`QuizTakingService._load_enrolled` currently 403s any assignment whose `class_id` is not
in the caller's enrolled set — so a placement assignment (`class_id IS NULL`) is
un-takeable today. Replace it with a two-branch predicate selected by *which target
column is populated*, which the XOR CHECK guarantees is exactly one:

```python
def _load_permitted(self, session, student_uuid, assignment_uuid) -> QuizAssignment:
    assignment = session.get(QuizAssignment, assignment_uuid)
    if assignment is None:
        raise QuizTakingNotFoundError(f"Unknown assignment: {assignment_uuid}")
    if assignment.student_id is not None:            # direct-to-student
        if assignment.student_id != student_uuid:
            raise QuizTakingOwnershipError(...)
        return assignment
    if assignment.class_id in self._class_service.enrolled_class_ids(student_uuid):
        return assignment                            # class-enrolled
    raise QuizTakingOwnershipError(...)
```

Fail-closed by construction: there are exactly two `return` statements, one guarded by an
equality on `student_id` and one by membership in `class_id`, and no trailing
`return assignment`. Student B opening student A's placement test hits the first branch's
inequality → 403; the D3.4 403-vs-404 split is preserved unchanged (an id that exists
anywhere is a 403, not a 404 — the same accepted existence-oracle trade-off). Every other
method (`get_take`, `save_answer`, `submit`) already calls this one helper first, so the
authorisation change lands in one place. All three keep their existing role gate:
`lemely/web/routers/quiz.py:115` already mounts `/api/student/quizzes` behind
`require_role(Role.student)`.

**Take/save/submit endpoints are reused verbatim** — `/api/student/quizzes/{assignment_id}`
and its `PUT .../answers/{ref}` and `POST .../submit`. That reuse *is* the "do not fork"
payoff, and it is what makes S-04's "connection lost mid-test, answers must survive" free:
the autosave and lazy-submission machinery is the one that has already been tested.
Placement adds only three new routes, all thin:

- `GET  /api/student/placement/{subject_code}/availability` → `{available, reason, topicCount, questionCount, estimatedMinutes}` (S-03).
- `POST /api/student/placement` `{subjectCode}` → 201 `{assignmentId, quizId, questionCount, topicCount, estimatedMinutes}`; **409** carrying the same availability payload when unavailable.
- `GET  /api/student/placement/{assignment_id}/result` → S-05 (§6).

Retake = a new `quizzes` row with a fresh sample, never a mutation of the old one — the
same "an assigned quiz is duplicated, never edited" rule the teacher builder already
follows. Assembly excludes `question_bank_id`s used by this student's prior placement
quizzes for the same subject where the pool allows it.

### 5. The ~15-minute rule: duration is derived from marks and a *transcribed* paper rate, and there is no new column

There is no per-question duration anywhere in the schema, and there will not be one.
A nullable `question_bank.estimated_minutes` was rejected because nothing could populate
it except a guess — it moves the invented number into a column where it acquires the
authority of a fact, the exact laundering D4.4 §5 refused for low-confidence topics.

**Chosen: a marks-based proxy with a per-paper rate transcribed from source.** New data
file `lemely/data/paper_timing.json`, keyed `(board, subject_code, paper_number)` →
`{duration_minutes, total_marks, source}`, transcribed from the **Assessment overview**
section of the same three syllabus PDFs D4.4 already fetched (each entry's `source` names
the syllabus document number and cycle, as `syllabus_topics.json` does). The rate is then
`duration_minutes / total_marks`, **computed, never hardcoded**, and a question's estimate
is `question_bank.total_marks × rate(its paper)` — resolved via
`question_bank.paper_id → papers.paper_number/subject_code`, both of which already exist
and are NOT NULL. P4.4's implementer transcribes these numbers from the PDF; **no
marks-per-minute figure may be written from memory.** A question whose paper has no
timing entry, or no `paper_id` at all, is ineligible for placement — not estimated by a
subject average, which would be a guess wearing a measurement's clothes.

**Budget:** target 15 min, accept 12–18 (±20%). Greedy fill; stop when the next question
would exceed 18. `quizzes.time_limit_minutes` is left **NULL** — S-03 promises "~15
minutes", an estimate, and S-04 shows *elapsed* time; a hard cutoff on a baseline test is
churn at the highest-churn moment in the product (S-05's own framing). The displayed
estimate is recomputed on read from the frozen `quiz_questions.total_marks`, so it stays
true if a question is ever removed, and costs no column.

**Topic spread.** Only questions with a non-NULL `topic` are eligible — an untopiced
question cannot contribute to a topic-keyed weakness profile, which is the entire point of
the test (this is what makes 62 of the 0625 bank's 273 rows ineligible). Breadth first:
one question per distinct syllabus topic, in syllabus-code order, across the topics of the
papers the student's `student_enrolment_papers` rows say they will sit; then a second pass
adding a second question per topic until the budget fills. Difficulty comes from the
existing `QuestionBankService.count_by_band`/`select_questions` band filter, preferring a
mix.

**Viability floor and the honest "not available" path.** Assembly succeeds only if the
selected set reaches **≥4 distinct topics, ≥6 questions, and ≥12 estimated minutes**.
Otherwise the API returns unavailable with a machine-readable `reason`
(`no_questions` / `insufficient_topics` / `insufficient_duration`) and S-03 says so plainly
per subject — never a silently short test, never a padded one (spec §1.4). **Today this
means placement is available for 0625 only** (211 topiced rows spanning 29 distinct labels
across all six topics) and unavailable for **0580 and 0606**, which have no ingested
questions at all. That is the correct behaviour, not a gap to code around: onboarding must
route those students straight to S-06 with the questionnaire-derived plan, and the
availability endpoint is what makes the day the maths corpus lands a data change rather
than a code change. **S-05's working-level estimate is shown only if the assembled set
spans ≥2 difficulty bands**; otherwise S-05 shows strongest/weakest topics and states that
the sample was too narrow to estimate a level.

### 6. Weakness-profile initialisation adds no persistence at all

Marking a placement submission already runs `summarize_weaknesses` and writes
`WeaknessRecord` rows through `AttemptRepository._persist` — and the topic vocabulary
already joins up end to end: `_snapshot_bank_row` freezes `question_bank.topic` onto
`quiz_questions.topic`, and `quiz_question_to_scheme_question`
(`lemely/db/quiz_marking_repo.py:382`) already passes `topic_hint=qq.topic` into the
marking engine. So a placement test marked today produces real topic weaknesses keyed on
the P4.2 label vocabulary, with no new code on the marking side. (D4.4 §6's gap is the
*past-paper* path, whose `topic_hint` is None on all 637 parsed 0625 questions; it is
unrelated to this one and still open.)

Therefore: **no `placement_results` table, no `student_weakness_profile` table.** The
placement result *is* `quiz_submissions.attempt_id` plus that attempt's `WeaknessRecord`
rows, reached by the join in §3. S-05 reads them; the study plan (P4.7) reads them; a
second copy could only drift from the first.

`PlacementResult` in `lemely/core/study.py` — `subject_code` + `WeaknessReport`, called by
nothing — is deleted by P4.4. Both its fields are already persisted (`quizzes.subject_code`,
`weakness_records`); keeping it would leave a second, unwritten definition of what a
placement result is.

### 7. Testability

- **Schema:** insert a placement quiz with both owners set, and one with neither, and
  assert both raise `IntegrityError` on `ck_quizzes_owner_xor`; same for
  `ck_quiz_assignments_target_xor`. Assert `kind='placement'` with a non-NULL `teacher_id`
  is rejected by `ck_quizzes_kind_owner`.
- **Fail-closed regression (the one that matters):** with a placement quiz and a placement
  assignment in the DB for student A, assert `QuizService.list_quizzes(teacher)` omits it,
  `get_quiz(teacher, quiz_id)` 403s, and `QuizTakingService.list_assigned(A)` omits it.
  These are the assertions that catch a future refactor swapping an owner predicate for a
  `kind` one.
- **Cross-tenant:** student B calling every one of the four take/save/submit/result routes
  against A's placement `assignment_id` → 403, no body leakage.
- **Assembly:** unit-test the budget/spread selector against a synthetic bank; separately
  run it against the real 0625 bank and assert it yields ≥4 topics and 12–18 minutes, and
  against 0580 and assert `available=false, reason="no_questions"`.
- **Duration:** assert `paper_timing.json` covers every `(subject_code, paper_number)`
  present in `papers` for any subject the availability endpoint reports available, so a
  new ingest cannot silently make questions ineligible.
- **Marking:** end-to-end placement → `attempts.origin == quiz`, `grade IS NULL`,
  `predicted_grade IS NULL`, and ≥1 `WeaknessRecord` whose topic is a P4.2 label.
- **`alembic check`** reports no drift after 0010 (D1.3), including the new nullability.

---

## D4.8 — Placement assembly: paper links were missing, and breadth was counting subtopics as topics (P4.4 chunk B)

D4.6 §5 designed the marks-derived duration budget on paper. Building it surfaced
three things that only a measurement against the real bank could have found. All
three are recorded here because each cost real work and none is re-derivable from
reading the code.

### 1. `question_bank.paper_id` was NULL on every banked question, and `papers` was empty

D4.6 §5 says the rate is "resolved via `question_bank.paper_id →
papers.paper_number/subject_code`, both of which already exist and are NOT NULL".
The `papers` *columns* exist and are NOT NULL. The **link** did not: P4.1 banked
273 real past-paper questions with `paper_id IS NULL` on all of them — its own
module docstring records that it "does not create `Paper` rows" — and both
`papers` and `subjects` were empty tables. Nothing had needed the link before,
because nothing before placement resolved a bank row back to its paper.

The consequence was total, not marginal: with no paper, no timing; with no
timing, ineligible; so the first honest run of the assembler returned
`no_eligible_questions` for **0625 as well as** 0580/0606. Had this not been
measured, "placement is unavailable for every subject" would have looked exactly
like the expected 0580/0606 corpus gap.

**Fix: `QuestionBankService.link_past_paper_rows` + `lemely question-bank
link-papers`.** The paper identity is *parsed*, never inferred: P4.1 already
builds `source_question_id` as `f"{qp_stem}#{ref}"`, so `"0625_s23_qp_11#22"`
carries the source PDF's filename, and the same
`parse_caie_qp_filename_metadata` the ingest used reads it back. A stem that does
not parse is counted and left unlinked rather than attached to a guessed paper.
The `subjects` row the FK requires is created with the **transcribed**
`subject_name` from the bundled taxonomy; a subject with no bundled syllabus is
skipped rather than given an invented display name to satisfy a foreign key.
`PaperLinkOutcome` is shaped so `considered == linked + unparseable +
no_subject_taxonomy`, because a backfill that silently drops rows is the failure
mode worth designing against.

**Measured: 273 considered → 273 linked, 26 `papers` rows, 1 `subjects` row, 0
unparseable, 0 skipped.** Re-run considers 0 (idempotent — only NULL rows are
looked at). Dry run creates nothing.

### 2. Breadth was counting subtopics as topics, and the count was a lie

D4.2's classifier writes whichever level it matched, so the bank holds a mix of
top-level labels (`"3 Waves"`) and subtopic labels (`"1.2 Motion"`). Treating
those as peers, the first successful assembly reported **"13 topics"** for a set
in which **nine of the 13 questions sat under physics topic 1**. The number was
broad; the test was not. A weakness profile built from it would have been a
profile of one corner of the syllabus wearing a whole-subject label — the same
invented-precision failure UI spec §1.4 forbids, arriving through a counter
rather than through a value.

**Chosen:** breadth is measured on the top-level code (`_syllabus_group`: the
part before the first `.`), depth on the full label. The round-robin is now two
levels — across top-level topics on the outer loop, across that topic's subtopics
on the inner — and `Assembly` carries `syllabus_topic_count` as a field distinct
from `len(topics)`, with both documented, so a caller cannot pick up the
flattering number by accident. `MIN_TOPICS` now means four *syllabus topics*.

**Rejected: normalising the bank's labels to top-level.** It throws away real
information the classifier earned, and subtopic labels are what
`student_confidence_ratings` (D4.5) is already keyed on.

### 3. The greedy fill refused sets it could have completed

Filling stopped the moment `spent >= target_minutes`, which on a mark-heavy pool
left the set below `MIN_QUESTIONS` and then refused it — when one more question
inside the existing 18-minute tolerance would have made it viable. The fill now
continues past the target, bounded by `max_minutes`, while questions are still
owed. It is still a refusal when the extra question does not fit: the tolerance
is a tolerance, not a licence to overrun.

### The measurement that stands (do not re-derive)

After all three: **0625 assembles 9 questions, 15.2 estimated minutes, all six
physics topics, two difficulty bands.** 0580 and 0606 return `no_questions` —
correct and required behaviour per D4.6 §5, not a gap to code around. Practical
papers (0625 Paper 5/6) are excluded from placement by default: their questions
assume apparatus, so a practical question in an at-home 15-minute test measures
whether the student owns a ripple tank. Their timings are still transcribed and
reachable — this is assembly policy, not a claim the data is wrong.

$0.00 Gemini, zero LLM calls: every step here is deterministic.

---

## D4.9 — Placement narrows to the papers the student will sit; the empty case is "not answered", not "sits nothing" (P4.4 chunk B-4)

Chunk B-4 landed `PlacementService` (availability / create / result) and the three
S-03/S-04/S-05 routes over the already-measured assembler. Everything in D4.6 §1/§3/§4/§6
was implemented as designed and needs no new decision. One clause of D4.6 §5 was **not**
implemented in the first pass, and the omission is worth recording because it is invisible
from the code and would have silently biased every downstream artefact.

### What was missed

D4.6 §5: selection runs *"across the topics of the papers the student's
`student_enrolment_papers` rows say they will sit"*. The first implementation loaded every
`source='past_paper'` bank row for the subject and every transcribed timing for it, with no
reference to the student's enrolment at all.

**Why that is not cosmetic.** 0625 is tiered: Core is papers 1/3, Extended 2/4. A Core
student assembled against Extended questions is measured on material they will never sit,
so every topic that sample touches reports a weakness the student does not have — and
P4.7's adaptive study plan is built out of exactly those `WeaknessRecord` rows. The error
would have compounded into the plan rather than staying visible at the placement screen.
Nothing in the test suite would have caught it: the seeded bank is single-paper, so the
narrowing is unobservable unless a test deliberately enrols the student elsewhere.

### The fix, and where it is applied

`PlacementService._timings_for` narrows the **timings mapping**, not the candidate list.
A paper the student will not sit therefore has no rate, and a candidate with no rate is
*already* ineligible in `core.placement.assemble` — so eligibility keeps having exactly
one deciding site (D4.8's design property), and the reported reason stays
`no_eligible_questions` rather than a fourth bespoke one.

### The judgment call: a student with no enrolment-paper rows is not narrowed

D4.6 §5 does not say what to do when the student has no rows, and this is the branch that
matters in practice, because **every S-02 field is skippable (D4.5)**. Empty means *"not
answered"*, never *"sits no papers"*. Treating it as an empty allowlist would deny
placement to every student who skipped one onboarding question, while reporting
`no_eligible_questions` — a defaulted answer wearing a filter's clothes, which is the
laundering D4.4 §5 and D4.8 §2 both already refused in other forms. So: **rows present →
narrow; no rows → no restriction.**

Pinned by four tests, each verified by its inverse rather than asserted one-way: the same
Paper-4 bank is unavailable to a P1/P3 student, available to a P4 student, available to a
student with an enrolment but no papers, and student B's Core enrolment cannot deny
student A (the lookup is owner-scoped).

### Measured, not assumed

Run against the **live local bank**, not a fixture, and matching D4.8's standing figure
exactly: 0625 → `available=True`, 9 questions, **6 syllabus topics**, 15.19 minutes;
0580 and 0606 → `available=False, reason="no_questions"`. The `topic_count` of 6 is
`Assembly.syllabus_topic_count`; `len(topics)` for the same set is ~13, which is the
overstatement D4.8 §2 exists to prevent — the wire payload carries the honest number.

**Gates:** all 13 green, 0 skipped. **2121 tests / 6 skipped / 0 failed**, coverage
**89.68%** (P4.3 baseline 89.57%). `$0.00` Gemini, zero LLM calls — every path here is
deterministic, and the end-to-end marking test uses a Gemini stub that raises if called.

### One deviation from the brief, accepted

`test_placement_repo.py` exercises availability against a **seeded** 0625-shaped bank
rather than the ingested corpus, so the suite does not depend on 273 banked rows existing
in a fresh checkout. The real-corpus measurement above was made by the orchestrator
directly and is recorded here instead of being encoded as a test that would fail on a
clean clone.

---

## D4.10 — Practice sets: the honest-shortfall path is the normal path, and `list_assigned` grows a positive allowlist (P4.5)

P4.5 built the practice generator as the third consumer of the quiz engine, after the
teacher builder (P3.5) and placement (P4.4). No migration: migration 0010 already shipped
`quizkind` with all four members, so `kind=practice` needed only code. `$0.00` Gemini —
selection from an existing bank is deterministic throughout.

### 1. Availability is tri-state, not binary, because a short set is not a failed set

Placement's viability floor is a genuine floor: a four-topic, twelve-minute minimum exists
because a narrower sample cannot support a weakness profile (D4.6 §5). **Practice has no
such floor.** A student who asks for 20 questions on one subtopic and can be given 7 has
been served, not failed — refusing would be the product withholding material it holds.

So `PracticePreview.available` is `True` whenever `create` would succeed *at all*,
including the shortfall case, and the shortfall carries its own reason
(`insufficient_pool`) alongside the true `available_count`. `available=False` is reserved
for the two genuine refusals: `no_questions` (nothing for this subject) and
`no_weaknesses` (weak-topic mode with no `WeaknessRecord` rows to target).

**The set is never padded and never silently shortened.** The returned count is what the
bank actually holds after filtering, and the reason says so — the S-20 form is kept honest
before the student commits rather than after (spec §1.4). Given the corpus, this is the
*normal* path, not an edge case: 0580 and 0606 refuse outright, and any topic-narrowed
0625 request is a shortfall long before it is a full set.

### 2. Weak-topic targeting reads `WeaknessRecord`; it does not re-derive weakness

MISSION §4 makes "generated practice demonstrably targets seeded weaknesses" a Phase-4
acceptance criterion, so the mode has to be real rather than present. The topic filter is
derived from the caller's own `WeaknessRecord` rows for the subject, in P4.2's
`"<code> <name>"` vocabulary — the vocabulary D4.7 made real on the marking side, which is
what makes the join work at all. A second weakness computation here would be a second
definition that could drift from the first.

A topic with zero net lost marks is not a weakness (mirroring `group_weak_areas`), and is
excluded — pinned by its own test, because "targeting" that included a perfectly-answered
topic would be targeting in name only.

### 3. `list_assigned` — the site D4.6 §3 deferred, and the shape it had to take

D4.6 §3 named `quiz_taking_repo.list_assigned` as the one place P4.5 must change: a
practice set is `class_id IS NULL`, so `class_id IN (:enrolled)` excluded it by SQL
three-valued logic and it was invisible in S-25/S-26.

**Chosen: two independently owner-scoped queries, unioned and re-sorted** — the class
branch unchanged, plus a new branch scoped by `QuizAssignment.student_id == caller` and
narrowed by a **positive** `kind IN (practice, study_plan)` allowlist
(`_STUDENT_ASSIGNED_KINDS`).

**Never `kind != 'teacher'`.** That form is one character shorter and fails open the day a
fifth kind is added — and it would *already* be wrong today, because it would surface
placement tests in the assigned-work list. `placement` is deliberately absent from the
allowlist: a placement test is governed by its own S-03/S-04/S-05 flow.
`test_a_placement_quiz_is_not_an_assigned_quiz` (written in chunk B-1, before practice
existed) still passes unmodified, which is the regression that matters.

### 4. The export/print payload excludes marking material structurally

S-21's printable set reuses D3.8's discipline: `model_answer`, `mark_scheme_points` and
`mcq_answer` are absent from the export dataclass itself, not omitted by a caller that
remembers to. A test asserts the *dataclass field set*, not just one response body, so a
future field addition cannot leak an answer key by being added in the obvious place.

### 5. D4.9's enrolment lesson generalised

`_load_enrolled_paper_numbers` moved out of `placement_repo` into
`student_profile_repo.enrolled_paper_numbers`, shared by both services: narrow to the
papers `student_enrolment_papers` names when rows exist, do not narrow when they do not.
Mirrored by the same four inverse-verified tests D4.9 introduced.

### Measured against the live bank (do not re-derive)

| Request | Result |
|---|---|
| 0625, count 20, no filters | `available=True`, 273 available |
| 0580 / 0606, count 20 | `available=False`, `no_questions`, 0 available |
| 0625, count 5, topic `"4.3 Electric circuits"` | `available=True`, 10 available |
| 0625, count 5, `weak_topics_only` (no weakness rows) | `available=False`, `no_weaknesses` |

Note the pool for unfiltered practice is **273**, not the 211 topic-labelled rows placement
is restricted to: an untopiced question is unusable for a weakness *profile* but perfectly
good practice *material*. The two services filter differently on purpose.

**Gates:** all 13 green, 0 skipped. **2153 tests / 6 skipped / 0 failed**, coverage
**89.81%** (P4.4 baseline 89.68%).

**Process note.** The implementing subagent reported done with `ruff format` failing on two
of its own files; the orchestrator's own gate run caught it. MISSION §5's "verify their
output yourself — never trust a subagent's claim of success" earned its place again.

---

## D4.11 — Flashcards: an AI card stays an AI card, a private deck denies its own existence, and "nothing due" is a state with information in it (P4.6 chunks B/C)

Closes P4.6. Chunk A (migration 0011 + the pure clock-injected SM-2 scheduler) is recorded
in STATE; this covers the service, the AI generator, and the routes.

### 1. Three honesty rules, and where each is actually enforced

The chunk plan named three non-negotiables. Stating them in a docstring is not enforcement,
so each lives in a place where violating it requires a deliberate, visible act:

1. **An AI card stays distinguishable for its whole life.** `edit_card` has **no `source`
   parameter** — not a validated one, not an ignored one. There is no code path that
   relabels. On the wire this is stronger still: `ApiModel` is `extra="forbid"`, so a
   `PATCH` body carrying `"source": "manual"` is a **422**, not a body the server quietly
   drops. A test pins both halves, because "silently ignored" and "rejected" look identical
   to a passing assertion that only checks the stored value.
   `CardDTO.source` is also on the wire for every read: the rule is worth nothing if the
   screen rendering the card cannot tell which kind it is.
2. **A weakness deck records the topic it targeted.** `origin='weakness'` resolves the
   student's own top net-lost-marks `WeaknessRecord` topic (ties broken alphabetically, so
   the choice is deterministic rather than whatever the query planner returned) and
   **rejects a caller-supplied topic** rather than ignoring it — accepting one would let a
   caller label a deck with a topic the weakness engine never flagged, which is the same
   laundering D4.4 refused when it discarded the 34 `low`-band classifications.
3. **No weakness rows is an honest refusal.** `no_weaknesses`, reusing **P4.5's exact
   string** so practice and flashcards speak one machine-readable vocabulary rather than two
   a frontend would have to reconcile. Verified there is no husk deck left behind.
   Generation reports `generatedCount` beside `requestedCount` and never pads a short model
   response.

### 2. Another student's deck id is a 404, not a 403 — a deliberate divergence from P4.5

`practice.py` renders someone else's practice assignment as **403**. This router renders
someone else's deck as **404**, identical in body to an id that never existed.

The service still raises two distinct typed errors (`FlashcardNotFoundError` vs
`FlashcardOwnershipError`) and both are still tested — only the HTTP rendering is flattened.
The reason for the divergence is what the object *is*: a practice assignment is quiz-shaped
and a teacher may legitimately hold a reference to one, so 403 is informative. A deck exists
for exactly one owner, so a 403 answers "does this id exist?" for anyone willing to
enumerate — an existence oracle over another student's private study material, bought for
nothing. The test asserts the real deck id and a random UUID return **byte-identical**
bodies, and inverts it (the owner still gets 200) so the 404 is proven to be about identity
rather than absence.

### 3. `due_session` exists because an empty list is not a state

The chunk plan required S-22's "nothing due today" to carry the next due date. `list_due_cards`
could only return a list, so a new `due_session` returns `cards` + `total_due` + `next_due_at`.
Two things it deliberately does **not** do:

- `total_due` is the **real backlog, unaffected by `limit`** — a capped session reporting its
  own cap as the whole backlog is invented precision (spec §1.4), and pinned by a test that
  requests 2 of 4.
- `next_due_at` is `None` when the student owns no cards *or* when everything they own is
  already due. The second case is not a gap: `cards` is non-empty there, so the screen has
  something better to say than a date.

### 4. `delete_deck` was missing from the chunk-B handover

`generate_deck` can put a deck a student never asked for in front of them. Without deck
deletion the only remedy was deleting cards one at a time and keeping the empty husk. Added,
with the cascade proven at **both** levels (ORM `delete-orphan` and DB `ON DELETE CASCADE`)
by asserting the card row is actually gone — an ownership check that passes while orphan
rows survive is a leak, not a delete.

### 5. Two unguarded inputs the orchestrator's own read caught, not the subagent's report

Both were on the wire in the chunk-C handover, both reachable by any authenticated student,
and neither was covered by the 20 route tests:

1. **`GET /due?limit=-1` was a 500.** `limit` reached SQL as a bare `LIMIT` and Postgres
   rejects a negative one with an error. Now `Query(ge=1)`, so a plainly malformed request
   is a 422 at the boundary.
2. **`POST /decks/generate` took an unbounded `count`** and passed it straight to
   `FlashcardGenerator.generate` — the size of a **billed** Gemini request, against
   MISSION §8's hard $8 ceiling, chosen by the caller with no cap anywhere downstream.
   Now `Field(ge=1, le=50)`. The 50 is a deck-sized ceiling, not a spend calculation; the
   point is that an arbitrary caller-supplied number cannot reach the model at all.

The `count` test asserts on the **generator mock**, not only the status code — a 422 that
still called the model would have spent real money before rejecting the request, and a
status-code-only assertion cannot tell those apart. Both tests carry their inverse
(`count=50` → 201 and the generator *is* called; `limit=1` → 200).

### 6. Process

The chunk-B implementation was found **already on disk, uncommitted**, from a session that
died mid-task. Its tests passed and `ruff` was **red on 8 findings** — the identical pattern
P4.5 hit one task earlier. The handover's word is not evidence; the orchestrator's own gate
run is. Worth repeating because the failure mode is silent: a killed session leaves work that
*looks* finished.

Gemini spend for the whole task: **$0.00** — the generator is mocked in every test and no
live call was made.

## D4.12 — The study plan schedules the week it claims to schedule, and refuses honestly when it has no signal (P4.7 chunk A)

### 1. What the old scheduler actually was

`build_study_plan` split `weekly_hours` across weak topics proportionally to `lost_marks`
and emitted one `StudySession(week=1, hours=…, focus="Practice and review: {topic}")` per
topic. That is advice with a number attached, not a plan: `week` was a literal `1`, there was
no activity type, and a student reading "Waves: 2.4 hours — practice and review" has been told
nothing they did not already know. MISSION §4 asks for **concrete sessions (topic, activity
type, duration)**. It also ignored placement and the questionnaire entirely.

### 2. Three signals, weighted, and why a missing one is not a zero

Weakness `lost_marks` **0.5**, placement result **0.3**, S-02 confidence rating **0.2** —
most-evidential to least: a rolling aggregate over every graded attempt, then real graded
evidence from a single sitting, then the student's own guess. The weights live in the module
docstring at the point of divergence, each pinned by a test, following the precedent
`core/spaced_repetition.py` set for its four SM-2 departures.

The consequential choice is **renormalisation**: a topic missing a signal is scored on the
signals it does have, not on a zero standing in for the absence. Zero-filling would punish a
topic for the student not having sat a placement test yet — and since S-02 is answered
*before* any grading exists, the most common real state at onboarding is confidence-only.
Zero-filling would have made every brand-new student's plan uniformly flat.

All three are keyed on the P4.2 `"<code> <name>"` topic vocabulary. That shared key is why
merging them is possible at all; it was built deliberately across D4.2/D4.4/D4.5.

### 3. The defect: a ten-hour week that scheduled four and a half hours

Found by measuring the first implementation against real inputs, not by reading its report.
Sessions were capped at `MAX_SESSION_MINUTES = 90` and any excess was dropped:

| weak topics | budget | scheduled (before) | scheduled (after) |
|---|---|---|---|
| 3 | 600 min | **270** | 585 |
| 6 | 600 min | 540 | 600 |
| 10 | 600 min | 600 | 600 |

The three-topic case — a student with a *focused* weakness profile, which is to say a student
the plan should serve best — lost 55% of its budget. `StudyPlan.weekly_hours` still said 10,
and `StudyPlan.tsx` renders `{plan.weeklyHours} hours a week` as the S-24 header. The header
would have described a week the sessions beneath it did not add up to.

The fix is to **split** a topic's allocation into several shorter blocks on **distinct days**
rather than truncate it to one capped sitting. This is also better teaching — spaced blocks
beat one 200-minute sitting — so the honest option and the pedagogical one agree. Distinctness
is enforced (`_day_offsets` spaces blocks `7 // block_count` apart), because splitting a topic
and then scheduling both halves the same evening defeats the point; verified across 1–10
topics. Residual drift is only ±5 minutes of per-block rounding.

Block count is capped at seven — one per day — which only binds above 10.5 hours on a *single*
topic, where the honest answer is that it does not fit in the week.

### 4. Two tests rewritten, and why that is not weakening them

`TestWeighting` read priority off the *position* of a topic's first session. Once sessions are
laid out by calendar date and a high-priority topic is split across days, position stopped
being a proxy for priority. They now assert **total minutes per topic**, which is what the
weighting actually decides — a more direct assertion than position ever was. Nothing was
skipped, deleted, or loosened; MISSION §5's rule is about not weakening a test to get green,
and a proxy that has become invalid is a different thing from an inconvenient assertion.

### 5. Honest states, and the one that does not survive the wire yet

Three distinct outcomes, all pinned by inverse-verified tests:
- **`available=False, reason="no_signal"`** — no weaknesses, no placement, no ratings. A
  refusal, never an invented week. Reuses `core/placement.py`'s machine-readable-reason shape
  rather than inventing a third convention (D4.6/D4.10 precedent).
- **`available=True, sessions=[]`** — there was something to evaluate and nothing to schedule.
- **A real plan** from any partial combination of signals.

**Activity type must be earned.** `TopicAvailability` is an *input* — chunk B supplies real
counts — so `practice` is never scheduled for a topic the bank cannot serve, nor `flashcards`
for a topic with no deck. `review` needs no resource and is the honest floor. A plan that
told a student to "practice Electric circuits" when the bank holds zero such questions would
be inventing precision (UI spec §1.4).

**Open gap for chunk C, stated rather than left to be discovered:** `StudyPlanDTO` carries no
`available`/`reason`, so the refusal and the empty-week state both reach the frontend as an
empty `sessions` list and are indistinguishable there. This is a gap, not a regression — the
distinction did not exist before this chunk — but chunk A's central honesty property dies at
the wire until chunk C decides the DTO. `activityType`/`date` are likewise not yet exposed;
`hours` is a unit conversion of `duration_minutes`.

Gemini spend: **$0.00**.

---

## D4.13 — The study plan gets its own surface, and "no plan yet" stops looking like "no plan possible" (P4.7 chunk C)

### 1. A new router, not an extension of `/api/student/plan`

`GET`/`POST /api/student/plan` (`routers/student.py`) were the obvious place to put this and
are the wrong one. They are HistoryStore-backed and **ephemeral**: they rebuild a plan from
scratch on every request and carry no plan id, no session ids, no subject selection, and no
persistence. Completion and weekly regeneration — the two things chunk B exists to provide —
are not expressible in that shape at all. Reshaping them in place would have silently changed
the contract `web/src/portals/student/screens/StudyPlan.tsx` consumes *today*, in a phase whose
frontend work (P4.10) has not started.

So: `lemely/web/routers/study_plan.py` at `/api/student/study-plan`, student-only at the router
level, with `lemely/web/schemas_study_plan.py` for its DTOs — the same "thin router, own DTOs,
don't grow `student.py`" shape `placement.py` and `flashcards.py` already set. **The legacy pair
stays untouched and is deleted in P4.10**, when the screen migrates. That ordering is the
reversible one: two surfaces briefly, rather than a broken screen for two tasks.

### 2. The three states, which is the whole point of the chunk

D4.12 §5 recorded the gap it left: `StudyPlanDTO` had no `available`/`reason`, so chunk A's
honest `no_signal` refusal and a real-but-empty week both reached the frontend as an empty
`sessions` list. Persisting the plan (chunk B) added a **third** state on top of those two, and
all three are things a student is owed a different screen for:

| wire | means | S-24 shows |
|---|---|---|
| `{"generated": false, "plan": null}` | no plan generated for this ISO week | route to placement/questionnaire |
| `generated: true`, `plan.available: false`, `reason: "no_signal"` | a plan was generated and honestly refused | why there is nothing to schedule |
| `generated: true`, `plan.available: true` | a real plan (possibly `sessions: []`) | the week |

The envelope (`CurrentStudyPlanDTO { generated, plan }`) exists so state 1 does not have to be
a 404. A 404 would have conflated "you have no plan this week" with "that subject does not
exist" and with an ordinary network failure, and the frontend would have had to guess. **"No
plan yet" is a successful answer to a reasonable question**, so it gets a 200.

`activityType` and `date` reach the wire here for the first time (D4.12 §5 named both as
missing). S-24 requires subject, topic, activity type and duration per session; without those
two fields the screen could only have rendered the same vague advice the old scheduler emitted.

### 3. Both service errors render 404, and both are still tested

`StudyPlanNotFoundError` and `StudyPlanOwnershipError` become a **404 with a byte-identical
body**. A study plan belongs to exactly one student and no teacher-visibility story exists in
this phase, so a 403 on someone else's session id would be an existence oracle over private
study material for anyone willing to enumerate UUIDs — D4.11's flashcard-deck reasoning,
applied to the same shape of object. The service keeps raising both typed errors and both are
still asserted; only the HTTP rendering is flattened. The test asserts a real other-student id
and a random UUID return identical bodies, then **inverts it** (the owner gets 200 on that same
id) so the 404 is proven to be a guard rather than a broken route.

A malformed (non-UUID) `session_id` is a **422**, not the 500 `_as_uuid`'s bare `ValueError`
would otherwise have produced.

### 3b. Two isolation properties pinned that the handover left unpinned

The completion route's 404 was tested; the **read** route's scoping was not. Both properties
below hold structurally today — `get_current` is passed `auth.user_id` and the path's
`subject_code`, never a caller-supplied id — so these are regression pins, not bug fixes, and
each carries its inverse so it cannot pass vacuously:

- `test_another_students_plan_is_invisible` — the guard that matters if a later phase adds a
  "view this student's plan" selector for teachers and threads it through this route. A plan is
  private study material and P4 has no teacher-visibility story for it.
- `test_a_plan_for_one_subject_is_not_returned_for_another` — the path segment **selects** the
  plan rather than decorating the URL. A student holds one plan per subject per week, and
  serving the physics plan under `/0580` would schedule maths study against physics weaknesses
  — wrong in a way an empty-plan bug is not, because it looks entirely plausible on screen.

### 4. What this does not do

No migration (0012 covers it), no `web/` diff, no narration — the AI narrator stays on the
legacy route and is P4.10's call, because `PlanView` persists no narrative and inventing a
column for one at route level would have put a Gemini call behind a GET.

Gemini spend: **$0.00**.

---

## D4.14 — A question the bank cannot fully render must not be served (P4.8 chunk 0)

### 1. Found by measuring while scoping S-04, not by a failing test

`question_bank` has **no image/figure column at all** — verified against `information_schema`,
not assumed. P4.1 excluded 654 figure-bearing leaves at ingest, but exclusion was decided on the
*source PDF's* structure, so stems that merely **reference** a figure in their prose survived.
Twenty-five of 273 banked 0625 stems read an existing figure as their source of information
("The diagram shows a radioactive source, a thick aluminium sheet and a radiation detector…").
There is no figure. The question is unanswerable.

**Why this outranked the frontend work it was found during.** A 0625 placement assembles ~10
questions, so a single such draw makes ~10% of the test unanswerable. The student loses those
marks; the placement then records a weakness they **do not have**; and that false weakness is
exactly what seeds the P4.7 study plan and P4.5 weakness-targeted practice. The failure
compounds downstream and is invisible at every gate — the stem renders perfectly, the
screenshot looks clean, every test passes. Same class as D3.21's confidently-wrong paper 22:
the number is wrong and nothing in the system is capable of noticing.

### 2. Exclusion from serving, not deletion

`renderable_bank_filter()` in `question_bank_repo.py` — a pure Postgres `~*` predicate over the
existing `prompt` column. **No migration, no Gemini, $0.00.** The row stays in the bank, stays
`is_active`, stays auditable; only the read paths that assemble a student-facing pool apply it.
If a figure column ever lands, the predicate is one function to relax rather than 25 rows to
re-ingest.

### 3. It is deliberately NOT folded into `visible_bank_filter`, and that is the load-bearing find

The obvious seam was `visible_bank_filter`, which `PracticeService` and `StudyPlanService`
already share. **`PlacementService` does not call it at all** — `_load_candidates` builds its own
subject/source/`is_active` filter. Folding the new predicate into `visible_bank_filter` would
have looked like a clean one-line fix, passed review, and **left placement — the single worst
affected path, the one that plants the false weakness — completely unfixed.** The two predicates
also mean different things: one is an owner/school *authorization* check, this is a content
*completeness* check. Applied explicitly at all four pool sites instead.

### 4. Where the honest line was drawn: 25, not 4 and not 32

A loose `Fig.|figure|diagram|table below|image` match hits 32 of 273. Every one was read
individually rather than pattern-matched in bulk:

- **Excluded from the exclusion — bare "image" (3).** All the optics sense ("a real image is
  formed"), a lens question, not a photograph.
- **Excluded from the exclusion — "draw a diagram of the circuit used" (4).** The student
  produces this diagram; it is their *answer*, self-contained in prose. Suppressing these would
  have silently shrunk the pool for a class of question that works fine.
- **Excluded from serving (25).** Five shapes, all reading an *existing* figure: `"Fig. 8.1
  shows"`, `"On Fig. 8.1, draw…"`, `"as shown in Fig. 7.1"`, `"in diagram 1"`, `"complete Fig.
  4.1"`. Note `"On Fig. 8.1, draw…"` **is** a dependency despite containing "draw" — Fig. 8.1
  already exists and must be seen.

### 5. What the fix cost, measured rather than assumed

Placement breadth is the thing that could have broken, and it did not — but the test **changed**,
and pretending otherwise would hide a real effect:

| 0625 placement | before | after |
|---|---|---|
| questions | 9 | **10** |
| duration | 15.19 min | **17.06 min** |
| syllabus topics | 6 | **6** |

Still under the 18-minute ceiling (D4.8), still spanning all six physics topics. It got longer
because the excluded questions had been counted toward the 15-minute target. Pool 273 → 248 for
practice. 0580/0606 remain an honest `no_questions` — unchanged, they have zero ingested
questions (D4.6 §5).

**Latent trap checked, not just reasoned about:** `not_(prompt ~* …)` evaluates to NULL for a
NULL prompt, which would silently drop the row. `question_bank.prompt` is `NOT NULL` and there
are zero NULL prompts today, so the three-valued-logic hole cannot bite — recorded because a
future nullable column would reopen it invisibly.

Gemini spend: **$0.00**.

---

## D4.15 — Saves for one question are serialized, and a save may only mark clean what it actually sent (P4.8 chunk B)

**Found by the MISSION §6 gate-7 adversarial review of the chunk-B diff, after the three
answer-loss defects in `c2d444f` were already fixed.** A fourth, narrower path to the same
outcome, in the same class as D3.21: the student sees their answer on screen while the paper
is marked against different text, and every gate this build runs stays green.

### 1. The defect

Two saves for the same question could be on the wire simultaneously:

- the reconnect/reload retry pass, resending the cached value, and
- the debounced edit path, sending a just-typed newer one.

That overlap was deliberate, not accidental. `refsToRetry` excludes in-flight refs so the retry
never duplicates a save; the debounce path deliberately does **not** consult it, because a
student who types while a save is in flight must have that newer edit sent rather than dropped
as a duplicate. Both halves are right on their own.

What was missing is that **network arrival order is not dispatch order**, and
`quiz_taking_repo.save_answer` is a plain last-write-wins upsert with no version or timestamp
guard. So the older save could land last at the server. Worse, `doSave`'s `onSuccess` wrote the
value *its own call had captured* back into the cache and stamped it `dirty: false`,
unconditionally — so the newer answer was overwritten locally too, and marked "confirmed
saved". On the next reload `mergeAnswers` sees a clean entry, defers to the server's value, and
the newer answer is gone with no error shown anywhere.

Reachable on the ordinary flaky-connection path this whole subsystem exists to serve.

### 2. Two independent lines, because one would have been enough to look fixed

1. **Serialization.** Each question ref owns a promise chain (`saveChains` in `QuizTaker.tsx`);
   a save requested while one is in flight is appended rather than dispatched. Two saves for a
   question can no longer overlap, on the wire or at the server, so ordering ambiguity is gone
   at the source.
   **Coalescing, not cancelling** — that distinction is what stops the fix from becoming a
   fifth loss path. The queued save reads `answerCache` **when its turn comes**, not when it
   was queued, so it carries the newest value; a newer edit is deferred, never dropped.
2. **`isCacheEntryUnchanged`.** A completing save may only mark an entry clean if the cache
   still holds exactly what that save put on the wire. **Value equality, not object identity**,
   on purpose: a student who types a change and undoes it back to the same text still gets a
   clean commit rather than a needless resend that would leave the entry dirty and block
   submit.

Line 2 is redundant given line 1 holds. It is kept because line 1 is an invariant maintained by
component wiring, and this one is a pure, tested check at the point of the actual write.

### 3. The single-field payload is deleted, not left dead

`buildAnswerSavePayload` ("only send the key that changed", the D4.5 onboarding rule) was
correct while each edit owned its own save. It stops being *expressible* under coalescing: one
save now stands for several edits, possibly to both fields, so there is no single "field that
changed" to name. Every save sends both fields from the cache, which is safe for the reason
`buildRetrySavePayload` already documented — a cache entry always holds the question's true
current state — and `SaveAnswerRequestDTO` treats an omitted field as "leave untouched" and a
present one as "set to this", which is exactly what a both-fields re-assertion wants
(verified against `lemely/web/schemas_quiz.py:312`, not assumed).

Its three tests were deleted with it. Keeping a tested function nothing calls would have been
the worse trade.

### 4. Submit now blocks on the cache, not on its own promises

`flushPendingSaves` had **zero test coverage** despite being the fix for the worst of the three
`c2d444f` defects. Two changes fell out of covering it:

- It waits on refs that are **busy but clean** (`refsToFlush`), not just dirty ones. A save
  already on the wire may still fail, and a save that fails after submit has gone through marks
  the paper without an answer the student can see.
- It decides failure by re-reading the cache for dirty entries rather than by catching its own
  rejections. Stronger contract: it blocks on *any* unsaved answer, however it got that way,
  not only the ones this call happened to dispatch.

### 5. `Object.keys` is not selection order (S-02 → S-03 routing)

`Object.keys(drafts)[0]` was documented as "the first subject they enrolled in, in their own
S-01 selection order". It is not: JS enumerates integer-like string keys first, ascending,
ahead of every other key's insertion order. Invisible today **only** because all three current
syllabus codes carry a leading zero (`0625`/`0580`/`0606`) and so are not integer-like — it
goes live the day a code without one is added. `placementInviteSubject` orders by the
`SUPPORTED_SUBJECTS` catalogue instead: "the first subject as S-01 presented them", a rule that
stays true whatever the codes look like. The test pins the trap itself
(`Object.keys(...)[0] === "9709"`) next to the function avoiding it.

### 6. Verification

11 new unit tests, **each verified by inversion** rather than assumed: probing
`isCacheEntryUnchanged` to always-true fails exactly 5, reducing `refsToFlush` to the dirty
set fails exactly 5, and reverting `placementInviteSubject` to `enrolledCodes[0]` fails exactly
3. 224 web unit tests green, `tsc --noEmit` clean.

Gemini spend: **$0.00**.

## D4.16 — Every new screen shipped without an h1, and three gates were passing over it (P4.8 chunk C)

### 1. What happened

Chunk C's whole premise was that `ui-thresholds` had been green on a registry that never
listed S-01..S-05, so the gate was passing *vacuously*. Sessions 5 and 6 fixed two vacuity
defects by reading. Session 7 was the first to actually **run** the registry, and the run found
a defect no amount of reading had surfaced: **all five new screens had no `<h1>` at all.**

Every one of the seven new states reported axe `page-has-heading-one` (**moderate**) while all
24 Phase-3 routes reported zero violations at any severity. Each screen rendered its page title
as a styled `<div>` — `font-serif text-display-md` — so the *visual* heading existed and the
*semantic* one did not.

### 2. Why it survived every gate

MISSION §6 gate 8 sets the axe threshold at "zero serious/critical". `page-has-heading-one` is
**moderate**. So the gate passed, and would have kept passing forever, even though
**QUALITY-BAR.md:40's neighbour at line 45 requires "one h1 per page, heading order unbroken,
landmarks" outright**. The finding sat in the gap between the automated threshold and the
written bar.

This is the same shape as D3.21's confidently-wrong paper 22 and D4.14's figure-dependent
stems: it renders perfectly, it screenshots perfectly clean, and the only person who
experiences the defect is the one using a screen reader — who reached the product's onboarding
and its first question-rendering surface with nothing to orient by.

### 3. The fix, and the two judgement calls in it

Title `div` → `h1`, same classes plus `m-0`. Tailwind preflight already zeroes heading margins
and makes headings inherit font size, so this is **visually identical** — confirmed against the
re-captured screenshots at all three breakpoints, not assumed.

- **`QuestionShell` is safe as the single h1** because `QuestionnaireStep` renders
  `steps[stepIndex]` — exactly one question at a time. Had all five shells rendered together
  this would have traded one violation for five.
- **`QuizTaker` gets an `sr-only` h1 carrying the real `quizTitle`, not a visible one.** The
  screen has no visible page title *by design*: mid-test the identity a student needs is
  "Question 3 of 10" and the countdown, and a banner title would push both down the viewport on
  a 380px phone. The heading still has to exist. It carries `quizTitle` rather than a constant
  because placement composes this component now and practice/assigned quizzes compose it in
  P4.9/P5 — the fix lands once for all three.
- **Loading and error branches get `sr-only` h1s**, following the P3
  ReviewItem/StudentDetail/QuizResults precedent, because `ErrorState` renders its heading as a
  non-heading element — the Phase-2.5 report §8 gap, still open.

### 4. The Impeccable audit, and what was deliberately NOT fixed

`/impeccable audit` on the five changed files scored **16/20 (Good)**; detector clean.
Implementation-integrity **PASS** on real grounds: the honesty states are structural rather
than cosmetic (discriminated-union views, `showWorkingLevel: false`, "Not enough data yet.",
"Not set", a class-less placement rendering the *absence* of an affiliation).

**Fixed (P1):** three controls below QUALITY-BAR.md:40's 44×44px floor — `QuizTaker`'s
flag-for-review (~30px) and two `Button size="sm"` call sites (~31px: 12.5px text + `py-2`).
All three pass WCAG 2.5.8 AA's 24px minimum, which is exactly why no automated gate caught
them. Raised **at the call sites, not in the `Button` variant** — `size="sm"` has 33 call sites
and 11 of the 15 files are teacher screens, where 44px would break dense layouts. Changing the
shared variant is a cross-portal decision, not a P4.8 one (verified by counting, not assumed).

**Deliberately deferred, recorded rather than smoothed over:**
1. **The global reduced-motion rule is the blanket kill the audit reference explicitly flags.**
   `index.css:742` applies `animation-duration: 0.001ms !important` to `*`. On S-05's unmarked
   state the spinning `CircleNotch` *is* the evidence that marking is in progress, beside copy
   promising "This page will update on its own" — with reduced-motion on, it freezes and the
   user cannot distinguish working from stalled. Pre-existing Phase-2.5 behaviour affecting all
   41 routes; `processing-state.tsx:19` already acknowledges it. Editing the global rule risks
   visual regression on every route and is out of P4.8's scope.
2. **Ad-hoc container widths** — `max-w-[560px]` ×3, `max-w-[720px]`, `max-w-[820px]` where a
   shared token belongs. (`min-h-[44px]` and the slider's `py-9px` are *not* this: both are
   documented repo-wide touch-target idioms.)
3. **S-04 re-renders its whole question tree once per second** from the elapsed ticker, with no
   memoization. Lighthouse perf is 82 so it is not currently measurable — but this exact ticker
   is what turned an unstable react-query object identity into a duplicate-PUT-per-second bug
   (D4.15 §1), so the cadence is a standing amplifier for that class of defect.

### 5. Verification

Full 13-gate run **ALL PASS, 0 skipped** — run three times this session, the last after every
fix in this record. **2308 passed / 6 skipped / 0 failed / 90.30% cov** (re-measured, not
carried forward — the backend diff since chunk 0 is not empty; earlier chunk-C sessions added
the placement seed and its tests). Second audit run confirms all seven
new states at **0/0/0/0 at every severity**, zero nonzero axe counts anywhere in the registry,
**Lighthouse a11y 100** on all four scored new routes (perf 80–83, at or above §11's student
floor), zero console errors, zero horizontal-scroll violations; `ui-thresholds` clean across
**41 routes**.

Spot-checked visually rather than trusted to the string asserts: the `questionnaire-skipped`
capture shows the thumb at `min` reading **"Not set"** (D4.5 honest on screen), and S-05 renders
"This is a baseline, not a grade", the working-level refusal, and "Not enough data yet."

**Measurement trap worth not re-deriving:** a bare `.venv/bin/pytest` reports **1 failed** —
`tests/architecture/test_import_linter.py` shells out to `lint-imports`, absent from PATH unless
you export `.venv/bin` yourself. A `FileNotFoundError` in the harness, not a broken contract:
with PATH set the test passes and `lint-imports` exits 0 ("Contracts: 2 kept, 0 broken").
`check.sh` exports PATH at its line 34, which is why its `pytest` gate is green.

Gemini spend: **$0.00**.

### 6. The second defect the same gate run found: the seed still collided on rerun

`playwright-e2e` failed on a genuine `uq_question_bank_paper_question (paper_id,
source_question_id)` IntegrityError for `0625_s88_qp_21#12`.

`build_placement_paper_stem` was added earlier in this chunk (`b9d610a`) specifically to make
reruns safe, by hashing `run_tag` into the session-year digits. **It reads only the tag's first
two characters.** The year therefore has a 100-value namespace, so by the birthday bound two
runs share a `papers` row roughly every dozen runs — and their identical `#1..#24` suffixes then
collide on the second run's `link_past_paper_rows()`. After a day of repeated gate runs, it
fired. Its docstring asserted it was the rerun-safety guarantee; it was not, and the existing
test that "proved" this picked two tags which also differ in the *stem*, so it passed throughout.

**Uniqueness moved to where it can carry the whole tag:** `source_question_id` is now
`f"{stem}#{run_tag}-{ref}"`. `_paper_identity` splits on the first `#` and parses only the stem
(`question_bank_repo.py:241-243` — checked, not assumed), so the suffix is opaque to the linker
and free to hold all 12 hex characters. The stem hash stays, because a distinct `papers` row per
run is closer to reality and sharing one is harmless once suffixes differ — but it is no longer
load-bearing, and both misleading docstrings now say so explicitly.

**Why the fix is not "purge and reseed":** the module contract is no teardown, per-run
namespacing throughout, and 184 `quiz_questions` rows from prior runs reference the linked bank
rows. Deleting them would break that contract and those references.

Verified three ways: the new test
`test_source_question_ids_differ_even_when_the_paper_stem_collides` uses two tags that provably
share a stem and is **verified by inversion** (reverting the suffix fails exactly this test and
none of the other 57); two real seed runs *forced onto the same stem* (`0625_s77_qp_21`) both
exit 0 with zero IntegrityErrors; and the full 13-gate run then passed.

**Local-state cleanup, done deliberately and only after looking:** 48 unlinked seed rows had
accumulated from the two runs that aborted at the link step. Confirmed **zero** `quiz_questions`
referenced them and that 24 of them duplicated an already-linked row's `source_question_id` —
the collision itself — before deleting. Local dev DB only; nothing committed, and re-running the
seed restores an equivalent state.

**The general lesson, which is the point of this whole chunk:** three sessions fixed vacuity
defects in this registry by *reading* it, and the two worst defects — a missing `h1` on every
new screen and a seed that could not run twice — were both found in the first ten minutes of
actually *running* it. Reading finds what is wrong with the code you are looking at; running
finds what you did not think to look at.

## D4.17 — S-23's end-of-session summary ships with no XP, and that is a spec override

**Context.** P4.9 chunk B built S-22/S-23 (flashcards) on the ten P4.6 routes.
`docs/LEMELY_UI_SPEC.md` §S-23 specifies the review session's end-of-session summary as
"a card with a reveal interaction, a self-grade control …, session progress, and an
end-of-session summary **with XP**".

**The conflict.** XP is Phase 5. It does not exist: P4.7 chunk B deliberately left
`study_plans.completed_at` as the XP seam and added no points or streak column, and there is
no XP table, service or route anywhere in the codebase. So the spec asks a Phase-4 screen to
display a quantity that has no source.

**Decision — the summary reports real session facts and no XP.** Cards reviewed, the
again/hard/good/easy distribution, the `intervalBeforeDays`→`intervalAfterDays` change
`ReviewResultDTO` already returns, and the remaining backlog (`totalDue` minus reviewed).
No XP number, no placeholder, no zero.

**Why this is not a shortfall.** The authority order in MISSION §10 puts the UI spec above
skill opinion, but the spec's own §1.4 product principle — never invent precision — is
higher still, and the two collide here. Any XP figure this screen could render would be
fabricated: there is no rule that says what a flashcard review is worth, because designing
the XP scheme is explicitly a Phase-5 task that MISSION §4 requires be recorded in
DECISIONS.md *before* implementation. Rendering `0 XP` is worse than rendering nothing —
it is a real-looking number that says the student earned nothing for real work. Inventing a
rate here would also pre-empt the Phase-5 design and quietly become the de-facto scheme.

**How it is pinned, so P5 cannot drift into it by accident.** `summarizeSession` is
asserted to return exactly `["reviewed", "gradeCounts", "intervalChanges"]`, with
`"xp"`/`"points"`/`"streak"` explicitly absent from the shape. When P5 adds XP it must
change that test deliberately — which is the point. The seam is the review audit log
(`flashcard_reviews`, P4.6 chunk A, built precisely as P5's XP seam); no schema change is
needed to add XP later.

**Same family as the two other deliberate non-builds in P4.9:** fact 4 (reveal-answer is not
built, because no route returns a model answer and adding one would put marking material on
a student surface) and fact 6 (the photo-answer route is not built, because no image field
exists anywhere on the quiz answer path and a camera affordance would silently discard the
student's work). In all three the honest move was to leave it unbuilt and say so, not to
build a convincing shell.

## D4.18 — Gate 8 for S-20..S-23: opacity on text broke two contrast floors, and the seed's "hermetic 24-row bank" was never actually 24 rows (P4.9 chunk C)

P4.9 chunks A and B shipped four screens (S-20/S-21 practice, S-22/S-23 flashcards) with **no
audit-registry entry at all**, so `ui-thresholds` was green over them without ever loading one
— the same vacuous pass P4.8 chunk C's own header note warns about. Chunk C adds 13 registry
entries / 14 captured states on three deliberately non-overlapping seeded accounts
(`active`/`settled`/`bare`), and the run found three real defects that reading had not.

**1. Two serious axe violations, both `opacity` applied to text, neither a token problem.**
`--t3` is fine (5.58–7.17:1 on every base surface, per `index.css`'s own history). What axe
measured was `#b3a7a5` on `#fffcfb` — exactly `--t3` (`#67534f`) composited at 50%.
- **S-20**: `PracticeGenerator` dimmed the *entire* Topics `<Card>` with `opacity-50` while
  "Weak topics only" was on. That dragged the card's "Topics" heading and its two explanatory
  paragraphs down to **2.28:1**. Dimming the label of a genuinely disabled control is exempt
  from WCAG 1.4.3; dimming a section heading and the prose that explains *why* the section is
  inactive is not.
  Root cause was one level down: **C-14 `Checkbox` self-dimmed only on its own `disabled`
  prop**, but these checkboxes are disabled by an ancestor `<fieldset disabled>`, which React
  never propagates as a prop. With `appearance-none` the browser draws no disabled affordance
  either, so the screen had no way to show the state except the card-wide wash. Fixed at the
  component with `has-disabled:` (`:has(:disabled)`), which covers both the prop and the
  ancestor case; the card-wide `opacity-50` is then deleted rather than tuned.
- **S-23**: the keyboard hints (`(2)`/`(3)`/`(4)`) on the three accent grade buttons were
  `opacity-70` — white at 70% over `--accent` measured **4.17:1**. `opacity-70` removed rather
  than nudged: `text-2xs` already de-emphasises the hint, and this is a *keyboard affordance*,
  the one thing on that button that must not be hard to read. Nudging a computed blend is the
  loop `--t3`'s own comment records failing twice.

**2. The seed's hermetic bank was never hermetic, and it broke a capture silently.**
`PRACTICE_SET_COUNT` and the placement assembly are both reasoned against a documented
"hermetic 24-row Paper 2 bank (6 rows/topic × 4 topics)". `seed_e2e.py` had no teardown and
run-tags its question ids, so every run **added** 24 rows: the live DB held **96**. A student's
practice pool is scoped by subject+paper, never by run, so the student saw all of them.
This is invisible until a capture depends on the pool's *size* — and S-20's `insufficient_pool`
is the first one that does (6 available < 10 requested at the screen's default count). Once two
runs had accumulated, the weak topic held 12+ rows, the shortfall panel stopped rendering, and
that route **timed out and produced no screenshots and no axe report at all** while the other
S-20 states passed. A gate that passed on a virgin database and failed on every run after it.
Fixed by purging prior runs' fixture rows at seed start, which *restores* the invariant the
code already documented rather than inventing a new one. Safe because `question_bank` is
referenced only by `quiz_questions.question_bank_id` `ON DELETE SET NULL` (verified against
`pg_constraint`, not assumed). `is_placement_seed_prompt`'s docstring asserted the opposite
("earlier runs' rows stay in the bank") and was corrected in the same commit rather than left
to mislead.

**Why the third defect is the one worth remembering.** Both axe violations were loud — a gate
names them. The bank accumulation was *silent*: the audit exited non-zero for the two contrast
findings, and the missing route was visible only by noticing that `reports/.scratch/screens/S-20/`
had no `default--*.png` and `axe/` had no `student-practice-generator.json`. An exit code that
already has a reason to be non-zero will hide a second, unrelated failure behind it. Verified by
listing the captures, not by reading the summary line.

**Verification.** All 13 gates green, 0 skipped, exit 0. 14/14 axe reports clean at every
severity (not just serious/critical); 42 screenshots (14 states × 3 breakpoints); Lighthouse
a11y **100** on all four newly-scored routes, performance 80–82 (student floor is ≥80). Bank
re-measured after the fix at exactly 6 rows/topic × 4 topics. $0.00 Gemini.

## D4.19 — AI study-plan narration leaves the web surface, and the loss is recorded rather than restored (P4.10 chunk D)

**Context.** P4.10 chunk D deletes the legacy `GET/POST /api/student/plan` pair, superseded by
P4.7 chunk C's persisted `/api/student/study-plan`. STATE's chunk-D scoping (twentieth session)
flagged "trap 3": the legacy `POST` is the only web path to AI study-plan narration
(`payload.narrate` → `StudyPlanNarrator`, `routers/student.py:857-865`), and the replacement
`StudyPlanWeekDTO` has no `narrative` field, so deleting the route loses the feature on the web.
It named the fork — record the loss, or carry narration onto the new route — and left it open.

**Correction to that framing, measured before deciding rather than inherited.** The loss is not
chunk D's to cause: it has already happened. The old `StudyPlan.tsx` called the legacy POST with
a literal `{weeklyHours, narrate: true}` and rendered `plan.narrative` in a panel
(`git show 94326a1 -- .../StudyPlan.tsx`, removed lines 78 and 134-138). **P4.10 chunk A deleted
that screen**, and chunk A shipped green through the A+B gate run. So web narration died at
`94326a1`; the route has had zero callers ever since, and chunk D removes dead backend, not a
live feature. This matters because "chunk D loses a feature" invites restoring it inside a
cleanup commit, and the honest statement is narrower: **Phase 4 replaced the narrated plan
screen with an unnarrated one, and that is the change to record.**

**Decision — record the loss; do not restore narration in this phase.** `narrative` is not added
to `StudyPlanWeekDTO`, no Gemini call is added to the study-plan surface, and the web plan ships
unnarrated. The loss goes into the Phase-4 report's limitations and, per MISSION §9 (the adaptive
study plan is an inventoried feature), into DELIVERY.md.

**Why not restore it.**
1. It is new feature work wearing a cleanup commit's clothes: a schema field, a billed Gemini
   call on a student surface against the $8 ceiling, and an AI-content honesty affordance
   (D4.11's rule — AI-written content stays distinguishable from the real thing for its whole
   life — would apply to a narrative panel too). MISSION §8b forbids speculative work, and a
   deletion chunk is the worst place to hide a feature addition; a gate failure there would be
   unattributable, which is the same reasoning that split chunk D out of chunk C.
2. The register is wrong for what Phase 4 built. MISSION §4's stated complaint about the old
   plan is that it was "vague advice with a number attached" and must become "concrete sessions
   (topic, activity, duration) not vague advice". The narrator prompt asks for a "2-3 paragraph
   study guide" and is explicitly forbidden from touching the sessions
   (`io/prompts/study_plan.py:16-18`). Re-attaching a motivational essay above a schedule of
   real sessions restores exactly the layer the phase set out to replace, and it would be the
   one part of S-24 a student could not check against anything.
3. Nothing is burned. `lemely/io/study_plan_ai.py`, its prompt, and `StudyPlan.narrative` in
   `core/study.py` all survive intact and stay live on the CLI (`cli.py:582 --use-ai`,
   `:612-614`) — **so `study_plan_ai.py` must not be deleted by this chunk**. Carrying narration
   onto the new route later is an additive field plus a route, deliberately decided, in its own
   commit. Simplest, cheapest, most reversible (MISSION §5).

**What chunk D must therefore do about it**, beyond the deletions STATE already scoped: leave
`lemely/io/study_plan_ai.py` and the CLI path untouched, and state the web-side loss in the
Phase-4 report rather than letting it vanish as a side effect of a cleanup diff. The
already-shipped half (chunk A dropped the rendering) is the part most likely to go unrecorded,
because no gate in this build can see a feature that stopped being offered.

---

## D4.20 — The placement band assertion was pinning luck, not a rule

**Context.** P4.10 chunk C's gate run failed `pytest` on exactly one test,
`tests/test_placement_assembly.py::test_a_broad_pool_assembles_inside_the_budget`
(`assert result.spans_multiple_bands is True` → False). Chunk C's diff is
`seed_e2e.py` + `test_seed_e2e.py` + `audit.mjs` + two deleted frontend hooks —
nothing within reach of placement — and the same test passed the A+B run. The
flake dates to `5809814` (P4.4 chunk B-3), the commit that introduced the test.

**Measured, not assumed.**
1. **Flake rate: 1 failure in 30 runs** of that test alone (the prediction from
   reading was "roughly 1 in 20"). After the fix: **60/60 runs of the whole file
   green.**
2. **Live 0625 corpus: `spans_multiple_bands` is True.** The corpus had been
   lost from the local Postgres in a DB reset, so it was re-ingested first
   (deterministic, $0.00, zero Gemini) and the reconstruction verified against
   the recorded figures before any conclusion was drawn: 273 banked / 273 linked
   / 26 papers / 211 classified, 248 servable after the P4.8 chunk-0 renderable
   filter — every number matching D4.1/D4.2/D4.8/chunk-0 exactly. Placement then
   assembles **10 questions / 17.06 min / 6 syllabus topics**, matching the
   chunk-0 measurement, of which **6 are `foundation` and 4 `standard`**. So the
   real bank does span bands, **S-05 does show a working level, and this is not
   a Phase-4 limitation.**
   A first measurement said 8 q / 15.94 min because the DB also held the E2E
   seed's 24 placement fixture rows; excluding them reproduced 10 q / 17.06 min.
   *A measurement taken against a seeded DB is not a measurement of the corpus.*

**Two independent defects, and the assertion is the more important one.**

1. **The fixture was random.** `_c` minted `uuid.uuid4()` per candidate, and
   `assemble` breaks ties on `str(candidate.question_bank_id)`. In `_spread`
   every candidate carries identical marks, so the primary sort key
   `abs(estimated_minutes - share)` **ties for every option** and the pick was
   decided by a random UUID string sort. Fixed with a per-test counter
   (`uuid.UUID(int=n)`, reset by an autouse fixture so ids never depend on test
   order). Note `test_assembly_is_deterministic` could never have caught this:
   it assembles the *same pool object* twice, so it pins determinism within a
   run, not across runs.

2. **`assemble` has no band-spread rule at all**, so the assertion pinned a
   behaviour that was never implemented and passed ~97% of runs by luck. It
   selects breadth-first across top-level topics with a nearest-to-even-share
   tie-break and **never reads `Candidate.difficulty`**. Worse, the assertion
   argues against the property's stated design: `spans_multiple_bands` exists
   precisely to be False sometimes — it is what stops S-05 inventing a
   working-level estimate from a sample drawn from one band
   (`placement.py:152-158`).

**Decision: delete the assertion; do not make the fixture deterministic and
re-pin whatever falls out.** Making the pool deterministic *would* have made the
assertion pass every time — and that is exactly the trap, because it would have
laundered a lucky draw into a guarantee the algorithm does not offer. The
assertion is replaced by `TestBandSpread`, an explicit inverse pair proving the
real contract (the flag *reports* the bands in the selected set: True for a
mixed pool, **False for a viable single-band one**), with the live-corpus
measurement recorded in the docstring as a measurement rather than an assertion.

**Deliberately not done: no band-spread rule was added to `assemble`.** Making
placement guarantee two bands is a product change to the assembly contract, not
a test fix, and MISSION §8b forbids speculative work. The corpus currently
yields a mixed set anyway, so there is no user-visible gap to close.

---

## D4.21 — Every state view in the product overflowed the 380px breakpoint

**Context.** The same chunk C gate run also failed `ui-thresholds`:
`student-study-plan-week-refused` had horizontal overflow at 380px
(scrollWidth 418 > clientWidth 380).

**It is not a study-plan bug.** The offender is
`web/src/components/ui/state-views.tsx`, the shared `StateView` — so the defect
was in **every empty, error, offline and refusal state in the product**, and the
S-24 refused state is merely the first one the audit registry drove a browser
into at that width. Two causes, both fixed at the component:

1. `mx-auto flex max-w-sm …` with **no `w-full`**: `max-w-sm` caps a box at
   384px but does not make it shrink, so the element kept its intrinsic 384px —
   4px wider than the 380px breakpoint before its own `px-6` is counted.
2. The action row (`mt-2 flex items-center gap-2`) could not wrap, and `Button`
   sets `whitespace-nowrap`. S-24's refused state carries two actions ("Take the
   placement test" + "Rebuild this week's plan") which cannot sit side by side
   on a phone. Now `flex-wrap` + `justify-center`. **Wrapping, not truncating**:
   a clipped label hides what the button does, and this state's whole job is to
   tell a student what to do next.

Neither change affects wide viewports (`max-w-sm` still caps at 384, `flex-wrap`
only engages when the row cannot fit), so no baseline is re-based.

**The gate is the regression pin.** The responsive check at 380px is what caught
it and is what would catch it again; a unit test asserting the presence of a
utility class would restate the fix rather than test the behaviour.

## D4.22 — Retiring the legacy `/api/student/plan` pair and `/api/student/onboarding` (P4.10 chunk D)

**What was deleted.** `GET`/`POST /api/student/plan` and
`POST /api/student/onboarding` on `lemely/web/routers/student.py`, plus their
now-callerless schemas in `schemas_student.py` (`PlanSessionDTO`,
`StudyPlanDTO`, `StudyPlanRequest`, `OnboardSliderInput`, `OnboardingRequest`,
and the **legacy** `StudentProfileDTO`), the six route tests in
`tests/test_web_student.py`, and the three dead TS interfaces in
`web/src/lib/studentTypes.ts`. All three routes had zero frontend callers:
P4.8 chunk A deleted `usePostOnboarding`, P4.10 chunk C deleted
`useStudyPlan`/`usePostStudyPlan`.

**The load-bearing part is the authz matrix, not the deletion.**
`tests/test_authz_matrix.py` had **zero** coverage of either replacement
surface — `/api/student/plan` (`STUDENT_GET_ROUTES` + `STUDENT_POST_ROUTES`)
and `/api/student/onboarding` were the *only* authz-matrix representation of
the study-plan and onboarding surfaces in the product. Deleting those three
entries alone would have **silently shrunk the RBAC matrix and still passed all
13 gates**, which MISSION §6 gate 6 forbids. The replacements were added in the
same commit, and deliberately **not** symmetrically:

* `/api/student/study-plan/*` carries a **router-level**
  `require_role(Role.student)` (`routers/study_plan.py:50-52`), so the file's
  existing representative-spread convention applies: one GET
  (`/api/student/study-plan/0625`) + one POST (`""`) prove the router.
* `/api/me/student-profile*` does **not**. `routers/me.py:57` is a bare
  `APIRouter(prefix="/api/me")` with per-route guards, and two of its routes
  (`/notification-preferences`, `/profile`) are deliberately role-agnostic — so
  a spread would prove nothing about the routes it skipped. **All five**
  student-only routes are listed individually. This needed two new
  parametrized method families (`STUDENT_PATCH_ROUTES`, `STUDENT_PUT_ROUTES`);
  the file previously only parametrized GET and POST for the student surface,
  which is why a PATCH/PUT guard could never have been proven here before.

The two explicit former-IDOR pins (`test_plan_post_ignores_any_caller_supplied_id`,
`test_onboarding_uses_token_identity`) died with their routes. The property they
pinned — identity is the token, never the payload — is structural on the
replacements: `/api/me/student-profile*` takes no student id in any body, and
`ApiModel` is `extra="forbid"`, so smuggling one is a 422.

**Verified positively, not by absence of failure.** The deletion was confirmed
against the running app's OpenAPI schema (both paths absent, all three
replacements present, 88 routes), not merely by the suite staying green — a
test file that no longer names a route cannot fail when the route survives.

**Feature loss, recorded not smoothed over (extends D4.19).** The legacy
`POST /api/student/plan` was the only *web* path to AI study-plan narration
(`payload.narrate` → `StudyPlanNarrator`). `StudyPlanWeekDTO` has no
`narrative` field, so nothing on the new surface replaces it. Per D4.19 this
is **recorded, not restored** — restoring it would smuggle a schema field and a
billed Gemini call into a deletion commit, and the narrator's "2-3 paragraph
study guide" is exactly the vague-advice register MISSION §4 replaced with
concrete sessions. Narration survives on the CLI (`cli.py --use-ai`), so
**`lemely/io/study_plan_ai.py` is deliberately NOT deleted**. This belongs in
DELIVERY.md's limitations, since MISSION §9 inventories the adaptive study plan.

**Stale-note sweep, the trap this build has been bitten by twice.** Every
docstring that described the deleted pair as live was rewritten in the same
commit: `routers/student.py` module docstring, `schemas_study_plan.py:7-8`,
`routers/study_plan.py:6`, `tests/test_web_student.py:9`,
`web/src/lib/studentTypes.ts` (header + the P4.8 note that had said the backend
was "left for P4.11 to formally retire"), `studyPlanTypes.ts:7`,
`useStudentApi.ts:53`, `StudyPlanWeek.tsx:25`. Also `tests/conftest.py:50`,
whose D4.3 billed-Gemini-guard rationale cited a test this chunk deletes — the
**guard stays, the reference was fixed**, since a comment citing a deleted test
is the same trap as `audit.mjs`'s own worked apology.
`audit.mjs:89-91` and `data.ts:93-94` were checked and left alone: both
describe the *frontend* route `/student/plan/:subjectCode`, which still exists,
and chunk C's history, which is accurately told.

## D4.23 — At-risk rule 2 gets its own class, not a fourth seat in the roster (P4.11 chunk D)

**Context.** Rule 2 of the at-risk engine ("predicted >= 2 grades below target",
D3.3) has never been pinned by a test. It could not be: there was no
target-grade column until P4.3 shipped `student_subject_enrolments.target_grade`
(D4.5), so `scripts/seed_e2e.py` *described* the rule in its docstring instead of
seeding it. P4.3 deliberately deferred the seeding to P4.11, and chunk D is it.

**The trap, found by measurement rather than hit.** The obvious implementation —
a fourth student in the seeded class — breaks a spec that is not the one under
test. `web/e2e/teacher-journey.spec.ts` hardcodes three figures derived from the
roster: 3 students, a 69% average mark (the mean of 55/75/78), and 2 at risk. A
fourth grade-bearing student moves all three. `seed_e2e.py`'s own comment at the
review-queue item already names this trap and dodges it by reusing an existing
attempt; this is the same trap one scenario later.

**Two measurements decided it, and one corrected a note this build had been
carrying.**

1. Is `teacher-journey.spec.ts:48`'s "69%" class-scoped or teacher-wide?
   **Class-scoped.** The locator is
   `page.locator("main a").filter({ hasText: seedClass.name })` — a per-class
   card on the overview, not a teacher-wide aggregate.
2. Does the classes table's `classesCells.nth(3)` index by row position, making a
   second class row unsafe unless it sorts last? **No — and STATE.md's note
   claiming it did was wrong.** The row is selected by
   `page.locator("tbody tr").filter({ hasText: seedClass.name })`; `.nth(3)`
   indexes cells *within that already-filtered row*. Class ordering is irrelevant
   to every assertion in that file.

**Decision: a second class owned by the same teacher.** `teacher_at_risk_list`
(`lemely/web/routers/teacher.py:1766`) walks `service.list_classes(...)` and each
class's roster, so a second class keeps the student visible to T-06 while leaving
every roster-derived number the roster's own. The class is named
`"P4.11 Below-Target Class {run_tag}"` so it sorts after `"P3.10 Seed Class …"` —
belt-and-braces against a *future* positional assertion, not the reason this
works.

**The fixture's shape is load-bearing in two ways that are easy to get wrong.**
The account gets **one** attempt, recorded **recently**. One record means rule 1
cannot fire (it needs a 3-record window); a recent date means rule 3 cannot fire
(it needs 14 days of silence). Together they keep `expectedAtRiskReasons` exactly
`["below_target"]` rather than a superset, which is also what keeps
`at-risk-flags.spec.ts`'s one exhaustive assertion — `?reason=inactive` returns
exactly `[inactive.userId]` — intact. The target is keyed on `SUBJECT_CODE`,
matching the attempt's own metadata: `assess_at_risk` resolves a target only for
the subject of the *latest grade-bearing record*, so a target on any other subject
yields `NOT_EVALUABLE` and the seed would fail **silently, as an unflagged
student**, not loudly. Grade `D` against target `A` is a 3-position gap, chosen to
clear the 2-position threshold with room rather than sit exactly on it.

**Both docstring defects in `scripts/seed_e2e.py` fixed in the same pass**, since
correcting one and leaving the other makes the file contradict itself: the false
"Rule 2 … cannot fire in Phase 3" paragraph, and `inactive` mislabelled "rule 2"
when `lemely/core/at_risk.py` orders the rules declining / below-target /
inactivity, making it rule **3**.

**Non-vacuity was proven by inverting the fixture, three rounds, all reverted.**
Target `A`→`C` (gap 1) failed exactly the three gap-dependent tests while the
not-evaluable inverse stayed green; date 1→20 days failed **all five** (rule 3
joins every assertion); the published gap 3→2 failed exactly the one test that
publishes it. The five new tests live in `tests/test_seed_e2e.py`, beside the
existing no-DB scenario proofs for the other three students.

## D4.24 — The screenshot corpus gets corpus maths, or MISSION §4's visual check is vacuous (P4.11 chunk E)

**Context.** MISSION §4 requires that question rendering — maths notation and
diagrams — be *"verified visually in screenshots, not assumed"*. The obvious
reading is that this is a pure evidence pass: `audit.mjs` already carries 48
registry entries covering S-01..S-05 and S-20..S-25, so axe, Lighthouse and the
screenshot corpus already run over every Phase-4 screen on every gate pass, and
chunk E only has to look at the output and report the numbers.

**That reading is wrong, and the reason is the finding.** The two screens that
render a `question_bank.prompt` are S-04 (`QuizTaker`) and S-21 (practice
set/export). Both draw their questions from the E2E seed, and **every stem the
seed authored was pure ASCII on a single line** — `"Synthetic placement seed
item {ref} for topic {topic!r} (…)"`. So the committed captures contained
neither Unicode maths nor an embedded newline. "Inspect the captured stems and
confirm the maths renders" against that corpus is a **vacuous pass**: it cannot
fail, and it looks identical to a real one. Same shape as the trap chunk B's
scoping caught, where an S-05 assertion passed on a string that also renders on
`PlacementInvite`.

**Decision: seed a corpus-verbatim maths sample, additively.** A new
`PLACEMENT_MATHS_SAMPLE` is appended to the placement pool's prompts. Four
constraints shaped it:

1. **Verbatim from the real bank** (`0625_w23_qp_42#1c`), not authored by hand.
   A screenshot of maths written to make the screenshot pass proves nothing
   about how the product renders *corpus* text. It carries `×` and a
   superscript `⁵` — the superscript is the harder rendering case, which is why
   this pick beat the α/β/γ candidates — plus 4 newlines for `white-space:
   pre-line` to preserve.
2. **Figure-free, checked rather than eyeballed.** `_FIGURE_DEPENDENT_PATTERN`
   is a *Postgres* POSIX regex and is not valid Python `re` (it raises
   `PatternError` on `\m`), so it was evaluated **in Postgres** against the
   assembled prompt, with a positive control (`"The diagram shows a circuit."`
   → match) proving the check was not itself vacuous. A careless pick matching
   that pattern would be dropped by chunk 0's `renderable_bank_filter`,
   silently emptying the placement pool this seed exists to fill — and it
   surfaces as a `no_eligible_questions` refusal on S-03, not as an error.
3. **One site, not two.** `seed_e2e.py` has two `prompt=` sites; only the
   placement pool reaches a captured screen. The teacher-quiz bank
   (`build_quiz_bank_questions`, `source=generated`) feeds the P3.10 teacher
   quiz and is rendered by no audited screen, so editing it would add corpus
   text no screenshot ever looks at — the same vacuous shape, one level down.
4. **Additive, keeping `{ref}`/`{topic!r}` and the honesty marker.** The
   per-row interpolations are what keep prompts distinct;
   `uq_question_bank_paper_question` fires if they collapse. The
   `PLACEMENT_PROMPT_MARKER` substring check `is_placement_seed_prompt` relies
   on is unaffected, so the seed still refuses to answer a question it did not
   author.

**Two tests pin it, and the split between them is deliberate.** One asserts on
the *assembled* prompt (a test reading only the constant would still pass if
the interpolation appending it were deleted); the other pins the provenance
wording, because "verbatim from the corpus" is load-bearing evidence rather
than decoration. Proven non-vacuous by inverting the product — removing the
interpolation failed exactly the assembled-prompt test while the provenance
test stayed green.

**No KaTeX/MathJax, and that stays decided.** P4.8 measured the corpus at 21
distinct non-ASCII characters across 273 stems with 1 LaTeX-shaped; plain
Unicode is the real case and every browser renders it natively. The rendering
risk here was always the newlines, not the glyphs.

**`ruff` caught the glyph as an ambiguous character (RUF001/RUF003) — noqa'd at
the two sites where it is load-bearing, with the prose reworded to avoid it
elsewhere.** Swapping `×` for ASCII `x` would delete the exact thing the
inspection exists to look at; the rationale matches the existing per-file
ignore on `lemely/io/det/symbols.py` ("Α is Alpha, not A — that is the point").

## D4.25 — The performance floor MISSION §11 claims is gated is not actually enforced (P4.11 chunk E)

**Found by doing chunk E's verification honestly instead of assuming.** Chunk E
was scoped as "verify and report the UI-gate half; do not rebuild it". Reading
the numbers rather than the PASS line turned up a gap between what this build
*says* it gates and what it *does*.

`scripts/check_ui_gates.py` enforces exactly one Lighthouse threshold:
`ACCESSIBILITY_FLOOR = 95`, per route. There is no performance check anywhere in
it. But MISSION §11 states the standing automated checks include "Lighthouse
thresholds (accessibility ≥ 95, **performance ≥ 80 on the student routes**)",
and `audit.mjs:218` justifies not applying frugal browser flags to Lighthouse's
browser on the grounds that "**the run gates on performance ≥ 80** — a cheaper
score bought by throttling the browser we measure in would be a dishonest gate".
Both describe an enforcement that does not exist.

**It is not hypothetical — a student route is already under the floor.** This
run's scores: `student-flashcards-due` **performance 79**, against MISSION §11's
≥ 80 student-route floor. `ui-thresholds` passed anyway, because performance is
never read. Four teacher routes are further down (`teacher-quiz-detail` 65,
`teacher-class-roster` 73, `teacher-schemes` 75, `teacher-class-analytics` 77),
but MISSION §11's floor only ever covered the student routes and Phase 3 already
carries the teacher-route figure as a known limitation.

**Decision: record it, do not fix it inside P4.11.** Adding the missing check is
one constant and one loop, but it would turn `ui-thresholds` **red on a real
79** — and the fix for that red is genuine frontend performance work on
`student-flashcards-due`, which is not P4.11's scope and not something to start
unattended at phase end. Shipping the check while quietly setting its floor to
75 to keep the run green would be exactly the dishonest gate `audit.mjs`'s own
comment warns against. So the number is reported, the discrepancy is recorded,
and both go into the Phase-4 report and DELIVERY.md as a carried limitation.

**The general shape is worth keeping**, because this build has now hit it three
times (D3.20's never-typechecked `web/e2e/`, P4.8's screens with no registry
entry, and this): *a gate that is believed to cover something it never loads
reads exactly like a gate that does.* A PASS line is evidence only for what the
gate actually asserts.

**This run's UI-gate numbers, for the phase report:** 122 axe route-states with
**zero violations at any severity**, 34 Lighthouse routes with **a11y floor 96**
(`teacher-review`) and student-route a11y **100**, **zero** console errors,
**zero** responsive/horizontal-scroll violations, screenshot corpus across 39
screen directories.

---

## D5.1 — The XP, streak and leaderboard specification (P5.1, written before any implementation)

MISSION §4 Phase 5 requires this spec to exist *before* the code. It governs
P5.2 (XP engine), P5.3 (leaderboards) and P5.4 (friends). Everything below is a
decision, not a sketch — where a later task disagrees with this document, the
disagreement gets recorded as its own D5.x rather than silently drifting.

### 0. The constraint that outranks every other rule here

**XP must never be a function of how well a student did.** Not their marks, not
their percentage, not their predicted grade, not their accuracy on a quiz.

This is not a style preference. MISSION §3 fixes "leaderboards show XP (effort),
never grades", and UI spec §1.4 makes grades private to the student, their
parents and their teachers. A leaderboard is the one public surface in this
product. If XP correlated with performance, the leaderboard would be a grade
ranking wearing a costume — and it would leak *precisely* the information the
product promises to keep private, to *precisely* the audience (classmates) the
student would least want to have it.

So: a student who scores 18/80 and a student who scores 76/80 on the same paper
earn **identical XP**. XP answers "did you do the work", never "were you good at
it". Two structural consequences, both binding on P5.2/P5.3:

- **The XP award functions take no mark, score, grade or accuracy argument.**
  Not "ignore it" — do not plumb it in. An argument that does not exist cannot
  be used by a later well-meaning change.
- **The leaderboard query must not join to any marking table** (`attempts`,
  `question_results`, `papers`, `weakness_records`). P5.3 carries a test that
  asserts this over the emitted SQL, so the rule survives a refactor that
  nobody reads carefully. A comment saying "don't join marks here" is not a
  control; a failing test is.

### 1. What already exists (do not rebuild it)

`xp_events` and `streaks` were created in **migration 0002**, Phase 1's core
schema — see the corrected Phase-4 limitation in STATE.md. `xp_events` carries
`(user_id, source, amount, awarded_on, metadata)` with an index on
`(user_id, awarded_on)`; `streaks` carries `(user_id UNIQUE, current_length,
longest_length, last_active_on, freezes_available)`. The `xpsource` enum holds
exactly four values and they are exactly MISSION's four sources:
`paper_corrected`, `quiz_completed`, `flashcard_reviewed`,
`study_session_completed`.

**Adding a fifth XP source requires an enum migration.** The four are the scope;
P5 does not invent a fifth.

### 2. Award amounts

Effort-proportional, weighted by how much real work each act represents:

| Source | XP | Unit |
|---|---|---|
| `paper_corrected` | **50** | per paper reaching a completed marking |
| `quiz_completed` | **30** | per quiz/practice/placement assignment submitted |
| `study_session_completed` | **20** | per study-plan session marked complete |
| `flashcard_reviewed` | **1** | per card graded in a review |

The ratios matter more than the absolute numbers. Correcting a past paper is the
product's core loop and its hardest single act, so it dominates. A flashcard is
one keypress, so it is worth one point — which is also what makes the daily caps
in §3 defensible rather than arbitrary.

### 3. Anti-farming caps

The cheapest action to repeat is the one that needs the tightest bound. Caps are
**per user per streak-day** (§4's day, not a UTC day):

| Source | Daily cap | Effective XP ceiling |
|---|---|---|
| `flashcard_reviewed` | 60 cards | 60 |
| `quiz_completed` | 3 | 90 |
| `paper_corrected` | 5 | 250 |
| `study_session_completed` | 4 | 80 |
| **Global** | — | **250 XP/day** |

Two rules on how a cap behaves, because the wrong choice here is a support
burden:

- **A capped action still succeeds.** Hitting the flashcard cap does not block
  the 61st review — it reviews normally and awards 0 XP. The learning activity
  is never gated on the gamification layer. (If the two ever conflict, the
  learning wins; that is the whole product.)
- **A capped award writes no `xp_events` row**, rather than a row with
  `amount = 0`. Zero-rows would inflate the "XP earned this week broken down by
  source" breakdown on S-31 with entries that contributed nothing.

### 4. The streak day, and why it is not UTC

**A streak day is a civil date in `Africa/Cairo`.**

The codebase's convention everywhere else is aware-UTC-now with an injectable
clock (`lemely/db/flashcard_repo.py`), and P5 keeps that for *timestamps*. But a
streak is a claim about *which day a human was working*, and Cairo is UTC+2/+3.
A UTC day boundary falls at **02:00–03:00 Cairo**, so a student revising at 1am
— the single most likely hour for this cohort to be doing flashcards — has that
work credited to *yesterday*. That silently breaks today's streak while
double-counting yesterday's. Both failure modes are invisible to a test written
in UTC and infuriating to the student.

Consequences, and one trap worth naming loudly:

- **`xp_events.awarded_on` holds a Cairo civil date, NOT a UTC date.** The
  column type is `Date` and gives no hint. Anything comparing it against
  `datetime.now(UTC).date()` is wrong for two to three hours out of every
  twenty-four. P5.2 converts through a single helper and nothing else computes
  a streak date inline.
- Egypt has not observed DST continuously; the helper uses `ZoneInfo`, never a
  fixed `+02:00` offset, so a reinstated DST rule is a tzdata update rather than
  a code change.
- The timezone is a **launch-market default, not a per-user setting.** MISSION
  §1 scopes v1 to Egypt. Per-user timezones are a real feature with real edge
  cases (a student who moves mid-streak) and are out of scope; the helper takes
  the zone as a parameter so that adding them later is a wiring change.

### 5. Streaks and the freeze

`current_length` counts consecutive streak-days on which the user earned **any**
XP at all. Any source counts — one flashcard keeps a streak alive. The streak
rewards showing up, and the caps in §3 already stop showing up from being
farmed into a leaderboard win.

**Everything is computed lazily on read.** There is no scheduler, cron or
background worker in this build, so a streak must resolve correctly no matter
how long the user was away — including the case where they return after 40 days
and three freezes should have been consumed. P5.2 evaluates from
`last_active_on` and the clock at every read and every award; it never assumes
a nightly job ran.

**Freeze grant.** One freeze per 7 consecutive active days, capped at **2 held**.
Not purchasable — payments are out of scope (MISSION §1), and a purchasable
streak protection is the exact mechanic UI spec S-31 warns against.

**Freeze consume.** On the first missed day, automatically and silently: one
freeze is spent, `current_length` is *preserved but not incremented*, and the
streak survives. A second consecutive missed day with no freeze left resets
`current_length` to 0. `longest_length` is never reduced.

**The kindness rule is a design constraint, not a copy note.** UI spec S-31 asks
for a streak that feels worth protecting "without being manipulative — a
streak-freeze that's offered kindly beats a guilt-trip". So a freeze is reported
**after** it saves the student ("your streak was protected"), never sold to them
beforehand as urgency. The "streak about to break" push in MISSION §4 stays,
because a factual reminder before the fact is different from a manufactured
panic — but it is one notification, it respects quiet hours, and it is
suppressible from G-12 like everything else.

### 6. The weekly leaderboard window

**ISO week: Monday 00:00 Cairo through Sunday 23:59:59 Cairo**, matching §4's
day so a student never sees their streak and their weekly XP disagree about what
day it is.

**Weekly totals are computed by summing `xp_events`, never denormalized into a
running column.** This build has now been burned three times by a hand-written
mirror that nothing regenerates (`gemini_spend_usd`, the `SeedContract`, and the
XP-schema limitation this very phase corrected). A `weekly_xp` column would be a
fourth, and it would drift silently in the direction that flatters the user. The
existing `ix_xp_events_user_id_awarded_on` index is exactly the right shape for
the sum, and the row counts here are trivial — the caps in §3 bound a user to at
most a few dozen rows per week.

### 7. Per-subject XP needs a column that does not exist

S-29 requires boards "for basis — total XP or per-subject XP", and `xp_events`
has **no subject attribution at all**. Two additive changes, which together are
the only XP-related schema work P5 does:

1. **`xp_events.subject_id`, nullable, FK to `subjects`.** — **SUPERSEDED BY D5.2:
   this is `subject_code`, a String FK to `subjects.code`, because all eight
   other subject-scoped tables key on the code and every award seam already
   carries one.** The rest of this item stands. Nullable because not
   every award has a subject — a flashcard review does, a future account-level
   award might not. Per-subject boards filter on it; total boards ignore it.
   Storing it in the `metadata` JSONB instead was rejected: it is a real foreign
   key with real referential integrity, and it must be indexable.
2. **A uniqueness constraint for idempotency** — see §8.

Additive-only, consistent with D1.2/D1.3.

### 8. Idempotency is enforced by the database, not by care

A paper can be re-marked. A teacher can override a result. A plan session can be
un-completed and completed again. None of those may re-award XP, and "we only
call the award function once" is not a control that survives a year.

Every award carries a **`dedupe_key`** derived from the identity of the thing
that caused it (the paper id, the assignment id, the plan-session id, the
flashcard-review id), and a **unique index over `(user_id, source, dedupe_key)`**
makes a double award a database error rather than a leaderboard anomaly. The
award path treats a uniqueness violation as a no-op success, not a failure —
re-marking a paper is a legitimate act that simply earns nothing new.

This is also what makes the caps in §3 safe to evaluate optimistically: the
worst case of a race is a rejected insert, not a double count.

### 9. Opt-out

**`student_profiles.leaderboard_opt_out`, boolean, not null, default false**
(additive; `student_profiles` arrived in migration 0009, and leaderboards are a
student-only surface so the flag belongs with the student profile rather than
with `users`).

Semantics:

- An opted-out student is **absent from every board**, including boards their
  own friends see. There is no "hidden but still ranked" halfway state.
- They **keep earning XP**, keep their streak, and still see their own totals on
  S-31. Opting out is about being *ranked publicly*, not about leaving the
  system, and it must be losslessly reversible — no XP history is deleted, so
  opting back in restores their position exactly.
- Their own S-29 shows their XP without ranks, and says plainly that they have
  opted out with a route to undo it. A blank screen would read as a bug.
- **Enforced in the query's WHERE clause, not filtered in the DTO layer.** A row
  that never leaves Postgres cannot leak through a serialization bug, a logging
  statement, or a future endpoint that reuses the repo function and forgets the
  filter. Same reasoning as §0's no-join rule: put the guarantee where it is
  structural.

### 10. What this spec deliberately does not decide

Named so a later task does not read the silence as an oversight:

- **Achievements/milestones** (UI spec S-31) — the screen mentions them; no
  schema exists and MISSION §4's Phase-5 bullet does not list them. Out of scope
  unless P5.8 finds the screen unbuildable without them, in which case it gets
  its own decision record.
- **Level thresholds.** S-31 says "total XP and level". The mapping from XP to
  level is a display concern with no schema implication; P5.8 fixes it and
  records it, so long as it is a pure function of total XP.
- **XP for a *teacher* or *parent*.** `xp_events.user_id` is a `users` FK, so the
  schema permits it. The product does not: engagement mechanics are a student
  surface. P5 awards XP to students only.

---

## D5.2 — D5.1 §7 was wrong: `xp_events` keys subjects by code, not by UUID (P5.2 chunk A)

D5.1 §7 specified **`xp_events.subject_id`, nullable, FK to `subjects`** — a
UUID pointing at the `subjects.id` surrogate key. The P5.2 implementation built
exactly that, and flagged it rather than quietly following the house style. The
flag was right and the spec was wrong.

**Every other subject-scoped table in this schema keys on the code, not the id.**
Eight of them, with no exceptions: `papers`, `quizzes`, `quiz_questions`,
`flashcard_decks`, `study_plans`, `student_subject_enrolments`, `attempts`,
`announcements`. Only two foreign keys in the entire model layer point at
`subjects.id`; two point at `subjects.code`, and the `subject_code` *column*
convention is universal.

**Why this actually mattered rather than being cosmetic.** Every award seam P5.2
chunk B is about to wire — a corrected paper, a submitted quiz, a reviewed
flashcard deck, a completed plan session — already carries a `subject_code` and
none of them holds a subject UUID. A `subject_id` column would therefore have
forced a code-to-UUID lookup at *every single award call site*, to store a value
no caller possesses, purely to satisfy a line in a spec. That is a per-call-site
query and a per-call-site failure mode bought for nothing.

**Corrected to `subject_code`, nullable `String`, FK to `subjects.code`**, with
`ix_xp_events_subject_code`. Migration 0013 was amended before being committed,
so there is no second migration and no schema churn. `XpService.award` now takes
`subject_code: str | None` and does no UUID coercion on it.

**The process point is the reusable one.** D5.1 was written from the UI spec and
MISSION without reading the model layer's existing subject convention, and it
specified a column shape that contradicted eight tables. It was caught because
the implementation was briefed to *implement the spec and report disagreement
rather than silently deviate* — so the divergence arrived as a labelled note in
a migration docstring instead of as an inconsistency discovered months later.
A spec written above the code is worth having; it is not automatically right
about the code, and the brief that lets an implementer say "this is wrong" is
what makes the difference.

---

## D5.3 — The `paper_corrected` dedupe key is the upload id, not the attempt id (P5.2 chunk B)

P5.2 chunk B wired the four XP award seams. Three were uncontroversial. The
`paper_corrected` seam shipped its first implementation keyed on
**`str(attempt_id)`** — the id `AttemptRepository.persist_correction` returns —
because that is what the implementation brief's table said to use. **The brief
was wrong, and D5.1 §8 already said so.**

§8 opens: *"A paper can be re-marked. A teacher can override a result. A plan
session can be un-completed and completed again. None of those may re-award
XP."* It then names the dedupe identity as **"the paper id"**.

`persist_correction` inserts a **fresh `Attempt` row on every call**. So an
attempt-keyed dedupe key is re-minted on every re-correction, the partial
unique index over `(user_id, source, dedupe_key)` never fires, and a student
re-running `/student/correct` on the same uploaded paper earns another 50 XP
every time — bounded only by the 5/day `paper_corrected` cap, i.e. **250 XP/day
from one PDF**. That is the exact leaderboard anomaly §8 exists to prevent, and
it is the cheapest farm in the whole system: re-marking costs the student one
click.

**Corrected to `str(owned.id)`, the `student_uploads` row** — the stable
identity of "this paper" that the endpoint has already resolved and
ownership-checked before streaming starts. Re-marking still works, still
persists a second attempt, and now earns nothing new, which is precisely what
§8 asks for.

**Two things worth keeping from how this was caught.**

1. The implementer **flagged it rather than silently following the brief**,
   as the same standing instruction that produced D5.2 required — it reported
   that the seam "is not idempotency-safe by construction" and declined to
   change the key unilaterally, calling it a product decision. It was right
   that it was a decision and wrong that it was out of scope: D5.1 §8 had
   already made it. A flag that names the defect precisely is worth more than
   a silent fix, because it arrived with the reasoning attached.
2. **The regression test was verified by inversion**, not assumed. With the
   key reverted to `attempt_id`, `test_re_correcting_the_same_paper_does_not_re_award`
   fails on `2 != 1` xp_events rows and `test_paper_corrected_awards_xp` fails
   on the dedupe-key assertion; both pass with `owned.id` restored. The test
   also asserts that **two `Attempt` rows exist** after the second correction,
   so it cannot pass vacuously by the pipeline having refused to re-run — a
   green from "nothing happened" would be worthless here.

**The general lesson, which is the same one as D5.2 from the opposite
direction.** D5.2 was the spec being wrong about the code. This is the *brief*
being wrong about the spec: the orchestrator's task table paraphrased D5.1 §8
and lost its meaning, while the authoritative sentence sat in DECISIONS.md
unchanged. A restated requirement is a copy that can drift. Where a brief
paraphrases a spec, the spec wins, and the implementer should be reading it —
which is why the brief pointed at D5.1 by line number rather than only
summarizing it.

**`flashcard_reviewed` is deliberately NOT analogous** and was left alone. Each
review mints a genuinely new review id because reviewing a card again is a real,
repeatable act the SM-2 scheduler depends on; two reviews of one card correctly
award twice. Its anti-farming control is the 60-cards/day cap in D5.1 §3, not
dedupe. `tests/test_web_xp_awards.py::test_flashcard_reviewed_two_reviews_of_the_same_card_both_award`
pins that reading so a later reader does not "fix" it into the paper seam's shape.

---

## D5.4 — Students belong to a school through a `Seat`, not a `SchoolMembership` (P5.3 chunk A)

The P5.3 brief specified the school leaderboard scope as "students holding a
`school_memberships` row for the viewer's school". **That is not what the table
means.** `SchoolMembership`'s docstring says "Staff member (teacher or
school_admin) association with a school", and `MembershipRole` has exactly two
values — `teacher` and `school_admin`. **No student ever gets a
`SchoolMembership` row.**

Scoping the school board on that table would have compiled, typechecked, passed
lint, and returned an empty board for every real student forever — the school
scope would have reported itself permanently "unavailable" and looked like a
data problem rather than a code defect.

Students are linked to a school through **`Seat`** (`seats.school_id` +
`seats.assigned_user_id`, status not `revoked`), which is how
`lemely/db/class_repo.py` and `lemely/db/seat_repo.py` already resolve the same
question. The leaderboard's school scope uses that.

**This is the same failure mode as D5.2** (`subject_id` vs `subject_code`) and
worth naming as a pattern rather than a one-off: *an orchestrator brief that
paraphrases the schema from memory is not a source of truth about the schema.*
D5.3 recorded the spec-level version of this ("where a brief restates a spec,
the spec wins"); this is the model-level version. **Read the model before
keying a query on it.** Both times the implementing agent caught it by reading
the table rather than trusting the brief, and both times the brief was wrong in
a way that no gate would have caught — an empty board is not a test failure.

### Two smaller calls made in the same chunk

- **`RANK()` ties.** The first cut ranked with
  `RANK() OVER (ORDER BY xp DESC, user_id ASC)`. Postgres decides ties over the
  *whole* `ORDER BY` tuple, so two students on equal XP received ranks 1 and 2
  instead of 1 and 1. The tiebreak now lives in the outer query's `order_by`,
  where it fixes display order without touching rank values. D5.1 §0's spirit
  applies: equal effort must read as equal standing.
- **The opt-out join must be an outer join.** `student_profiles` rows are
  created on first touch, so a student who never completed onboarding has no
  row. An inner join for the `leaderboard_opt_out` filter would have erased
  exactly those students from every board — the null-safe
  `coalesce(leaderboard_opt_out, false) = false` predicate treats "no profile"
  as "has not opted out", which is the only correct reading. Pinned by a test.

---

## D5.5 — A leaderboard never falls back to a student's email (P5.3, from adversarial review)

The rest of this codebase resolves display identity as `display_name or email`
— `lemely/db/quiz_taking_repo._display_name` and several siblings each
re-declare it locally. P5.3's `LeaderboardService.display_names_for()` copied
that pattern, and the adversarial review caught it.

`users.display_name` is **nullable at signup** (`lemely/web/routers/auth.py`),
so the fallback fires for real users, not hypothetical ones. The reason it is
safe everywhere else is audience: a quiz result list is seen only by the class
that sat the quiz. **A leaderboard is the one surface in this product where
that assumption does not hold.** `LeaderboardScope.global_` shows every ranked
student on the platform to every other student, so the identical line
broadcasts a real contact address to an audience of strangers.

D5.1 §0 reasons about the leaderboard from exactly this premise — it is the one
public surface, which is why it must not carry a mark. A contact address is not
a mark, so this does not violate §0 literally; it undercuts the same premise
§0 protects, and it is not information a ranking needs in order to rank.

**Decision: an unnamed student ranks normally under a neutral placeholder**
(`ANONYMOUS_DISPLAY_NAME = "Student"`). Anonymity is not exclusion — they keep
their rank, their XP and their position. `display_names_for()` no longer
selects `users.email` at all, so the address cannot leak through a later
serialization change either; the column is simply absent from the query. This
is the same "make it structurally unreachable rather than carefully handled"
reasoning as D5.1 §9's opt-out-in-the-WHERE-clause rule.

Pinned by `tests/test_web_leaderboard.py::test_a_student_without_a_display_name_is_never_shown_by_email`,
which asserts over the **response body** (what actually leaves the server, not
what the repo intended) and includes the strong form: no `@` anywhere in the
payload.

**Not adopted from the same review:** `board()` issues three queries (top rows,
viewer XP, viewer rank) without pinning them to one snapshot, so a concurrent
award mid-request can make the viewer's own row disagree with the returned
top-N by a few XP. Left as-is deliberately — it self-corrects on the next
request, a leaderboard is an inherently stale read, and a REPEATABLE READ
transaction would be real cost for a discrepancy no user can perceive.
Recorded so a future reader knows it was seen and judged, not missed.

---

## D5.6 — The friends model: a friend code, one canonical row per pair, and no tombstone (P5.4 chunk A)

D5.1 governs P5.4 but says nothing about the friendship *table* — §10 lists
what the spec deliberately leaves open and friends is not among the listed
omissions, so these are P5.4's decisions to make and record.

### 1. S-30's "add by username" is unbuildable as written

UI spec S-30 asks for "add by username or invite link". **`users` has no
`username` column** — checked against the model, not assumed. The two
obvious substitutes are both wrong:

- **Search by `display_name`.** Not unique, so a lookup is ambiguous, and
  worse, it lets any student type a common name and enumerate strangers.
- **Search by email.** This is precisely the leak D5.5 closed on the
  leaderboard three days ago, re-opened in a new place.

So: **`users.friend_code`**, `String(8)`, **nullable**, **unique**, minted
lazily on first read by `FriendService.friend_code_for`. It serves both of
S-30's affordances — type the code, or share a link containing it — and it is
non-enumerable, which a display name is not.

Details that are decisions, not incidentals:

- **Alphabet `ABCDEFGHJKMNPQRSTUVWXYZ23456789`** (no `0/O`, no `1/I/L`). A
  friend code is read aloud or typed off a screenshot, and those are exactly
  the pairs where transcription fails.
- **`secrets.choice`, never `random`.** The code is a lookup key handed to
  strangers.
- **Nullable, minted lazily, not backfilled.** A `NOT NULL` backfill would
  have to invent a code for every teacher, parent and admin who will never
  hold one.
- **Honest limitation:** there is no rate limit on code lookup. 8 characters
  from a 31-symbol alphabet is ~2^40 of space, which makes blind enumeration
  impractical, but the real control for a guessing attack is rate limiting
  and this build has none anywhere. Recorded rather than papered over.

### 2. One row per pair, enforced by Postgres

`friendships` stores one direction of *record* (`requester_id`,
`addressee_id` — who asked whom is real information S-30 needs for "requests
in and out") plus a second, order-independent representation of the same two
parties: `pair_low`/`pair_high`, always the smaller/larger id.

"A and B are friends" must be unique regardless of who asked, and a unique
constraint on `(requester_id, addressee_id)` admits both A→B and B→A. The
natural fix — a unique index on `(LEAST(...), GREATEST(...))` — is not
available, because Postgres will not index a non-`IMMUTABLE` expression. So
the canonical pair is materialised into two real columns, with
`uq_friendships_pair` unique over them and **three CHECK constraints**
(`ck_friendships_no_self`, `ck_friendships_pair_ordered`,
`ck_friendships_pair_matches_parties`) making it impossible for the pair
columns to disagree with the parties.

This is **D5.1 §8's principle applied to a second table**: "idempotency is
enforced by the database, not by care". `tests/test_friend_repo.py` pins it
by inserting the reciprocal row *directly through the session* and asserting
an `IntegrityError` — the guarantee is worthless if only the service layer
respects it.

The same structure answers the crossed-requests case: if both students press
"add" before either sees the other's request, `FriendService.request`
**accepts the existing reverse-pending row** rather than attempting a second
insert the unique index would reject anyway. Two people who both ask to be
friends must end up friends, not deadlocked on whoever called the API second.

### 3. Two statuses, and no tombstone

`friendshipstatus` has exactly `pending` and `accepted`. Decline, cancel and
unfriend are all the same database act — deleting the row — so
`FriendService.remove` is one method covering all three, and separate ones
would have differed only in the word used in an error message.

**Consequence, stated rather than discovered later:** a removed friendship
leaves nothing behind, so a declined request can be re-sent immediately.
That is deliberate (re-friending after a mistaken decline must work), and it
means **P5 ships no block/mute**. Blocking is a moderation feature; it is not
in MISSION §4's Phase-5 bullet, and S-30's "blocked/removed" state list is
the only place in the spec that mentions it. Carrying it forward as a known
limitation is honest; a `blocked` enum value with no enforcement anywhere
would not be.

### 4. Errors never confirm what the caller cannot see

`accept` and `remove` raise the **same** `FriendRequestNotFoundError` whether
the friendship does not exist or exists between two other people — and the
requester trying to accept their own request gets that same error, not a
distinct one. Same reasoning as P5.3's `LeaderboardClassAccessError`
collapsing "no such class" into "not your class": an error that distinguishes
the two is an existence oracle.

### 5. Opt-out on a friends *list* is not opt-out on a *board*

D5.1 §9 says an opted-out student is absent from every board, **including
boards their own friends see**. The friends leaderboard honours that
unchanged — the opt-out lives in `_ranked_subquery`'s WHERE clause and the
new `friends` scope inherits it for free.

A friends *list* is not a board. It has no ranks, and the relationship is
mutual and consented to by both parties, unlike a leaderboard that shows a
student to classmates who never opted into being compared with them. Removing
an opted-out friend from the list would also make them **unremovable** — you
cannot unfriend someone you cannot see.

So `list_friends` keeps them, and returns `xp=None, streak=None,
opted_out=True`. The UI states the fact instead of rendering a fabricated
`0`, which UI spec §1.4 forbids. Note this is the *stricter* reading on the
numbers and the *looser* one on presence, and both follow from the same
question: what did this student actually consent to?

### 6. Smaller calls made here

- **The friends board includes the viewer's own id explicitly.** The other
  three scopes get the viewer for free — class/school/global membership is
  defined in terms of something the viewer already belongs to — but no
  friendship row names the viewer as their own counterparty, so without the
  extra union term a student would be unranked on their own board.
- **An empty friends board is an honest board of one, not `unavailable`.**
  S-29's "too few friends to rank" is a display state read off `len(rows)`;
  a new `LeaderboardUnavailableReason` would push a presentation decision
  into the query engine.
- **`friends` XP is lifetime, not weekly.** S-30 asks for "XP and streak"
  with no window, unlike S-29's explicitly weekly board.
- **The leaderboard reads `friendships` directly** rather than calling
  `FriendService`, matching what that module already does with
  `ClassEnrollment`/`Seat`.

## D5.7 — A lost insert race in `FriendService.request` must answer 409, not 500 (P5.4, from adversarial review)

**Found by the P5.4 reviewer subagent (MISSION §6 gate 7), confirmed by reading the
code, fixed before P5.4 was marked done.**

`FriendService.request` resolved an already-existing pair by SELECTing it first
(duplicate ask → `FriendAlreadyExistsError`; reverse-pending → accept the crossed
request). The genuinely-new-pair branch then inserted with no `IntegrityError`
handling at all. Two callers can both pass the `existing is None` check for the
same never-before-seen pair, and the loser's INSERT violates `uq_friendships_pair`.

**The reason this was worse than it looks:** the insert was a bare
`session.add()` + `flush()` inside `with session.begin()`, so under a real race
the violation surfaces on **COMMIT — after `request()` has returned**, outside any
frame the router can catch. `routers/friends.py` catches only the `Friend*` domain
errors and `ValueError`, so the honest outcomes (409 duplicate, or 201-with-accepted
for a crossed request) degrade to a raw **500**. Concrete: two tabs open for student
A both `POST /requests` with B's code on their first-ever contact — one gets 201, the
other a 500.

**Decision.** Wrap the insert in `session.begin_nested()` and catch `IntegrityError`,
exactly as `friend_code_for` already does for `uq_users_friend_code` (and `xp_repo`
does for its dedupe index) — this is the house pattern, not a new one. On a
`_is_pair_violation` match, re-read the winning row and resolve it through the *same*
`_resolve_existing_pair` helper the sequential path uses. Any other `IntegrityError`
(foreign key, one of the three CHECKs) still propagates.

- **The savepoint is the load-bearing part, not the `except`.** Without
  `begin_nested()` the error cannot be caught here at all, because it is not raised
  here — it is raised at the transaction boundary.
- **The resolution branch is shared, not duplicated.** A concurrent insert and a
  sequential one produce the same outcome by construction, so the two paths cannot
  drift.
- **The re-read is sound under READ COMMITTED**: the losing INSERT blocks until the
  winner commits, so a fresh SELECT after the savepoint rollback always sees it.
- **Not a security or integrity defect** — the database constraint always won, no
  duplicate or reciprocal row was ever possible (D5.6 holds). This is purely about
  the service translating a DB truth into an honest HTTP answer.

**Proven by inversion, not assertion.** `tests/test_friend_repo.py` blinds the first
`friendships` SELECT — which is exactly what losing the race does to it — and lets
everything downstream run for real against the real index. Only the missed SELECT is
simulated; a genuinely concurrent commit cannot be staged deterministically
single-threaded.

**What inversion actually shows** (re-run in the forty-first session with the
`begin_nested()` replaced by a bare `if True:`, rather than carried over as a claim):
both new tests fail, but *not* with the `IntegrityError` surfacing on COMMIT as this
entry first said. Without the savepoint the failing `flush()` raises `IntegrityError`
immediately and **poisons the enclosing transaction**, so the recovery SELECT dies
first with `sqlalchemy.exc.InvalidRequestError: Can't operate on closed transaction
inside context manager`. The conclusion is unchanged and the fix is unchanged — an
uncaught exception out of `request()` is a 500 either way — but the mechanism is
worth stating correctly: a savepoint is what makes the error *recoverable at all*,
not merely *catchable here*. Once the outer transaction is poisoned there is nothing
left to re-read with.

**Method note, the fourth instance in Phase 5.** D5.2/D5.3/D5.4/D5.5 were all "a
brief or a convention was trusted where the schema or spec should have been read."
This one is different and worth naming separately: **the invariant was correctly
enforced in the database and the service simply had no story for being told so.**
A CHECK or unique index is a guarantee, not an error handler — every place that can
provoke one needs a decision about what the user sees when it fires.

---

## D5.8 — The exam calendar ships with a real table and no dates (P5.5 chunk C)

**Decision: build `exam_dates`, build a strict ingestion path, and ship the
student surface honestly empty. Do not populate a single row.**

### The measurement that forced it

There is **no CAIE timetable data anywhere on this machine.** `Sources/` holds
AdditionalMathematics/Mathematics/Physics *mark schemes* and four solved
scripts; the PaperScraper corpus at `/home/sico/PaperScraper/papers/CAIE/`
holds 648 question papers and grade-boundary documents. Neither contains a
timetable, and `find -iname "*timetable*" -o -iname "*calendar*"` over both
returns nothing. The scraper has no timetable route — the artifact lives in a
separate official CAIE timetable PDF this build has no path to.

MISSION §4 Phase 5 says "auto-populated official CAIE session dates". The
*auto-populated* half is unbuildable without the source document. Three
options existed:

1. **Invent plausible dates.** Rejected. IGCSE sessions do cluster in May/June
   and Oct/Nov, so a generated date would look right and be wrong by days.
2. **Skip the feature.** Rejected — the table and ingestion are the expensive,
   design-bearing part, and deferring them means P5.8's screen has nothing to
   consume and the work lands twice.
3. **Table + ingestion + honest empty state.** Chosen. The tri-state
   availability pattern P4.5 established for the practice generator (D4.10),
   applied to a second surface that must refuse rather than fabricate.

### Why inventing here is worse than inventing anywhere else

UI spec §1.4 forbids invented precision generally. This screen sharpens it: the
exam calendar's entire purpose is a **countdown a student plans revision
around**. A missing date disappoints. A wrong date actively misdirects study
scheduling toward the wrong week, and the student has no way to detect it —
the app is the authority they are consulting precisely because they do not
know the date. A wrong exam date is not a degraded feature; it is harm
delivered confidently, which is the same failure shape as D3.21's paper 22.

### The design decisions inside the table

- **The grain is the paper *variant*, not the paper number.** The official
  timetable dates components (`0625/22`), and variants of one paper number can
  sit on different days in different zones. Storing at number grain would have
  forced the ingester to pick one real date and discard the others — invented
  precision arriving through the back door. `paper_number` is stored *beside*
  the variant because it is the only key the read path can join on
  (`student_enrolment_papers.paper_number` is what a student declares, P4.3),
  and it comes from the source document rather than from parsing a digit out
  of the variant string.
- **`source` is `NOT NULL`.** A row that cannot name the document it came from
  is indistinguishable from an invented one. It is also on the wire, so a
  student or teacher who believes a date is wrong can name the timetable
  rather than argue with the app.
- **`uq_exam_dates_variant` makes ingestion idempotent by database, not by
  care** — the fourth table in Phase 5 to make that choice (0013, 0015, 0016).
  Timetables get republished with corrections, so re-ingest must *update in
  place*; appending would put one paper on a student's calendar twice with two
  different dates, which is worse than having no calendar.
- **A batch that contradicts itself is rejected whole.** Two lines claiming the
  same variant with different dates means the document disagrees with itself.
  Last-one-wins would let a stale line silently overwrite a correct one.
- **Nothing is defaulted at parse time.** A missing `paperNumber` is not
  inferred from the variant, a missing `sessionYear` is not taken from the
  current year, and one bad entry rejects the document rather than ingesting
  the good rows. Each convenience would manufacture a fact about a real exam.
- **`starts_at_local` is a string, not a `Time`.** The document prints a
  wall-clock time in a zone this table does not model; coercing it to a typed
  time would imply a precision about *which* zone we do not have. A missing
  time is `None`, never midnight.

### Three empty causes, kept apart

`no_enrolment` (the student has not said what they are sitting),
`no_timetable` (they have, and we hold no official dates), and per-paper
`no_session` (that enrolment names no session). Collapsing the first two would
tell a student who never onboarded that *Cambridge* has not published dates —
a false statement about a third party, and one that hides the action the
student could actually take. Pinned by tests.

### Past dates are deliberately not filtered

The read path does not compare anything to "now" — the service takes no clock.
A session's components sit within a few weeks of each other, so dropping past
dates would empty a student's calendar halfway through their own exam series
and make `no_timetable` — the state that means "we have no data" — fire when
we hold all of it. The screen decides what a past date looks like.

### There is no ingestion route

Loading a timetable is an operator act against a published document, not a
request any authenticated user makes. Exposing it over HTTP would put the one
write path capable of publishing a wrong exam date behind nothing but a role
check. Pinned by a test asserting the router's OpenAPI surface is exactly one
`GET`.

### The honest gap, stated rather than hidden

**There is no CLI wrapper around `ExamCalendarService.ingest` yet.** The
ingestion path is the service plus `parse_timetable_payload`, both fully
tested; loading a real timetable today means calling them. A `lemely
ingest-exam-timetable <file>` command is a thin wrapper and the natural next
step, deliberately not built speculatively (MISSION §8b) while no document
exists to feed it. **Carry this into the Phase-5 limitations list**, together
with the empty table itself — neither is a defect to quietly fix, and neither
may be closed by generating data.

## D5.9 — The notification spec: the inbox is the record, push is a side effect (P5.6, written before any implementation)

**MISSION §4 Phase 5 mandates spec-before-code for the engagement layer, the
same ordering P5.1/D5.1 followed for XP.** This is that spec. Every claim about
existing schema below was verified by reading the models on 2026-08-10, not
carried from the phase plan — five earlier Phase-5 tasks were mis-briefed by a
note paraphrasing the codebase from memory (D5.2, D5.4, D5.5, and both of
P5.5's deps predictions).

### 0. What already exists, measured

- **`notifications` (`lemely/db/models/ops.py:140`) exists and has zero
  writers.** Columns: `id`, `user_id`, `type`, `title`, `body`, `payload`
  (JSONB, defaults `{}`), `read_at`, indexed on `(user_id, read_at)`.
  `grep -rln "Notification("` over `lemely/` excluding `models/` returns
  nothing — no repo, no service, no route, no call site. **No migration is
  needed for the inbox**, same situation P5.2 found for `xp_events`.
- **`NotificationType` has exactly five values** (`enums.py:164`):
  `grade_ready`, `announcement`, `streak_warning`, `study_plan_reminder`,
  `at_risk_alert`. These are precisely MISSION §4's four student triggers plus
  the teacher/parent at-risk alert. **No enum value needs adding.**
- **`notification_preferences` (`ops.py:335`) already carries one boolean per
  type, under the same five names**, all `NOT NULL DEFAULT true`, plus
  `quiet_hours_start`/`quiet_hours_end` (nullable `Time`).
  `NotificationPreferencesService.get/set` reads and writes them today and
  `routers/me.py` exposes them. **So "make preferences gate delivery" needs no
  schema work at all** — the toggles have existed since migration 0008 and
  what is missing is a consumer.
- **Nothing anywhere mentions VAPID or push subscriptions.** The
  push-subscription table is this task's **only** migration.
- **There is no scheduler in this build** — no cron, no Celery, no APScheduler,
  nothing in `pyproject.toml`. This constrains §5 below.

### 1. The inbox row is the source of truth; push is a best-effort side effect

A notification is **a row in `notifications`**. Web push is one *delivery* of
that row to one device. Push therefore:

- never decides whether a notification exists,
- never fails the user action that produced it,
- never fails the inbox write.

This is D5.1 §3's fail-open reasoning ("the learning wins") applied a second
time, and it reuses the shape already proven in
`lemely/web/xp_awards.py::award_xp_safely`: the notify call sits at the router
layer after the action has committed, wrapped in a helper that logs and
swallows. A student whose grade is ready must not get a 500 because a push
endpoint was unreachable.

### 2. A type toggle suppresses the row; quiet hours suppress only the push

These two preferences mean different things and must not be collapsed:

- **A type toggle off is a content preference** — "do not notify me about
  this". So it suppresses **the row as well as the push**. An inbox that fills
  with items the user explicitly said they did not want is not a feature.
- **Quiet hours are a timing preference** — "do not buzz my phone at 2am". So
  they suppress **the push only; the row is always written** and the user sees
  it when they next open the app.

**Suppressing a row loses no information, and that is what makes this safe.**
No notification is the sole record of anything: a ready grade is on the results
screen, an announcement is in P5.5's announcements list (which owns its own
read-receipts), a streak is on the dashboard, a study-plan session is in the
plan. The notification is a pointer, never the data. If that ever stops being
true for a new type, this decision must be revisited rather than extended.

**Default is opted-in.** `NotificationPreferencesService.get` returns an
all-defaults row for a user who has never configured anything, so "no row"
means "wants everything" — the gate must never read a missing row as opt-out.

### 3. Parent at-risk alerts consult the parent's own preferences

MISSION §4: at-risk alerts go "to the teacher and (if opted-in) parent". The
opt-in is **the parent's**, read from the parent's own
`notification_preferences.at_risk_alert` row. Reading the *student's* row
would let a student silence alerts about themselves to their own parent, which
inverts the point of the feature and quietly breaks UI spec §1.4's teacher
authority.

### 4. The transport seam, and why it is a protocol

Web push cannot be exercised from a headless test, and MISSION §4's acceptance
explicitly asks for "push delivery (headless push mock)". So:

- a `NotificationTransport` **protocol** with `send(subscription, payload)`,
- a real VAPID implementation,
- a **recording in-memory double** that captures what would have been sent,
- selected in `deps.py` like every other service, and reset by
  `reset_singletons()`.

**VAPID keys come from `lemely/runtime/config.py` `Settings` and their absence
is not an error.** With no keys configured the transport reports itself
unavailable, logs once, and the inbox keeps working — this build has no keys,
so a hard requirement would make every notification fail in the exact
environment the tests run in. Same tri-state honesty as D4.10/D5.8: available,
unavailable-for-a-named-reason, empty.

**A dead subscription is deleted, not retried.** A push service answering 404
or 410 means the browser subscription is permanently gone; keeping it produces
a growing table of endpoints that can never succeed.

### 5. What cannot be built here, stated now rather than discovered later

`streak_warning` and `study_plan_reminder` are **time-triggered, not
action-triggered** — nothing a user does produces them. With no scheduler in
this build, P5.6 ships the *service method* that computes and sends each one,
plus a manual entry point, and **nothing invokes them on a timer**. That is the
honest deliverable and it goes in the Phase-5 limitations; inventing a
scheduler daemon in an engagement task is out of scope and would be untested
infrastructure. `grade_ready`, `announcement` and `at_risk_alert` are all
action-triggered and are wired to real seams.

### 6. Dedupe: the same lesson as D5.3, applied before it bites

`grade_ready` keys on **the upload**, not the attempt. `persist_correction`
inserts a fresh `Attempt` on every call, so an attempt-keyed notification
re-fires every time a student re-runs a correction on one PDF — this is
exactly the defect D5.3 found in the XP paper seam, and it is written down here
*before* implementation so it is not re-discovered a second time.
`announcement` keys on `(announcement_id, user_id)`.

## D5.10 — Push carries no payload: VAPID auth only, and the service worker fetches the inbox (P5.6 chunk B)

D5.9 §4 fixed the *seam* (a `NotificationTransport` protocol, a real VAPID
implementation, a recording double, chosen in `deps.py`) but deliberately left
the wire format open. This is that choice, made before the implementation
because it is load-bearing and hard to reverse once a service worker ships
against it.

**The decision: send RFC 8030 push messages with an empty body, authorised by
an RFC 8292 VAPID `Authorization` header, and no RFC 8291 content encryption.**
The push tells the browser *that* something happened; the service worker then
calls the authenticated inbox API to find out *what*.

### Why this is the right shape, not merely the cheap one

D5.9 §1 already fixed the architecture: **the inbox row is the source of truth
and a push is one delivery of it.** A payload-carrying push contradicts that by
making the push message a second, independent copy of the notification — one
that can disagree with the row, and one that must be encrypted precisely
because it holds content. A payload-less push is the same architecture stated
on the wire.

It also removes a real disclosure. An encrypted-payload push still routes a
student's notification title and body through Google's, Mozilla's or Apple's
push infrastructure. Payload-less, **nothing about a student ever transits a
third-party push service** — the endpoint URL and a signed assertion that we
are who we say we are, and that is all. The content is fetched from us, over
the same authenticated API that already gates every other read.

### What it costs, stated now

A browser requires that *some* notification be shown for each push it
delivers. With no payload, the service worker must fetch the inbox first, so a
push that arrives while the device is offline — or whose fetch fails — shows a
generic "You have a new notification" rather than the real title. That is a
genuine degradation and it belongs in P5.9's service-worker brief and the
Phase-5 limitations, not hidden here.

### The dependency arithmetic that made the alternative unattractive

`pywebpush` is the standard payload-carrying implementation and it **is**
installable here (verified: `uv pip install --dry-run pywebpush` resolves
cleanly). It would add **11 packages**, including `aiohttp` — an entire second
HTTP stack alongside the `httpx` this project already depends on — plus
`http-ece` and `py-vapid`. The alternative, hand-rolling RFC 8291's
ECDH/HKDF/AES128GCM against `cryptography`, was rejected for a different and
stronger reason: **it could not be honestly verified here.** Correct-looking
content encryption is only provable against a published test vector or a live
push service, and this build has neither. Generating a "test vector" from my
own implementation and asserting against it is exactly the invented precision
UI spec §1.4 forbids — it would prove the code agrees with itself.

Payload-less push needs neither. The VAPID JWT is ES256 over a three-claim
body and is verifiable *by decoding it*, which a test does directly with the
public key. **Zero new dependencies:** `pyjwt[crypto]` is already in the `db`
extra and `httpx` is already in the `web` extra.

### Reversibility

Swapping to payload-carrying push later means implementing one protocol method
behind the same seam. Nothing outside the transport module knows a payload
exists or does not — `NotificationService` never touches it, the routers never
touch it, and the recording double's shape does not change.

### Settings, and the absence of keys

VAPID material lands in a `[push]` block (`LEMELY_PUSH__*`): an application
server public/private key pair and a `sub` contact URI. **Their absence is not
an error** (D5.9 §4): with no keys the transport reports itself unavailable,
logs once, and the inbox keeps working. This machine has no keys, so any harder
requirement would fail every notification in exactly the environment the tests
run in. A `404`/`410` from a push service deletes the subscription through
`NotificationService.forget_endpoint`, per D5.9 §4 — a permanently gone browser
subscription is not a retryable failure.

## D5.11 — At-risk alerts fire on correction and dedupe per student, reason and day (P5.6 chunk C2c)

D5.9 fixed the transport, the gate and the fail-open rule, but left the
`at_risk_alert` seam open because at-risk had no event to hang on. This is that
choice, recorded before the code per MISSION §4's Phase-5 ordering.

**1. The seam is the post-correction point, and that is a real constraint, not
a convenience.** At-risk is computed **on read** today — `assess_at_risk` is
called from `routers/classes.py` when a teacher opens a class — so there is no
existing "a student became at-risk" event anywhere in the build. Manufacturing
one would mean either a scheduler (D5.9 §5 says there is none) or an
assessment-state table nothing else needs. A newly marked paper is the thing
that actually changes the answer: it is the input to rule 1 (declining trend
across the last N papers) and rule 2 (predicted grade below target). So the
alert is raised immediately after `grade_ready`, on the same already-committed
correction.

**2. Rule 3 cannot fire here, and this is stated rather than quietly omitted.**
"≥14 days inactive" is true of a student who is doing *nothing* — a student who
has just uploaded a paper is by definition active. Rule 3 is time-triggered and
joins `streak_warning` and `study_plan_reminder` in D5.9 §5's no-scheduler
limitation. The consequence is concrete: **the one at-risk reason most likely
to matter for a disengaging student is the one this build cannot deliver.**
That belongs in the Phase-5 limitations, not in a comment.

**3. The dedupe key is `(student_id, reason, civil date)`.** At-risk is a
*state*, not an event: a student whose trend is declining stays declining
across every paper they upload that week. Keying on the upload — the right
answer for `grade_ready`, which announces one specific artifact — would send a
teacher of thirty students one alert per upload per student, and a notification
stream nobody can read is worse than none. Keying on nothing but the reason
would collapse a term into one alert. A civil day is the cheapest honest bound,
and it is **`Africa/Cairo`, via `civil_date_in_zone`** — the same day boundary
D5.1 §4 fixed for streaks, reusing that helper rather than re-deriving one
(Cairo is UTC+3 in summer, so a hardcoded offset is wrong for half the year).
The recipient half of the key comes free from migration 0018's
`(user_id, type, dedupe_key)` unique index, as established in chunk C2b.

**4. Recipients are derived server-side, per recipient, from their own
preferences.** Teachers come from a new narrow `ClassService.teachers_for_student`
— the chunk's recon predicted `student_classes` would serve, and **it does
not**: `StudentClassRow` carries `class_id`/`name`/`subject_code`/`school_name`
and no teacher id at all. (Seventh time this phase that reading the model beat
paraphrasing a note.) Parents come from `ParentLinkService.list_parents`. Each
recipient's row is gated by **their own** `notification_preferences.at_risk_alert`
(D5.9 §3) — `notify_safely` already reads the recipient's prefs, so this is
free, but it is pinned by a test, because the failure it prevents is a student
silencing alerts about themselves.

**5. The alert names the student and the reason, never a mark or a grade.**
D5.9 §2 and UI spec §1.4 hold here even though the audience is staff: the row
is a pointer to the teacher's own at-risk view, which already renders the
evidence with its confidence intact. A grade on a lock screen is a grade on a
lock screen regardless of who is holding the phone.

---

## D5.12 — The device limit is disclosed by a 409 challenge on a re-authenticated login, never by an unauthenticated device list (P5.7, written before any code)

**Context.** UI spec G-10 ("Device limit reached") says the screen contains *a
list of the three currently signed-in devices, a clear statement that signing in
here will sign out the oldest, and a confirm action*. The backend already
implements the policy — `DeviceRegistry.register_login` (D1.11) locks the user
row `FOR UPDATE`, registers the new device, and evicts the oldest beyond
`MAX_DEVICES = 3` in the same transaction. Two things are missing, and neither is
the policy: **no route exposes a user's devices at all** (G-11's list and
individual sign-out), and **eviction is silent** — `DeviceRegistration` carries
`evicted_session_ids`, but `AuthService._register_device` returns only
`session_id` and drops them, so the client cannot know a device was signed out.
Verified by reading `lemely/db/device_repo.py`, `lemely/auth/service.py:123-140`
and `lemely/web/routers/auth.py`, not by trusting a note.

**1. The device list is never shown to an unauthenticated caller.** The naive
reading of G-10 — show the three devices *before* signing in, so the user can
decide — requires enumerating a stranger's devices from an email address alone.
That hands anyone who knows an email address a list of that person's browsers and
activity times. It is refused: **credentials are proven first, the challenge is
returned second.**

**2. The challenge is a 409 on the login itself, and the confirm is a re-sent
login.** When a login would evict, `POST /api/auth/login` answers **409** with
the three device summaries and **mints no token and evicts nothing**. The client
shows G-10 and, on confirm, re-sends the same login with
`confirmDeviceEviction: true`, which registers and evicts normally. The
alternative — a stateful, short-lived "confirmation ticket" — was rejected as the
more expensive and less reversible of the two: it adds a token kind, an expiry, a
store and a revocation story, to save a second credential check on a path that
fires only when a user is genuinely at three devices. Re-authenticating is also
the *stronger* guarantee: the confirm cannot be replayed by anyone who did not
just prove the password again.

**3. "Would this evict?" is answered inside the same lock that does the
evicting, never before it.** `register_login` grows `allow_eviction: bool = True`
and raises `DeviceLimitReachedError` from *inside* the existing `FOR UPDATE`
transaction when eviction is needed and not permitted. A separate preflight query
would be a TOCTOU: two tabs could both be told "no eviction needed" and both
evict. The default stays `True` so every existing caller — signup, phone-OTP,
the E2E seed — is unchanged.

**4. A re-login on a known device is never a challenge.** The `client_device_id`
match path reuses its slot and evicts nothing, so a user with three devices
signing in again on one of them sees no G-10. This is the common case and it must
stay silent, or the limit reads as broken.

**5. Rough location is deliberately absent from the device list.** G-10 asks for
it; this build has **no geo-IP source and does not store an IP address**, so a
location would have to be inferred or invented. UI spec §1.4 (never invent
precision) forbids that outright, and a wrong city beside "sign out this device"
is worse than no city — it is the field a user would make the decision on. The
list ships with device label, user-agent-derived description, and last-active
time, all of which are real. Carried to the Phase-5 limitations as an honest gap,
not silently dropped.

**6. Signing a device out is a revocation, not a delete, and is idempotent.**
`DeviceRegistry.revoke` already scopes to the caller's own devices and is
idempotent; the route reuses it. Revoking the *current* device is permitted and
is simply "sign out this browser" — the liveness check in `get_auth_context`
turns the caller's own next request into a 401 without any special case.

---

## D5.13 — The XP profile read route, and the level curve D5.1 §10 deferred to P5.8 (P5.8 chunk A, written before any code)

D5.1 §10 named two S-31 questions and explicitly left them here: *"the mapping
from XP to level is a display concern with no schema implication; P5.8 fixes it
and records it, so long as it is a pure function of total XP"*, and
*"achievements/milestones … out of scope unless P5.8 finds the screen
unbuildable without them"*. This is that record, plus the route S-31 needs.

### 0. The correction that made this a chunk at all

P5.8's brief said every backend these four screens need was already built and
gate-green. That is true of S-28, S-29 and S-30 and **false of S-31**.
`XpService` is wired into the web layer at **write seams only** — `deps.py`,
`xp_awards.py`, and the four award call sites in `student.py`, `quiz.py`,
`flashcards.py`, `study_plan.py`. Nothing reads. The read *methods* exist and
are covered (`xp_repo.py`: `total_xp`, `xp_breakdown(start, end)`,
`streak(now)`), so this is one thin router in the shape of P5.3's
`leaderboard.py`, not an engine. Eighth instance this phase of the codebase
beating a note; the standing rule holds.

### 1. The level curve

**`level(total) = isqrt(total // 100) + 1`.** Equivalently, level *N* begins at
**100·(N−1)² XP**: 0, 100, 400, 900, 1600, 2500, 3600 …

Why quadratic rather than linear. A linear curve makes every level cost the
same, so the number stops meaning anything once a student is past the first
month — it becomes a slow restatement of total XP. The quadratic makes the
first few levels arrive quickly (one paper corrected, at D5.1 §2's 50 XP, puts
a new student halfway to level 2 on their first day) and later ones a genuine
record of accumulated work, which is what UI spec S-31 asks the screen to feel
like: a training log. Against D5.1 §2's real earning rates — a student
correcting one paper a day earns 350 XP/week — that is level 2 on day 2, level
3 on day 8, level 4 on day 18, level 5 on day 32. A level roughly every two to
three weeks by mid-game, without a cap or a prestige mechanic to design.

**It is integer arithmetic on purpose:** `math.isqrt(total // 100)`. The
integer form is *exactly* the rule in the paragraph above — `isqrt(x // 100) >=
N` iff `x // 100 >= N²` iff `x >= 100N²`, because N² is an integer — so the
prose and the code cannot drift apart, and the equivalence is provable by hand
rather than by sampling.

> **Corrected in place after the code, and the correction matters more than the
> decision.** This paragraph first said the float form `floor(sqrt(total /
> 100))` is *wrong* at the boundaries, citing `sqrt(1600 / 100)` landing at
> 3.9999999999999996. **That was inverted and it is false**: swapping the
> implementation to the float form leaves all 62 tests in
> `tests/test_xp_levels.py` green, because at a boundary `100·N²` both the
> division and the square root are exact in IEEE 754 for any total this product
> can reach (the first inexact case needs a total above 2⁵³). The integer form
> is still what ships — its correctness does not *depend* on that
> floating-point argument holding for every input forever, while the float
> form's does — but the original reason was a failure mode nobody had
> reproduced. Same shape as P5.6 chunk C2b, where a guard was removed for being
> justified by a false comment, and D5.7, where an inherited "proven by
> inversion" claim turned out not to be the test it described. **Writing the
> reason before running the inversion is how a decision record acquires a
> confident sentence that is not true.** Invert first, then write why.

The route returns `levelStartXp` and `nextLevelXp` beside `level` so the screen
draws a progress bar without re-deriving the curve in TypeScript. **The curve
exists in exactly one place** (`lemely/web/xp_levels.py`); a second
implementation on the client is the sort of duplicate that stays right for a
year and then disagrees after one tweak.

### 2. The week is one definition, shared with the leaderboard

S-31's "XP earned this week" and S-29's weekly board must be the same week, or
a student reads two different numbers for one fact on two screens they can
switch between in a tap. `_week_bounds` was private to
`lemely/db/leaderboard_repo.py`; it moves to `lemely/db/xp_repo.py` as
**`week_bounds`**, beside `civil_date_in_zone` and `DEFAULT_ZONE`, which
`leaderboard_repo` already imports from. One definition, D5.1 §6's Monday
00:00 → Sunday 23:59:59 Cairo, used by both. Same reasoning as P5.6 chunk C2b,
where the announcement seam and the student read path were made to share one
predicate rather than derive the audience twice.

### 3. What the screen may show, and the thing it must not

UI spec S-31 lists "lifetime stats (papers marked, questions answered, hours
studied)". **Those are not shipped, and the reason is not that they were hard.**
The tempting source is `xp_events`: count the `paper_corrected` rows and call it
papers marked. That number is **wrong by construction** — D5.1 §3's daily caps
mean a capped award writes *no row at all*, so a student who corrected eight
papers in a day has five rows, and D5.1 §8's dedupe means a re-corrected paper
has one row for two markings. It would read as a precise lifetime count and be
neither precise nor a count. UI spec §1.4 forbids exactly that, and a wrong
number on a "record of real work" screen is worse than an absent one because the
student has no way to tell.

So the route is deliberately about **XP and the streak only**: total, level,
this week split by source, and the streak. `bySource` is XP per source, labelled
as XP, never as an activity tally. "Hours studied" has no source in this
schema at all and is not approximated. Carry to the Phase-5 limitations.

**Achievements/milestones stay out of scope** on D5.1 §10's own terms: S-31 is
fully buildable without them (streak, level and the weekly breakdown carry the
screen), no schema exists, and MISSION §4's Phase-5 bullet does not list them.

### 4. The streak calendar needs per-day data, so the route carries it

S-31 asks for "current streak with its calendar visualisation", and
`Standings.tsx`'s header comment records a 28-cell streak heatmap that P5.0
deliberately removed rather than mock. `StreakState` carries lengths and
`last_active_on` — enough for a number, not for a calendar. So `XpService`
gains one narrow reader, **`xp_by_day(user_id, start, end)`**, and the route
returns the last 28 days as `(date, xp)` pairs for days that earned XP.

It reports **XP per day, not a boolean "active"**, because the honest thing the
table knows is how much XP a day earned; "active" would be a derived claim about
attendance that the caps and dedupe rules can falsify in the same way §3
describes. Days with no XP are simply absent from the list — the client fills
the 28-cell grid from the window it asked for, so an empty day and a missing
day cannot be rendered differently by accident.

### 5. Route shape

`GET /api/student/xp`, its own thin router
(`lemely/web/routers/xp.py`), `require_role(Role.student)` at the router level,
mirroring P5.3's `leaderboard.py` exactly. **Identity is structurally
`auth.user_id`** — no caller-supplied user id parameter exists on the route, so
one student cannot request another's profile, and that is a property of the
signature rather than a check that a later edit could drop.

Non-students get 403 from the router guard rather than an empty profile; unlike
P5.6's deliberately role-agnostic notification router, this surface has exactly
one intended reader, because D5.1 §10 already fixed that XP is awarded to
students only.

## D5.14 — S-29/S-30 need two small backend additions, and one spec element is deliberately not invented (P5.8 chunk C, written before any code)

P5.8's brief says "every backend these screens need is already built". That was
true for S-28 and it is **nearly** true here — `GET /api/student/leaderboard`
and `GET/POST/DELETE /api/student/friends` are complete and gate-green. Reading
the code before writing the screen found two places where the built backend
cannot express what UI spec §S-29 names, and one place where it should not try.
This is the ninth time this phase that a note lost to the codebase, and the
correction is recorded here before the screen, not after it.

### 1. `scope=class` is unreachable from the student SPA today

`GET /api/student/leaderboard?scope=class` requires a `class_id`, and **no
student-facing route lists a student's classes**. `grep '@router.get'` over
`lemely/web/routers/student.py` returns overview / subject / result / standings
/ parent-links and nothing else; `/student/classes/join` is a POST. The only
readers of `ClassService.student_classes` are the *parent* portal's P-01 and
P-02 (`routers/parent.py:347`).

So the class tab is not "hard" — it is unaddressable. The two options were to
drop a quarter of the spec'd scope selector and record it, or to add the thin
read route. **Added: `GET /api/student/classes`**, reusing
`ClassService.student_classes` directly rather than deriving a second
`ClassEnrollment` query — that method's own docstring asks callers not to write
one ("do not write a second `ClassEnrollment` query anywhere else for that
purpose"), and honouring it is the reason the parent portal and this screen
cannot drift about what class a student is in.

`StudentClassRow` already carries exactly the four fields a tab needs
(`class_id`, `name`, `subject_code`, `school_name`), so the DTO is a projection
with nothing new computed. Identity is `auth.user_id` structurally — no
caller-supplied student id exists on the route, matching P5.3's and chunk A's
shape, so one student cannot enumerate another's classes.

### 2. The per-row streak indicator is built, not dropped

§S-29 fixes each row as "rank, avatar, display name, XP, streak indicator".
`LeaderboardRowDTO` carries the first, third and fourth and **has no streak
field**. Shipping without it was the cheaper path and was rejected for a reason
stronger than spec-completeness: **S-30 already shows a friend's streak**
(`FriendDTO.streak`, D5.6 §5), so the leaderboard's own `friends` scope would
render the same people, on an adjacent screen, with the streak silently missing.
An inconsistency between two screens about the same fact is read as a bug, and
here it would be one.

A streak is effort, not attainment, so it is squarely inside MISSION §3's
"leaderboards show XP (effort), never grades" and adds no grade-shaped field —
D5.1 §0's structural guarantee is untouched, and
`tests/test_schemas_leaderboard.py`'s field-set introspection is updated
deliberately in the same commit, which is exactly the acknowledgement that test
exists to force.

`LeaderboardService.streaks_for(user_ids)` mirrors the existing
`display_names_for(user_ids)` exactly: one batched read keyed by the ids already
resolved for the board, never a per-row query. **`streak` is `int | None`, and
`None` means "no `streaks` row", never a rendered `0`** — the same rule
`FriendDTO.xp`/`streak` already follow (D5.6 §5, UI spec §1.4). A student who
broke their streak legitimately has `current_length = 0` and that is a real
zero; the two must stay distinguishable.

**No opt-out hole is opened by this.** An opted-out student is removed in the
query's own WHERE clause (P5.3 chunk A) and never reaches `rows`, so their
streak is not resolvable through this surface at all.

### 3. The avatar is a monogram, because there is no avatar

Nothing in this schema stores an avatar, an image URL, or a colour preference.
The row renders the display name's initial in a tinted disc — a *rendering* of
data we hold, not a fabricated field, and it degrades correctly for the
`"Student"` fallback D5.5 installed for unnamed users. No placeholder photo, no
generated identicon keyed on a user id: both would look like stored identity
the account does not have. Carry "no avatar storage" to the Phase-5 limitations
rather than implying one exists.

### 4. Opt-out sits on S-29 itself, and its endpoint is `/me/student-profile`

§S-29 requires the opt-out be "available and easy to find — this matters for
students who find ranking stressful". A settings screen two navigations away is
not that, so the control lives on the board it governs.

**The brief names `PATCH /me/profile`; the real route is
`PATCH /api/me/student-profile`** and `leaderboardOptOut` is on
`StudentProfileUpdateDTO` (`schemas_student_profile.py:85`). The frontend's
`meTypes.ts` mirror of that DTO predates P5.3 and is missing the field entirely
— it is added to both `StudentProfile` and `StudentProfileUpdate` here.
`leaderboard_opt_out` is NOT NULL on the model, so an explicit `null` is a 422,
never a coerced `false`; the toggle therefore always sends a real boolean.

**Opting out hides you; it does not lock you out.** The service keeps returning
the board to an opted-out viewer (`viewer_opted_out=True`, absent from `rows`,
`rank` null). That is deliberate on the backend and the screen states it
plainly with a one-tap undo, rather than blanking the screen — a student who
wants motivation without exposure is exactly who this setting is for, and
hiding the board from them would punish using it.

### 5. S-30 adds by friend code, and the code is the invite link

§S-30 says "add by username or invite link". **`users` has no username column**
(D5.6) and searching by display name (not unique, enumerable) or email (the
exact leak D5.5 killed) are both closed. `users.friend_code` is the built
mechanism and serves both halves: the student shows or copies their own code,
and pastes a friend's. The submitted value is normalised server-side with
`.strip().upper()` already, so a code copied out of a screenshot in lowercase
works — the screen does not re-implement that normalisation and cannot drift
from it.

`POST /requests` returns `status: "accepted"` in the crossed-requests case, so
the screen says "you are now friends" from the response rather than inferring
"request sent" from the 201. Decline, cancel and unfriend are one `DELETE`
(D5.6 §3) and one confirm-free action each — the row is recoverable by asking
again, so a modal would cost more than the mistake.

### 6. The weekly reset is stated in civil days

`weekStart`/`weekEnd` are dates (D5.1 §6, Monday..Sunday Cairo), so the screen
says "resets Sunday" / "N days left" and never an hour-precise countdown it has
no data for. Same reasoning as S-28's `daysUntil` (chunk B): a boundary the
student watches must not move while they sleep.

## D5.15 — The service worker: `injectManifest`, and a push handler that never holds a credential (P5.9, written before any code)

D5.10 fixed the wire — a push carries **no payload**, only a VAPID
`Authorization` header — on the reasoning that the inbox row is the source of
truth (D5.9 §1) and student notification titles/bodies must stay off Google's,
Mozilla's and Apple's push infrastructure. It left one thing unstated: **where
the `push` event handler actually lives**, and how it gets the content it was
deliberately not sent.

### 1. `generateSW` cannot host a push handler, so the strategy changes

`web/vite.config.ts` runs `VitePWA` with a `workbox: {...}` block and no
`strategies` key — that is the **generateSW** strategy, which emits a service
worker with **no `push` event listener at all**, and there is no service-worker
source anywhere in `web/src` (`web/dist/sw.js` is a build artefact, not an
input). So D5.10's transport is, today, invisible: the backend can send a push
and nothing on the client would render it.

Two ways to add the listener:

- **`workbox.importScripts: ["push-sw.js"]`** — keeps generateSW untouched and
  `importScripts()` a hand-written file in `public/`. Smallest diff.
- **`strategies: "injectManifest"` + `src/sw.ts`** — the SW becomes a real
  source file that vite compiles.

**Chosen: `injectManifest`**, for one reason that outweighs the smaller diff —
**the handler's decision logic must be testable, and `public/` is invisible to
every gate this build runs.** A file in `public/` is copied verbatim: not
typechecked by `tsc -b`, not linted by oxlint, not reachable by vitest. Putting
the only new client-side logic in this phase somewhere no gate can see it is
exactly the shape MISSION §4's "proven by a test" forbids. `src/sw.ts` is
compiled, linted and can import from `src/lib/`.

The cost was measured, not assumed: **all four workbox runtime packages are
already installed** (`workbox-precaching`, `workbox-routing`, `workbox-core`,
`workbox-window`, all 7.4.1, transitive from `vite-plugin-pwa` 1.3.0), so this
is **zero new downloads**. They are promoted to explicit `devDependencies`
because `src/sw.ts` imports them directly, and depending on a transitive
package without declaring it is how a lockfile bump breaks a build silently.

`injectManifest` means the precache setup is now ours to write rather than
generated, so the existing behaviour must be reproduced deliberately and not
lost: `precacheAndRoute(self.__WB_MANIFEST)`, the `navigateFallback` to
`/index.html` with the **`/^\/api/` denylist preserved**, and
`skipWaiting`/`clientsClaim` to keep `registerType: "autoUpdate"` meaning what
it meant before. The denylist is load-bearing — the original config's comment
records that `/api/*` must never be cached because marks and grades are live.

### 2. The finding that D5.10 did not have: **a service worker cannot authenticate**

D5.10 says "the service worker fetches the inbox over the authenticated API".
**As written, that is not implementable in this codebase.** The session — and
the bearer token with it — is persisted to **`localStorage`**
(`web/src/lib/auth/storage.ts:33/44`), and `localStorage` does not exist in a
`ServiceWorkerGlobalScope`. `lib/api.ts:45` builds `Authorization: Bearer
${token}` from that same store. A SW `fetch` would go out unauthenticated and
get a 401.

Three ways out, and the rejection matters more than the choice:

- **Rejected — mirror the token into IndexedDB** (which a SW *can* read). It is
  the only option that works with no tab open, and it is the wrong trade: it
  creates a second, longer-lived copy of a bearer credential in a store with an
  independent lifecycle, which every logout, token refresh and device eviction
  must now also clear. A single missed invalidation leaves a background process
  holding a valid token after the user believes they have left. This build spent
  all of P5.7/D5.12 making session boundaries real — deciding *at the login
  itself* whether a device may be admitted — and duplicating the credential into
  a store nothing else touches would quietly undo that to save one fetch.
- **Rejected — always render a generic notification and never fetch.** Honest,
  but it throws away the case that actually works.
- **Chosen — the SW asks an open client for the content.**
  `clients.matchAll({type: "window", includeUncontrolled: true})` plus a
  `postMessage` round-trip with a short timeout: the page, which *can* read
  `localStorage`, does the authenticated fetch and posts the title/body back.
  **The credential never leaves the page context** and no second copy is
  created.

### 3. The honest consequence, recorded rather than papered over

With **no tab open, every push renders the generic "You have a new
notification"** — the fallback P5.6 chunk B already predicted. The window where
push carries real content is a tab that is **open but backgrounded**. That is a
genuine reduction against a payload-carrying push, and it is the compound price
of D5.10's privacy choice and §2's credential choice. Both are still right; the
limitation is real and belongs in the Phase-5 limitations, not in a comment.

The fallback is **mandatory, not a nicety**: browsers require *some*
notification per push, and a `push` handler that resolves without calling
`showNotification` triggers the engine's own "This site has been updated in the
background" message in several of them. So there is no "show nothing" branch to
design.

### 4. Where the test seam is

`vitest` here runs `environment: "node"` with **no jsdom** (a deliberate choice,
`vitest.config.ts:25`), and there is no `ServiceWorkerGlobalScope` to mount in
any case. So the logic is split: a **pure function** that takes whatever the
client handshake returned (or `null`) and returns the notification to show, and
a thin `src/sw.ts` adapter that wires real events to it. The pure function is
what the tests drive, and the branch that matters — *content vs. fallback* — is
entirely inside it.

### 5. What cannot be claimed

This machine has **no VAPID keys**, so `GET /api/notifications/push/config`
reports the transport unavailable by design (D5.9 §4) and **no real push can be
delivered in any harness in this build**. The push path is verified by unit
tests over the pure function and by the screen's handling of the `unavailable`
state — never by an end-to-end delivery. Do not write "push delivery verified"
in the Phase-5 report; write what was actually exercised.

---

## D5.16 — G-12 states what it cannot do rather than offering a control that cannot work (P5.9 chunk C)

Recorded **after** the code rather than before it, and the distinction is worth
being honest about: MISSION §4's spec-before-code ordering for this phase was
served by D5.15, which settled the architectural question (the service worker
and the credential boundary). Everything below is a set of smaller calls made
while building G-12 that the file comments alone would lose.

### 1. The route is `PUT`, and the update is partial anyway

The task brief said `PATCH /api/me/notification-preferences`. The router
declares **`@router.put`** (`lemely/web/routers/me.py:176`). It is still a
genuine partial update — pydantic's `model_fields_set` tells "omitted" from
"explicitly sent", so an omitted field is left untouched server-side.

The screen therefore sends **exactly one key per toggle flip**. That is not a
bandwidth argument. A whole-object body would carry `atRiskAlert`, which the
router answers with a **422** for any role but teacher/parent whether the value
is `true` or `false`; and it would silently clobber a change made on another
device between this screen's load and its save. The partial body is what makes
the wire shape match what the reader actually asked for.

This is the seventh time in Phase 5 that a note paraphrasing the codebase has
been wrong where the code was right (D5.2, D5.4, D5.5, P5.5's header, the two
deps predictions). The rule holds: **read the router; where a brief restates
it, the code wins.**

### 2. `atRiskAlert: null` is information, not an absent value

The DTO returns `null` for every role except teacher and parent. That null does
not mean "off" — it means *this caller's role has no such preference*. So the
toggle is **filtered out of the list**, never rendered unchecked. Rendering it
unchecked would offer a student a switch that 422s on use, and would tell them
they had opted out of something that was never theirs.

### 3. Three push states, and the order between two of them is load-bearing

UI spec §G-12 asks for permission state to be shown "clearly with a route to fix
it rather than toggles that silently do nothing". `resolvePushState` collapses
four independent facts — server availability, browser support, permission,
subscription — into one state, and two orderings inside it are decisions:

**Server availability is checked before browser support.** Both mean push
cannot happen here. Only the browser one *looks* actionable, and acting on it
achieves nothing while the server has no VAPID keys to sign an assertion with —
so telling the reader to switch browsers would be an errand that ends in the
same place. The binding constraint no user action can change is stated first.

**`granted` without a live subscription resolves to `prompt`, not `enabled`.**
The permission is the browser's memory of an earlier answer; the subscription is
what the server can actually push to. Cleared site data, a new browser profile,
or a `410` the server acted on (D5.9 §4) leaves the first without the second.
Reporting "on" there is the single failure a settings screen exists to prevent.
Re-enabling from `prompt` shows no permission dialog when permission is already
granted, so the recovery costs a click and no interruption.

Both verified by inversion: dropping `subscribed` from the enabled check fails
`reports prompt, not enabled…`; swapping the two precedence lines fails `puts
server unavailability ahead of browser support`.

### 4. The test-notification button is a device check and says so

**No route in this backend sends a test push**, and on a build with no VAPID
keys none could. Rather than ship a button that pretends otherwise, it shows a
notification from the device itself and the copy beside it states plainly that
it does not check the server can reach you.

What it does prove is the half that actually breaks: permission is granted, the
service worker is registered and active, and the operating system will surface a
Lemely notification rather than swallowing it. It goes through
`registration.showNotification` rather than `new Notification()` — that
constructor is unsupported on Android Chrome, which is exactly where a
hand-rolled test button silently does nothing on the platform most of these
students are on.

### 5. Five toggles, and the sixth is refused structurally

UI spec §G-12 lists "weekly summary". `NotificationType` has five members, no
`weekly_summary` column, no sender and no row — a sixth switch would gate
nothing (UI spec §1.4). `NOTIFICATION_TOGGLES`'s key list is asserted **exactly**
in `tests/unit/notificationPrefs.test.ts`, so it cannot be added without the
backend growing the enum value first. Carried to the Phase-5 limitations.

### 6. Quiet hours refuse a half-filled pair before the server does

`NotificationPreferencesService.set` raises on a merged result with exactly one
bound set, and the router turns that into a 422. Catching it client-side is not
duplication: without it, a reader who types a start time and tabs away is shown
a server error for a form they have not finished filling in.

Start equal to end is deliberately **allowed through** — the backend accepts it,
and a client stricter than the server it mirrors is the same dishonesty in
reverse. An overnight window says out loud that it wraps past midnight, because
"22:00 to 07:00" read literally is an empty range and the reader has no other
way to check we understood them short of waiting until 2am.

### 7. What no gate exercises, and why it stays that way

The G-12 audit-registry entry runs under a student session against a build with
no VAPID keys. So **the `prompt`, `denied` and `enabled` push states, the enable
button and the test-notification button are covered by unit tests only** — never
by axe, Lighthouse or a browser — and a student-session audit sees four toggles
rather than five. Covering them would need a mocked push config, i.e. auditing a
screen this deployment never shows. Both non-coverages are written into the
registry entry itself and carried to the Phase-5 limitations. Do not write "push
enablement verified" in the Phase-5 report.

## D5.17 — Four Phase-5 acceptance flows, and the four judgment calls the E2E pass forced (P5.11)

MISSION §4 Phase 5 names four acceptance flows: XP accrual, leaderboard ordering,
push delivery (mock), announcement flow. Before P5.11 there was **zero** E2E
coverage of any Phase-5 surface. Building all four forced four calls worth
recording, because each one is a place where the obvious choice is wrong in a way
that still goes green.

**1. Two flows ride on `correct-paper.spec.ts` rather than getting their own spec.**
`POST /student/correct` is *both* the `paper_corrected` XP seam and the
`grade_ready` notification seam. A dedicated driver for either would re-run an
upload→mark journey the suite already runs, for no new coverage. The XP number is
exact (50) rather than a range because that spec signs up a **fresh** account, so
there is no prior XP to account for and no clock control needed.

The XP assertion is worth more than its size suggests, and this is why it must not
later be "simplified" into a smoke check: `award_xp_safely` is deliberately
**fail-open** (D5.1 §3 — an already-committed student action must never become an
error response), and `xp_events.subject_code` is a live FK whose violation that
helper swallows. So a missing `subjects` row costs a real student 50 XP while the
correction, the result screen and every other gate in this build stay green. This
is the **first test in the build that would catch a fail-open seam failing.**

**2. "Push delivery" is scoped to the notification row, and no push is mocked into
a pass.** This machine has no VAPID keys, so the transport reports itself
unavailable by design (D5.9 §4) and `notify_safely` records
`push_suppressed_reason="transport_unavailable"` *after* writing the row. The row
is the assertable fact. Asserting a "delivered push" here would mean asserting a
mock of our own construction — a test that proves the harness, not the product.
`grade_ready` is additionally asserted to render with **no** Open button: its
payload carries an upload UUID and `/student/result/:paperId` addresses papers by
history index, so a link would be a guaranteed dead one. The absence is pinned so
a later session does not "fix" it into one.

**3. S-31's label/value pairs diverge from C-2 `MarkDisplay`, deliberately.**
The established repo pattern puts the value inside the element's own `aria-label`
(`"12 out of 20 marks"`). Two problems with copying it here: it names a generic
`<div>`, which has no accessible name in the ARIA spec, and it duplicates the
number into a second place that can drift from the first. P5.11 instead names a
`role="group"` with the **label** and leaves the value as its content — the pair
is associated, the number is stated exactly once, and `getByRole("group", {name})`
is still a stable locator. This is a deliberate improvement on the house pattern,
not an oversight; C-2 itself was left alone (changing it would touch an assertion
in `correct-paper.spec.ts` for no behavioural gain).

**4. `BoardRow` takes its element as a prop, and G-10 declines Lighthouse.**
Two "the natural fix is the wrong one" cases in the same chunk:
* Making `BoardRow`'s root `<li>` unconditionally — the obvious way to get list
  semantics — turns the *pinned viewer row*, which renders outside the `<ol>` on
  purpose because its rank is out of sequence, into a listitem with no list
  parent. That is a **serious** axe violation on a route already in the registry,
  and no cheap gate catches it: there is no `Standings` component test and no
  vitest test imports axe, so all four web gates go green and it surfaces ~28
  minutes into a run.
* G-10's registry entry sets `lighthouse: false`. `runLighthouseAudit` drives its
  own navigation and never replays the entry's `ready`, so it would score the
  plain login form and file the number under G-10's slug — a measurement of a
  state it never reached. `/login` is already scored on its own entry. A wrong
  number is worse than no number (UI spec §1.4).

**Also recorded, because it is the same lesson a third time.** The audit
registry's exclusion list named four student routes as "still on mock data" and
every word of it was false by P5.11 — and the stale sentence was the one
*documenting the two previous times this happened*. Adding the three genuinely
unaudited routes immediately found that **none of them rendered an `<h1>`**.
Three more real screen-reader defects that a hand-maintained exclusion list had
been hiding, on top of the one the G-13 entry found the session before. The
generalisable rule, now paid for four times (`EXPECTED_TABLES` P5.4, the
`SeedContract` mirror P4.11, G-13 P5.9, this): **a hand-kept list that nothing
regenerates fails silently and in the direction of false confidence.** Write the
registry entry in the same chunk as the screen.

## D6.1 — `web/e2e/` gets its own tsconfig project, not a seat in the vitest one (P6.1a)

D3.20 recorded that `web/e2e/` and `playwright.config.ts` were in no tsconfig
`include`, so the most expensive gate in the build — 34 tests across 13 files by
Phase 6 — had never once been typechecked. Three phases carried it forward. P6.1
closes it.

**The obvious fix is wrong.** Adding `"e2e"` to `tsconfig.test.json`'s `include`
is one word and would have compiled. That project declares
`"types": ["node", "vitest/globals"]`, so every Playwright spec would then be
typechecked against **vitest's** ambient `expect`/`test` rather than the ones it
imports from `@playwright/test`. The two APIs overlap enough to typecheck and
differ enough to matter (`expect(locator).toBeVisible()` exists in one and not the
other), so the gate would pass while checking the specs against the wrong runner's
types — a green that means less than no green at all. Two runners, two projects.

`moduleResolution: "bundler"` rather than `nodenext` for the same class of reason:
the specs import `./seed` extensionlessly and Playwright's own transpiler resolves
that, so `nodenext` would report errors the runtime does not have — a gate that
fails on correct code teaches the next session to disable it.

**It found exactly one error, and it was real.** `webServer.env` was spread from
`process.env` (`string | undefined` per key) into a field requiring `string`.
Fixed by filtering the undefined-valued keys, not by casting: a cast would keep the
type system quiet while a genuinely-undefined value reached the subprocess as the
literal string `"undefined"`.

**The gate is now non-incremental (`tsc -b --force`).** `tsc -b` reuses
`node_modules/.tmp` tsbuildinfo, which is exactly how `tsconfig.test.json` shipped
without `jsx` for a whole phase while `npm run build` reported success. A gate that
can be green because of a stale cache is not a gate. `build` stays incremental;
only the gate forces.

## D6.2 — The Lighthouse performance floor becomes a real gate, scoped exactly as MISSION words it (P6.1b)

D4.25 recorded that `scripts/check_ui_gates.py` had **no performance check at
all**, while MISSION §11 and four phase reports described "performance ≥ 80 on the
student routes" as a standing automated check. By Phase 5, eight routes sat below
80 and `ui-thresholds` was green. Every citation of that green as a performance
pass was, without anyone intending it, false.

**Scope: the `/student` subtree only.** That is precisely what MISSION §11 claims a
floor for; it has never stated one for teacher or parent routes. Inventing a floor
MISSION does not state would be as dishonest as ignoring the one it does — so the
teacher/parent numbers are reported in the phase report and DELIVERY.md rather than
gated. The teacher routes are genuinely the worse ones (`teacher-quiz-detail` 65),
which is exactly why gating them here would look like diligence while actually
being an unrequested scope change made at the moment it would fail.

**Keyed on `path`, not on the slug prefix.** `audit.mjs` now writes each
Lighthouse row's route `path`, and the gate treats `/student…` as the student
subtree. Keying on the slug's `student-` prefix would mean a future student screen
slugged off-convention silently escapes the floor — the same shape of hole this
decision is closing. Report dirs baselined before P6.1 carry no `path`, so the slug
prefix is a documented fallback rather than a silent "not a student route", which
would let the gate pass by omission on an old corpus.

**The fix is code splitting, not a lowered bar.** The build emitted a single
1.3 MB `index-*.js` for all 44 routes — zero splitting, so every route paid for
every screen of every portal, and the scores clustered in a 65–87 band that had
little to do with any individual route's complexity. Screens are now `React.lazy`
with one `Suspense` boundary per portal wrapping the `<Outlet />` (portal chrome
stays painted and interactive while a screen chunk arrives). Entry chunk
**1.3 MB → 387 kB across 91 chunks**, with no test changes required (456/456 web
unit tests still pass).

`RouteFallback` lives in the C-11 state-view family rather than in each router
file. It was written as four local copies that had **already** drifted to three
different type/padding combinations before they were merged — the concrete version
of the Phase-2.5 rule that cross-cutting UI is composed from the library, not
re-invented per call site. It is deliberately not a `StateView`: those are terminal
answers about data ("there is nothing here"), while this is a sub-second gap that
should not flash a heading nobody needed to read. It keeps `role="status"` so a
screen-reader user hears something between activating a link and the screen
arriving.

## D6.3 — The concurrency pass found a real race in the XP cap, and one of its own tests was decoration (P6.2)

MISSION §4 Phase 6 asks for a concurrency test and basic load sanity. Neither
existed: grepping `tests/` for `concurren|asyncio.gather` hit only two files, both
incidentally. `tests/test_concurrency.py` and `scripts/load_sanity.py` are new.

**The finding: `XpService.award` could be defeated by concurrency.** The daily
anti-farming caps of D5.1 §3 were implemented as a plain read-then-write —
`session.get(User, ...)`, count today's awards, decide, insert — with no lock. Eight
concurrent awards against a cap of three all succeeded. Distinct `dedupe_key`s mean
migration 0013's unique constraint cannot save it. Fixed with
`with_for_update=True`, which is not an invention but the idiom already used on the
same `users` table by `DeviceRegistry.register_login` for the identical TOCTOU.

**Verified by inversion, not by reading.** With the lock reverted the test fails;
with it restored it passes. Worth recording because the inverted run failed with a
*different* symptom than the one that motivated the fix — a `uq_streaks_user_id`
UniqueViolation from concurrent streak-row creation, rather than the cap bypass. One
missing lock, two failure modes, and which one surfaces depends on thread timing. A
future session that sees only one of them should not conclude the other was
misdiagnosed.

That second symptom is the more dangerous one in production: `award_xp_safely` is
deliberately fail-open (D5.1 §3), so an IntegrityError there is swallowed and a real
student silently loses XP with every gate in this build still green.

**And the pass caught one of its own tests being decoration.** The same inversion
applied to `test_device_cap_holds_under_concurrent_logins` — removing
`device_repo.py`'s `FOR UPDATE` — left it **passing**, while its docstring claimed it
confirmed that lock holds under concurrency. It did not.

The cause was not the code but the test's own thread scheduling: with 4 unsynchronised
threads, the GIL plus a short critical section meant they often never actually
overlapped inside `register_login`, so the race window was simply missed. Measured
before the fix, with the lock removed: **8 pass / 12 fail over 20 runs** — a test that
catches its regression barely half the time reads as green often enough to be believed.
Fixed in the test only (`threading.Barrier` so every thread enters at the same instant,
and 11 threads rather than 4); `device_repo.py` was not touched. Re-measured by me
independently of the agent that wrote it: **lock removed → 0 pass / 10 fail; lock
restored → 3/3 green.**

A test that cannot fail is worse than no test, because it is cited as evidence. The rule
this establishes for the rest of Phase 6: **a test written to prove a concurrency
guarantee must be shown to fail when that guarantee is removed — repeatedly, not once —
and the inversion counts belong in the report.** Note also that a single inversion run is
not enough to *clear* a test: the first crude check I ran looked mixed because of how I
parsed pytest's output, and only a counted 10-run loop settled it. Count, don't eyeball.

**Load sanity is reported as numbers, with no verdict.** MISSION states no API latency
threshold, so grading against an invented one would be manufactured precision (UI spec
§1.4). `reports/phase-6/load-sanity.{json,md}` carry real measured output — 8
endpoints, concurrency 10, **zero errors across ~10,000 requests** — plus the caveats
that make the numbers readable (single machine, dev uvicorn, synthetic seed, Gemini
mocked).

One signal in that data is worth carrying into DELIVERY.md rather than losing in a
table: **`/api/teacher/overview` is 10-40x slower than every other endpoint measured**
(p50 396ms / p95 458ms, against 8-150ms for the rest). That is the shape of an N+1
across a teacher's classes and students. Not chased here — it is a performance
observation on seeded data, not a defect with a failing test — but it is the first
place to look if the teacher console feels slow, and it should not be discovered twice.

---

## D6.4 — The authz matrix becomes generated, and the security sweep found nothing to fix (P6.3)

MISSION §4 Phase 6 asks for the authz matrix to be re-verified over every route
including the Phase-4/5 additions, plus an adversarial security sweep.

**The matrix was re-verified by replacing the method, not by extending the list.**
`tests/test_authz_matrix.py` (P1.6) proves RBAC on a *hand-listed* spread that
stopped growing at Phase 3 — flashcards, friends, leaderboard, xp, notifications,
practice, placement, announcements, the exam calendar and the parent portal were
essentially unrepresented in it, and nothing made adding a route fail a test.
Extending the list by hand would have re-created that failure mode one phase later.
`tests/test_authz_matrix_complete.py` instead derives the route set from the app and
asserts it is **equal** to a declared table, so a new route with no declaration
fails, and a stale declaration for a deleted route fails too. The old file is kept,
not replaced: it carries per-route rationale that a generated file cannot.

**What the sweep actually found: nothing to fix.** All 121 route operations already
carry a guard — 5 public (the four auth entrypoints plus `/api/health`), 12
deliberately role-agnostic-but-authenticated (`/api/me`, notifications), 104
role-gated. The `reviewer` pass traced every caller-supplied identifier on the
Phase-4/5 routers from route parameter to SQL and found identity keyed on
`auth.user_id` in every case, with ownership failures collapsed to 404 rather than
403 where an existence oracle would otherwise leak. **No production code changed in
P6.3.** That is the honest result and it is recorded as such rather than dressed up.

**Three things worth carrying forward.**

1. **Provenance of the declared table is stated in the file, because it matters.**
   `EXPECTED`'s rows were seeded from the wired guards and then reviewed, not
   derived independently — so the guard-match property is a *freeze* of a reviewed
   state, not an independent check of it. The completeness and behavioural
   properties are independent of how the table was produced. A future reader must
   not over-trust that one property.
2. **The override-shaped blind spot the sweep named was real.** A 403 test that
   overrides `get_auth_context` proves `require_role` given a correct context but
   cannot see a break in token decoding, because the code building the context is
   the code it replaces. Twenty-one real-minted-token cases and four
   malformed-credential cases now cover the whole chain. This generalises: **a test
   that mocks the thing upstream of the guarantee is not testing the guarantee.**
3. **Mass assignment is now gated, and the gate had to be recursive to be worth
   anything.** Four separate `ApiModel` bases set `extra="forbid"`, but nothing
   proved every body inherits one, and a strict outer model with a lax nested
   element type still accepts unknown keys. The new test walks the dependency tree
   transitively — 39 models, all strict — and asserts pydantic *acts* on the flag
   rather than trusting the flag.

**Every guarantee was inverted and counted, per P6.2's rule.** Disabling the role
check fails 333/333 role-gated cases and 21/21 real-token cases while the 401
sweeps correctly still pass (a different guarantee); adding one undeclared route
fails all three structural tests; making one nested model lax fails exactly its two
cases.

**One process note.** The `reviewer` agent ran concurrently with inversion A and
read `deps.py` during the ~2 minutes the guard was deliberately disabled, then
watched it revert — and reported a Critical "something is mutating the auth guard
on disk". It was right about what it saw and wrong about what it meant. **Do not
run a read-only reviewer concurrently with an inversion run on the same checkout**;
either serialise them or tell the reviewer an inversion is in flight.

---

## D6.5 — The deployment stack joins Supabase's network, and ships no CORS on purpose (P6.4)

MISSION §3 asks for one command bringing up Supabase-local + backend + the built SPA
"with correct CORS/proxy configured". P6.0 established this was greenfield: no
Dockerfile, no compose file, nothing.

**Supabase local stays CLI-managed; our compose joins it.** The Supabase CLI owns its
own compose project, so the choice was to reimplement its stack (GoTrue, Kong, Storage,
Realtime…) in our file or to join the one it already runs. Joining is right, and the
mechanism matters: the network `supabase_network_Lemely` is declared **`external: true`**
and the backend addresses `supabase_db_Lemely:5432` and `supabase_kong_Lemely:8000` by
container name. **The host-published ports 54322/54321 do not exist inside a container**
— reaching for them is the obvious mistake here. Declaring the network rather than
marking it external would also let `docker compose up` silently create an empty network
the backend cannot reach Postgres through; `external` fails loudly instead, which is the
behaviour you want when the dependency is genuinely absent.

**No CORS middleware, and that is the configured-correctly state.** nginx serves the
built SPA and reverse-proxies `/api` to the backend, so the browser only ever makes
**same-origin** requests. CORS exists to relax the same-origin policy for cross-origin
traffic; there is none here, so there is nothing to relax and `Access-Control-*` headers
would be dead weight. Adding `allow_origins=["*"]` would strictly widen the attack
surface — it would let any origin that finds the directly-exposed backend port script
authenticated requests against it — while enabling no functionality. A future genuine
split-origin deployment needs an explicit config-driven allowlist with
`allow_credentials=False` (auth is a bearer token in a header, never a cookie, so
credentialed CORS is never required). **`grep -rn CORSMiddleware lemely/` returning
nothing is the intended state; a later session must not "fix" it.** The reasoning lives
as a comment block in `docker-compose.yml` so it cannot be lost with this file.

**Verification was re-done by the orchestrator, and it is worth noting why.** MISSION §5
requires verifying a subagent's work rather than trusting the claim. Beyond re-running
its curls on a `make up` stack, two checks it had not made were added: the container
actually reaching Postgres over the Supabase network (read 1610 seeded users and
`alembic_version = 0018` from inside the container), and the **auth chain end-to-end
behind the proxy** — 401 with no token, 200 with a real minted student token, 403 with a
teacher token on a student route. That last one is the only evidence that nginx forwards
the `Authorization` header at all; a health-endpoint 200 proves nothing about it. The
hardcoded local JWT secret was likewise compared against the *running*
`supabase_auth_Lemely` container's `GOTRUE_JWT_SECRET` rather than assumed to match.

**Two things handed to P6.5 rather than solved here.** The entrypoint runs
`alembic upgrade head` unconditionally on every start — correct for a one-command local
bring-up, wrong for production where schema migration is a separate gated step. And the
local-dev JWT secret baked into the compose file is a well-known Supabase default that
must be overridden in any real deployment. Both belong in `docs/deployment.md`.

**Environment fact:** `npm ci` fails in a slim node image because puppeteer's postinstall
downloads Chrome and the image has no `unzip`. `ENV PUPPETEER_SKIP_DOWNLOAD=true` in the
builder stage is the fix; puppeteer is audit-runner tooling and nothing at build time
imports it.

---

## D6.6 — Deployment docs written from the config surface, and the two blockers they found (P6.5)

`docs/deployment.md` covers the working local `make up` stack, a Supabase-Cloud +
container-host recipe, the configuration reference, and a copy-paste checklist. **The
cloud half has never been executed and the document says so in its opening lines.** Every
claim in it is anchored to a file and line in this repo so a reader can check rather than
trust — the alternative (a confident deploy narrative for a deploy that never happened) is
exactly the invented precision this build keeps paying to avoid. P6.4's two handoffs (the
unconditional `alembic upgrade head`, the well-known local JWT secret) are both discharged.

**Writing it surfaced two facts nothing had previously stated, both found by reading the
code rather than by reasoning about the deployment:**

**(a) The backend cannot run more than one replica.** Two pieces of state are
process-local, not persisted: `JobRegistry` (`lemely/web/jobs.py:31-37`), the dict behind
every in-flight correction job and its SSE progress stream, and the parent phone-OTP
challenge store (`lemely/auth/service.py:107`). With two replicas a student's browser
reconnects to a replica that has never heard of their job, and a parent's OTP is issued on
one instance and verified on another — the second one fails intermittently and
unreproducibly, which is the worst possible failure shape. Neither is hard to fix
(Postgres or Redis for both); neither is fixed. This is the single most consequential line
in the document, because a host that autoscales by default will trip it silently and no
test in this build would catch it.

**(b) `lemely/db/seed.py` creates nothing, and this is a P6.10 problem.**
`seed_reference_data` and `seed_demo_accounts` are stubs — both bodies are a bare `pass`
(`lemely/db/seed.py:26-51`) — so `make seed` inserts zero rows and creates zero demo
accounts while logging `db.seed.done`. The only working path is `scripts/seed_e2e.py`,
which does create all five roles, but under a per-run random `run_tag`, so emails and
passwords differ on every run. **P6.10's acceptance criterion is a fresh clone reaching a
working product with seeded demo accounts for all five roles**, and stable credentials a
document can name do not currently exist. Recorded now rather than discovered at P6.10.

**Not fixed here, deliberately.** The entrypoint's unconditional migration is documented
with the guard flag a production deploy would want (`LEMELY_RUN_MIGRATIONS`) described but
**not implemented** — P6.5 is a documentation task, and adding an untested env-gated
branch to the container start path at phase end is the kind of change that breaks the
`make up` that P6.4 just verified. The doc names it as a small honest change, which is what
it is.

**Also carried into the doc from measurements already on disk:** the `/api/teacher/overview`
N+1 shape (p50 396ms vs 8-150ms elsewhere, `reports/phase-6/load-sanity.md`), and one
consequence of containerising that nothing had noted — the $8 Gemini spend ledger lives
under `/app/.lemely-cache` on the **ephemeral container filesystem**, so a host that
recycles containers resets the measured spend to zero while the real bill keeps climbing.
Mount a volume there or the hard cap silently stops being a cap.

---

## D6.7 — The full-suite run found a time-bomb test, not a flake (P6.6)

**Context.** P6.6's whole point is "all 13 gates green on the final tree". The run came
back **12 of 13 PASS with `EXIT=1`**, the single failure being
`tests/test_push_transport.py::test_authorization_header_verifies_against_the_public_key`.

**What it actually was.** The test mints a VAPID assertion through a transport whose clock
is injected as `FIXED_NOW = 2026-08-10 12:00 UTC`, then verifies it with `jwt.decode`
against the **real wall clock**. RFC 8292 caps the assertion's lifetime at 24 hours, so the
token is expired for any run later than 2026-08-11 12:00 UTC. **The test was green on the
day it was written (P5.6, 2026-08-10) and has been red in every run since.** It went
unnoticed because nothing ran the full backend suite in that window — Phase 5's own closing
run predates the expiry.

**Product code is correct and was not touched.** The transport is properly clock-injected,
and the 24-hour cap has its own dedicated test (`test_the_assertion_expires_inside_rfc_
8292s_24_hour_cap`) which judges expiry against `FIXED_NOW` — the honest clock for it. The
defect was entirely in the *verification* step of a sibling test, which pinned the clock for
signing and then forgot to pin it for checking.

**Fix:** `options={"verify_exp": False}` on that one decode, with a comment saying why it is
required rather than convenient. This is **not** weakening a test to get green: the
assertion under test is the signature and the audience, and expiry is separately and better
covered.

**Inverted and counted, per P6.2's rule.** With the audience changed to a wrong origin the
test fails with `InvalidAudienceError`; with the assertion verified against a freshly
generated keypair instead of the signing one it fails with `InvalidSignatureError`. Both
still bite, so `verify_exp: False` did not gut the test. The other two `jwt.decode` calls in
the file pass `verify_signature: False`, which in PyJWT disables the other checks too, so
they carry no clock dependency and needed no change.

**The transferable lesson, and it is not about JWTs.** A test that pins a clock on the write
path and reads it back with the real clock is green until it silently isn't, and the
interval between those two states can be a single day. `grep -rn "jwt.decode" tests/` was
run to find siblings with the same shape; there were none. **Any test mixing an injected
clock with a real one is a dated assertion — the failure arrives on a calendar, not on a
code change**, which is exactly the kind a phase-end run is for and a per-commit CI never
catches.

---

## D6.8 — The fresh-clone run found four defects, and the product one was a claim with nothing behind it (P6.10)

**The acceptance criterion is MISSION §4 Phase 6's last line: `git clone` → the documented
commands → a working product with seeded demo accounts for all five roles.** It was run for
real — a clone of `feature/phase-6-hardening` at `be49d34` into `/tmp/lemely-fresh-1`, the
documented commands executed verbatim from it, and every claim checked against the running
containers rather than against the source.

**The headline is that it passes: `make up` from a fresh clone brought the product up
(`EXIT=0`, both containers healthy) and all five demo roles authenticate through it.** Four
password roles by `POST /api/auth/login` and the parent by phone-OTP, each verified through
nginx on :8080 (not against the backend directly) by reading `/api/me/profile` back:

| Role | `/api/me/profile` |
|---|---|
| student | `{"displayName":"Demo Student","email":"student@demo.lemely.local","role":"student"}` |
| teacher | `{"displayName":"Demo Teacher",…,"role":"teacher"}` |
| school_admin | `{"displayName":"Demo School Admin",…,"role":"school_admin"}` |
| platform_admin | `{"displayName":"Demo Platform Admin",…,"role":"platform_admin"}` |
| parent | `{"displayName":null,"email":"phone+10000000000@parents.lemely.local","role":"parent"}` |

That last row is finding 4 below. **Verifying through the proxy is the point** — it exercises
DNS, `Authorization` forwarding, JWT validation and RBAC in one pass, which is exactly the
cheapest end-to-end proof `docs/deployment.md` §6 names. P6.4 had only ever verified this
chain with *backend-minted* tokens; a real GoTrue password login through the packaged product
had never been run before this task.

### 1. The documented dev install omits two extras, so the next two documented commands fail

`README.md` said `pip install -e ".[dev,ui]"`, then `make db-migrate`, then `make seed`.
`db` (Alembic, SQLAlchemy, psycopg) and `web` (FastAPI, httpx — how `lemely.db.seed` reaches
GoTrue) are **separate extras**, so from a fresh clone the documented sequence produced:

```
make db-migrate → make: alembic: No such file or directory       (exit 127)
make seed       → ModuleNotFoundError: No module named 'sqlalchemy'
```

Both re-run green after `pip install -e ".[dev,ui,web,db]"` — the set `make dev` already
installed, so the Makefile was right and the README had drifted from it. Fixed in the README,
with the reason each extra is needed, because a bare corrected command would drift again.

### 2. `python` is not a command on Debian-family systems

`python3 -m venv .venv` works; the documented `python -m venv .venv` exits 127. The Makefile
carried the same assumption in `PYTHON ?= python`, which is what `make seed` invokes — so
`make seed` outside an activated venv failed for a reason that has nothing to do with the
seeder. Both now say `python3`, which inside an activated venv resolves to that venv's
interpreter anyway, so nothing is lost.

### 3. An empty environment variable is not "unset" — and `/api/health` was lying because of it

**The product defect, and the one worth carrying.** `docker-compose.yml` forwards optional
credentials as `${GEMINI_API_KEY:-}`. On a `make up` stack with nothing exported the variable
is *present and empty*, so pydantic built `SecretStr("")` — which is not `None`. Every
`is None` "not configured" check in the codebase therefore answered **configured**, with
nothing behind it. Measured inside the running container, not reasoned about:

```
GEMINI_API_KEY=            → gemini_api_key is None: False | secret length: 0
LEMELY_SUPABASE__ANON_KEY= → anon_key is None: False | length: 0
GET /api/health            → {"status":"ok","apiKeyConfigured":true}
```

**`apiKeyConfigured: true` on a stack that cannot mark a single paper.** That is the same
family as this build's other recurring bug — a claim nothing regenerates — except this one is
served to the product's own health endpoint. It also makes `docs/deployment.md` §6's
"(or accept `apiKeyConfigured:false` and no marking)" describe a branch that is *unreachable*
through Compose.

The second consequence is quieter and worse. `GoTrueClient._anon_key` / `_service_key` raise
an explicit `AuthError("… is not configured.")` on `None` — the guard exists precisely so this
fails legibly. With an empty string they never fire, and an empty `apikey` header goes to
GoTrue instead. **Local Kong tolerates it, so login works locally and every test stays green**;
Supabase Cloud rejects it as an unrelated-looking 401. This is the exact failure shape
`scripts/seed_e2e.py`'s docstring already warns about ("reads like a broken script rather than
'you forgot to export two variables'"), reappearing one layer down.

**Fix:** a `BeforeValidator` in `lemely/runtime/config.py` mapping a blank/whitespace-only
string to `None`, applied to the optional *credential* fields only — `gemini_api_key`, both
Supabase keys, and the three VAPID fields, which fail the same way (a blank key would report
the push transport available and then fail). Deliberately **not** applied to ordinary strings,
where a blank value can be meaningful. Five tests; inverted per P6.2's rule, and 4 of the 5
fail with the guard neutered while `test_a_real_credential_is_not_stripped_or_dropped`
correctly still passes — it is not testing the guard's firing, and a test that fails under
every inversion is measuring the wrong thing.

### 4. `DEMO_PARENT.display_name` was declared and applied nowhere

The parent is the one demo account created through the OTP flow rather than
`AuthService.signup`, and `verify_otp` mirrors a row with no display name — hence the `null`
in the table above while the other four carry theirs. Fixed in `_create_or_recover_parent`,
**including on the recognise path**, so a database seeded before this fix is corrected by the
next `make seed` rather than staying nameless forever. Two tests, both inverted.

### What this run did not prove

The Supabase stack was **already running**, so `scripts/up.sh` took its documented
already-running branch and `supabase start` from a cold machine is still unexercised here.
`make seed` from the clone reported `demo_accounts: 0` because the accounts already existed —
correct idempotent behaviour, and creation-from-empty was proven separately at session 101 on
a cleared demo slate. Both are stated rather than rounded off.

**The transferable lesson: a fresh-clone test is not a formality, and its value is entirely in
running the documented commands as written instead of the ones you know work.** Every finding
here was invisible to all 13 gates — which had just gone green, 0 skipped, on this same tree.
The gates run inside an environment that is already correct; the criterion is about the
environment being *reachable* from a clone.

---

## D6.9 — The CLS defect was fixed in the route, never in the threshold; and one gate is vacuous (P6.7)

Two judgment calls came out of the full-product visual QA sweep. Both were made in the
direction that costs more work and keeps the gate honest, and neither is visible from the
green `ui-thresholds` verdict that followed.

### 1. `student-standings` scored 74 on CLS 0.386, and the fix was to reserve the space

The failing run (`/tmp/check_p610b.log`) was **12 gates PASS + `ui-thresholds` FAIL** on a
single line: `lighthouse: student-standings performance score 74 < 80`. TBT (120 ms), LCP
(2.8 s) and speed-index (2.3 s) were all healthy — **the whole deficit was cumulative layout
shift**, 0.386 against the 0.1 "good" threshold.

**The previous session's stated hypothesis was wrong and is recorded here so it is not
re-adopted.** It named P6.1's `React.lazy` split — specifically `RouteFallback`'s sizing — as
the likely cause. The attribution was done instead from a committed artifact:
`reports/phase-5/lighthouse/student-standings.json` already carried the `layout-shifts` audit
for this route at **CLS 0.220**, so the defect *predates the code split* and is not a
regression caused by it. Both recorded shifts name `<section aria-labelledby="s29-subjects">`
— "Your subjects" being pushed down the page — not the route fallback. P6.1 raised the other
four metrics and left this one untouched, which is why the same tree could score 92 on one run
and 74 on another: **the shifts only count when the skeleton paints before the data arrives, so
a fast run hides them entirely.** That intermittency is what made it look like noise near a
floor, and it was not.

Three blocks above that section grow after first paint: the board card (one "Loading the
board…" line → a real board, ~335 px on seeded data at 380 px wide), `OptOutControl` (rendered
`null` while its profile read is in flight, then ~124 px), and the XP-basis tab row (~34 px).

Fixed in `web/src/portals/student/screens/Standings.tsx` (`46bd5f7`):

- The two null-until-loaded blocks now render their own frame with the **real copy** marked
  `invisible` + `aria-hidden` + `inert` while pending. Reserving with the actual text rather
  than a `min-h-*` guess is what makes the reservation correct at every breakpoint — the height
  comes from the same wrapping in the same box, so it cannot drift from the content it reserves.
- The board card gets a `min-h-96` floor **in every state, not only while loading**. 384 px is
  the height of the smallest real board on seeded data (a C-11 empty panel plus the pinned
  viewer row), so it is a measurement rather than a round number, and it also stops the page
  jumping when the student switches Friends / Class / School / Everyone — the same defect seen
  by a person instead of by Lighthouse.

Result: **CLS 0.000 — zero shifts recorded, not a smaller number — and performance 74 → 93.**
Zero shifts is what makes it a fixed defect instead of a luckier run.

**The threshold was never touched, and that is the decision.** D4.25 exists because this floor
went unenforced for two entire phases; P6.1 (D6.2) made it a real gate. Loosening it at the
first route that failed it would have been worse than never having enforced it at all — the
gate would then be a record of what we were willing to measure, not of what the product does.

### 2. `npx impeccable detect` is vacuous on this machine, and is reported as such

MISSION §4 asks Phase 6 to "run `npx impeccable detect src/` and resolve every finding".
impeccable 3.5.0 returns `[]` for `src/` — **and also for files written deliberately to trip
it**: an inline `style={{color:"#ff0000"}}`, a CSS file with an off-scale `font-size: 13.7px`,
and an em-dash-overuse file. With `--json`, `--quiet` and `--no-config` alike: exit 0, zero
bytes, every time. No `.impeccable` config suppresses anything (`config.local.json` holds only
hook consent).

So the criterion is satisfied **trivially**, and the honest report of it is that **a green
`impeccable-detect` gate is evidence of nothing** — not that the frontend is clean. It is
written that way in the phase report §4 and in `DELIVERY.md` rather than counted among the
passes.

Not chased further, deliberately: it is third-party tooling, the deterministic checks that do
bite (axe, Lighthouse, console-error, horizontal-scroll) are unaffected and all pass on real
findings, and the `/impeccable audit` *skill* pass is a separate and non-vacuous leg of the
same task (`reports/phase-6/impeccable-audit.md`, 15/20, Good). **A gate that cannot fail is a
reporting problem, not a licence to claim a pass.**

---

## D6.10 — The CI red was toolchain drift in two places, and the fix pins rather than upgrades

**Date:** 2026-08-12 (session 107) · **Task:** P6.12 · **Commit:** `7f11f58`

Session 106 found GitHub Actions red on PR #3 since ~2026-08-09 while all 13 local gates were
green, and correctly refused to call either statement wrong. It deferred the fix to Copilot's
PR #4. This session did not: **PR #4 has been stale since 2026-08-05 — it predates the failure
it is named after** (RUF036 arrived with ruff 0.16, days later), so it could never have fixed
the red. Two independent defects, neither in the product code.

### 1. `test (3.12/3.13/3.14)` — `ruff check .`, 10 × RUF036

`pyproject.toml` pinned `ruff>=0.7`, so the runner resolved **0.16.2**, while this venv *and*
`.pre-commit-config.yaml`'s `rev` both held **0.15.20** — which does not carry the rule. Three
ruff instances, two versions, one tree, two verdicts. **An unpinned linter is a gate whose
verdict changes without a commit**, the same shape as P6.6's dated VAPID assertion: a red that
arrives on a calendar rather than on a change, and therefore invisible to every local gate.

**Both halves were done, because either alone leaves the trap armed:** `ruff==0.15.20` in the
dev extra *in lockstep with the pre-commit rev* (a comment on each line says to bump them
together), and the 10 annotations reordered so the tree is already clean when someone does.
Verified with the version CI actually resolved rather than the local one —
`uvx ruff@0.16.2 check .` → *All checks passed!*

**Pinned rather than bumped, and the measurement is the reason.**
`uvx ruff@0.16.2 format --check .` reports **6 files would be reformatted and a widened file
set (340 → 387 files)**. Upgrading would have traded a red lint gate for a red format gate plus
a 6-file reformat on a shipped tree. Pinning is the smaller, more reversible move, and the
RUF036 fixes mean the upgrade — when it is taken deliberately, with the format churn in its own
commit — is no longer blocked by it.

### 2. `pre-commit` — 291 mypy errors, all `Cannot find implementation … "fastapi"`

That job installed `.[dev]` only. The hook is `entry: mypy lemely`, `language: system`, so it
resolves imports from the job environment — the **identical** command is green in the `test`
job, which installs `.[dev,ui,web,db]`. Now it installs the same extras.

This is the third time this build has paid for the same lesson, and the first time in CI:
**"module/executable not found" is an environment answer, never a verdict on the code.** STATE
already records it for `pre-commit`/`mypy` locally and for `supabase` not being on a
non-interactive PATH. Here it produced 291 errors, which is exactly the volume that reads as a
catastrophic code failure.

### 3. `gradio` — the same drift again, one step further along the run (`f980fbc`)

Fixing 1 and 2 moved the red rather than clearing it, which is the useful part of this record.
The next run got past ruff and past the fastapi imports, then failed on **12 × `"Button" has no
attribute "click"`** in `lemely/app/gradio_app.py`. Cause: `ui = ["gradio>=6.1,<7"]` let the
runner resolve **6.23.1** against this venv's **6.19.0**. Only the type surface moved — runtime
behaviour is unaffected — but `mypy lemely` is a gate, so it was red in CI and green locally on
the same tree, again with no commit in between. Capped at `<6.20`.

**Three instances of one defect is a pattern, so the pattern was closed rather than the third
instance.** Every tool whose output *is* a gate verdict is now upper-bounded: `pytest >=8,<10`,
`pytest-cov >=5,<8`, `mypy >=2.1,<2.2`, `pre-commit >=4,<5`, `import-linter >=2.1,<3`. mypy is
minor-capped because it adds checks in minors — the same drift as ruff's. Its old floor is worth
recording: **`>=1.13` spanned an entire major this build has never run a gate on**, while the
venv behind every green record sits at 2.1.0.

**Verified by resolving, not by reasoning.** `uv pip compile` against `pyproject.toml` for each
CI interpreter — 3.12, 3.13, 3.14 — exits 0 on all three and selects exactly `gradio==6.19.0`,
`mypy==2.1.0`, `ruff==0.15.20`, i.e. the versions this tree is green on. **A first attempt at
that check was vacuous** (`... | tail -4 && echo OK` reports OK on failure too) and was caught
and redone — the same shape as P6.2's decorative concurrency test and P6.7's vacuous
`impeccable detect`: *a check that cannot fail is not evidence.*

### What was deliberately not done

**PR #4 was not merged and not superseded on its own branch** (MISSION §4 — never merge a PR).
Its two correct ideas are implemented here independently; its other two changes would have hurt:
it narrows `ruff format --check .` to `lemely tests`, dropping `web/` and `scripts/` from the
format gate, and it guards two steps with `if: matrix.python-version == "3.13"` — GitHub Actions
expressions require single-quoted strings, so that workflow would not have parsed. **A stale
fix-it PR is not a reason to leave a gate red; check whether it predates the failure.**

## D6.11 — D1.9 is closed as won't-do: the two history stores have incompatible id contracts

D1.9 has sat as the build's last open checklist item since Phase 1, carried across every
subsequent phase as "opportunistic backlog, parity already proven". It reads: *migrate CLI +
Gradio history to the DB (or retire Gradio), then delete `lemely/io/history_store.py` +
`tests/test_history_store.py`.* Six sessions deferred it without looking at it. This is the
first session to actually cost it out, and the framing was wrong: **it is not a mechanical
cleanup that nobody got round to, it is a change of contract on a shipped surface.**

**The blocking fact.** `DbHistoryStore` cannot store what the CLI stores.
`lemely/db/history_repo.py:128` (`parse_user_id`) raises `ValueError` for any `student_id` that
is not a UUID, and `append`'s docstring states the id "must be a UUID string that already exists
in `users` (the FK is enforced; see D1.8)". The CLI's `--student-id` is a free-form local label:
its own tests pass `test_student`, `alice`, `bob`, `nobody` (`tests/test_cli_new_commands.py`).
Every one of those raises under the DB store. So "migrate the CLI" is not a swap of backends —
it means the CLI grows a hard dependency on a running Postgres **and** on the student already
existing as a provisioned user row, for three commands that today run entirely offline:
`correct --record` (`cli.py:330-352`), `compare-performance` (`:374-383`), `study-plan`
(`:583-605`).

**A third consumer D1.9's text never mentions.** `tests/test_web_teacher.py` uses the JSON
`HistoryStore` as the in-process test double for `HistoryStoreProtocol`, via
`dependency_overrides[get_history_store]` — roughly a thousand lines of teacher-analytics tests
hang off it. Deleting the class does not just touch CLI and Gradio; it forces those tests either
onto a live Postgres or onto a newly written fake. That is a substantial test-infrastructure
change landing after P6.11's closing `EXIT=0`, to delete 147 lines of working, tested code.

**Why this is not a limitation to apologise for.** The product surface is already fully
migrated: `get_history_store()` (`lemely/web/deps.py:83`) returns `DbHistoryStore`
unconditionally, so every student, teacher and parent route runs on Postgres today. Parity
between the two backends is proven by `tests/test_history_repo_parity.py`, and
`HistoryStoreProtocol` (`lemely/core/history.py:143`) already isolates every caller from the
concrete class. What remains on JSON is exactly the set of surfaces that *should* be: a
standalone CLI used for offline accuracy work, and Gradio, which MISSION §3 designates an
internal debug tool, not a product surface. Two stores behind one protocol, chosen per surface,
is the right end state — not debt.

**Alternatives rejected.** (a) *Migrate the CLI to Postgres* — breaks offline CLI use and makes
the accuracy tooling require a provisioned user row per student id; a real regression traded for
a deletion. (b) *Retire Gradio and drop the three CLI history commands* — deletes working,
shipped functionality to satisfy a cleanup item. Both are less reversible than keeping a
147-line class that has a passing test file and a proven-equivalent sibling.

**What would reopen it:** a decision that the CLI is a first-class product surface and should
share the product's identity model. That is a product call for Habeeby, not a refactor.
Recorded in `DELIVERY.md` §5 with this reason rather than the previous wording, which implied
unfinished work. **The build now has zero open checklist items.**

## D6.12 — Sign-in was broken outside a secure context, and every gate in the build was blind to it

**What.** `getDeviceId` (`web/src/lib/auth/storage.ts`) minted the client device fingerprint
with a bare `crypto.randomUUID()`. That method is **secure-context-gated**: it exists on
`https://` and on `http://localhost`, and is simply absent anywhere else. `getDeviceId` runs on
the **login path** — a fresh browser profile mints an id before a session exists — so on any
plain-HTTP non-localhost origin the first call threw `TypeError: crypto.randomUUID is not a
function`, the sign-in form caught it and rendered the TypeError as its own error message, and
nobody could log in. That set includes the LAN IP, `*.local` hostname and tunnel cases, i.e.
exactly how the Docker-Compose deployment MISSION §3 calls "done for deployment" gets reached
from a second device. Some older in-app webviews lack the method on `https` too.

**Fix.** `web/src/lib/uuid.ts` exposes `randomUuid()`, which tries `crypto.randomUUID`, then
`crypto.getRandomValues` — **not** secure-context-gated, so the hand-built RFC 4122 v4 layout is
a genuinely cryptographic UUID in precisely the environments missing the one-liner — then
`Math.random` for a host with no Web Crypto at all. Committed as `7bbf256`, pinned by
`web/tests/unit/uuid.test.ts` (one case per host tier, plus a 500-draw uniqueness check).

**Why a shared helper rather than a guard at the call site.** `CameraCapture` already carried
its own inline `typeof crypto !== "undefined" && "randomUUID" in crypto` guard with a
`page-${Date.now()}-${Math.random()}` fallback, so the codebase already had one private copy of
this workaround and `storage.ts` would have made two. Same reasoning as the `initialsOf`
consolidation in P3.7 chunk c.

**The `Math.random` tier is documented as non-cryptographic, deliberately.** Both current
callers need uniqueness, not unguessability: one is a React list key, and the device id is a
slot label the server matches against (`client_device_id` is an unvalidated nullable string
column) — never a credential, since the session is the bearer token. The docstring says so, so
that the third caller does not quietly inherit a weak random source for something that must be
unguessable.

**The part worth keeping.** This build's closing figures are 13/13 gates, 3508 tests, 73 axe
route-states, 44 Lighthouse reports, 246 screenshots — all green, all over a codebase where
sign-in was dead outside localhost. **Not one of them could have caught it**, because every
harness in the build (Playwright, Puppeteer, Lighthouse, the E2E server) drives the app at
`http://localhost`, and `localhost` is a secure context by definition. The gates were not
weak; they were *uniform*. Same family as D6.9 (`impeccable detect` vacuous on this machine)
and P6.6's dated VAPID assertion: **a green gate is a statement about the conditions the gate
runs under, and a condition every harness shares is a condition no harness tests.**

**Not done, and why.** The visual/a11y leg was not re-run for `7bbf256`: a UUID here is a React
list key and a `localStorage` value, neither of which renders, so the screenshot corpus and axe
results are unchanged by construction. Web test/typecheck/oxlint/build and all ten pre-commit
hooks were run and are green. **What would genuinely close this class** is a harness that
exercises the SPA over a non-localhost HTTP origin; that is a new test-infrastructure task, not
a line in this fix, and it is recorded here rather than started unattended.

---

## D3.22 — Redesign Phase 3: the audit could not see the largest IA defect, because source is not a viewport

Phase 3 (IA & UX flows) implemented DECISIONs D1.1–5 as approved-by-timeout, and
found more in the doing than the audit found in the looking. The findings worth
carrying forward:

**1. Neither the student nor the teacher portal had any navigation below
820px / 768px.** Both sidebars are `hidden` at those widths and nothing replaced
them: no tab bar, no menu, no drawer. A student on a phone could reach the screen
they landed on and whatever it happened to link to, and nothing else. The mission's
framing is "students live on phones".

The Phase 1 audit mapped nav *inventories* per role and got them right. It read
them from source, and source records which items a sidebar contains, never the
width at which that sidebar exists. The audit said so about itself — "nothing was
verified against a rendered viewport" — and this is what that limitation was
hiding. **The generalisable lesson is the same one D6.12 records from the build
era, arriving from the opposite direction:** there, every harness ran under one
condition (localhost) and so could not test it; here, the audit ran under one
condition (source, no viewport) and so could not see a whole class of defect.
A responsive defect is invisible to a reader who never resizes.

**Why a drawer and not a bottom tab bar.** The student nav carries eleven
destinations, the teacher's eight. A five-slot bar means ranking the survivors
and dropping the rest, which is a product decision Phase 3 has no answer for and
should not invent. The drawer carries every item the desktop sidebar carries.
`BottomNav` stays in the kit, unused, as the fast path Phase 4 may add *alongside*
it once daily-use data exists.

**2. Two cross-portal links were dead for every role that exists.** "Open the
teacher portal" in the student sidebar and "Open the student portal" in the
teacher's. `RequireAuth` gates each portal to disjoint role sets, so following
either one redirects straight back. No account holds both. They are build-era
conveniences from before the guard existed, left rendering in the product.

**3. Honesty defects survive in the places nobody re-reads.** The teacher
dashboard showed "Helwan Science Centre · Sunday 27 July" — a fabricated school
name of exactly the kind P3.7 and P3.10 had already deleted from both sidebars,
plus a hardcoded date, to every teacher every day. Both dashboards hardcoded the
time-of-day greeting. "Build a quiz" and "Post an announcement" sat disabled
under "Coming soon" chips while both features shipped and sat in the sidebar.
That last one had a *comment* above it asserting the features did not exist:
**the comment outlived the fact it described, and made the stale code read as
deliberate.**

**4. What gets a gate, and what gets left.** Three rules this phase could have
"swept" were instead given enforcement, because a sweep decays and a gate does not:
`scripts/check_copy.mjs` for the em-dash ban, `tests/unit/rtlSafety.test.ts` for
logical properties, `tests/unit/navigation.test.ts` cross-checking every nav
destination and crumb against the routes the router actually mounts. Each found a
defect while being written — dead keys in the student `crumbs` map, three false
positives in the copy checker, `isRange` blind to `${...}` interpolation — which
is the argument for writing them.

§9.8 binds the copy gate to "all new/edited copy", so the 91 remaining prose
em-dashes on un-migrated screens are Phase 4's, per surface, not a silent
exemption.

**5. Not everything should be unified.** The parent portal's first-run screen was
reviewed and deliberately left alone rather than converted to the shared
`GettingStarted` component. Every step there is an action somebody else takes on
another device, and that component models steps the reader performs, each with
somewhere to go. Forcing the shape would have produced three inert steps or three
buttons that lead nowhere. Only its copy changed.

**6. `GettingStarted` is constrained by what can be observed, not by what would
look good.** No endpoint reports per-step onboarding progress. So `done` is
caller-supplied and only passed with evidence, and in practice neither dashboard
passes it. A tick we cannot substantiate is a claim about the reader's own
history, and is worse than a fabricated statistic: it tells a student they have
already done something they have not.

**Standing gap, recorded not hidden:** Phase 2 emitted 19 kit components without
the hallmark pre-emit critique stamp §9.1 requires on every emitted surface.
Phase 3's six are stamped. The 19 are not, and Phase 4 should stamp each as it
touches it rather than back-fill scores nobody re-derived.

**Blocked, see `BUILD/BLOCKERS.md` B4:** the e2e functional-safety gate cannot be
fully evidenced. `reuseExistingServer` made Playwright adopt an unrelated
`python -m lemely.web` process squatting on port 8000 instead of starting
`scripts/e2e_server.py`, so the mocked vision seam never loaded and
`correct-paper.spec.ts` fails. Verified pre-existing (identical failure at
`0451e5e`) and verified environmental, not a product defect. Four of the five
specs whose assertions Phase 3 changed pass.

---

## D4.1 — Redesign Phase 4, surface 1 (student dashboard): the display face was never on screen, and three states nobody could see

Phase 4's first surface is the student dashboard: `screens/Overview.tsx` plus
the portal shell (`portals/student/index.tsx`) that every other student screen
renders inside. Migrating it to the Study Notebook found more than styling.

**1. The product's display typeface was not rendering anywhere.** `--font-serif`
was never a token in this system, so Tailwind's own default
(`ui-serif, Georgia, Cambria, "Times New Roman", Times, serif`) survived
untouched, and the ~20 `font-serif` call sites across Landing, Subject,
QuizBuilder, FlashcardReview and `primitives.tsx::Display` were rendering
**Georgia**. Newsreader was installed, imported, tokenised, documented in
DESIGN.md §4, and reached by nothing that used this class name.

Verified in the shipped bundle rather than reasoned about: `dist/assets/*.css`
carried the literal default stack before, and carries
`.font-serif{font-family:var(--font-display)}` after. The fix is one line in
the compatibility block, deliberately placed there rather than swept: Phase 4
migrates surfaces one at a time, and the un-migrated ones should not spend the
intervening phases in the wrong typeface.

**The generalisable point is what made it invisible.** Every gate this build
runs would pass a screen in the wrong font. The token-discipline gate greps for
raw values *bypassing* the token block, and `font-serif` is not a raw value —
it is a well-formed utility that happens to resolve to somebody else's default.
`tests/test_design_tokens.py` pins contrast, which typeface does not affect.
Nothing compares what DESIGN.md declares against what the bundle emits. A
missing definition fails silently where a wrong definition would not.

**2. Both dashboard panels rendered a blank chart instead of an empty state**,
which DESIGN.md §11 makes mandatory. `MomentumDTO` returns `path=""`,
`area=""`, `lastX="0.0"`, `lastY="88.0"` below two grade-bearing papers,
because a polyline needs two points, and this screen drew that unconditionally:
an empty plot box with one stray dot pinned to the bottom-left corner and an
empty label row. That state is not an edge case, it is **every student who has
just marked their first paper** — precisely the reader the first-run
getting-started view hands over to. Both panels now route through `ChartFrame`,
which has no children-only path that can skip the check.

**3. The trend column told a student with one paper that they were improving.**
`trend` is the first-to-last percentage delta, so with one paper first *is*
last and the delta is 0, while `trendUp` is `delta >= 0` and therefore true —
"+0" rendered in teal with an upward reading. A flat arm is now derived from
the number rather than the flag. Separately, the column carried its meaning in
colour alone (teal vs red on a bare signed integer) against §3.6; it now pairs
colour with a direction glyph and a spoken label, and the bare integer gets a
unit in its accessible name, since "+4" beside a percentage column does not say
percentage *points*.

**4. "Forecast" was a concatenation presented as a value.** The DTO builds it
as `" ".join(row.grade for row in subjects)`, so a student with three subjects
read "Forecast B A C" under a label promising one number. Every grade in that
string is already rendered one row below, attached to the subject it belongs
to. The presentation is removed; the DTO field is untouched.

**5. What the screenshot round caught that source review did not.** The
desktop grade badges rendered as "BPredicted" on one line: `GradeBadge` is an
`inline-flex flex-col`, and the call site's `md:block` overrode its display
mode, so the desktop copy collapsed while the mobile copy of the same component
stacked correctly. This is D3.22's lesson arriving a third time — a defect
invisible to a reader who never renders the thing. Also caught and fixed in the
same batch: ~600px of dead space in each subject row (the text column held the
flex share, and a subject row has almost no text, because `SubjectRowDTO.name`
echoes the code), and a momentum panel a third empty because an 88px chart was
pinned to the top of a card stretched to its taller sibling.

**6. The capture harness lied once, and now cannot.** `scripts/capture_surface.mjs`
stubs the API so the five states are deterministic, which is necessary because
**B4 still blocks the real corpus** — the foreign `python -m lemely.web` process
still holds port 8000, and a fresh signup against it can only ever produce the
zero-paper view, not the populated ledger or the one-paper state these changes
are about. Its first run produced ten images that were byte-identical per
viewport: Playwright matches the most recently registered route first, so the
catch-all swallowed `/api/me/profile`, `data.role.split("_")` threw, and every
state photographed the same error screen. Nothing said so; the only tell was
the file sizes. The script now hashes every capture and fails when two states
that must differ do not. **A capture round that silently photographs the same
screen five times is worse than no capture round, because it looks like
evidence.**

Worth recording that the bad round did prove one thing: Phase 2's error
boundary caught the render exception and showed its designed error screen
rather than white-screening, which is the gap audit finding C3 raised.

**Also fixed, smaller:** the student portal's breadcrumb was an inert mono
string while teacher and parent got D1.5's real trail, so no student sub-screen
had a back path that was not the browser gesture; it is now `Breadcrumbs`, fed
by a `resolveCrumbTrail` derived from `resolveCrumb` so the two cannot disagree.
`/student/result/:paperId` was interpolating a raw UUID into that crumb on the
flagship screen, against the honesty rule the teacher trail states and tests;
it now reads "This result", pinned by a test verified to fail on the old
behaviour. The sidebar's accent dot became the real Phase-2 mark (audit M9's
fourth stamp), eleven identical nav dots became Phosphor glyphs, the nav's
focus ring stopped being the accent (§3.9 makes focus deliberately blue so it
is distinguishable from the *active* state, which this nav marks in accent),
and the hand-rolled circular avatar became the kit's squircle `Avatar` — a
circle in a sidebar footer sitting directly under eleven circular nav dots is
exactly the collision §6 reserves the circle against.

**Deferred, not silently dropped:**

- `SubjectRowDTO.name` echoes the syllabus code, so the dashboard shows "0625"
  where "Physics" would read far better. The authoritative table exists
  (`lemely/db/seed.py::DEMO_SUBJECTS`); `_subjects` in
  `lemely/web/routers/student.py` should resolve against it. Not done here:
  that is a data change, and smuggling one into a design pass is how a phase
  stops being reviewable. Subject *colour* is handled client-side in
  `subject-tag.tsx` because which pastel means Physics is a design decision.
- The kit uses `focus-visible:outline-accent` in several components, against
  §3.9's deliberately-blue focus ring. Fixed in this surface's nav only;
  product-wide it belongs to the surfaces that own those components.
- `primitives.tsx::Eyebrow` is mono where DESIGN.md §4.2 puts the `eyebrow`
  rung in Geist. Left alone on purpose: changing the face would restyle a dozen
  screens this surface does not gate and cannot see.
- `check_copy` holds at 91. This surface had no prose em-dashes of its own to
  clear, so the count is unchanged rather than reduced.

---

## D4.2 — Redesign Phase 4, surface 2 (past-paper correction flow): a run that could fail in silence, and two numbers set in the wrong face

Surface 2 is the flagship flow: `screens/CorrectPaper.tsx` (upload, the marking
wait, the failure) and `screens/PaperResult.tsx` (the result a student comes to
the product to read). Migrating it to the Study Notebook found five things that
are not styling. Two of them are defects no gate in this build could see.

**1. A marking run could end with no result, no error, and no way to tell.**
`streamActivity` (`lib/api.ts`) never checked `res.ok`. A FastAPI 500 or 503
carries a JSON body, so `res.body` was truthy, the reader found no `data:` lines
in it, the generator ended, and `CorrectPaper`'s `for await` loop simply
finished. `finally` set `running` to false and the panel went back to reading
**"Ready when you are"**. A student pressed the button, watched nothing happen,
and was told the screen was ready. `request()` and `fetchBlobUrl()` both throw
on a non-OK response; this was the one transport of the three that did not, and
it is the one carrying the longest-running request in the product.

Fixed in two places, because there are two ways to end without a result. `api.ts`
now throws an `ApiError` built the same way `request()` builds it (so a caller
reading `.detail` gets the same shape from all three transports), and the screen
now treats *falling out of the loop* — a connection that dropped mid-run — as
the failure it is, with `STREAM_ENDED_WITHOUT_RESULT`.

**Worth noting what made it invisible.** The comment directly above the missing
check already described the failure mode: "a failure here is silent (no body,
generator ends, the screen just never shows progress)". It was written about the
401 path, and the fix it prompted was a token refresh. The same sentence was
true of every other status code and nobody read it that way.

**2. The student's confidence threshold disagreed with the backend's and with
the teacher's.** `PaperResult` bucketed each mark against **0.85**, described in
its own comment as "a frontend judgement call made for this retrofit". The real
review floor is `lemely.core.schemas.REVIEW_CONFIDENCE_THRESHOLD` = **0.90**, it
is not operator-tunable, and `routers/teacher.py:688` counts confidence against
it directly. So a mark at 0.87 was called *confident* on the student's copy of
the paper and *not confident* on the teacher's copy of the same paper, and the
number shown to the student was the invented one.

Nothing in either test suite could see it, because each side was internally
consistent. It now lives in `lib/markingConfidence.ts` and is pinned against the
Python constant by `tests/test_web_shared_constants.py`, which also fails on any
*other* web module that reintroduces a bare numeric confidence comparison —
verified by inversion, not assumed.

The landing page has already been corrected on this exact number once: D2's
record notes its stated "confidence floor" read 0.70 and the real one is 0.90.
Same number, wrong in a second place, found eleven phases apart.

**3. The mark and the grade were set in the heading face.** DESIGN.md §4 gives
the data face "all scores, **grades**, marks, XP, timers, paper codes, IDs", and
§4.2's `data-lg` rung is named for precisely this: "the big number: a score, a
predicted grade". `MarkDisplay` rendered its hero as `display-hero` (60px
Newsreader) and `GradeBadge` rendered its letter with `font-serif`. The two
figures a student reads first on the flagship screen were both in the wrong
family.

`MarkDisplay`'s own docstring stated the rule while the code broke it: "Numeric
figures use JetBrains Mono **at the inline size**". The rule was applied
everywhere except the one call site it was written for. This is D4.1's
`--font-serif` finding a second time and it fails the same way — a well-formed
utility resolving to a face nobody chose, invisible to a token gate that greps
for raw values *bypassing* the block. Both are corrected and verified in the
shipped bundle (`dist/assets/*.css` carries
`.text-data-lg{font-family:var(--font-mono)…}`), not reasoned about.

**4. The page could not do what its own first sentence promised.** "Scan or drop
the paper" has been the opening line of this screen since the build era, and
there was no drop target anywhere on it — a bare `<input type="file">` with a
styled `file:` pseudo-element. `FileDrop` (C-21) is a real one, and it is a real
`<input>` underneath: visually hidden but focusable, with a bound `<label>`, so
it works from a keyboard and on a phone where there is nothing to drop from.
Drag-and-drop is layered on as a pointer-only enhancement, which is the correct
direction. All 8 states, with a preview cell.

**5. Retry in place (audit M5).** The only path out of a failed run was to pick
the file again and re-upload it, redoing the one part of the run that had
succeeded. `paperId` is now held past the failure, so the retry re-opens the
stream against the scan the server already has, and the panel says so
("Your scan is already uploaded"). `uploadScan` and `runCorrection` were always
two calls; nothing about this needed a backend change.

**Audit M4 is deliberately NOT done here**, and the reason is worth recording
rather than deferring silently. The run lives in component state, so a refresh
mid-marking loses it. The teacher console hit the identical defect and the fix
was architectural: D6.13 records that marking became a server-side job the
console *polls*, "precisely so a reload could not wipe the only progress
readout". The student side still drives its run from the browser stream, i.e.
**the defect was fixed on one side of the product and left on the other.** That
is a backend change, Phase 6.2 owns it, and smuggling it into a design pass is
how a phase stops being reviewable. What is done here is the half that is honest
to do now: the failure has a way out.

**What the screenshot round caught that source review did not** (four findings,
fixed in one batch, one confirm round, stopped there per §3.2 item 16):

- **On a phone, everything that reports progress sat below the whole upload
  form.** Pressing "Mark this paper" pushed the status panel roughly 1700px off
  the bottom of the screen. On the product's longest, highest-latency flow, on
  the device its own brief says students live on, the panel that says what is
  happening was the one thing you could not see while it happened. It now leads
  on mobile once a run is in flight or has failed, and does not on desktop,
  where both columns are visible anyway.
- **Two identically sized drop zones stacked**, giving a reader nothing to tell
  the required upload from the optional one. `FileDrop` grew a `compact`
  density; the scheme field uses it.
- **Two buttons reading "Start marking again" at once**, the header's and the
  panel's. The header action is now hidden while a failure is showing, so the
  screen keeps the single obvious primary action the Operate lane asks for and
  it sits next to its reason.
- **The result card's integrity sidebar was two-thirds empty**: a short column
  in a grid stretched to a much taller sibling, with the provenance block pinned
  to the bottom by `mt-auto`. Identical in shape to D4.1's momentum-panel
  finding, one surface later.

**Also fixed, smaller.** The result screen rendered two stacked kickers
("Against the 2024 boundaries" above `BoundaryBar`'s own "Grade boundaries")
with an indented empty widget beneath them; `BoundaryBar` now takes the label.
`railFoot` ("63/80") was removed from the presentation — it is the same number
`MarkDisplay` shows at 32px four lines above, the same judgement as D4.1's
"Forecast" removal, and the DTO field is untouched. The 404 body interpolated
the raw paper id into a sentence for the reader. The four terminal states of
`PaperResult` were four hand-built page shells that had already drifted (two
used a build-era 22px gap, two used 24px); they share one now. And the student
shell's "Correct a paper" CTA was a `<Button onClick={navigate}>` — the same
finding D4.1 fixed on the dashboard's subject rows, sitting unremarked in the
shell that renders above *every* student screen — and it rendered on
`/student/correct` itself, where pressing it does nothing observable. It is a
`<Link>`, and it is not rendered on the screen it points at.

**The capture harness now takes a surface.** `scripts/capture_surface.mjs` was
written for one screen; it is now a registry of surfaces over a shared harness
(server, session, viewports, catch-all route, duplicate detector, console-error
log). Copying the file per surface was the alternative, and eight copies of a
duplicate-detector is how the detector ends up disabled in seven of them.
Surface 1 was re-run through the generalised version to prove it still produces
its ten distinct captures.

**Gates.** typecheck / lint / **694 unit tests (+32)** / `check:copy` **90, down
from 91** / 30 Python token+constant tests / both builds / pre-commit (with
`.venv/bin` on PATH — `mypy` and `lint-imports` are `language: system` hooks and
are invisible to a bare `pre-commit` invocation): **all green**. 28 captures
across three surfaces, all distinct, console errors only the deliberately-failing
states' own 404/500/503. **e2e still blocked by B4** — port 8000 is still held by
the foreign `python -m lemely.web` process, verified again this session.

---

## D4.3 — Redesign Phase 4, surface 3 (study surfaces): two destructive actions with no confirmation and no failure report, and a bar that measured something other than the number beside it

Surface 3 is the Read lane's first appearance in this redesign: `screens/flashcards/`
(decks + review), `screens/studyplan/` (week + session), `screens/practice/`
(generator, set, result, print). Eight screens, ~1,970 lines. "Classifieds" in the
mission's surface list has no screen of its own — it is the **classified-worksheet
practice flow**, i.e. `PracticeGenerator`, which builds a set from topic and
difficulty filters. Recorded here so a later reader does not go looking for a
missing screen.

**1. Deleting a deck was unconfirmed, and both deletes were silent on failure.**
One tap on a Trash glyph destroyed a deck and every card in it. There was no
confirmation step, and — the part no gate could see — `useDeleteDeck` and
`useDeleteCard` both expose `isError` that **nothing rendered**. So a delete that
failed left the deck sitting exactly where it was, with no message, which is
indistinguishable on screen from a delete the student imagined pressing.

What makes it a finding rather than an omission is which mutations were covered:
`addCard.isError` and `editCard.isError` were both rendered, carefully, right next
to their fields. The two mutations with no error path were the two **destructive**
ones. The reversible operations reported their failures and the irreversible ones
did not.

This is D4.2's headline shape a second time. There it was `streamActivity` falling
out of its loop and the panel going back to "Ready when you are"; here it is a
DELETE returning 500 and the screen showing the deck as though nothing happened.
Both are "the action failed and the UI's resting state is indistinguishable from
success". Both now say so.

The fix uses `Modal`'s `dismissible={false}`, whose own docstring names this exact
case — "destructive confirmations where an accidental Escape must not discard a
decision silently" — and which had **no call site in the product**. Phase 2 built
the affordance; this is the first surface that needed it.

**2. The week bar and the count beside it measured different things.** On
`StudyPlanWeek`, `weekProgress().percentComplete` is completed **minutes** over
planned minutes. The line directly above the bar counts **sessions**. So a student
who had finished two short sessions out of four read "2 of 4 sessions done" beside
a bar sitting at 25%, with nothing on screen accounting for the gap. Neither
number was wrong; the screen just presented two different denominators as though
they were one fact rendered twice. The bar now carries its own label stating its
own denominator ("45m of 2h 5m planned study time done").

Found by reading `studyPlanData.ts` rather than the screen — the screen's own
`aria-label` said "Study time completed this week", which was *correct* and was the
clue. `completedMinutes` was computed by the DTO and rendered nowhere.

**3. That same bar animated `width`.** It was hand-rolled — `role="progressbar"`
plus a filled `<div>` driven by `transition-[width]` — where DESIGN.md §9.2 says
animate only `transform` and `opacity`, no exceptions. A layout-animating property
on the one element that changes every time a session is ticked off. It is C-24
`ProgressBar` now, which is also what `FlashcardReview` two screens away was
already using: one surface shipped two progress bars, and the hand-rolled one was
the one that broke the rule.

**4. The Read lane rendered at four different widths.** DESIGN.md §13 fixes the
Read container at 680px. The eight screens carried `max-w-[560px]`, `[640px]`,
`[720px]` and `[840px]`, so the same lane changed measure depending on which link
a student followed. They share one `lm-read` utility now, with `lm-prose` (65ch)
separate from it, because §2 caps *prose* at 65ch while the column still has to
hold full-width cards and rows — collapsing the two would have shrunk every card
to text measure.

**5. The texture layer had never been used.** `ruled-bg` and `dotted-bg` were
written in Phase 2, are named by §8 item 2 **for the Read lane specifically**, and
had **zero call sites product-wide**. Not a defect in prior work — surfaces 1 and 2
were both Operate, where §13 turns texture down — but this is the first Read
surface, so it is the first one where they were supposed to appear. The flashcard
card face is ruled now, and it is the only texture element on that viewport, well
inside §8's budget of two. `EmptyState`'s `marginalia` prop (the Caveat layer) had
two call sites in the entire product, both on surface 2; the empty states here now
carry it.

**Also fixed, smaller.** The card editor hand-rolled six `<input>`s off a local
`CARD_INPUT_CLASS` that pinned focus to the accent, against §3.9's deliberately-blue
focus ring — they are C-6 `Input`s now. The new-deck size control was a raw
`<input type="range">` while the practice generator on the same surface used the
kit `Slider`. The keyboard shortcuts on the review screen ("(Space)", "(1)") were
plain prose spans, so the affordance that makes that screen fast was
typographically identical to the label it annotated; C-19 `Kbd` existed and was
unused. Six text loaders became layout-matching skeletons. `PracticePrint` indented
its MCQ options with a physical `pl-4` (the one real RTL violation this sweep
found) and had no zero-questions case, so an empty export rendered as an empty
bordered box under a Print button that would have printed a blank sheet. The
"nothing due today" panel was drawn with a **warn** border — a colour that says
"this needs your attention" about the one state on that screen needing nothing.
And `PracticeResult`'s marking wait was a bare spinning glyph, where §12 permits a
spinner only "for an indeterminate action under ~1s inside a button"; it is
`ProgressBar`'s indeterminate mode now, which its docstring describes as being for
exactly this.

**A judgement call, stated rather than buried.** DESIGN.md §2 says the Read lane
has "no sidebar; navigation collapses to a back path and progress". These screens
keep the student sidebar. Removing it is a shell-level IA change affecting every
student route, and these are screens a student moves *between* (practice →
flashcards → plan); stranding them without the portal nav to satisfy a macrostructure
line would cost more than it bought. What is applied is the rest of the lane: the
680px column, the prose measure, the texture allowance. Flagged for Phase 6 rather
than silently half-done.

**QuizTaker: tokens only, deliberately.** `PracticeSet` is a thin wrapper around
`components/quiz/QuizTaker.tsx` (708 lines), which is **shared with `PlacementTest`**
— a screen belonging to the Auth/onboarding surface this one does not gate. Its 21
compat-token call sites were migrated because the aliases are *value-identical*, so
that change is provably a no-op for placement while removing this surface's last
compat dependency. Its layout and structure were left alone. Same reasoning as
D4.1's `Eyebrow` deferral: changing what another surface's gate has not seen is how
a phase stops being reviewable.

**The new gate, and why it is a source gate.** `tests/unit/studyNotebookMigration.test.ts`
asserts that a migrated file names no compat-layer alias, that every Read screen
takes its column from `lm-read` rather than an arbitrary pixel width, and that no
migrated file animates a layout property. It has to read source rather than pixels:
the compat aliases resolve to the correct values *today*, so `text-t1` renders
identically to `text-ink` and no screenshot, contrast measurement or rendered check
can tell them apart. That is the D4.1 `--font-serif` failure shape exactly — a
class that is well-formed, resolves to something, and is therefore invisible to
every gate that looks at output. All three assertions were **verified by inversion**
(a real violation reintroduced, the gate observed failing, then reverted), and the
comment-stripping needed a cross-line block-state machine rather than a per-line
test — assuming per-line was enough is what made the gate first report the middle
line of a JSX comment describing the very fix it was checking for.

**Gates.** typecheck / lint / **752 unit tests (+58)** / `check:copy` **69, down
from 90** (21 cleared; the surface's own em-dashes were page titles of the form
"Flashcards — Physics", replaced by restructuring rather than by swapping
punctuation) / 30 Python token+constant tests / both builds / pre-commit with
`.venv/bin` on PATH: **all green**. Visual round: 28 captures across four
registered sub-surfaces at 1440 and 375, all distinct, console errors only from the
deliberately-failing state. Four findings from the round, fixed in one batch, one
confirm round, stopped there (§3.2 item 16): the revealed answer was the quietest
thing on the card that exists to show it; a whole sentence was set in the data face
where §4 gives that face figures only; two deck counts with no delimiter scanned as
one run-on string; and the review card floated in the top third of a tall empty
desktop well, D4.2's integrity-sidebar shape on the screen least able to carry it.
**e2e still blocked by B4** — port 8000 re-verified occupied this session.

**Deferred, not silently dropped:**

- `ConfidenceIndicatorSummary` renders in full error-red whenever any question
  needs review, so a routine practice result (2 of 4 confident) is framed as an
  alarm. It is a kit component shared with `PaperResult`, which surface 2 gated and
  shipped, so retoning it here would restyle a screen this surface cannot see.
  Belongs with the Phase 5/6 pass that owns the kit's semantic tones.
- `Chip` (`components/ui/chip.tsx`) is still the build-era component and is written
  entirely against compat aliases. This surface's call sites moved to `Badge`; the
  component itself is still consumed by un-migrated screens and dies with them.

---

## D4.4 — Redesign Phase 4, surface 4 (gamification): a page-title class that was never a class, and the celebration register built at last

Surface 4 is `screens/Standings.tsx` (leaderboards), `screens/Friends.tsx`,
`screens/Profile.tsx` (the training log) and `components/ui/xp-streak.tsx`.
This is the surface DESIGN.md §9.3 was written for: the celebration register
had no implementation anywhere in the product, only four unused tokens
(`--ease-celebrate`, `--dur-celebrate`) and a paragraph of prose.

### The headline: `text-display` is not a class, and four `<h1>`s carried it

D4.1's finding was `--font-serif`: a token that never existed, so ~20 call
sites rendered Georgia instead of Newsreader for the whole build era. **The
same shape is here in a different family.** `text-display` is defined nowhere
in `index.css`, there is no `--text-display` or `--color-display` for Tailwind
to generate it from, and the shipped bundle contains **zero** rules matching
it — verified by grepping `dist/assets/*.css` for `.text-display{`, not by
reasoning about it.

Four page titles named it: `Profile`, `Standings`, `Friends` and
`Announcements`. All four rendered at the browser's default `<h1>` — 2em bold
in the body sans face — where §4.2 puts `display-lg`, 32px Newsreader. Three
are on this surface; the fourth is on an un-migrated screen and was fixed
anyway, per P4.2's second lesson.

**Twice is a pattern, so the deliverable is a gate for the pattern**:
`tests/unit/utilityExistence.test.ts`. It compares the `text-`/`bg-`/`border-`/
`font-` names migrated source uses against the names the stylesheet actually
defines, and fails on any that resolve through none of the legitimate routes
(a literal `.class`, a theme variable, a Tailwind built-in, an arbitrary value,
an opacity modifier). Verified by inversion on the real string.

Why nothing else caught either one, stated because it is the interesting part:
the token gate greps for raw values *bypassing* the token block, and a missing
class contains no value; the migration gate lists *build-era* names, and a
name that never existed is not on it; contrast tests measure declared tokens,
and this one was never declared; screenshots and axe see a heading that still
looks like a heading. **A well-formed class name that resolves to nothing is
invisible from every direction except comparing source against stylesheet.**

### The celebration register (§9.3), and the one moment it deliberately omits

`lib/celebration.ts` (rules, DOM-free, 20 tests) + `components/ui/celebration.tsx`
(`CountUp`, `Flourish`, `Celebrate`, `MilestoneSticker`) + two keyframes in
`index.css`. Three properties are load-bearing:

1. **A count-up never displays a figure the student has not earned.**
   `--ease-celebrate` overshoots y=1 by design; on a scale that is the spring,
   on a *number* it would render ~1,240 XP on the way to 1,180. The easing is
   shared, the number's progress is clamped, and monotonicity plus the ceiling
   are pinned by tests.
2. **Reduced motion is read in JS, not just CSS.** index.css's global rule
   flattens CSS durations and cannot reach a `requestAnimationFrame` loop.
   Without the `matchMedia` check, "reduced motion" would have meant
   "everywhere except the one animation written in JavaScript".
3. **Only an increase celebrates, and never a first observation.** A mount or a
   refresh staging a gain that did not happen on this visit is §9.3's banned
   engagement-celebration arrived at by accident. Day 1 is not a milestone for
   the same reason.

**§9.3 names "a leaderboard climb" and this surface does not have one.**
`LeaderboardRow.rank` and `LeaderboardViewer.rank` are the only rank fields on
the wire and both are *current*; nothing records where the student stood
before. A climb flourish would have to invent the movement it congratulates, on
a screen whose own header comment forbids inventing a last place. Not faked.
It needs a `previousRank` on the DTO.

### Five other findings

- **C-9 `XPStreak` had no call site anywhere in the product.** Built in Phase 2
  for this surface; this surface then hand-rolled its own cards. Same shape as
  surface 3's unused texture classes. Resolved by giving it the call site its
  docstring names: the student header. That pill has history — P3.10 chunk c
  deleted a "24 day streak" pill because the 24 was a literal, and recorded
  that wiring it to `StandingsDTO.streakDays` "would have replaced a hardcoded
  lie with a mislabelled one" since that field counts distinct active days, not
  consecutive ones. Its closing note was "streaks are Phase 5's to build for
  real". Phase 5 built them, so the pill is restored from
  `GET /api/student/xp`'s genuine `streak.current`. It renders nothing while
  loading and nothing on failure (a `0` would state a broken streak the student
  may not have), is hidden below 640px where this row has previously
  overflowed, and is a `<Link>` to the training log.
- **The header pill is shape-checked, not presence-checked.** It renders above
  all 24 student routes, so `xp.data.streak.current` on a body without a
  `streak` would throw *inside the shell* and blank every screen.
  `request<XpProfile>` is a cast, not a validation. Found while stubbing the
  captures, whose catch-all answers unmatched calls with `{}` — exactly that
  body, exactly that crash.
- **Friends reported every mutation failure in the wrong words, and two of
  three in the wrong place.** All three rendered `err.message` verbatim, so a
  dropped connection showed the browser's `TypeError: Failed to fetch`; and
  accept/remove printed theirs in a block at the very bottom of the page, below
  every section, so a student who declined a request at the top got a notice
  quite possibly off-screen. `lib/friendOutcome.ts` owns the wording (keeping
  the backend's own sentence where it wrote one for a human, which was a
  considered decision and survives); placement moved into the section that
  produced it.
- **The opt-out toggle's `isError` was rendered nowhere.** A failed "Hide me"
  left the control reading its old value with no explanation, and the student
  reasonably concludes they are hidden when they are not. Same shape as surface
  3's two destructive deletes.
- **`npm run check:copy` never read a `.ts` file.** User-facing copy has been
  moving out of components since P4.2 (`correctionOutcome.ts`, every screen's
  `*Data.ts`). Extending the walk found **9 real em-dashes in user-facing
  strings no run of this gate had ever seen, five of them on surface 3, which
  had been reported clean.** D6.12's lesson again: a condition every harness
  shares is a condition no harness tests. Here it was a file extension. The
  reported total is not comparable across the change — 64 under the old scope,
  67 under the new one. The count did not grow, the gate's eyesight did.

### Found by the gates, in my own new code, worth recording

- `tsc` caught `Celebrate` accepting a documented `flourish` prop and never
  reading it — so `flourish={false}` on the training log's XP total was
  throwing confetti anyway. That is P4.2's first lesson (a docstring stating a
  rule the component breaks) reproduced by me, and caught by an
  unused-parameter check rather than by anything looking at the screen.
- The token gate rejected an arbitrary one-pixel radius on the confetti pieces,
  then rejected the *comment* explaining the old value. Both correct.
- A "known reference value" I asserted for the Bézier solver was wrong from
  memory; the implementation was right. Replaced with a point derived by hand
  in the test's own docstring, so the test asserts something other than that
  the code equals itself.

### Visual round

30 captures across 3 registered sub-surfaces (`standings`, `friends`,
`profile`), 1440 + 375, all distinct, console errors only from the deliberately
failing states. One inspection round found four, all fixed in one batch, one
confirm round, stopped (§3.2 item 16):
(a) the Level and Streak cards labelled their figures in opposite orders while
sitting side by side; (b) the "Your subjects" rank column had no label, so a
tone-coloured "3" sat beside "9 papers" inviting the two to be read as a pair;
(c) the Send request button was aligned to the field *wrapper*, which grows a
line on error, so pressing it with a bad code dropped the button below the
field; (d) the friend-code field spanned the full card width, about 1350px at
1440, for an eight-character value.

### Deliberately not done

- **A confirmation modal on "Remove" / "Decline" / "Cancel".** D5.6 §3 settled
  this: all three delete the same row, the mistake is cheap and recoverable by
  asking again, and a modal would cost more than the error it prevents. Surface
  3's confirmation finding was about *irreversible* destruction; this is not
  that, and applying the same fix here would be pattern-matching rather than
  reasoning.
- **Lifetime stats and achievements on the training log.** Still absent, still
  correct (D5.13 §3): every available source is wrong by construction under the
  daily caps and the dedupe. The screen looks thin because that is its honest
  shape.
- **`Chip` migration.** Still build-era, still consumed by un-migrated screens,
  unchanged from D4.3's note.
- **Placement's three em-dashes**, now visible to the widened copy gate. They
  belong to an un-migrated surface and clear when it lands.

---

## D4.5 — Redesign Phase 4, surface 5 (teacher portal): a class family the gate could not see, and a review queue that painted doubt green

Surface 5 is the whole teacher portal — 19 files, 7,432 lines, 908 build-era
class usages, none of them migrated. The mission names this surface "teacher
dashboard + quiz builder", and those are its two headline screens, but no later
surface covers Grading, Review, ReviewItem, MarkSchemes, Classes, ClassDetail,
ClassRoster, StudentDetail or Announcements. Leaving them would ship a portal
half in each language and fail §12's "zero pages left in the old language", so
the surface is the portal. It landed in five commits, A–E.

### The headline: the resolves-to-nothing shape, third and fourth time, inside the gate's own blind spot

D4.1 was `--font-serif`, a token that never existed. D4.4 was `text-display`, a
class that never existed, and its deliverable was `utilityExistence.test.ts` —
a gate for the *pattern* rather than the instance, on the grounds that twice is
a pattern.

It recurred anyway, because that gate checks `text-`/`bg-`/`border-`/`font-`:
the four families where **Tailwind** owns the vocabulary. `lm-` is the one
family where the **project** owns it outright, and it was never scanned.
`lm-head` and `lm-body` sat on the student shell's `<header>` and `<main>` —
in a file the gate already listed by name. Widening it to a fifth family
immediately found a fourth instance, `lm-cols`, on nine elements across four
screens, two of them migrated surfaces.

All six emit **zero** rules in `dist/assets/*.css`, verified by grepping the
shipped bundle rather than by reasoning about it, and nothing selects on them
in source, tests, scripts or the capture harness. They are removed rather than
defined; in every case the layout was already carried entirely by the real
utilities beside them.

The `lm-` family is the *easiest* of the five to check, not the hardest: there
is exactly one legitimate route, a literal `.lm-x` rule in `index.css`, with
none of Tailwind's generated-utility, arbitrary-value or built-in escape
hatches to allow for. It was unscanned because the gate was written from the
two instances in front of it, and both happened to be Tailwind-shaped.

### The second headline: the review queue called sub-floor marks confident

`Review.tsx` carried its own `confidenceTone`, bucketing at **0.8**. The review
queue exists *because* a mark scored below `REVIEW_CONFIDENCE_THRESHOLD`
(0.90) — that is what puts an item in it. So a mark at 0.85 arrived in the
queue as not-confident and was then painted in the same green the product uses
for marks it is sure about, on the one screen whose entire job is directing a
teacher's attention to doubt.

This is D4.2's finding a second time, and `lib/markingConfidence.ts` was built
in P4.2 to be the single owner of this decision precisely so it could not
recur.

**Why the gate written to prevent it missed is the part worth keeping.**
`tests/test_web_shared_constants.py::test_no_other_web_module_invents_its_own_confidence_floor`
greps for a bare numeric comparison against the word `confidence`. This
function's parameter is called `score`, so the word never appeared beside the
operator and the gate saw nothing. That is D6.12's lesson in miniature — a
condition every harness shares is a condition no harness tests — and here the
shared condition was an assumption about *naming*: that a variable holding a
confidence would be called one. The gate now matches a list of aliases, skips
comment lines so it cannot fail on its own fix note, and carries an inversion
test asserting it catches the exact line that shipped.

**The fix also drops the queue from three confidence tones to two, and that is
the point rather than a casualty.** The old third band split "uncertain" again
at 0.5, and no such number exists anywhere in the product: the backend has one
threshold, so any second boundary is a frontend invention — the defect class
the module exists to close. Nothing is lost to the reader, since the score is
printed beside the chip.

### Portal-wide findings

- **Every one of the fifteen screens rendered a raw `error.message`**, at 44
  call sites. A dropped connection put the browser's `TypeError: Failed to
  fetch` in front of a teacher. This is surface 4's Friends finding at fifteen
  times the scale, so it gets `lib/teacherOutcome.ts` — the third module in the
  family after `correctionOutcome.ts` and `friendOutcome.ts`. Two entry points,
  because a failed read asks "can I retry" and a failed write asks "did it
  save"; the honest answer to the second is always no, since every mutation in
  this portal is a single request. The endpoint's own `detail` still wins where
  there is one: the at-risk acknowledge route's 422 is a real race with no
  other spelling.

- **Destructive actions were confirmed by `window.confirm`, at four sites**,
  including deleting a class, which the dialog itself says "removes it for
  every enrolled student". Surface 3 established `Modal dismissible={false}` as
  the pattern and built exactly one, on the student flashcard deletes; the
  teacher portal never used it. `window.confirm` is worse than it looks: its
  buttons say "OK" and "Cancel" so the destructive choice is never named, it
  cannot show the pending or failed state of the mutation behind it, and
  browsers may suppress it after repeated use, so a confirmation the product
  believes it is showing can silently stop appearing. C-24 `ConfirmModal` lifts
  surface 3's implementation into the kit and `FlashcardDecks.tsx` now consumes
  it rather than owning a private copy.

  The four do not say the same thing. The component's default consequence is
  "This cannot be undone.", true for deleting a class or an announcement and
  **false** for removing a student from a class (reversible from the form
  directly above it, and it does not touch their marked work) and for
  unassigning a quiz. Each states its own real consequence; that is why
  `consequence` is a prop rather than a constant.

- **`portals/teacher/components/Avatar.tsx` was a `rounded-full` circle at six
  call sites across five screens** — the exact violation the kit's `<Avatar>`
  was written to prevent (§6: avatars are squircles, circles mean status). The
  kit component had one call site product-wide. Same shape as surface 4's
  unused `XPStreak`. Deleted; the six move over and gain an accessible name
  they did not have.

- **`StatCard`'s big number was `display-lg` Newsreader** where §4 puts the
  data face, and the same defect recurred on the class cards' average mark, the
  six engagement figures, and four mark inputs. Every one of those values is
  `str(round(...))` from the server. D4.2 again: the same figures in the same
  product set two different ways depending on which portal you were looking at.

- **Ten hand-rolled inputs and three selects**, all with `outline-accent` where
  §3.9 puts a deliberately blue focus ring, none with the disabled/error states
  §9 gate 4 requires. One `<label>` wrapped a loading branch, so while classes
  were fetching it pointed at no control at all.

- **The teacher portal had no texture layer at all** — no `paper-grain`, which
  the student shell has had since surface 1. It is the cheapest carrier of §1's
  protected quality and its absence is most of why the portal read as the
  generic dashboard §1's anti-references name.

- **The brand lockup was still the placeholder** accent circle with an italic
  `l` (audit M9, "stamped in three places"). The student copy was replaced in
  surface 1; this one was still live. P4.2's second lesson exactly. It was also
  a `font-serif` call site, so the placeholder was not even rendering in the
  face it reached for.

### A workaround retired because the thing it worked around was fixed

`Quizzes.tsx` and `QuizBuilder.tsx` both deliberately avoided the `--t3` step
and used `--t2` for every muted label. The reason was real and measured: axe
put the build-era `--t3` at **4.36:1** against the default surface, below the
4.5:1 AA floor, at the 10–13px sizes those labels use. `QuizBuilder`'s module
doc recorded that fixing the shared token was out of that chunk's scope.

Phase 2 fixed the shared token. `--ink-faint` sits at L 0.529 *specifically* so
it clears AA against the darkest surface it ever meets — 4.94:1 on `--paper`,
5.17:1 on `--paper-raised`, 4.60:1 on `--paper-sunk` — and DESIGN.md §3.2
removes the lighter fifth step that made the defect reachable. All three ratios
are pinned by `tests/test_design_tokens.py`. The divergence is retired: these
screens are AA by construction rather than by avoidance.

### The copy gate's classifier had two gaps, and the classifier was fixed rather than the source

`check_copy` reports prose em-dashes and exempts placeholders. Two exemptions
were too narrow and were reporting real placeholders:

1. It bailed out of the quoted-placeholder exemption whenever a line held more
   than one dash, so the review queue's `{awarded ?? "–"}/{maximum ?? "–"}` — a
   row where neither figure is known — was counted as prose. The bound existed
   only because `indexOf` cannot locate a second match.
2. The JSX exemption looked for `>` and `<` within 12 characters *on the same
   line*, so a dash a formatter had wrapped onto its own line was missed.

Both widenings are pinned in the strict direction too: a line holding a
placeholder **and** a prose dash must still report, and a lone dash with words
beside it is still prose. Contorting the source to satisfy a classifier would
have been the wrong repair — the gate encodes judgement calls, and these two
were wrong.

Count: **67 → 18**, and none of the 18 are in the teacher portal. 51 of the
original 67 were.

### Deliberately not done

- **Nivo charts.** `@nivo/*` is not installed; §11's chart theme is Phase 5's
  named work and building it here would pull that phase forward into a surface
  pass. `ClassAnalytics`'s hand-rolled grade bars and cohort table are migrated
  in place, and the empty-data states §11 requires already exist.
- **A confirmation on bulk-approve.** It approves marks rather than destroying
  rows, and every item it touches remains individually reviewable afterwards.
  Applying surface 3's confirmation finding here would be pattern-matching
  rather than reasoning, the same call D4.4 recorded for the friend actions.
- **`Chip` migration.** Still build-era, still consumed by un-migrated screens,
  unchanged from D4.3's and D4.4's notes.

---

## D4.6 — Redesign Phase 4, surface 6 (parent views): the banned easing was the default on every transition, and two back links to one place

**Surface:** the whole parent portal — the shell plus its four screens
(`portals/parent/`, 5 files, 1,015 lines), plus the two kit components only it
and one teacher screen still consume (`weakness-chip.tsx`,
`trend-sparkline.tsx`).

### The headline: DESIGN.md's banned easing was in force product-wide, and no call site named it

§3.2 item 14 says "never `linear` or `ease-in-out` on a designed transition",
and §9.1 gives four custom easings for the purpose. Every one of the 27
`transition-colors` / `transition-transform` call sites across the migrated
surfaces and the whole component kit was running on
`cubic-bezier(0.4, 0, 0.2, 1)` — symmetric ease-in-out under another spelling —
because Tailwind's own `--default-transition-timing-function` is that curve and
a bare `transition-*` inherits it.

**Verified in the shipped bundle before and after, not reasoned about.**
`dist/assets/index-*.css` carried
`--default-transition-timing-function: cubic-bezier(.4, 0, .2, 1)` with six
utilities resolving through `var(--tw-ease, var(--default-transition-timing-function))`;
after the change it carries `var(--ease-out-soft)` at `.12s`.

This is D4.1's `--font-serif` shape a fourth time — a well-formed utility
silently resolving to somebody else's default — with one difference that
matters and is worth stating: `font-serif`, `text-display` and `lm-head`
resolved to *nothing*, which is what `utilityExistence.test.ts` was built to
see. These classes emit rules. They emit the **wrong** ones, which is invisible
from every direction that gate looks. So the deliverable is a gate that checks
the *value* rather than the name (`tests/unit/motionDefaults.test.ts`), pinned
in both directions and inversion-tested: with the default put back to
Tailwind's curve, four of its assertions fail.

The fix is two lines in the `@theme` block rather than an edit to 27 call
sites, and it is deliberately the defaults rather than a sweep: a plain
`transition-colors` is the idiom the codebase already writes, and the right
repair is to make that idiom correct, not to ask every future call site to
remember an easing.

**Found because I nearly shipped the same defect myself.** The parent shell's
first draft wrote `duration-instant`, on the assumption that `--dur-instant`
generates a utility the way `--ease-out-soft` does. It does not: the easings
live in `@theme` and the durations live in `:root`, so `duration-instant`
emits nothing. Checking that assumption rather than trusting it is what
surfaced the defaults. `motionDefaults.test.ts` pins the named-duration case
too.

### The second finding: every child screen had two back links to the same place

P3.1 added the shell's breadcrumb trail without removing the inline back links
the three child screens already carried, so each of them shipped a crumb row
with a second, redundant affordance stacked directly beneath it — "‹ Your
children" under `Your children › Overview`, "‹ Back" under `… › Overview ›
This subject`. For the reader PRODUCT.md describes as having "no interest in
learning an interface", two controls in a column doing one job is not a
convenience; it is a decision to make. The crumb stays and the three inline
links are gone.

The crumb also stopped saying "This subject". It now names the subject, read
from the react-query entry the screen below has already filled
(`useCachedChildSubject`, `enabled: false` — subscribed to the cache, never
fetching), falling back to the syllabus code from the URL. `getQueryData` was
tried first and is wrong here: it reads without subscribing, so the crumb would
have stayed on its fallback for the life of the screen.

### `parentOutcome.ts` is not `teacherOutcome.ts` with the nouns changed

All four parent screens rendered a raw `error.message`. The obvious fix was to
reuse the teacher module. Reading the endpoints rather than assuming showed why
that would have been wrong: **every `detail` the parent API can produce is
machine text** — `str(exc)` from a stringified Python exception (`parent.py`
122–130), and raw UUIDs in the 403 and 404 (`Child 6f2c… is not linked to this
parent`). `teacherOutcome.ts` is detail-first precisely because several teacher
endpoints write their 4xx `detail` for a human; the parent routes have no such
case. So this module classifies on status and writes every sentence itself, and
a test asserts the negative directly: no branch may echo the server's detail,
and no message may contain a UUID.

It also has **no `mutationFailureMessage`**, because `routers/parent.py` has no
write route. A write-failure helper here would be a function with no caller
asserting "nothing was saved" about saves that cannot happen. Its absence is
recorded so the next surface does not add it back for symmetry.

### Found by looking at the rendered pages (six fixes, one batch)

1. **The same fact, two numbers, stacked.** The "Last worked" stat card printed
   `relativeTime(lastActiveAt)` above `daysSinceLastActivity`, and the capture
   photographed them disagreeing: **"1d ago" directly over "2 days ago"**, from
   one timestamp. Two derivations of the same fact — one in the browser, one on
   the server — round differently across a day boundary, and a parent has no
   way to tell which is the answer. This is the D3.3/D3.4/D3.5 divergence
   again, except visible in a single card rather than across two screens. One
   figure now.
2. **"6 more marks for a A".** A hardcoded article, producing the wrong one for
   exactly the grades a parent most wants to read about. `gradeArticle` spells
   the rule out by letter name rather than by vowel test, because "F" fails a
   vowel test and "U" passes one. Pinned by test.
3. **Good news in the alert register.** The boundary-distance panel — "6 more
   marks for an A", the most encouraging sentence on the screen — was on
   `--accent-wash`, which sits a hair from `--err-wash` on this palette. This
   is surface 5's finding (d) recurring: there, a healthy "Assigned" state was
   accent-toned and read as alarm. It is `info` now, which is §3.6's register
   for a neutral notice.
4. **A tone-coloured percentage with no label**, for the third time in this
   surface family after surface 4's rank column and surface 5's review-queue
   confidence. A bare "36%" pinned to the end of a row on a page headed "what
   to work on" invites being read as a score out of a hundred; it is the share
   of the marks available on a topic that the child has taken, and it says so.
5. **The same chip crowded the row at 375**, taking half the width and wrapping
   both the topic title and its sentence. It drops below the text at mobile.
6. **An empty state that was a bare sentence in a box.** §12 wants marginalia
   plus an explanation plus the action that fills it; the composed version has
   the first two, and deliberately not the third — everything that fills a
   parent's page is done by the child on their own account, and a button for
   this reader to press would be a button that does nothing.

### Also fixed, each already fixed once elsewhere

- **The placeholder brand lockup**, audit finding M9's third and last stamp
  (student sidebar went with surface 1, teacher with surface 5). It was also
  this file's only `font-serif` call site.
- **No texture layer**, the same gap surface 5 found in the teacher portal.
  `paper-grain` on the shell, `margin-rule` on each screen header, one Caveat
  line on the two empty states.
- **Text loaders** on all four screens, replaced with `loading-shapes`.
- **Counts and marks set in the body or display face**, moved to the data face
  (§4): the papers-marked total, every `marks` string, every paper code.

Three surfaces running have now each found a defect already fixed on another.
That is the standing lesson, not a coincidence.

### The container width, recorded rather than quietly kept

The portal stays at 960px, which is none of §13's three container values.
§2 puts parent views in the Operate lane, but Operate's 1200px is measured
beside a 240–280px sidebar — it is a content well, not a page — and this portal
has no sidebar by design (UI spec §4.8, "two taps to the answer"). 960px is
that same well without the sidebar in front of it. Stated in the shell's
module doc so the next reader finds a reason rather than a drift.

### One gate inconsistency, observed and deliberately not changed

`design-tokens.test.ts` does not strip comments, so it reported the two hex
values quoted in a code comment explaining finding 3. Its sibling
`studyNotebookMigration.test.ts` strips comments precisely so a file may name
the thing it stopped using. The comment was reworded rather than the gate
loosened: relaxing a colour gate to let my own prose through is the wrong
direction to resolve that in, and the inconsistency is small. Recorded here
rather than fixed.

### Gates

typecheck / lint / **980 unit (+53)** / check:copy **14** (down from 18, none
in the parent portal) / both builds / 31 Python token+constant tests: green.
e2e: **still blocked, B4**. Visual round: 32 captures across 4 registered
sub-surfaces, all distinct, console errors only from the deliberately-failing
states.

---

## D4.7 — Redesign Phase 4, surface 8 (auth): the first screen anyone sees spent the build era as scaffolding, and a parent was shown an enum member

**Surface:** the two signed-out screens and the refusal between them —
`portals/auth/Login.tsx`, `ParentLogin.tsx`, `DeviceLimitNotice.tsx` (695
lines). Surface 7 (admin views) is deferred behind D1.6, not skipped; see
STEERING.md.

### The headline: the OTP failure a parent reads was an enum member

`ParentLogin.tsx` rendered `err.message` verbatim for a failed code, and
`AuthService.verify_otp` raises
`AuthError(f"OTP verification failed: {result.value}")`
(`lemely/auth/service.py:320`), which the router passes through as the 401
detail. So the sentence on screen was literally

    OTP verification failed: wrong_code

shown to the reader PRODUCT.md describes as the least confident user of the
product, on the screen the UI spec calls "the lowest-friction entry".

**The file's own docstring asserted the opposite**, in as many words: "the
parent reads the actual reason rather than a client-side guess at which it
was." That claim was half right in the way that matters most — the backend's
*distinction* was real and worth keeping, and its *vocabulary* was never fit to
show anyone. A docstring stating an intention is not evidence the code meets
it, and this is the second time this phase that a comment described the fix
rather than the behaviour (surface 2's `MarkDisplay` docstring stated the type
rule it was breaking).

`lib/authOutcome.ts` maps the four `OtpResult` members to four sentences, which
keeps the distinction and fixes the words. An unmapped member falls through to
a written sentence rather than the raw string, so a member added server-side
later cannot become copy — asserted directly by test.

### The same module makes the opposite call one endpoint over, on purpose

The OTP *request* 429 keeps the server's own wording. `OtpRateLimitError` says
"OTP already sent; retry in 12s." (`lemely/auth/otp.py:112`) — a real sentence
with the one number the reader wants, and nothing written in the client could
improve on it.

That is the family's actual rule, stated properly now that five modules exist:
**keep the detail where a human wrote it for a human**, and that has to be
decided per endpoint by reading the endpoint. `teacherOutcome` is detail-first,
`parentOutcome` is never detail-first, and `authOutcome` is both, three lines
apart. Copying any one of them into the next surface would have been wrong.

### And a third rule on the same screen, for a different reason entirely

The password 401 says only "That email and password don't match an account."
It never reveals which half was wrong, and it never echoes a backend detail
that might. Distinguishing "no such account" from "wrong password" hands an
account-enumeration oracle to anyone with a form and a word list, and this
product's users are children. The cost is accepted and stated: someone who
mistyped their email gets a less helpful message than they could have.
`authOutcome.test.ts` asserts the two cases produce the identical string.

### Login.tsx had been scaffolding since the build era, and said so

Its module docstring opened "infrastructure to exercise the auth plumbing, not
final UI. Screen polish is P2.7/P2.8's job." Those chunks came and went; the
note stayed accurate. Three defects follow directly:

1. **The card was invisible.** Page and card were both `bg-surface`, so a panel
   sat on a background of its own colour with a hairline as the only evidence
   it existed. DESIGN.md §3.1's tonal system exists precisely for this.
2. **The error sat at the bottom of the form**, below both fields and above the
   button — the arrangement §12 rules out. The fields are the kit's `Input`
   now (visible label, eight states, field-level errors under their own field),
   and the form-level error sits with the button that produced it.
3. **It rendered `login.error.message` raw**, and `request()` falls back to
   `` `${res.status} ${res.statusText}` `` when a body carries no string
   detail, so a failed sign-in could put **"401 Unauthorized"** on screen.
   Pinned by test.

### M9's fourth stamp

The audit's finding M9 reads "the logo is a lowercase italic *l* in a filled
circle, **stamped in three places**". Surface 1 replaced the student's, surface
5 the teacher's, surface 6 the parent portal's — and it was here too, in
`ParentLogin`, the one signed-out screen the audit reached by grep rather than
by rendering. Four places. It was also this file's only two `font-serif` call
sites (D4.1), so the placeholder was not drawing in the face it reached for.

`AuthFrame` now owns the mark, the paper, the grain and the column for both
signed-out screens, because three copies of a frame is how three screens end up
with three ideas of where the logo goes.

### Smaller, and each one a rule this system already had

- **The OTP boxes were set in Newsreader** (`text-display-md`). A one-time code
  is data (§4: "all scores, grades, marks, XP, timers, paper codes, IDs"), and
  it is on `data-lg` now. Same category error as surface 2's mark and grade.
- **"Will be signed out" was `--t2` muted text** — the quietest register on the
  screen, marking the one row about to be destroyed. It is a `warn` chip, on a
  row with a `warn` border, so the warning has two carriers and neither is
  colour alone (§3.6). The row is deliberately *not* washed: `Chip tone="warn"`
  is itself `warn-wash`, and washing the row would hide the chip in its own
  colour.
- Radius, type scale and tokens across all three files; `paper-grain` on both
  screens, which had no texture layer at all.

### The harness caught its own fixture

The `device-limit` capture photographed the login form where the device notice
should have been: the invented challenge omitted `reason:
"device_limit_reached"`, which `isDeviceLimitChallenge` narrows on, so the 409
fell through to the generic sign-in failure. That is the fixture being wrong
and the product being right — and it is exactly what a batched capture round
over states-that-must-differ is for. Fixture corrected, re-captured, verified.

### Gates

typecheck / lint / **1,013 unit (+33)** / check:copy **14** (flat; none in
auth) / both builds / pre-commit / 31 Python token+constant tests: green.
e2e: **still blocked, B4**. Visual round: 16 captures across 2 registered
sub-surfaces, all distinct, console errors only from the deliberately-failing
states.

---

## D4.8 — Phase 4, surface 9: Marketing / landing

### The headline: the marketing page had no reader

`/student/landing` sat inside `studentRoute`, which `App.tsx` wrapped in
`RequireAuth allowedRoles={["student"]}`. Following that through:

- a signed-out visitor, the *entire audience* of a marketing page, was
  redirected to `/login`;
- a signed-in **teacher** was redirected to `/teacher`, so the page whose own
  eyebrow reads "For CAIE teachers and their students" was unreachable by one
  of the two audiences it names;
- `/` sent every signed-out visitor to `/login` too, so the product had **no
  public page of any kind**;
- and the one reader who could reach it, a signed-in student, is the person
  who least needs selling. They saw it wrapped in the app shell: sidebar,
  breadcrumb trail, streak pill, and a "Correct a paper" header CTA sitting
  directly above a hero that says "Mark a paper".

The part worth recording is that this was **known and half-fixed**. D1.1's note
in `portals/student/data.ts` calls it "the marketing page, orphaned inside the
authenticated app" and removes its *nav entry* — which fixed the symptom a
student saw and left the page with no reader at all. A route removed from the
nav is invisible; a route removed from the nav *and* behind an auth guard for
the wrong role is dead.

Nothing could have caught it. Typecheck passed, lint passed, the route rendered
correctly for the one person who did not need it, and the audit reached it by
grep. A guard placed around the wrong subtree is invisible to every gate this
build runs, which is why the fix ships with `tests/unit/marketing.test.ts`
asserting which top-level routes are public and which are guarded, in both
directions.

**IA change (REDESIGN-MISSION §1 permits, §7 requires documenting):** a new
`portals/marketing/` lane with its own public frame; `/landing` mounted at the
top level with no guard; `/` renders it for a signed-out visitor and still
redirects a signed-in one to their portal; `/student/landing` stays mounted as
a redirect so saved links, D1.1's explicit condition and `navigation.test.ts`
all keep working.

### The second finding: the audit deleted the numbers and left the sentences

DESIGN-AUDIT C1/C2/C3 were closed in Phase 2. **Six fabrications were still
live on this page**, each verified against the backend one at a time rather
than assumed:

1. `cardMeta` read "marked in 41s" — the *exact figure* C1 deleted from the
   proof band for having no source, still standing four sections up the same
   file.
2. The hero footnote read "Free for every student of a partnered teacher - No
   card to start". PRODUCT.md:105 lists partner schools among the things that
   must not be fabricated, and this promised both a partner programme and a
   billing arrangement one screen above the placeholder saying pricing is
   undecided. That is C2's fabrication, in prose.
3. "QR attendance with face or 2FA check" — there is no QR code, no facial
   check and no 2FA anywhere in the repository, and
   `lemely/web/schemas_teacher.py:7` records attendance itself as a screen
   field with **no backend source**.
4. "Lesson retention down to the replayed minute" — same file, same line:
   `retention` is structurally empty by construction.
5. "Results by WhatsApp the moment marking ends" — WhatsApp appeared nowhere
   in the product except this sentence.
6. "Course payments in the same place" — PRODUCT.md:74 puts payment processing
   out of scope outright.

Every bullet now traces to a shipped route and carries that module in a comment
beside it. `tests/unit/marketing.test.ts` pins the ten banned claims literally,
because the failure mode is not a wrong number, it is a plausible sentence
about a feature nobody built.

Two smaller honesty corrections in the same pass: the hero body said Lemely
"pulls the official mark scheme", which B1 established it cannot do (there is
no download path; `resolve_mark_scheme` reads an uploaded sibling PDF or a
parsed cache), and the hero's result card showing 38/40 now carries an
**Example** tag inside the card, because the product has no customers whose
result it could be.

### What the capture round found that reading could not

- **The page had two left edges.** `Section` took a `wide` prop, so the hero
  and proof band sat at 1280 and the loop, pillars and close at 1200, jogging
  40px on alternate sections. §13 gives the Persuade lane one container.
- **Three proof stats in a two-column grid** left the third beside an empty
  cell, a hole in the middle of the one band that has to look considered.
- **`ruled-bg` drew nothing.** The three loop cards are opaque
  `--paper-raised` and cover every pixel of their parent, so the texture
  existed in the class list and nowhere on screen. One step along from the
  shape `utilityExistence.test.ts` catches: the rule *is* emitted, it is simply
  painted over. Removed rather than kept as a claim in the markup.
- **The Parents link was hidden below 640px** — on the phone, for the login
  route whose entire selling point is that a phone number is the whole of it.
- Both hero CTAs pointed at `/login`. The secondary now scrolls to the teacher
  case on the page, which is what its label promises and the only destination
  that honestly exists.

### The capture harness needed two corrections, and made both of them itself

The duplicate detector failed the first round: six "scroll position" states
were six copies of one image, because `fullPage` captures the document without
scrolling. The second round then failed with `full == reduced-motion` — which
was **correct behaviour** the detector cannot express, since a reduced-motion
reader sees the same settled page.

Both are now assertions rather than pictures, which is stronger in each case:

- `/` is verified to render the landing page for a signed-out visitor. An
  image proves nothing about which URL produced it.
- Reduced motion is verified to render the **foot of the page opaque without
  scrolling at all**. `Reveal` starts every section at `opacity: 0`, so the
  failure mode of getting this wrong is not too much movement, it is a blank
  page for the reader least able to tolerate one.

The ordinary capture now scrolls the page before the shutter, because the
first `full` image photographed four blank sections and would have read as
evidence.

### New capability

- **`components/ui/reveal.tsx`** — the scroll-entry motion DESIGN.md §9 and
  REDESIGN-MISSION §4 both specify and **nothing in the product implemented**.
  `lm-screen` is a different thing: it fades a whole route in once on mount, so
  for content below the fold the animation finishes before anyone arrives.
  IntersectionObserver only, transform/opacity only, reduced-motion read in JS
  at mount (a media query that skips the transition while leaving the element
  at `opacity: 0` is exactly how a page ends up permanently invisible), and a
  fallback to visible when the observer is missing — the failure to avoid is
  the blank page, not the unanimated one.
- **`src/routes.tsx`** — the route table, split out of `App.tsx`.
  `createBrowserRouter` touches `document` at import, and `vitest.config.ts`
  runs the node environment on purpose, so routing facts could previously only
  be checked by reading the file as text. That is how the guard defect above
  survived. `App.tsx` is now one line.

### D4.8 (the decision) — does the design gallery ship?

`/student/directions` is an internal A/B/C gallery, reachable by any signed-in
student, showing mock data, with no nav entry. Same shape as the kit preview,
which Phase 2 moved behind its own Vite entry precisely so the product could
never ship it. Sent to the steering channel with a 30-minute timeout and
default **A, move it to `web/dev-previews/`**. Not blocking.

It was migrated in place either way, and while migrating it two things
surfaced: every heading was `font-serif` (D4.1's non-token, so the screen whose
job is to demonstrate typography was demonstrating Georgia), and **direction C
is now ruled out by the design system it is illustrating** — DESIGN.md §3.1
bans a dark panel inside an app screen. Each treatment now renders what became
of it, which is the one thing a gallery has to say and this one never did.

### Gates

typecheck / lint / **1,061 unit (+48)** / check:copy **14** (flat; none in the
marketing lane) / both builds / pre-commit / 31 Python token+constant tests:
green. No horizontal scroll at 320 / 375 / 414 / 768 / 1024 / 1440.
e2e: **still blocked, B4** (port 8000 re-verified occupied this session).
Visual round: 4 captures plus 4 in-harness assertions, all distinct, zero
console errors.

---

## D4.9 — Redesign Phase 4, surface 10 (404 / misc): the surface that was not a tidy-up

**2026-08-14.** Branch `redesign/study-surfaces`. Commits `9619dd6`, `7a70e5a`, and this one.

### What the surface was supposed to be, and what it was

STATE.md scoped surface 10 as `NotFound.tsx` "plus whatever the sweep finds
unmigrated", naming two settings screens. The sweep found **twelve** files
carrying **181 live compat-layer call sites**, and ten of them were product
screens no row of the Phase 4 ledger had ever claimed: the whole of onboarding
(3 files), the whole placement flow (3), `Subject`, `Parents`, `Notifications`,
`Announcements` and `PracticeSet`.

MISSION §1 names "onboarding/placement test" in scope outright and §12 requires
zero pages in the old language, so this was not a judgement call and no DECISION
was raised for it — only more work than the ledger recorded. It was reported to
the human on ntfy at the point it was found, not at the end.

**The consequence is worth more than the count.** The first three screens a new
account ever sees stood between it and every screen that had been redesigned.

### The mechanism, which is the real finding

The three gate lists (`MIGRATED_FILES`, `RTL_CLEAN_FILES`, `SCANNED_FILES`) grow
by hand, one entry per surface as it lands. **A screen no surface claims is
therefore a screen no gate reads.**

`text-body` and `text-title` sat on the notification inbox's own `<h1>` and body
copy, emitting **zero CSS rules** in the shipped bundle for the entire build —
the resolves-to-nothing shape for the fifth and sixth time. Proved by inversion
rather than assumed: putting `text-title` back with `Notifications.tsx` now in
`SCANNED_FILES` makes `utilityExistence.test.ts` fail immediately. So the gate
was never too narrow. The file was never in it.

That is the opposite conclusion from surface 5's, where the gate genuinely
needed widening, and it needs the opposite fix: not a better gate, but a
guarantee that no screen escapes the list. Recorded in STATE.md as binding.

### Findings, each verified against the source of truth rather than reasoned about

1. **A sign-out that did not happen reported nothing.** `DELETE /me/devices/{id}`
   never raises: a device id that does not exist, is already revoked, or belongs
   to another account all answer `200 {removed: false}`, deliberately, so the
   route cannot probe another account (`schemas_devices.py`). React-query ran
   `onSuccess`, the list invalidated, the row came back, and the screen said
   nothing at all. This is surface 3's "deletes that could not fail out loud"
   on the one screen a reader opens *because* they think somebody else is
   signed in to their account.

2. **"Skip for now" deleted the answer it offered to defer.** Rendered only when
   `answered` was true, so a student who left a question blank never saw it and
   a student who filled one in was offered a button whose label promises
   deferral and whose handler set the field to `undefined` before advancing.
   Split into "Clear my answer" (unsets, stays put) and "Skip" (the primary
   action when unanswered, still clearing first because a seeded value can be
   `null` and only an explicit unset keeps it out of the PATCH body, D4.5).

3. **The Subject topic map printed an impossible fraction.** Each tile showed
   `acc` — which `routers/student.py:364` builds as
   `f"{round(area.accuracy * 100.0)}%"` — above a hardcoded "of 24 marks", under
   a heading promising "marks earned / marks available". So "73% / of 24 marks",
   a numerator above its own denominator. `TopicTileDTO` carries no denominator
   at all, so the 24 was not stale, it was invented, and it was the same 24 on
   every tile of every subject. The heading now says what the number is and no
   denominator is rendered.

4. **The weighted-mean delta was green whatever it said.** Built as
   `f"{'+' if delta >= 0 else ''}{delta} since first paper"`, rendered in
   `text-ok` unconditionally, so a student sliding backwards saw their decline
   in the product's success colour. D4.1's "+0 in teal" on a different screen.

5. **A fourth docstring asserting an intention the code did not meet.**
   `Parents.tsx`'s `linkErrorMessage` said non-404s "keep the backend's own
   `detail`", implying one worth keeping. The only `ValueError` the parent-link
   repo raises is `f"Identifier must be a UUID, got {value!r}"`.

6. **Two 404s that were the same screen and should not have been.** An unmatched
   path inside a portal fell to the top-level catch-all, ejecting the reader
   from the app they were inside. Both `routes.tsx` and `NotFound.tsx` carried
   it as a written note from P3.1. A note is not a gate.

7. **A compat rung on the 404 screen itself**, `font-mono text-metadata`, which
   declares `font-family` twice because `text-metadata`'s replacement already
   names the data face (D4.2's shape). Invisible until the file joined
   `MIGRATED_FILES` — it was written in P3.1, before that list existed.

### Two new outcome modules, and why not one

The family reaches **seven** and stops. `settingsOutcome.ts` exists because the
settings lane's reader is *all five roles at once*, which is the first time that
has been true and means it cannot tune its register the way the other six do.
`studentOutcome.ts` exists because `correctionOutcome.ts` is deliberately
detail-first (the marking router writes its 4xx `detail` for a human) and these
routers answer `str(exc)` with raw UUIDs and Python reprs, so widening it would
have been wrong for half the student's screens. Both headers carry the
endpoint-by-endpoint evidence. Neither was written by symmetry.

### Alternatives considered and rejected

- **Reusing one outcome module for both.** Rejected on evidence: see above.
- **Making the exam countdown's urgency conditional on proximity.** Rejected —
  any threshold for "now it is urgent" would be invented. It moved to the
  neutral `info` register and lets the number carry the urgency.
- **Migrating the 17 remaining component-kit files too.** Rejected as scope: they
  are Phase 2's deliverable, they render correct *values* through the aliases so
  nothing is visually wrong, and folding them in would have expanded this
  surface a third time. Recorded in STATE.md as what `index.css`'s compat block
  is waiting on, and as Phase 6 work.
- **Adding a confirmation to every list removal.** Rejected. Only the current
  device gets one, because signing out the browser you are reading on ends the
  session mid-sentence while signing out a phone costs it one sign-in. C-24's
  `consequence` is overridden to say what really happens rather than the
  default's "cannot be undone", which would be false.

### D4.8, defaulted

30-minute timeout elapsed with no reply, so option A: the design-directions
gallery left the product route table for `web/dev-previews/`, behind the kit's
own Vite entry — the call this project had already made once, for the component
kit. **Verified rather than assumed:** its marker string appears nowhere in
`dist/`, and the product precache dropped 129 → 127 entries.
`navigation.test.ts` flips from "keeps it mounted" to "no longer mounts it",
documented in place per §9.7, and `audit.mjs`'s DEV-01 entry is retired with its
reason recorded rather than deleted silently — its own rationale was "it is a
reachable route in the shipped bundle", which stopped being true.

### Gate results

typecheck / lint / **1,166** unit (+105) / **check:copy 0** (down from 14; the
product now has no prose em-dash in any UI copy) / both builds / pre-commit / 31
Python token+constant tests: green. No horizontal scroll at
320/375/414/768/1024/1440. Visual round: 38 captures across 6 registered
sub-surfaces, all distinct, plus 6 in-harness assertions; console errors only
from the deliberately-failing states.

**e2e remains blocked by B4** and is unchanged: port 8000 is still held by
another local user's process, so `scripts/e2e_server.py`'s offline marking seam
is still never installed. Not killed unattended.

### What this leaves

**Phase 4 blocks.** Admin views are the only surface left and D1.6 is still
unanswered and deliberately undefaulted; §10 says a question with no sane
default must not be a timeout question, so this is the point to block rather
than guess. Phase 5 does not depend on it.

### Addendum — B4 resolved the same day, and what the first honest e2e run found

The human freed port 8000 and reported `correct-paper` passing. Verified rather
than accepted: the *whole* suite was run, and it found **four more failures**
that had been invisible for the entire redesign because the suite could never
run correctly (B4: Playwright adopted a stranger's process on 8000 and never
installed `e2e_server.py`'s offline marking seam).

All four are assertion drift against deliberate, documented redesign changes,
not functional regressions. Each is updated in place with its reason recorded,
per §9.7:

- **`student-journey`** asserted `getByRole("button", {name: /0625/})` on the
  dashboard. Surface 1 replaced that `<button onClick={navigate}>` with a real
  `<Link>` — the audit's own M8 finding, raised against the teacher portal and
  sitting unremarked on the student side. The spec now asserts the better
  markup, scoped to the ledger panel (as a link, "0625" is ambiguous with four
  sidebar entries). Its row text and this surface's `EmptyState` split moved
  too.
- **`engagement`** counted five listitems where three board rows exist, because
  a page-wide `getByRole("listitem")` began matching P3.1's `Breadcrumbs`
  trail. Scoped to the list, which the spec's own comment always meant — it
  warned that a global selector "asserts nothing a refactor would not silently
  break", and then was one.
- **`parent-journey`** read the OTP dev code with `div.font-mono`; surface 8
  moved it onto the `data-lg` rung.
- **`phase4-practice`** expected a heading "Practice — …"; §3.2 item 10's
  em-dash ban made it "Practice for …".

**Result: 34 passed, 0 failed.** Hard Gate §9.7 (functional safety) is green for
the first time in this redesign; every earlier surface reported it as blocked,
which was accurate and is now closed. Every surface row in STATE.md has been
updated, because leaving nine rows claiming a blocker that is resolved is the
same class of staleness this phase keeps finding.

**Not done, and still the real bug:** `reuseExistingServer: !process.env.CI`
reuses whatever answers on 8000 without checking it is the process the config
would have started. B4's own proposed guard — a `GET /__e2e__` marker route
asserted in `e2e/global-setup.ts` — remains unimplemented. Today it works only
because nothing else holds the port.

### D1.6, answered

The human answered on the same channel: *"fully build the required screens and
completely wire them"*. That is stronger than option A as it was worded, and the
wording matters — "completely wired" rules out the scaffold-and-shell reading
that option C offered. Phase 4 unblocks; surface 7 is the next work unit, and it
must check what `routers/school.py` actually exposes before designing a screen
around it rather than stubbing a panel and calling it wired.

---

## D4.10 — Redesign Phase 4, surface 7 (admin views): the two roles in one guard were never alike, and the platform console had no backend at all

**Date:** 2026-08-14 · **Phase:** 4, surface 7 (the last one) · **Branch:**
`redesign/study-surfaces`

D1.6 was answered by the human on 2026-08-14: *"fully build the required screens
and completely wire them"*. This records what "completely wired" turned out to
cost, and the two findings that only appeared once the wiring was attempted.

### Headline 1 — `TEACHER_ROLES` bundled two roles that are opposites

`routes.tsx` gated the teacher portal to `["teacher", "school_admin",
"platform_admin"]` for the whole build. The bundle looked harmless because it
was *correct about permissions*: `require_role` really does admit all three on
every `/api/teacher/*` route. It was wrong about data, and in opposite
directions for the two admin roles:

* **`school_admin` genuinely holds that data.** `ClassService.list_classes`
  branches on role and returns every class in the schools they administer;
  `_visible_students`, `review.py` and `announcements.py` scope them the same
  way. The teacher portal works for them, and removing their access would have
  deleted working capability — marking review, class analytics and school-wide
  announcements are not rebuilt on the new surface. They keep `/teacher` and
  gain `/school` as their **home**, with a cross-link in the sidebar.
* **`platform_admin` holds none of it, deliberately.** Every one of those same
  services returns **empty** for the role, stated outright in `class_repo.py`,
  `review.py`, `teacher.py` and `at_risk_repo.py` ("no super-role bypass",
  D1.6/D1.10). So the console a platform admin landed in could only ever have
  been blank — and a permanently blank console is indistinguishable on screen
  from a broken one. They are removed from `TEACHER_ROLES` and live at
  `/platform`.

Nothing could have caught this. A guard that admits a role the API also admits
passes typecheck, lint, the design hook and every existing test; the defect is
that the *data* behind it is empty by design. `tests/unit/adminRoutes.test.ts`
now asserts the removal by name and in both directions, and was **verified by
inversion**: re-adding `platform_admin` to the list fails exactly one test.

### Headline 2 — X-01/X-02/X-03 had no backend whatsoever

`school.py` shipped three endpoints (list seats, invite, revoke). There was no
`/api/admin/*` router at all, and no service that could answer a global
question, because every service in `lemely/db` is tenant-scoped by construction.
"Completely wired" therefore meant building the backend first:

| New | What it is |
|---|---|
| `lemely/db/school_admin_repo.py` | K-01 counts, K-03 staff roster, invite-teacher, remove-teacher-with-reassignment |
| `lemely/db/admin_repo.py` | The first service in the product with **no tenant scope**, reached by its own router rather than by widening an existing one |
| `lemely/web/routers/admin.py` | 5 routes gated to `platform_admin` alone |
| `lemely/web/schemas_admin.py` | X-01/X-02/X-03 DTOs |
| migration `0019_activation_review` | `subscriptions.activation_note` + a `rejected` status value |
| `SeatRow` enrichment | `assigned_display_name`, `classes`, `last_attempt_at` |

**Migration 0019 is the decision worth defending.** X-02 asks for "activate /
reject with a note", and neither existed. The note is a plain nullable column.
The status is the interesting half: `cancelled` was the only existing exit from
`inactive`, and it already means *the subscriber ended this*. Reusing it would
have made "we declined your request" and "they quit" indistinguishable in the
one table an audit would read, so `rejected` was added instead —
transaction-safe on PG12+ because the migration only declares the value and the
first row to carry it is written at runtime.

### What was refused rather than faked

Every one of these is on screen as a sentence, not silently dropped:

- **K-01's subscription status.** `subscriptions` is a **per-user** table. No
  school-level subscription, plan or billing state exists anywhere in the
  schema. The panel is absent and the screen's header records why.
- **K-02's "last active".** No table records a session or a login: `users` has
  no `last_seen` and `devices` records registration, not use. The column is
  headed **"Last marked"** and the field is named `lastAttemptAt`.
- **K-02's "invited / active / inactive" status.** The schema has
  `available`/`assigned`/`revoked`, the route filters revoked out, and there is
  no "invited" state at all because an invite creates the account immediately.
  The column became "On a seat since", which is the real fact underneath — and
  it put `assignedAt` on screen, which nothing had rendered.
- **K-04's create / reassign / archive.** `POST /api/classes` is teacher-only
  (the authz matrix says so), no `archived` column exists at any level, and the
  only delete is destructive and also teacher-only. The screen is read-only and
  a panel at the foot says exactly which of the three exist and where.
- **X-03's marking accuracy.** Produced by the accuracy harness into
  `reports/`, on demand, by nothing a request can reach. The API returns prose
  naming the harness rather than a figure the screen could not date.

### The one departure from a standing instruction

`BUILD/STATE.md` says the failure-copy family is closed at seven: "do not write
an eighth by symmetry." `lib/adminOutcome.ts` is an eighth, and the header
states the evidence. Both detail-first modules (`teacherOutcome`,
`correctionOutcome`) are wrong here because every admin `detail` is machine text
carrying a UUID or a JSON field name; and the status-first modules are wrong
too, because two of these failures carry meaning no status sentence holds — a
409 on removing a teacher and a 409 on deciding an activation both mean *"the
thing you were looking at changed under you"*, and the only useful next action
is to reload. Hence one helper per action rather than one `mutationFailed`.
This is a judgement call and is flagged as one.

### Inspection round

One batched round (1440 + 375 together), 7 findings, all fixed in one batch, one
confirm round, stopped there per §3.2 item 16:

(a) **the accent was carrying the alarm on four panels** — the seat meter at
quota, the spend meter past its threshold, and the boundary-fallback bars — in
the same terracotta the links beside them use, so one colour meant both "this is
wrong" and "this is a link". All four moved to the `warn` register and gained a
labelled chip; (b) the stat-card links wrapped mid-link ("See" / "the roll"),
which is a two-line clickable target and banned outright; (c) two class names in
the seats table ran together into one string; (d) the "Status" column was a
constant on every row; (e) `toLocaleDateString()` rendered `8/11/2026`, which is
11 August or 8 November depending on the reader and says nothing about which;
(f) the invite form pushed the roll below the fold on the screen whose job is
showing the roll; (g) a docstring claimed the school heading was suppressed for
the single-school case, which it never was — **the fifth time this phase a
comment described an intention rather than the code**.

### Gate results

typecheck / lint / **1,255** unit (+89) / check:copy **0** (still) / both builds
/ pre-commit / full Python suite (3,573, rc=0) including **33 new backend tests**
across `test_web_school_admin.py` and `test_web_platform_admin.py`: green.
**e2e: 34 passed, 0 failed** — the admin split changed no e2e assertion, because
`rbac.spec.ts` tests the API's guards and those did not move. Visual round: 78
captures across 7 registered sub-surfaces, all distinct, console errors only from
the deliberately-failing states.

`tests/test_authz_matrix_complete.py` gained 9 rows and did its job on the way:
it failed at collection the moment the admin router mounted, which is the drift
gate working exactly as its docstring promises.

### What this leaves

**Phase 4 is complete.** All ten surfaces are built. Phase 5 (motion and
data-viz) is next and depends on none of this.

Still open, carried forward: B4's own proposed fix (`GET /__e2e__` asserted in
`global-setup.ts`) remains unimplemented, and the compat layer still cannot die
because 17 kit components name build-era aliases in their own source.

---

## D5.1 — Redesign Phase 5.3 (charts): the geometry was in the wrong language, and `var()` is not a colour

**Phase 5.3, "build/theme every chart on the shared Nivo theme".** Nivo installed
(`@nivo/core`/`line`/`bar`/`theming`, 0.99, React 19 supported), one shared theme
at `web/src/lib/nivoTheme.ts`, two wrappers (`LineChart`, `BarChart`), four charts
moved onto them, and a new gate. Six findings, four of them defects that were
live in the product.

### The headline: a token discipline that would have drawn nothing

Every component in this product references colour through a Tailwind class that
resolves to `var(--token)`, and that is correct everywhere except inside a chart.
Nivo hands a series colour to react-spring (`useSpring({ color })` in
`@nivo/line`'s line and area renderers) so it can interpolate across a
transition, and **react-spring parses the string as a colour before it ever
reaches the DOM**. `var(--accent)` is not a parseable colour. One level lower the
same hazard exists without react-spring: CSS custom properties are not
substituted inside SVG presentation attributes, so `stroke="var(--accent)"`
resolves to nothing either.

So the natural, disciplined-looking thing to write would have produced a chart
drawn in nothing — passing typecheck, lint, the token gate (no raw value to
find), and `utilityExistence` (no class name to check). That is `--font-serif`
(D4.1), `text-display` (D4.4), `lm-head` (D4.5) and the banned easing (D4.6)
arriving a **fifth** time, by a route none of those four gates watch. This was
found by reading Nivo's compiled source before building on it, not after.

The theme therefore resolves tokens off `:root` at runtime, so DESIGN.md stays
the single source of values and `nivoTheme.ts` stays a list of names. It **fails
closed**: `ready` is false until real values resolve, and a chart renders a
space-reserving skeleton rather than drawing in a browser default. A chart in
the wrong colours is far harder to notice than a missing one, which is the
asymmetry all five of these findings share.

`tests/unit/chartTheme.test.ts` gates it: every named token exists in
`index.css`, no `var()` or colour literal survives in any chart source, the
series order matches §11, the accent stays out of the categorical set, and no
file under `src/` imports `@nivo/*` outside the two wrappers. **It walks the
tree rather than reading a file list** — P4.10's finding was that the gate lists
only grow by hand, and a gate written this phase should not add a fourth list to
forget. Verified by inversion: renaming a token, reinstating a `var()` string,
and importing Nivo directly in a screen each fail exactly the intended test.

### `MomentumDTO` shipped SVG path data, and the transform clipped

The student dashboard's momentum chart had its geometry computed **in Python**:
`path`, `area`, `lastX`, `lastY` against a hardcoded 300x88 viewbox and a
55-100% band. Two defects came with that, and both are gone rather than fixed,
because the geometry has left the backend.

1. **The band clipped from below.** `y = 88 - ((pct - 55) / 45) * 78` puts
   anything under 55% past the bottom of the viewbox — 40% lands at y=114, 30%
   at y=131 — and the `<svg>` was `overflow-visible`, so the line escaped the
   panel and drew over the labels beneath it. **The students whose momentum
   matters most were the ones whose line left the chart.** Proved arithmetically
   before changing anything, and pinned by
   `test_overview_momentum_percentages_are_never_rescaled`.
2. **`labels` was `recorded_at[:7]`**, a year-month, so five papers in one month
   rendered five identical ticks. This also blocked the migration outright: a
   Nivo point scale keys on its label, and five points sharing one key collapse
   into one. The x-axis is now the paper's ordinal, which is unique by
   construction and matches the panel's own subtitle ("per corrected paper");
   the date moved to the tooltip and the accessible label, which is where a date
   is useful and an axis of five identical months never was.

The wire now carries `points: [{recordedAt, percentage}]`. A **third** copy of
the same transform was found and deleted in `web/scripts/capture_surface.mjs`,
which had to render an SVG path because the DTO shipped one.

### The grade panel's empty state could never fire

`grade_distribution` returns *every* rung of `GRADE_ORDER` with zero counts
included — deliberately, so a frontend never infers "nobody on a B" from a
missing key. Which makes `length === 0` unreachable, so a class with nothing
marked drew a full ladder of empty tracks with a 0 beside each: a blank chart
wearing a chart's clothes, against §11's mandatory empty state. The test is now
"every count is zero". Same shape P4.1 got right on the momentum panel by keying
off `path === ""`.

### Two defects only a rendered capture could find

Both survived typecheck, lint, 1,304 unit tests and the design hook.

- **A count axis asked for four ticks produced "0 0 0 1 1 1".** Nivo divides the
  domain evenly and hands the fractions to `format`, so a class whose largest
  grade bucket held one student got ticks at 0, 0.25, 0.5, 0.75, 1, which
  `Math.round` turned into six labels reading as three duplicated integers. The
  numbers were right, the formatter was right, and the axis was gibberish.
  `BarChart` now uses whole-number ticks whenever every value is whole.
- **The last x-tick clipped, and clipped into a different valid date.** The tick
  is centred on the final point, which sits on the plot's right edge, so half
  the label hung outside a 12px right margin. A cohort trend whose last point
  fell on **11 August rendered an axis reading "Aug 1"** — not a smudge, not an
  ellipsis, a plausible date ten days out, with the table three lines below
  saying "Aug 11, 2026". Margin is now 28px.

### The XP calendar: colour was the only channel the quantity arrived on

The four-week heatmap was carefully built (four *named* bands rather than a
continuous ramp, a distinct empty cell, exact numbers in `title` and
`aria-label`), and the quantity still arrived in exactly one visual channel.
Every reader who degrades that channel had a hover tooltip as their only route
to a number. It is now a bar chart: height is not a colour channel, and the
tooltips and labels carried over unchanged. The window's honest property
survives and is restated in code — a day with no XP and a day the student never
opened Lemely are the same zero-height bar, because they are the same fact.

### §11 exceptions, logged rather than assumed

§11's vocabulary (grid, axis, series, legend, tooltip) describes a plot in a
coordinate space. Four things in this product are not that, and each stayed:

- **The topic-weakness heatmap** (`ClassAnalytics`). Its no-data-vs-0%
  distinction is the single thing on that screen that must not be got wrong, and
  Nivo's heatmap has no notion of it. Trading that guarantee for a nicer
  transition is not a trade worth making.
- **"Weakest threads"** and **"This week, by source"**: labelled meters where
  every row already prints its topic and its value as text. A meter is a visual
  aid to a number that is stated; it is not a plot.
- **`BoundaryBar`**: a positional scale, bespoke by design.
- **`TrendSparkline`** in table rows (`ClassRoster`, parent `ChildOverview`): one
  Nivo canvas per table row is a real performance cost, and a table cell is not
  a chart. It keeps the SVG polyline.

The grade distribution *did* convert, and the difference is the point: it has a
category axis, a count axis and a per-bar tooltip that now states each grade's
share of the cohort. `BarChart` grew a `colorFor` hook so the four `--grade-*`
band colours survive the move — that colour is not a series key, it is the one
colour relationship in this product a teacher actually learns.

### Two screens no capture surface had ever claimed

`ClassAnalytics` and `StudentDetail` carry the cohort trend and the at-risk
trend, and **neither had a capture surface of any kind** — P4.10's finding one
phase later. Both are now registered (`teacher-analytics`, `teacher-student`),
with states that exercise the cases the charts exist for: a class that has
marked nothing, a single-point trend, and a *descending* student trend, since a
capture of a flat line would not test the panel's actual job. Writing the
fixtures found one more: the invented grade ladder had nine rungs and
`GRADE_ORDER` has seven. A fixture that does not match the wire is a fixture
that can be wrong and look like a bug.

---

## D5.2 — Redesign Phase 5.1/5.2/5.4 (motion): the rule stated in units that nothing implemented, and an `!important` that did nothing

Phase 5's three remaining parts. Four findings, three gates, and one scope
decision stated rather than taken quietly.

### 26 elements changed colour in a single frame

DESIGN.md §9.2 is unusually specific: "Press: `scale(0.98)` over `dur-fast`.
Hover: a colour or 1px translate shift over `dur-instant`." Twenty-six elements
across the teacher portal, the admin portal, onboarding and four kit components
changed colour on hover with **no `transition-*` utility at all**, so they
snapped. There is no global `a { transition }` rule, and P4.6's
`--default-transition-duration`/`-timing-function` only reach an element that
already carries a transition utility — they made the *idiom* correct, not its
absence.

This is invisible from every automated direction and it is worth naming why:
every class is real and resolves (`utilityExistence` is happy), every value is a
token (the token gate is happy), the easing is never the banned one because
there is no easing at all (`motionDefaults` is happy), and a screenshot of a
hover state is pixel-identical whether it arrived over 120ms or over 0ms. Only
the frames *between* two states are wrong, and nothing looked at those.

So the deliverable is `tests/unit/hoverTransition.test.ts`, not 26 edits. The
check parses **balanced class-expression groups** rather than lines, because the
naive version reported `Button` as broken: its base holds the transition and its
variants hold the hovers, twelve lines apart, entirely correctly. It also
ignores hovers nothing can animate (`hover:underline`, `hover:cursor-pointer`),
since demanding a transition for those is noise. One exemption, named with its
reason: `nav-shells.tsx`, a build-era shell with no call site, due for Phase 6's
compat closeout.

### The result reveal needed the count-up to do the thing it refuses to do

§9.3 lists "the marked-paper result reveal" in the celebration register, and
`useCountUp` — correctly — refuses to animate a first observation, because there
is no honest origin for one: a student's XP total did not just climb from zero,
that is simply what it has been since before the screen mounted.

But a marked paper is the one place where the value genuinely *did* arrive while
the reader watched. They uploaded a script, waited through the marking, and the
mark went from unknown to 63 in front of them. So `CountUp` gained an explicit
`from`, and the honesty lives entirely in **which call sites may pass it**:

- `PaperResult` reveals on its `live` path (the `location.state` `CorrectPaper`
  sets right after marking) and **not** on the path that fetches a paper by id
  from the history table, which is exactly the "already true since yesterday"
  case the default exists for.
- `PracticeResult` could not tell the two apart at all — it is always fetched by
  `assignmentId` — so `PracticeSet` now navigates with `justSubmitted: true` and
  the screen reveals only on that. A screen that cannot distinguish a result the
  student waited for from one they reopened must not animate either.

**No flourish, at any mark, deliberately.** Confetti would require the product
to decide a mark is good, and it has no honest basis for that: any threshold
makes its *absence* read as disappointment, and §9.3 rules celebration out on a
dropped mark outright. A count-up is legible drama for a number the student has
been waiting for; it is not a verdict on it.

`celebration.test.ts` gates the whole shape: which path reveals, that the reveal
is hero-only, that no unlisted file passes `from`, and — the part that makes the
allowlist honest — that each listed file actually *gates* on evidence rather
than revealing unconditionally. Verified by inversion on all four.

### "A correct answer" has no honest moment in this product

§9.3's fifth celebration is a correct answer, and it is not implemented, because
nowhere does this product tell a student "that one is right" at the moment they
answer. Every assessment path is submit-then-mark: practice sets submit and
navigate, the placement test is a diagnostic, and flashcard review is
**self-graded** (again/hard/good/easy), so celebrating there would be
celebrating the student's own self-report. The celebration attaches to the
result instead, which is what was built. Recorded rather than faked, same
judgement as D4.4's leaderboard climb — which remains impossible, because no
`previousRank` is on the wire and inventing the movement is still refused.

### An `!important` that looked like it covered the case

`index.css` carries a global `prefers-reduced-motion` block that flattens every
CSS animation and transition, including `scroll-behavior: auto !important`. That
rule appears to settle smooth scrolling permanently. It does not: per CSSOM
View, a `behavior` passed **explicitly** to `scrollIntoView` takes precedence
over the CSS property, and `"auto"` is the value that defers to it. The landing
page's secondary CTA passed `"smooth"` literally, so a reader who had asked for
no motion was scrolled across the whole page anyway — with an `!important` rule
sitting directly above it appearing to prevent exactly that.

`motionDefaults.test.ts` now asserts the global block's three declarations and
that no source passes a literal `behavior: "smooth"` without reading
`prefersReducedMotion`. Both verified by inversion.

The rest of the JS motion audit came back clean, and is worth recording so the
next pass does not redo it: `Reveal` reads the query at mount (deliberately —
it must never leave an element at `opacity-0` if the observer never fires),
`useCountUp` and `Flourish` read it per run, `useChartAnimation` reads it *live*
because a chart outlives a scroll entry, and the only other two
`requestAnimationFrame` call sites — `Modal` and `NavDrawer` — defer focus
rather than animate.

### Scroll entries stayed in the Persuade lane, and that is a decision

REDESIGN-MISSION §5.1 says "sweep every surface with the motion spec: scroll
entries with stagger". Taken literally that means fade-up-on-scroll on every
dashboard, and it is **not** what shipped. `Reveal` remains scoped to the
marketing lane.

The reasoning, stated so it can be overruled rather than discovered later:
DESIGN.md §9 opens with "Baseline is **invisible**. The user should feel the
interface is responsive, not watch it perform"; §2's lane model separates
Persuade from Operate; impeccable's Operate mode ranks scanability and task
speed above expression; and the project's named north star, Notion, has
essentially no scroll-entry animation inside the product. Content that fades in
as you scroll delays reading, on a product whose users are revising. Every
surface was considered against the spec; the Operate and Read lanes were
excluded on purpose rather than skipped.

If the intent was literal, this is one prop on a handful of screens and is
cheap to reverse.

### Press feedback, three controls

`Tabs`, `Stepper` and `FileDrop` are real press targets that had no press
state — on a tab, the only thing confirming a tap was the panel changing
underneath. All three now carry §9.2's `scale(0.98)`. `FileDrop` takes it only
when unlocked: a locked target that springs back tells the reader it accepted a
tap it is going to ignore.

---

## D6.1 — Redesign Phase 6.1 (adapt): the gate that could not fail, and a touch floor that was nowhere

Phase 6's first part. §6.1 asks for every page verified at 320/375/414/768 and
desktop, with five hallmark mobile non-negotiables enforced. Two of the five
turned out to be unimplemented product-wide, and one of the two was being hidden
by another that *was* implemented.

### `checkNoHorizontalScroll` has been vacuous since Phase 2

`scripts/audit.mjs` carries a function whose own docstring calls it "MISSION
§11's no horizontal scroll at any breakpoint from 320px up as a real,
non-optional check rather than something only a screenshot review would catch".
It opened with a guard clause:

    const { scrollWidth, clientWidth } = ...documentElement...
    if (scrollWidth <= clientWidth + 1) return null

Phase 2 added `overflow-x: clip` to html and body in `index.css`. That is itself
one of the non-negotiables and it is correct. But clipping suppresses the very
scroll the guard measured, so from that commit `documentElement.scrollWidth`
could never exceed `clientWidth`, the function returned `null` for every route
at every breakpoint, and the DOM walk beneath it — the part that names the
offending elements — became unreachable code.

Measured rather than reasoned about. A 900px div in a 320px viewport:

| | scrollWidth | clientWidth | guard fires | element's own right edge |
|---|---|---|---|---|
| without `overflow-x: clip` | 900 | 320 | yes | x=900 |
| with `overflow-x: clip` | 320 | 320 | **no** | x=900 |

Every "no horizontal scroll at 320/375/1440" claim in the ledger from Phase 3
onward rests on this function. Those claims are not necessarily wrong — the
re-measure below found only two violations — but they were not evidence.

This is D5.2's shape exactly one phase later: a rule that looks like it covers a
case and does not, because a second correct rule changes what the first one can
observe. Two non-negotiables, each right on its own, one silently disabling the
enforcement of the other.

The fix reads element geometry, which clipping does not touch, with an ancestor
exemption so a table or scroller deliberately clipping its own children is not
reported as page overflow. html and body are excluded from that exemption on
purpose: their clip is the mask being seen through. It costs a DOM walk on the
clean case, which is the price of a check that can fail.

Note the failure mode changed too, not just the measurement. With the clip in
place there is no scrollbar to find: content is simply cut off the side of the
page with nothing telling the reader it is there. Silent truncation is worse
than a scrollbar, because a scrollbar is an affordance.

### The 44x44 touch floor was implemented nowhere

`scripts/adapt_audit.mjs` (new) walks all 35 registered capture surfaces at
320/375/414/768/1440 — 745 page-states — and measures the non-negotiables
instead of photographing them. Four of the five are invisible in a picture,
which is why five phases of visual review never surfaced this.

Interactive heights across the product measured 20, 24, 27, 28, 32, 33, 34, 38
and 40px. The kit's **default** button was 34px, so the most common control in
the product missed the floor by ten pixels on every phone, on a product whose
own brief says students live on phones.

The floor is keyed on `(pointer: coarse)`, not on a width breakpoint, because it
is a finger rule. A 375px-wide desktop window is not a finger, and the teacher
and admin portals are deliberately DENSITY 7 (§3.3) for a mouse; widening their
table controls on a narrow desktop window would be a regression dressed as a
fix. The gate emulates the same thing rather than inferring it from width —
verified in both directions before the rule was written: Chromium with
`hasTouch: true` reports `(pointer: coarse)` true and `(pointer: fine)` false.

Two carve-outs, both deliberate and both stated in the CSS:

- **Links inside a sentence** are `display: inline`, and `min-block-size` has no
  effect on a non-replaced inline box, so prose links keep their line height and
  stay exempt. That is the same carve-out WCAG 2.5.5 makes, for the same reason,
  and here it falls out of the cascade rather than needing a selector.
- **Checkbox and radio inputs are excluded, and the exclusion is load-bearing.**
  Both render the real input as `absolute inset-0 h-full w-full` inside an 18px
  painted box (the `appearance-none` technique that keeps the native control in
  the accessibility tree). A 44px floor on the input would not enlarge the box;
  it would leave a 44px invisible hit area hanging 26px below an 18px control,
  overlapping whatever sits under it — in a radio group, the next option. That
  turns a tap on one choice into a tap on another, which is worse than the
  defect being fixed. The floor goes on the label row, which is what a person
  aims at. Found by reading the components before shipping the rule, not by
  measuring afterwards.

### `overflow-wrap` was absent product-wide, and the clip rule hid it

No display rung, and nothing else in `src/`, set `overflow-wrap` anywhere. A
display heading is the largest type on the page and the most likely to hold
something unbreakable — a school name, an email address — and at 320px one long
token is wider than the viewport.

The two non-negotiables interact, which is the point worth carrying forward:
implementing `overflow-x: clip` without `overflow-wrap` does not produce a
scrollbar you can find, it produces a heading with its end cut off and nothing
saying so. Implementing one alone makes the absence of the other invisible.

`anywhere` rather than `break-word`, deliberately: only `anywhere` participates
in min-content sizing, which is what lets a heading inside a grid or flex track
actually shrink. `break-word` breaks the glyphs but leaves the track sized to
the unbroken word, so the overflow it is supposed to prevent survives.

The **data** rungs are deliberately excluded and the gate's selector was
narrowed to match after one run. They carry marks, percentages and XP, where a
break would split "128" across two lines and read as a different number. No
value that short can overflow; if one ever does, the geometric check reports it
as overflow, which is the honest signal. A wrap rule there would make a wrong
number look intentional.

### Three grid templates, and one that nothing used

`grid-subject-ledger` was written correctly in P4.1 with `minmax(0, 1fr)` and a
comment explaining why. The three build-era templates beside it used a bare
`1fr`, whose `auto` minimum is the classic refusal-to-shrink. `grid-subjects-row`
was deleted rather than fixed: zero call sites product-wide, and the comment
claiming un-migrated screens still referenced it stopped being true when Phase 4
migrated the last of them.

### Two real overflows at 320px

- **The parent portal header, in every state.** The brand lockup plus the child
  switcher, Settings and Sign out are wider than the 288px the row has between
  its own padding. Because html and body clip, Sign out was not merely awkward
  there: it was off the side of the screen, unreachable, with nothing on screen
  to say it existed. The row wraps now.
- **`Subject`'s `min-w-80`.** 320px of minimum column plus the screen's own
  horizontal padding is wider than a 320px screen, by construction. The intent
  was "keep this column beside the cards until there is no longer room for
  both", which is what a flex *basis* says; a min-width also forbids the column
  from ever being narrower, which is not what was meant.

### Two-line clickable text, and where the rule has to yield

§6 bans a clickable label breaking across lines — P4.7's "See" / "the roll" is
the canonical case, where the second line reads as a separate control. Fixed:
the admin sidebar's two footer links (each one long sentence in a 219px column,
so they broke at every width from 320 to 768), "See all" on the parent overview,
and the "Target grade" sort header.

The remaining cases are a different thing and are exempted explicitly rather
than quietly: a link whose text is a class name, a quiz title or a syllabus
topic is **content the school typed**, and the only ways to keep it on one line
are to truncate it or let it overflow. Both cost the reader information the
product does not own and cannot shorten. Those opt out with a
`data-wraps-content-title` attribute, so the exemption is visible in the source
of the screen taking it rather than buried in a list nobody reading the JSX
would find.

### One list, not two

`adapt_audit.mjs` imports `SURFACES` from `capture_surface.mjs` rather than
restating it, and `capture_surface.mjs` became importable to allow that. P4.10's
finding was that a hand-maintained gate list is a list some screen is missing
from; a second copy of a 35-entry registry is that finding waiting to happen.

### Gate

`tests/unit/adaptRules.test.ts`, 9 tests, **verified by inversion**: reinstating
the `scrollWidth` guard, reverting a grid track to a bare `1fr`, dropping one
display rung from the wrap rule, and re-keying the touch floor to a width
breakpoint each fail exactly the intended test (the last fails two, correctly).

The last test is the one that matters. The vacuous-gate defect cannot be caught
by asking whether a check exists — it did exist and it ran. It can only be
caught by pinning the *shape* that made it vacuous, so the gate asserts that
neither audit script compares `scrollWidth` to `clientWidth`, and that both
still call `getBoundingClientRect`. The cheap guard looks entirely reasonable,
which is how it survived four phases.

### Correction, found while verifying this record rather than trusting it

**The pin above did not do what this section says it did, and the inversion that
"verified" it was the reason.** Its first draft matched
`/scrollWidth\s*<=?\s*clientWidth/` — the *destructured* spelling the original
guard happened to use, because the original read
`const { scrollWidth, clientWidth } = ...`. It was then inverted against that
same spelling, which is the one shape it could see. Measured, not argued:

| Reinstated guard | Pin fires |
|---|---|
| `if (scrollWidth <= clientWidth + 1) return null` | yes |
| `if (el.scrollWidth > el.clientWidth) return null` | **no** |
| `if (doc.clientWidth >= doc.scrollWidth) return null` | **no** |
| `if (document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1) return null` | **no** |

Three of the four are the identical defect, one property access or one flipped
operator away, and the fourth is the *literal original line* with its receiver
written out instead of destructured. So the gate caught a verbatim revert and
nothing else, while its own docstring claimed it caught "ANY check gated on the
difference between them".

This is D6.1's own finding one level up. The section above is about a rule that
looks like it covers a case and does not; the check written to stop that
recurring had the same property, and an inversion pass agreed with it because
inverting against the one spelling you already have in mind cannot discover the
spellings you do not. **An inversion proves a gate fires on the case you
inverted. It is not evidence about the case class.** That is the reusable part,
and it applies to every "verified by inversion" claim in this file.

The pin now matches either identifier order, any comparison operator, and any
receiver, within a single statement, and is inverted against all four rows of
the table above — each fails exactly one test, and the clean tree passes 9/9.

---

## D6.2 — Redesign Phase 6.1, second pass: the gate was aiming at the wrong element

D6.1 recorded the `adapt` work as though it were finished. It was not: the
record was written, the gate was never run to green, and `STATE.md` still had
Phase 6 as PENDING. Running it produced **198 findings** (156 `smallTarget`,
42 `tightPair`).

Three of the four defects below are in the gate itself, not the product. That is
worth stating plainly, because D6.1's whole subject is a check that could not
fail, and the check written to replace it shipped with three ways of being
wrong about its own subject.

### It reported the product's largest tap target as its smallest, 40 times

`FileDrop` binds **two** labels to one input: a 13px caption ("Scanned paper")
and the drop zone, which is the thing a finger lands on. `aimedAt` resolved the
label with `querySelector`, which returns document order, so it picked the
caption every time.

Forty of the 156 findings were the paper-upload control on the flow the whole
product exists for, reported at 83x13 while the real target beside it was
several hundred pixels wide. Choosing by area rather than by document order is
what makes the answer independent of markup order:

| | picked | measured |
|---|---|---|
| `querySelector` (before) | caption | 83x13 — fails |
| largest bound label (after) | drop zone | passes |

`correct-paper` went from 40 findings to 0 with no product change at all, which
is the tell: nothing was wrong on that screen.

### It reported a box as "44" and failed it for being under 44

The comparison ran on the raw float and the finding printed `Math.round`. A link
hand-padded to 43.7px was reported as `44`, i.e. as a finding that appears to
contradict its own rule. Findings now print tenths. That single change is what
made the next defect visible.

### It gave a different answer on identical runs

Three consecutive runs of `teacher-analytics` returned one finding, then two,
then a different element — always in a transient `loading` state, always at
43.95-44.0 on an element whose CSS floor is exactly `min-block-size: 44px`.
Chromium lays out in 1/64px LayoutUnits, so a 44px box measures fractionally
under depending on the offset it lands on.

A gate whose result changes between identical runs is worse than the vacuous one
it replaced: that one was at least consistently wrong, whereas this teaches
people to re-run until it passes. Fixed with 0.5px of tolerance, pinned so it
cannot be widened, and applied to the spacing rule as well — a control that
clears the size rule must not still count as `tiny` for spacing.

The genuine 43.7px miss is still caught, with 0.3px to spare. Every other real
finding was 20px or shorter.

### A waiver that covered one rule and not the other

The last 30 findings were all one control: the six-box OTP row, which carries
`data-touch-floor-exempt` with a stated reason. The gate honoured that waiver
for the size rule and then failed the same six inputs on **spacing**, 30 times.

The two are the same arithmetic. Six 44px boxes plus five gaps need 284px and
the card offers ~248px at 320px; that is why the boxes are under-width, and it
is equally why they sit 4px apart. No edit could have cleared those 30 findings
without undoing the reason the exemption exists.

Now honoured on both rules, but only when **both** sides share the same waiver:
one exempt control crowding an ordinary one is still a real mis-tap risk, and
the reason written on the OTP row is about the digit boxes among themselves,
where a mis-tap lands on an adjacent digit and is visible and recoverable. It is
reported as `exemptPair`, never dropped, on the same principle as
`exemptTarget`.

### The product defects underneath

Once the gate was measuring the right things, what was left was real:

- **`py-[11px]` is not a 44px floor.** 21.7px of line plus 22px of padding is
  43.7px. Two call sites (the review queue's student link, the study-plan topic
  link) had been tuned by hand to a number that depends on the rung's
  line-height, so it was right for neither. Both now state `min-h-11` and centre
  their content. `truncate` moved to an inner span at the same time: on a flex
  container the text is an anonymous flex item and `text-overflow` has nothing
  to apply to, so the ellipsis would have silently stopped working.
- **The bulk-approve checkboxes were 18px wide.** `Checkbox` in a table cell
  carries an `aria-label` and no visible text, so the label row the floor sits
  on collapses to the width of the painted box — a target twice as tall as it is
  wide, in the one place a teacher taps repeatedly. The inline axis is now
  floored on the label row too, which is a no-op on every labelled checkbox in
  the product.
- **The only way out of a class on a phone was 19.5px tall** (`← All classes`).
- Inline-axis misses on three standalone controls that had been given the block
  axis and not the inline one: breadcrumb crumbs (34px), the landing sign-in
  links (41px), the parent overview's "See all" (38px). Centred where they sit
  mid-row, end-aligned where the row ends, so the extra width does not shift the
  label off the edge its heading aligns to.

### What this pass did not change

The three impeccable design-hook findings on `index.css` are left as they are,
and deliberately: `--ease-spring` / `--ease-celebrate` overshoot **on purpose**
(§4's celebration register, and `celebration.ts` says so at the token), and
`ruled-bg` / `dotted-bg` are §4's notebook texture, which §1 names as the one
protected quality of this entire redesign. §3 says this mission's text wins over
a skill's when they conflict, and here they conflict. Not suppressed either: a
waiver needs the human, and this ran unattended.

### Gate

`adaptRules.test.ts` is 14 tests, up from 9. The three new pins are verified by
inversion **against the spelling that would actually be reached for**, per
D6.1's own correction: reverting to `querySelector`, widening the tolerance to
2px, and relaxing the pair waiver to "either side is exempt" each fail exactly
one intended test.

The reusable part is narrower than "run your gates". It is that a gate reporting
zero and a gate reporting nonsense are both consistent with a green ledger row,
and the only thing separating them is looking at what it named.

---

## D6.3 — Redesign Phase 6.2 (harden): the run was never lost, only the thing reporting it

Phase 6.2 is `harden`, and REDESIGN-MISSION §6.2 names one flow outright: the
paper upload and marking wait, "that flow has real latency; design the waiting
experience, progress feedback, and failure recovery properly". Two findings came
out of it. Neither was a styling job, and neither was where the audit said to
look.

### Audit M4: `UploadStatus.processing` had never been written by anything

`CorrectPaper.tsx`'s own docstring has carried M4 since P4.2 — "the marking run
lives in component state, so a refresh mid-run loses it" — deferred to this
phase with a note that the honest fix was architectural, as it had been for the
teacher console (D6.13, build era: marking became a server-side job the console
polls).

**The premise was wrong, and that is the finding.** A refresh never lost the
marking. `POST /student/correct` does its work on a background thread that does
not stop when the client disconnects, and it persists the attempt, marks the
upload complete, awards the XP and sends the notification regardless of whether
anyone is still reading the stream. A student who reloaded had a paper that
*would be marked*, and no way to find out.

What was missing was much smaller and much worse: **nothing recorded that a run
was in flight.** `UploadStatus.processing` shipped in the very first migration
and **no code path in the product had ever written it.** An upload went
`pending` at creation and jumped straight to `complete`/`failed` at the end of
the run, so for the entire duration of the marking — the minutes this whole
feature is about — the database said `pending`, which is also exactly what it
says about a scan somebody uploaded and abandoned.

Two things followed from that, and only one of them was known:

- **The reload could not recover** (M4), because there was no state to recover
  *from*. This is why the fix looked architectural: with the status unwritten,
  the only remaining evidence of a run really was in the browser tab.
- **The platform console's "Uploads in flight" was `pending + processing`**,
  i.e. entirely `pending`, i.e. every scan any student had ever uploaded and
  not marked. Nothing clears it. The figure could only grow, and the one
  question that panel exists to answer is "is anything stuck?". It is
  `processing` alone now, which returns to zero when marking stops — which is
  what makes a non-zero reading mean anything — and `pending` is reported
  beside it as what it is, "uploaded and never marked".

Recovery is then a read, not an architecture: `GET /student/uploads/active` and
`GET /student/uploads/{paperId}`. Two endpoints rather than one, because they
end differently — `active` stops naming a paper the instant it reaches a
terminal status, so a client polling only that would watch its run vanish and
never learn whether it was marked or failed. Discovery finds it; polling
follows it.

Three things the recovered screen deliberately does not do:

1. **It does not redraw the stage panel.** The SSE frames go to a
   process-global bus with no replay, so a recovered reader knows the run is
   going and nothing else. Ticking the three stages off from a status word
   would be the invented progress S-14 rules out by name. It renders prose.
2. **It does not re-POST `/correct`.** That would start a *second* marking run
   over the same scan: double spend against a hard-capped Gemini budget, a
   second attempt row, and — because the bus is global and single-stream —
   cross-talk between the two readers. It polls, and the start control is
   disabled for the duration.
3. **It does not animate the result.** A recovered run that finishes navigates
   without the `live` state, so `PaperResult` does not play §9.3's reveal. The
   reveal is for a figure that arrived while this reader watched it; a paper
   marked before the reload is not that.

`stale` is the fourth piece and is computed server-side, because the server owns
the clock the timestamp came from. A row can only stay `processing` if the
process holding it died, and nothing will ever come back to finish it, so past
`MARKING_RUN_STALE_AFTER` (20 minutes, far beyond a real run) the screen stops
saying "still marking" and starts offering to start again. `startedAt` is the
row's `updated_at`, which needs no migration and is exactly "when the status
last changed" — meaningful while processing and offered for nothing else.

One capability fell out of it that could not have worked before: **after a
reload there is no `File` object, and the scan is still on the server**, so
`canRetryInPlace` is the real test of whether marking can start. Requiring the
local file is what made a stopped run a dead end.

### The failure-copy family was never closed, and this is the sixth time

The same sweep found **fifteen live sites rendering an `Error`'s own `message`
to a reader** — after five previous phases each reported the family closed
(P4.2 the marking stream, P4.4 friends, P4.5 the teacher portal's 44 sites,
P4.6 the parent portal, P4.7 auth).

The mechanism is worth more than the count. **The outcome modules were written
surface by surface, and a screen redesigned before its module existed was never
revisited.** `studentOutcome.ts` arrived on surface 10. `Overview` and
`PaperResult` are surfaces **1 and 2** — the student's two most-read screens —
and both still answered a dropped connection with the browser's "Failed to
fetch". Nothing connected those two facts because nothing was looking.

Also found: every student `ErrorState` on the flashcard, practice and study-plan
screens (8 sites), both quiz-taker paths, the teacher grading console's stage
failure, and two in `CameraCapture` where the leaked text was **pdf-lib's** —
so a student who photographed a paper page by page and pressed done could be
told "Input image is not a JPEG", about a file they never chose, at the end of
the longest piece of work the product asks of them.

`studentActionFailureMessage` is new and is a third helper rather than a call
site of the second, for a stated reason: `STUDENT_SAVE_REJECTED` leads with
"Nothing you typed has been lost", which is the right reassurance for a form and
a confusing one after a button press where nothing was typed. It also keeps the
action in the sentence, because two different actions can fail on one screen and
a reader told only that something went wrong has to guess which.

### Gates

`tests/unit/failureCopy.test.ts` is the deliverable, not the fifteen edits. It
**walks `src/` rather than reading a file list** — P4.10's finding was that a
hand-maintained list is a list some screen is missing from, and that is precisely
the mechanism that let this survive five fixes. A new screen is covered the day
it is written.

Its own first draft was wrong in the instructive direction: it matched any
`.message` reaching a render and reported `setQuietError(result.message)` in the
notification settings, where `result` is this codebase's own quiet-hours
validator and its message is a sentence written for that exact reader. **A gate
that reports good copy teaches people to route good copy through an outcome
module to make a test go quiet**, which is worse than the defect. It now
requires an error-shaped receiver, and it found a sixteenth site the manual grep
had missed on the way. One rename fell out of it — `toggleError` held
already-converted copy, so it is `toggleFailure` now, which is both what it is
and unambiguous to the check.

`tests/unit/uploadRun.test.ts` pins the recovery decision as *logic*, not as
source text: `runPhase`/`canStartRun` live in `lib/uploadRun.ts` precisely so
the web runner (`environment: "node"`, no jsdom) can test them, because a
source-reading gate cannot tell a rule that works from a rule that still has the
right words in it. The two rules that are not expressible as a function — never
re-run a recovered paper, never redraw progress it cannot know — are read off
the source and **stated as the weaker evidence they are**; the behavioural proof
is in the Python suite, against a real database and a real run.

Six new backend tests, and both halves verified by inversion: removing the
`processing` write fails exactly the two tests about it, and widening
`get_active_run` to include `pending` fails exactly the one about that. Three
inversions on the web side each fail exactly one intended test.

### What this did not change

The event bus is still process-global and single-stream, and `sse.py` still says
so in a warning. Recovery is designed around that constraint rather than
fixing it — polling instead of re-attaching is what makes a second reader safe
today. Fixing the bus is a backend change with no design content, and it is not
what §6.2 asked for.

### The long-content pass, and the row that lost its own button

§6.2 also asks for a long-content pass, and the adapt gate does not give one:
its `badWrap` rule checks that display headers *carry* `overflow-wrap`, which is
a statement about CSS, not about what a long string does to a layout. Nothing in
the capture corpus had ever rendered one — every fixture name is "Amina Farouk".

The state added here is aimed rather than general: the teacher review queue's
student cell, because P6.1 had just moved its `truncate` onto an inner span (on
a flex container the text is an anonymous flex item and `text-overflow` has
nothing to apply to). A long name is the only thing that can show whether that
landed.

What it showed was worse than a missing ellipsis. The table is `w-full` with the
default `table-layout: auto`, so a long name **grows its own column**: at 1440,
one student's name widened the student cell by roughly 170px and pushed the
per-row **"Review →" button off the right edge of the card**. The action every
row exists for became unreachable without horizontal scrolling, on a desktop
screen with room to spare, because of one name.

Neither existing gate can see it. The adapt gate's overflow rule exempts an
element whose ancestor establishes its own clipping or scrolling context — which
is correct, and is exactly what the `overflow-x-auto` table wrapper is — so a
row scrolling inside a deliberately scrollable region is not page overflow and
should not be reported. The defect is not that something overflowed; it is that
*the primary action left the screen*, which is a layout judgement no geometric
check makes.

Fixed with a character measure on the cell (`max-w-[20ch]`, a count of glyphs
rather than a spacing value, same exemption as `CorrectPaper`'s `max-w-[60ch]`).
The first attempt used 30ch and **did not bind** — the name truncated and the
table still grew past the card, which is worth recording because the capture is
the only reason that was visible. 20ch is about the column's own natural width,
so ordinary names never reach it.

### A file in neither gate list, again

`src/components/CameraCapture.tsx` was in neither `rtlSafety.test.ts` nor
`utilityExistence.test.ts`. This is surface 10's mechanism for the third time —
"a screen no surface claims is a screen no gate reads" — and here it is not a
screen but the camera half of the flow the whole product exists for.

Adding it found a defect on the first run: `left-1` on the page-number badge,
against §3.4's RTL rule, so in a right-to-left layout the page number would sit
at the far corner from where the eye starts. One line, and it had been sitting
in an unread file since the build era.

The pattern is now three-for-three: every time a file has been added to these
lists, it has failed something. That is an argument for the lists being the
wrong shape, and `failureCopy.test.ts` and `chartTheme.test.ts` both walk the
tree instead. Converting the other two is not a Phase 6.2 job, but it is the
right Phase 7 note.

---

## D6.4 — Redesign Phase 6.3 (optimize): the report was stale, the render-blocker was 403 bytes, and the lazy image could not be made lazy

Phase 6.3 is `optimize`, and REDESIGN-MISSION §5 lists six things:
transform/opacity-only animation, no blur on scrolling content, the z-index
scale respected, lazy images (WebP/AVIF), skeletons that reserve space
(CLS < 0.1), and a font-display strategy. Two of the six were already true, one
was true for a reason nobody had written down, and the three that were not led
somewhere other than where they pointed.

### 0. The correction that has to come first: I built on a stale report

There was a Lighthouse corpus at `reports/phase-6/`, and it said this:

    teacher-quiz-detail   CLS 0.2427   cause: "Web font loaded"
    teacher-schemes       CLS 0.1807   cause: "Web font loaded" (x2)

That is two routes at 2.4x and 1.8x §6.3's stated CLS ceiling, with a single
named cause. I noted its date (2026-08-12, before Phase 5's charts and all of
Phase 6), said out loud that it was a hypothesis and not evidence, and then
**wrote the font-preload plugin before measuring.**

Running the audit against HEAD says something different:

    41 routes, 0 over CLS 0.1.
    Worst: student-overview 0.0982. Second: student-announcements 0.0242.
    teacher-quiz-detail: 0.0000. teacher-schemes: 0.0000.

The stale corpus names `instrument-serif-latin-400-normal-*.woff2`. Phase 2
replaced that face with Newsreader and **the font that caused the 0.2427 has not
been in the bundle since**. The crisis was three phases dead.

Two things follow, and the second matters more than the first.

**The work still stands, for a smaller and better-stated reason.** The one
remaining CLS failure is on the student dashboard, the product's most-visited
screen, and every shift Lighthouse attributes on that page has the same cause —
"Web font loaded", naming Newsreader, Caveat and JetBrains Mono landing together
on the Momentum panel. 0.098 on surface 1 is worth removing. It is not what I
started out believing I was removing, and the record says so.

**Build-era D6.9 warns that this number is not reproducible**, and it applies to
my own measurement, not just to the stale one: "the shifts only count when the
skeleton paints before the data arrives, so a fast run hides them entirely."
A single run cannot distinguish *fixed* from *fast*. So the honest defence of
the preload is not the after-number — it is that a preload **removes the race
rather than winning it**. The face is discovered in the HTML instead of three
steps into the CSS, so there is no window in which the fallback is painted and
then replaced. That argument does not depend on which run you look at.

### 1. The largest render-blocker in the product was 403 bytes and nobody's code

`render-blocking-insight` failed on **41 of 41 routes**. It names two resources.
The first is the stylesheet, which has to block. The second:

    http://127.0.0.1:4173/registerSW.js    403 bytes    301ms

`vite-plugin-pwa`'s default `injectRegister: "auto"` emits
`<script id="vite-plugin-pwa:register-sw" src="/registerSW.js"></script>` as the
last thing in `<head>` — no `defer`, no `async`, not a module. So it is
parser-blocking, and the parser has not reached `<body>` when it stops. 403
bytes whose entire job is to register a service worker that has nothing to do
until well after first paint, delaying first paint on every route in the
product, for the whole redesign.

`injectRegister: "script-defer"`. One line, all 41 routes, and nothing about
when the worker becomes useful changes.

This one is worth naming as a shape rather than a bug: **it was in nobody's
diff.** Every gate this build runs reads code the project wrote. This was
generated at build time by a dependency's default, and the only thing that could
ever have seen it was a measurement of the built artifact.

### 2. "Lazy images" could not be done by making the image lazy

§6.3 asks for lazy images. The product has one content image worth the name —
the teacher grading console's per-paper scan thumbnail — and `loading="lazy"` on
it would have done **nothing**, because the bytes are not fetched by the image
element. `useScanPreview` calls `fetchBlobUrl("/papers/{id}/preview")` and hands
the resulting `blob:` object URL to `<img src>`. By the time the element exists
the download has happened; a `blob:` URL is local and there is no request left
to defer.

That matters more than an ordinary lazy-loading miss, because the endpoint is
not a static file. `GET /papers/{id}/preview` opens the stored scan with PyMuPDF
and **renders page 1 to a PNG on demand**, and `GET /papers` is unpaginated
(`"""Return every tracked paper as grid cards"""`), and every card mounts its
own hook. Opening the console re-rendered every scan the school has ever
uploaded, server-side, at once, to fill a 64px strip most readers never scroll
to.

The cost was known and answered in the wrong place. The endpoint's own comment
reads: "every step up costs a bigger payload on every card in the grid at once
(96 dpi produced a 320KB PNG per paper)" — so the fix applied was to shrink the
image rather than to stop asking for it.

`useInViewOnce` + `useScanPreview(paper.id, nearViewport)`. The deferral is on
the fetch, which is where the request actually is. It fires a screen-height
early, because a lazy fetch whose point is that the image is *there* when the
reader arrives must not trade an over-eager grid for a visibly empty one — an
empty thumbnail on this card is also what a scan that failed to render looks
like. It fails **open** (no `IntersectionObserver` → fetch immediately),
restoring exactly the old behaviour rather than a grid of permanent blanks.

`Reveal` was deliberately not folded into the new hook. It runs the same
mechanism with a different policy — it fires when an element is genuinely on
screen and slightly past it, and it is short-circuited by
`prefers-reduced-motion`, which is load-bearing there and meaningless here (a
reader who wants less motion still wants their thumbnails). Merging them would
mean one call site silently inheriting the other's timing.

### 3. The z-index scale was a gate that had never existed

`index.css` has carried this comment directly above the scale since Phase 2:

    /* A raw z-index outside this scale is a gate failure. */

No gate read it. Four raw values had accumulated, and the scale was being spelled
two ways at once (`z-nav` in three files, `z-[var(--z-index-sticky)]` in ten).

Three of the four were in kit components no screen renders. **One was live**:
`ConfidenceIndicator`'s per-question tooltip declared `z-10`, which is
`--z-index-sticky`'s value — a floating layer sitting in the band this product
reserves for sticky table headers and portal top bars, i.e. the two things most
likely to be over it. Every other floating layer in the kit (`popover.tsx`) was
already in the dropdown band. It is live on `PaperResult` and `PracticeResult`
via `QuestionRow`, which is the screen a student reads their marks on.

Nothing could have caught it. `z-10` is a real Tailwind utility emitting a real
rule, so `utilityExistence.test.ts` sees a class that resolves and the token gate
sees no raw colour. It resolves to the **wrong** thing rather than to nothing,
which is D4.6's shape and not D4.1's.

All ten `z-[var(--z-index-*)]` were converted to the named utilities as well, so
the rule the gate enforces is one vocabulary rather than two spellings, and
`z-dropdown`/`z-nav`/`z-sticky`/`z-modal` were each verified to emit real rules
in the shipped bundle (`.z-dropdown{z-index:30}`) rather than assumed to.

### 4. The blur exception had one permitted value and the product used two

§3.2 item 6 bans glassmorphism with one carve-out: a subtle `backdrop-blur` on
the navbar, never on scrolling content. Four top bars use it. Three app shells
declared `backdrop-blur-[10px]`; the marketing header declared
`backdrop-blur-sm`, which is 8px in Tailwind v4. Both are arbitrary values
outside the token block, for a rule that permits exactly one thing.

Also: the marketing header sat at `z-sticky` while the three app shells sat at
`z-nav` — four bars doing one job in two bands, with the odd one out in the band
`table.tsx` reserves for sticky table *headers*.

`--blur-nav: 10px`, so `backdrop-blur-nav` is greppable and anything else is not;
marketing moved to `z-nav`. The comment above it claimed to be "the one permitted
`backdrop-blur` in the whole product" when there are four. Corrected in place.

### 5. `unicode-range` made nine font subsets free, and the service worker paid for them anyway

Every `@font-face` @fontsource emits carries a `unicode-range`, so a browser
rendering English never requests the Cyrillic, Greek or Vietnamese subsets. They
cost nothing **precisely because they are never fetched**.

The precache glob named all nine by filename. A service worker install does not
consult `unicode-range`; it fetches what the manifest lists. So every student's
first visit downloaded **187KB of glyphs no English page in this product can
display**, most of them on a phone on mobile data.

`globIgnores` on the non-latin subsets: precache 146 → 137 entries,
2621 → 2435 KiB, a 186 KiB drop that matches the measured figure.

The trade is stated rather than hidden. Online nothing changes — the browser
still fetches one of these the moment a glyph needs it, e.g. a student whose name
is not in latin. Offline, such a name renders in the fallback face. Precache is
the app *shell*, and a subset reachable only through particular user data is not
shell.

One thing I got wrong on the way and corrected by looking: the three PWA icons
appear **twice** in the precache manifest, which I first read as 267KB of
duplicated download. They carry identical revisions, so Workbox collapses them.
137 entries, 134 unique. Not a defect, and the 534KB I had written down was my
double-count and not the browser's.

### 6. The two items that were already true, and why one of them was luck

**Transform/opacity-only (§9.2) is clean.** Every `@keyframes` in `index.css`
animates `opacity` and `transform` and nothing else, verified by extracting the
animated property names rather than by reading the rules. The one
`transition-[width]` in the tree is a comment recording its own removal.
`progress-bar.tsx` reaches the same answer twice over, scaling a full-width layer
rather than resizing it and translating a segment rather than sweeping a
background.

**No blur on scrolling content** was true, but only because all four call sites
happened to be on `sticky` elements. Nothing checked it. The gate now does,
structurally: a `backdrop-blur-` and a `sticky`/`fixed` must appear in the same
class expression.

### 7. The new gate's first run flagged the best comment in the file

`elevationScale.test.ts` walks `src/` rather than reading a file list — P4.10's
finding, and three of the four z-index offenders were in kit components no
surface-derived list would ever have contained.

Its first draft reported six offenders. **All six were prose.** Five were the
comments this phase had just written explaining the fix ("`z-dropdown`, not the
raw `z-10` this carried"). The sixth was `celebration.tsx` explaining that it
deliberately uses DOM order instead of a `z-*` utility, "because a raw `z-1`
outside the scale is exactly what that gate exists to catch."

So the gate's first act was to flag the one component that had reasoned its way
to the right answer, and the cheapest way to make it green would have been to
delete the reasoning. That is D6.3's finding — a gate that reports good work
teaches people to launder it — arriving one phase later inside the gate written
to honour it. Restricting matches to quoted spans is not enough on its own,
because these files quote class names inside comments with backticks, which is
indistinguishable from a template literal to anything not tracking comment
state. Hence a small real lexer.

The allowlist is **derived from `index.css` every run** rather than written into
the test, so a renamed token cannot leave the gate checking names the product no
longer has. Verified by inversion, four ways: reinstating `z-10`, reverting to
`backdrop-blur-sm`, moving a blur onto a non-sticky element, and renaming a scale
token each fail exactly the intended test.

### 8. What this phase found and did not fix

- **The standing `ui-thresholds` gate is red on HEAD, and has been unrun since
  Phase 5.** 13 violations: 7 serious axe + 6 Lighthouse. Five are student-route
  performance below the §11 floor of 80 (`student-profile` 57,
  `student-standings` 70, `student-overview` 74,
  `student-study-plan-session` 76, `student-correct` 77) and one is
  `teacher-student-detail` accessibility 94 < 95. Note `student-standings`:
  build-era D6.9 fixed exactly that route to 93, so it has either regressed or
  the run was slow, and one run cannot say which.
- **The 7 axe serious violations are root-caused for 6.4, not fixed here.**
  42 of them are one mechanism: Nivo emits `aria-label` + `tabindex` +
  `focusable` on a bare `<rect>` with no `role`, which is prohibited ARIA, on
  `student-profile` (28), `teacher-class-analytics` (11) and
  `teacher-student-detail` (3). The rest are `color-contrast`:
  `text-ink-faint` (#686c6f) measures **4.48:1 on the pastel `#ffe7e1`** where AA
  needs 4.5. `tests/test_design_tokens.py` pins ink-on-paper contrast and has
  never measured ink-on-**pastel**, which is the actual gap.
- **`@fontsource/instrument-serif` is still a declared dependency with zero
  imports**, orphaned when Phase 2 switched the display face. Left in place
  during the audit run rather than removed mid-flight; removing it is a
  package-lock change and belongs in its own commit.
- **`index.html` still carries the build-era favicon and `theme-color`**, and
  there is still no `meta description` (41/41) and no valid `robots.txt`
  (41/41). All three are 6.5's scope, already itemised in STATE.md, and left
  there deliberately rather than pulled forward.

### 9. The confirm round, and why its headline number is not the evidence

The after-run is `reports/phase-6.3-after/` — a full 41-route pass against a
real build of the finished work. **Its Lighthouse performance mean went *down*
1.61 points, and that is reported first because it is the number a reader would
most expect to be hidden.**

    login                   93 -> 89   (-4)     student-overview        74 -> 82   (+8)
    settings-notifications  91 -> 85   (-6)     student-standings       70 -> 84  (+14)
    teacher-quizzes         85 -> 75  (-10)     student-study-plan-...  76 -> 84   (+8)
    teacher-student-detail  73 -> 62  (-11)     teacher-announcements   79 -> 85   (+6)

Swings of ±11 land on routes this phase did not touch in any way, in both
directions, which is build-era D6.9's warning arriving exactly as written: a
composite Lighthouse score measured on a loaded local machine is not
reproducible, and **a single after-run cannot separate *fixed* from *fast*, in
either direction.** So the composite score is reported and then set aside. It
is not evidence that this phase helped, and equally not evidence that it hurt.

What the run *can* settle are the structural audits, which are facts about the
built artifact rather than timings, and each of these was checked as a
before/after pair rather than asserted:

- **`registerSW.js` is off the render-blocking list on all 41 routes.** Before:
  every route named two blocking resources, `index-*.css` and `registerSW.js`.
  After: every route names one, the stylesheet, which has to block. The audit
  still *fails* 41/41 for that stylesheet, and saying "render-blocking fixed"
  would have been false — what was fixed is the half that had no business
  being there.
- **The student dashboard's CLS is 0.098 -> 0**, and it was the only one of 41
  routes over the 0.1 ceiling. Per §0 this remains the weakest of the three
  numbers here, because a fast run hides shifts; the preload's defence is still
  structural.
- **The dashboard's unused JavaScript is 103KB over two chunks -> 53KB over
  one.** The 50KB `nivoTheme-*.js` chunk is gone from first paint entirely,
  which is precisely what `lazy-chart.tsx` claimed and the one place a
  code-split can be confirmed rather than believed.
- **Precache 146 entries / 2621.92 KiB -> 137 / 2435.27 KiB**, verified by
  building both ways rather than by trusting the earlier note: a 186.65 KiB
  drop, matching §5's figure.

The gate-failing route count fell 6 -> 3 (`student-correct` 79, `student-profile`
57, `teacher-student-detail` accessibility 94). Given the noise above, **that
drop is not claimed as an improvement** — `student-overview`, `student-standings`
and `student-study-plan-session` cleared the floor on a run whose mean fell, and
regression to the mean explains that at least as well as this phase's work does.
The `ui-thresholds` gate is still red, for the reasons §8 root-caused.

### 10. The confirm round found something the corpus had never recorded

**Five routes died mid-run — T-08, T-09-detail, T-10, S-21 and S-22 — every one
of them on its `loading` state, with "Waiting failed: 15000ms exceeded".** They
did it in the after-run and, checked state by state against the before corpus,
in the before-run identically: the same five routes, the same missing state, the
same surviving states. This is not a Phase 6.3 regression, and it is not new.

The part worth keeping is why nobody had seen it. A route that dies on its
*last* state has already written its axe and Lighthouse rows, so
`reports/phase-6.3-before/` shows **41 lighthouse rows, an empty
`console-errors.json`, an empty `responsive-summary.json`, and reads as a clean
sweep.** `audit.mjs` did throw and did name them on stdout — but the run's own
output is not the corpus, and **nothing that survives a run recorded that five
routes had been unreachable.** Every gate downstream reads the files.

That is D6.1's finding pointed at the harness rather than at a product screen:
a gate reporting zero and a gate that never looked are both consistent with a
green ledger row. So `audit.mjs` now writes `route-failures.json` beside the two
summary files it already writes, always, including as `[]`; and
`check_ui_gates.py` reads it with the *same* convention it already applies to
those two — **missing is "not checked", not "clean"** — so a corpus baselined
before this change says so out loud instead of passing by omission. Verified
against both 6.3 corpora, which is exactly the case that must report the gap:
neither has the file, and the gate now names it.

**The file itself lands on the next audit run, not this one**, because the
change was written while the after-run was already in flight and a harness
artefact must not be authored by hand. The five failures are recorded here
instead, and 6.4 runs the audit that produces the file.

Their cause is not diagnosed and is not claimed to be: all five are `loading`
states, which the harness drives by holding a request open, so a teardown
timeout is as likely to be the fixture's as the product's. It is 6.4's to pick
up with the axe work, on the same run.

---

## D6.5 — Redesign Phase 6.4 (accessibility), part 1: the chart that was 28 tab stops, the rule with no gate, and a contrast number the browser does not agree with

Phase 6.3 root-caused the axe corpus rather than sweeping it, so this phase
starts from evidence: **47 serious/critical violations across 7 routes, and
only two mechanisms.** Both are now closed, and a third thing fell out of
verifying the second that is larger than either.

### 1. 42 of the 47 were one library default, and making them *valid* would have kept the worse half

Nivo emits per-datum accessibility as

    <rect ... focusable="true" tabindex="0" aria-label="18 Jul: 0. No XP earned">
    <g    ... focusable="true" tabindex="0" aria-label="Aug 8: 82%">

`aria-label` is prohibited on an element exposing no role, so axe reports
`aria-prohibited-attr`: 28 nodes on `student-profile`, 11 on
`teacher-class-analytics`, 3 on `teacher-student-detail`.

Our wrappers asked for this deliberately and said why —
`line-chart.tsx`'s docstring argued that `isFocusable` + `pointAriaLabel` make
every datum reachable without a mouse, which §11 requires and a hover-only
tooltip does not deliver. **The intent was right and the mechanism never
worked.** A label on an unlabellable element is announced or dropped at each
screen reader's discretion, so the guarantee the docstring claimed was never
one. (Read off Nivo's compiled source rather than assumed: `aria-label` is
emitted whenever the prop is passed, *independently* of `isFocusable` — the two
read as coupled and are not.)

**The half no rule reported is the one that mattered more.** 28 prohibited
attributes on `student-profile` is 28 sequential tab stops on one XP panel: a
keyboard reader trying to reach the content below the chart pressed Tab 28
times. Fixing only the ARIA — adding `role="img"` per rect — would have left
that exactly as it was, and axe would have gone quiet.

So the per-datum labels are gone from the SVG and the same values render as a
`sr-only` `<table>` (`components/ui/chart-data-table.tsx`): `<caption>`,
`<th scope="col">` per series, `<th scope="row">` per datum. A screen reader
gets table navigation over exact values with the header repeated per cell; a
keyboard user gets one tab stop for the panel. The plot keeps `role="img"` and
its summary label, and the caption is *the same string*, so the two cannot
drift into two descriptions of one panel.

Three decisions inside it are deliberate: rows and columns are keyed by index
rather than by label (two papers marked the same day share an x label, and a
duplicate key would silently drop a datum from the only copy a screen reader
gets); the line chart's x values are a **union across series in first-seen
order**, because a cohort trend and an at-risk trend are built from different
papers and taking one series' axis would drop every date only the other has;
and a gap reads `"No data"` rather than `0` or a dash, because `y: null` is a
gap the data genuinely has, zero would invent a reading, and bare punctuation
is announced inconsistently in a table whose whole purpose is to be spoken.

### 2. The remaining 5 were a rule this codebase wrote down in Phase 2 and never enforced

`index.css` has carried this directly above the accent tokens since Phase 2:

    --accent      4.34:1 on paper — fills, marks, large text only
    --accent-ink  9.75:1 on paper — any accent-coloured small text

Correct, measured, and **read by nothing**. `text-accent` had accumulated on
**11** small-text elements: both marketing eyebrows (11px, the smallest text in
the product), a notification-settings link, four teacher panel headings, three
status counts, and two hover states that *reduced* contrast from the
`accent-ink` they darkened from.

**axe found 2 of the 11**, because axe sees only what a route it audits happens
to render. That is the whole argument for a source gate beside the rendered
one, and it is P6.3's z-index finding again: a rule stated in a comment above
the tokens, nine phases unenforced. `contrastRules.test.ts` derives the
sub-24px rungs from the `--fs-*` scale in `index.css` every run (a renamed rung
fails the gate loudly rather than leaving it checking names the product no
longer has), parses balanced class-expression groups, and **leaves
`text-accent` on icons alone** — an icon is a non-text element answering to the
3:1 graphics floor, which the accent clears. Verified by inversion three ways:
reinstating an eyebrow's `text-accent` fails, an icon-only `text-accent` does
not, and renaming `--fs-eyebrow` fails the vocabulary test rather than passing
vacuously.

Its limit is stated in its own header rather than left to be discovered: it
reads one class expression at a time, so a `text-body-sm` parent with a
`text-accent` child is the same defect and invisible to it. That case is axe's,
which is why both still run.

The sixth site was `--ink-faint` on `--accent-wash` — **4.47:1 where AA needs
4.5** — on the leaderboard's viewer row, the one row of the board that carries
a tint. It is 5.12:1 on paper, which is why it survived: the pairing that fails
exists only on one variant of one row. `--ink-muted` is 5.51:1 there and stays
de-emphasised. Note what the standing token test measures: it pins
ink-on-**paper** and has never measured ink-on-**pastel** at all.

### 3. The finding that outgrew the phase: `test_design_tokens.py` asserts a contrast the browser does not render

Chasing the last violation — white on the accent fill, which axe scored 4.21
and the token block claims is a comfortable 4.65 — produced this:

    token  oklch(0.576 0.146 33)  ->  our oklch_to_srgb: #c0523c
    same token, rendered by Chromium:                    #c25741

    white on #c0523c (what the test computes): 4.658  -> passes AA
    white on #c25741 (what a user sees):       4.436  -> fails AA

**`--accent-on` is `#ffffff` and the token block calls it "the ONE permitted
pure white" at 4.65:1 on the accent fill. On screen it is 4.436:1, which is
below the 4.5 floor it was chosen to clear.** The gate is green and the
rendered product fails, because the gate and the browser disagree about what
`oklch(0.576 0.146 33)` *is*.

The disagreement is tiny — (192,82,60) against (194,87,65) — and that is
precisely why it matters here: every contrast value in this design system was
chosen to *just* clear its threshold, so a 2-5/255 error in the conversion is
enough to move a claim across the line. `test_design_tokens.py` "caught two
real AA failures" in Phase 2 and has been cited as the contrast authority ever
since; what it has actually been validating is its own colour space.

**Not fixed here, deliberately, and this is a refusal rather than a deferral.**
The honest repair is not a one-line nudge to `--accent`: it is (a) reconciling
the conversion with what browsers do, then (b) re-deriving *every* contrast
claim in the token block against the corrected values, then (c) whatever token
changes fall out — and `--accent` is the brand accent, present on every
surface, chosen in Phase 2 against a brand strategy. Changing it unattended on
the strength of one arithmetic run, at the end of a long session, is exactly
the kind of wide-blast-radius decision §10 says to put in front of the human.
The numbers above are the evidence; the decision is D6.6's.

What ships now is the part that is unambiguous and self-contained: the 42
prohibited attributes, the 11 accent-size misuses, the pastel pairing, and the
two gates that keep them from regrowing. The white-on-accent node is **still
red and left red** — per the standing rule from INBOX item 8, a bar that is not
met is not loosened.

---

## D6.6 — RESOLVED: the contrast authority was right, and the browser never disagreed (redesign P6.4 part 2)

**Answered by the human 2026-08-14 (`D6.6 = A`, ntfy `jEmAdfevMO65`, ts 1786722798).**
Option A: reconcile `oklch_to_srgb` with what browsers do, re-derive every
contrast claim, and **propose** the resulting token changes before applying any.

### Step 1: there was nothing to reconcile

| route | `oklch(0.576 0.146 33)` renders as |
|---|---|
| `oklch_to_srgb` (the Python) | **(192, 82, 60)** |
| `getComputedStyle` | preserved as `oklch(...)`, unconverted |
| canvas 2d `fillStyle` readback | **(192, 82, 60)** |
| screenshot, default colour profile | **(192, 82, 60)** |
| screenshot, `--force-color-profile=srgb` | **(192, 82, 60)** |
| screenshot, `--force-color-profile=display-p3` | **(192, 82, 60)** |
| a literal `#c0523c` painted beside it | **(192, 82, 60)** — the same pixel |

axe-core 4.12.1, run against an isolated reproduction of the same button,
reports `fg=#ffffff bg=#c0523c ratio=4.65` and **passes**.

So the conversion, Chromium and axe all agree, and `--accent-on` is **4.653:1**,
above the 4.5 floor it was chosen to clear.

### Where 4.21 came from, proved rather than narrated

axe reported `fg=#f9f9fa bg=#c25741`. Neither value is a design token, and the
foreground is not the `#ffffff` the token declares. Both are one CSS transition
sampled mid-flight: the state is reached by *clicking* a toggle
(`pressToggleOnce`), which flips that button from `variant="secondary"`
(`paper-raised` fill, `ink` text) to `variant="accent"` (accent fill, white text)
under `transition-colors`, and axe ran before it settled.

Solving each channel for its interpolation fraction:

    background  253 -> 192, observed 194   t = 0.9672
                252 ->  82, observed  87   t = 0.9706
                250 ->  60, observed  65   t = 0.9737
    foreground   47 -> 255, observed 249   t = 0.9712
                 52 -> 255, observed 249   t = 0.9704
                 55 -> 255, observed 250   t = 0.9750

**One fraction, t = 0.971 ± 0.004, explaining all six channels across two colour
pairs with different endpoints**, and reconstructing 4.216 against axe's reported
4.21. A coincidence at that precision is not available.

### What this retracts, and what it costs

D6.5 §3 read the disagreement as the Python being wrong about its colour space,
and said so at length. That reading is **withdrawn**. What it actually compared
was axe's mid-transition sample against a correct conversion, as though the
former were "what a user sees". The lesson is not that the arithmetic was hard —
it is that **a measurement was trusted because it came from a rendered page**,
and "rendered" was doing work the number could not support. The token block's
claims stand exactly as written; no token changed.

### The real defect, which is fixed

`runAxe` measured before animations settled. `settleAnimations()` now runs first
(infinite decorative loops — the skeleton shimmer, the indeterminate progress bar
— are excluded so they cannot hold a route open, and it fails open on timeout).

The direction that matters is the one that did **not** bite here: a transient
sample can read *higher* than the steady state just as easily, turning a real
failure green, and it is not reproducible between identical runs — D6.2's rule
about a gate whose answer changes between identical runs, arriving in the
measurement layer this time rather than in a gate's own logic.

---

## D6.7 — OPEN: `--ink-faint` clears paper and misses every tint (redesign P6.4 part 2)

**Status: PROPOSED, not applied.** Raised by D6.6 option A's step 2 (*re-derive
every contrast claim*), which is the step that found it.

### The hole

`test_design_tokens.py` has been this project's contrast authority since Phase 2,
and everything it asserts about text is measured against `TEXT_SURFACES` — the
three paper rungs. The product also paints text on **eleven tinted fills** (six
pastels, four semantic washes, `--accent-wash`), and not one of those pairings
had ever been measured.

P6.4 part 1 found `--ink-faint` on `--accent-wash` at 4.47:1 and found it *via
axe on a rendered page*, because axe sees what a route happens to render and this
file was not looking. Deriving the full matrix shows that instance was not
special:

| | ink | ink-muted | **ink-faint** | accent-ink |
|---|---|---|---|---|
| accent-wash | 10.65 | 5.51 | **4.47** | 8.84 |
| pastel-rose | 10.43 | 5.40 | **4.38** | 8.67 |
| pastel-amber | 10.73 | 5.56 | 4.51 | 8.91 |
| pastel-sage | 10.70 | 5.54 | **4.49** | 8.89 |
| pastel-sky | 10.63 | 5.51 | **4.46** | 8.83 |
| pastel-lilac | 10.50 | 5.44 | **4.41** | 8.72 |
| pastel-clay | 10.53 | 5.45 | **4.42** | 8.75 |
| ok-wash | 10.86 | 5.62 | 4.56 | 9.02 |
| warn-wash | 10.73 | 5.56 | 4.51 | 8.91 |
| err-wash | 10.39 | 5.38 | **4.36** | 8.63 |
| info-wash | 10.63 | 5.51 | **4.46** | 8.83 |

**Eight of eleven below AA**, and the three that clear do so by 0.01–0.06. This
is not a bad pairing on one surface; it is a token that clears paper and misses
every tint. The other three ink tokens are unaffected and are now pinned.

### The proposal

`--ink-faint: oklch(0.529 0.006 240)` -> `oklch(0.52 0.006 240)`.

- clears 4.5 on **all fourteen** surfaces (worst pairing 4.530, was 4.360)
- 5.13:1 on paper, so it stays comfortably the muted rung
- still lighter than `--ink-muted` (6.09:1 on paper), so the hierarchy holds
- the largest L that clears everything is 0.5216; 0.52 takes the round number
  just inside it

### Why it is not applied

`text-ink-faint` has **334 call sites** — it is the caption colour of the entire
product — and A's own wording is *propose the resulting token changes for review
before applying any of them*. Live exposure today is small (one same-expression
pairing, `bg-warn-wash`, which passes) but the nested case is invisible to a
source gate by construction, and the one live instance found so far was found by
axe, not by grep.

Held as eight `xfail(strict=True)` cases rather than a note. `strict` is the
point: if the token is changed, they start passing, and a strict xfail that
passes **fails** — so the proposal can be neither quietly forgotten nor quietly
applied without this record moving with it.

### RESOLVED — 2026-08-14, the human accepted the proposal

Steering `VqpbRSelzmn9`, ts 1786723759: `D6.7 = "--ink-faint 0.529 -> 0.52
(Proposal Accepted)"`. Applied as proposed, in three places that must agree:
`web/src/index.css` (the implementation), `DESIGN.md` §3.2 (the canonical
record, including the ≈hex, which moves `#696C6F` -> `#66696C`), and
`tests/test_design_tokens.py` (the transcription).

The eight `xfail(strict=True)` cases are gone, and not by deletion: `ink-faint`
joins `ink`/`ink-muted`/`accent-ink` in the one parametrised matrix, so the
token is now checked by the same rule as its three siblings rather than by a
special case. Measured after the change — 5.13 on `--paper`, 5.38 on
`--paper-raised`, 4.78 on `--paper-sunk`, and worst-of-fourteen **4.53 on
`--err-wash`**. The ink hierarchy holds (11.77 / 6.09 / 5.13).

One thing replaced the xfails rather than being dropped with them. The split
list encoded *which pairing was binding*, and folding it into the matrix would
have thrown that away — so `test_err_wash_is_the_binding_constraint_on_ink_faint`
asserts by name that `--err-wash` is still the tightest of the fourteen. L 0.52
was chosen **because** err-wash was worst; if that stops being true, the value
was derived against a constraint that has since moved, and one named test says
so instead of one of eleven parametrised cases going red anonymously.

### The finding this turned up, which is bigger than the token

**`TOKENS` in `test_design_tokens.py` is transcribed by hand from DESIGN.md, and
nothing checked it against `web/src/index.css`.** So the file that calls itself
this project's contrast authority could measure one palette while the browser
painted another, and every ratio it asserts would still be green.

That is not hypothetical — it happened here, during this decision's own
application. `index.css` was edited first, the suite was re-run, and eight tests
went red **reporting the old value**, because the transcription had not been
mirrored yet. That direction is loud, and it is luck that the edit happened in
that order. The opposite order is silent: nudge a colour in `index.css` alone
and the authority proves AA about a value nothing renders. This is D6.2's shape
("a comment describing an intention is not evidence the code has it") relocated
into the gate itself, and it is the *third* time this redesign has found a check
whose subject and object had drifted apart.

Closed by `test_transcribed_token_matches_the_css_the_product_ships`, which
**parses** `:root` rather than transcribing a third time, plus a guard asserting
the parser matched at least as many tokens as the file measures — so a regex
that stops matching cannot silently pass everything beneath it. Verified by
inversion: `index.css` alone set to L 0.515 fails with `--ink-faint is
oklch(0.515, 0.006, 240.0) in index.css but oklch(0.52, 0.006, 240) here`, which
is precisely the silent direction. Today the transcription is faithful — 36
oklch tokens parsed, 33 measured, zero drift, and the three unmeasured are the
`--rule-*` hairlines, which are borders rather than text/background pairs.

**Not yet gated at the time of writing: the change is unproven in the browser.**
`npm test`, typecheck, lint, both builds and `pre-commit` have **not** run,
because `/tmp` filled and no Bash command can execute (**B5**). The colour
arithmetic is fully verified; the product build around it is not. 107 Python
token tests pass (rc=0, up from 64 passed + 8 xfailed).

---

## D6.8 — legal links in the marketing footer (redesign P6.5)

**Status: TIMED OUT UNANSWERED, default A applied 2026-08-14.** Sent
`gAGLBRpzyxmd` at ts 1786727791 with a 60-minute timeout, due at 1786731391;
polled nine times across the window including after expiry, no reply. §10 says
proceed on the default and log it, which is what happened. `LAST STEERING TS` is
deliberately NOT advanced: a timeout is not an answer, and recording it as one
would put a decision in the human's mouth. One message reverses this.

What shipped is in D6.10. Reversing it is small in either direction: the page is
two files plus a route, and option B (ship nothing) is deleting them.

§5 Phase 6.5's closeout list ends with "legal links". The footer currently has
none and says so in its own comment, correctly: a link to a page that does not
exist is the dead navigation the Phase 1 audit went looking for.

**Why it is a question rather than a task.** Facts about this product can be
derived from this repo: what is stored, that a scan is sent to Google Gemini,
that Supabase holds the database. **Promises cannot**, and a privacy policy and
a terms of service are mostly promises. Writing one unattended would be
inventing content in the one category where invention has legal consequences,
which is a different act from inventing a testimonial and a worse one.

Options as sent: **A** one factual, promise-free "How Lemely handles your data"
page and no ToS [default]; **B** ship nothing and record the omission as
needing a lawyer; **C** A plus placeholders. C was argued against in the same
message rather than merely listed, because it is the dead-link pattern the
footer already refused.

**Found while preparing A, and true whichever way this goes: the product has no
account-deletion path and no retention rule anywhere in `lemely/`.** Nothing
purges, anonymises or expires a scan, an attempt or an account. A can still
ship (the page would state that, which is honest and more useful than silence),
but on a product whose users are minors this is a real gap, and it is exactly
what a policy would normally have to describe. Not fixed here: building a
deletion path is far beyond a footer link, and it is a product decision.

---

## D6.9 — Redesign Phase 6.5 (strategic omissions): the tab that said "Lemely" 48 times, and the one surface the redesign never reached

Three of the five §5 Phase 6.5 items shipped here. Two were already done and
were **verified rather than assumed**: the custom 404 landed in P3.1 and gained
its in-portal variant in P4.10, and the skip link is imported by all six frames
(`SkipLink` has call sites in the student, teacher, parent, admin, marketing and
settings shells plus the standalone 404). The fifth, legal links, is open behind
D6.8.

### 1. No screen in the product had ever set a `document.title`

All 48 routes were "Lemely", from the single static tag in `index.html`, for the
whole build and the whole redesign.

Three of the four costs are ordinary: indistinguishable tabs, useless bookmarks,
a tab-search feature that cannot find anything in this product by name. **The
fourth makes it an accessibility defect rather than a metadata one.** A screen
reader announces the document title on navigation, and in a single-page app
nothing else announces that the page changed at all — so a non-sighted reader
clicking through the sidebar heard "Lemely" after every single navigation and
was never once told where they had arrived. That is the reason this was worth
doing for authenticated screens no crawler will ever read, which is otherwise
the obvious place to stop.

**The mechanism was chosen for what could gate it, not for what was shortest.**
The obvious fix is `useDocumentTitle("...")` at the top of 48 screens. It was
rejected because a per-screen hook has nothing to check itself against, so route
49 ships untitled and nothing says so. That is not a hypothetical: it is how
`text-title` sat on a live `<h1>` emitting zero CSS for an entire build, how the
compat layer outlived every screen that used it, and how two whole admin portals
ended up in none of the three gate lists (P4.10). Route `handle` puts the title
**in the route table**, which can be walked, so `documentMeta.test.ts` walks it
and fails naming the exact route. Verified by inversion.

Titles name the **screen**, never the record on it. `result/:paperId` is "Paper
result", not the paper. The subject routes are the interesting case, because the
code is right there in the path and is still not used: a title assembled from a
URL segment is a value restated from somewhere else, and D6.7's whole lesson is
what happens to those.

Descriptions and `og:` tags go **only** on the four routes a signed-out reader
can reach. Everything else is behind `RequireAuth` where no scraper will ever
look, and writing marketing prose into the head of a teacher's review queue
would be inventing copy for an audience that does not exist.

### 2. The browser tab was the one surface the redesign never reached

`public/favicon.svg` was the build-era mark: a `#863bff` purple glyph, still
shipping three phases after Phase 2 replaced the identity. §4 names purple-blue
as this redesign's **hard anti-reference**, so the most frequently seen piece of
Lemely's brand was the one piece painted in the banned family. The three PNG
icons beside it were rasterised from that same purple mark on 2026-08-12, before
Phase 2 existed.

**Nothing here could have caught it.** Every gate this build runs reads code or
reads a rendered page. An icon is a binary that no test opens, displayed by an
operating system in a place no screenshot harness captures. It is D6.4's
`registerSW.js` finding in a second form: the defect was not in anybody's diff.

Fixed by generating them from the real mark with a checked-in script
(`scripts/generate_icons.mjs`, `npm run icons`), so the vector is the source and
the PNGs are the artifact. A PNG in a diff is unreviewable, and "how do I
regenerate the icons" is otherwise knowledge that lives in one head until it is
lost. The maskable cut is a **different image, not a resize**: Android crops to
the central 80% diameter, so a square of side s survives only when
`s * sqrt(2) <= 0.8w`, i.e. `s <= 0.566w`. The scale is 0.46 and the bound is
asserted in the script itself as well as in the test, because that is where
somebody editing the number is actually looking.

### 3. The manifest colours had already drifted, exactly as D6.7 predicted

`vite.config.ts` carried `theme_color: "#1e1310"` and `background_color:
"#faf4f2"` under a comment stating they were "computed from index.css's
student/default theme tokens via a real oklch->sRGB conversion (culori
formatHex): --ink oklch(0.2 0.02 35)".

**Every clause of that comment was false.** `--ink` is `oklch(0.321 0.009 234)`.
There is no `--bg` token. culori is not a dependency of this project and by the
look of the lockfile never was. Both hexes are build-era Material-3 values that
no token in the product has produced since Phase 2 rewrote the palette.

The consequence is small and constant: a phone drew a **near-black address bar
directly above a warm paper page**, on all 48 routes, for the entire redesign,
on the one device class the brief says students live on. Nothing failed because
nothing was checking — a manifest colour is read by an operating system, not by
a test.

`vite/brandTokens.ts` now computes them from `index.css` at build time and the
transcription is **deleted rather than corrected**, which is the only fix that
cannot drift again. `vite/themeColor.ts` injects the `<meta name="theme-color">`
from the same source and **throws** if anyone puts a literal hex back. Both
verified by inversion; the throw's message names the reason.

This is D6.7's question — *what re-states a value, and what checks that the two
still agree?* — asked of the three files P6.5 was always going to touch, and it
had already been answered badly in all three.

### 4. Two things found by verifying rather than reasoning

**`router.state.matches` is not `useMatches()`.** The former is
`DataRouteMatch[]`, where the handle lives at `match.route.handle`; the latter
hoists it to `match.handle`. They look interchangeable. Reading the wrong one
returns `undefined` for every route, so every page would have fallen back to the
default title and **the entire feature would have shipped doing nothing**, with
all 15 new tests still green (they exercise the pure functions and the route
table, not the wiring). `tsc` caught it. Worth recording plainly: this is the
one defect in P6.5 that a type checker could see, and the other three are a
catalogue of things it could not.

**`mark-favicon.svg` carried 12 lines of comment above its opening tag.**
`mark.svg`'s own comment warns, in as many words, that libvips (and so sharp)
sniffs only the first bytes and rejects the file when `<svg` is pushed out of
that window. The favicon cut was authored after that warning and did it anyway.
Nothing had noticed because nothing had yet asked sharp to read that particular
file — a latent defect that only becomes real the first time somebody uses the
asset for the thing it is for.

### 5. The OG card carries no text, deliberately

The obvious card sets "Lemely" in Newsreader beside the mark. It cannot be built
honestly here: @fontsource ships **woff2 only**, which librsvg cannot load, so an
SVG asking for `font-family: Newsreader` renders in whatever fontconfig picks,
almost certainly DejaVu Sans. §3.2 item 2 bans that class of face outright, and
a wrong face inside a generated binary is invisible to every gate in this repo,
because nobody diffs a PNG and the file only ever renders inside somebody else's
chat app.

So the card is the mark on ruled paper, and the product's name is carried by
`og:title`, which is real text in the scraper's own typography. A smaller card
than a wordmark lockup, and one that cannot quietly be wrong.

### 6. Found while checking a sentence: no deployment of this code can send an SMS

Not a P6.5 item, not fixed here, and recorded because it is the largest thing
this phase walked past.

Writing a meta description for `/login/parent` meant restating the screen's own
copy, which reads *"Enter your phone number and we'll text you a code."* That
sentence is checkable, so it was checked:

- `lemely/web/deps.py` wires `sms=MockSmsProvider()` **unconditionally**. There
  is no config switch and no alternative implementation in the repo.
- `MockSmsProvider.send_code` **logs the code at INFO level** instead of sending
  it. Its own docstring says so.
- `SmsProvider` (the protocol) documents a `delivers_out_of_band` flag whose
  comment reads "Any real provider added later **must** set this True" — which
  is a statement that, as of now, none has been.

So the parent OTP flow is real (codes are generated, stored with a TTL, rate
limited, and verified), and the **delivery** of it is not. `ParentLogin` already
renders a `devCode` panel whose own comment states it exists only when there is
no real gateway, so the product is internally consistent about this in code and
inconsistent about it in copy.

This matters more than a copy defect usually would, because §5's own framing
calls the phone route "the lowest-friction entry in the product" and it is the
only way a parent gets in. **A parent following that screen's instruction waits
for a text that no code path sends.**

Two things were deliberately not done. The screen's copy was not changed:
integrating an SMS gateway is the actual fix, it needs credentials and a
provider choice, and rewording the sentence to describe the mock would be
dressing a missing feature as a design decision. And the claim was **not carried
into the new meta description**, which says "a one-time code" instead of "a code
sent by text" — one file repeating an unverifiable claim is a defect; two files
repeating it is how it becomes a fact nobody rechecks.

### Gates

typecheck, lint (0 errors), **1,403 web unit tests (+15)**, `check:copy` 0, both
builds, 107 Python token tests, `pre-commit run --all-files`: all green. Titles
confirmed in a real browser on public and authenticated routes, including a
client-side navigation (the path `router.subscribe` exists for) and a portal
catch-all. Both new build-time throws verified by inversion.

---

## D6.10 — Redesign Phase 6.5 closeout: the page that describes instead of promising, and the gate that could not reach the pages it measured

Phase 6.5's last item (§5: "legal links") and the `adapt` re-run STATE asked
Phase 7 to do. The second one is the finding.

### 1. The adapt gate died at surface 8 of 35, and had been able to for four phases

Started at the top of the D6.8 wait window as independent work, the gate crashed
with `page.goto: net::ERR_CONNECTION_REFUSED at http://127.0.0.1:4319/landing`
after seven surfaces. It reproduces deterministically with `--surface=landing`.

**`adapt_audit.mjs` served `dist/` on port 4321. Six of the `act` callbacks it
imports from `capture_surface.mjs` navigate by absolute URL to 4319**, because
they assert on routing itself ("`/` renders the landing page for a signed-out
visitor", and both 404 surfaces answering on their own path), and an absolute
URL needs a host. The audit's own header opens with the sentence "this walks the
SAME registry that harness does — imported, never restated". The registry was
imported. The port was restated.

Consequences, in order of how bad they are:

- The run dies at the `landing` surface, **eighth of thirty-five**, so the
  twenty-seven surfaces after it were never measured at any width. Everything
  from `login` onwards, which is every auth screen, every marketing state and
  both 404s.
- **Unless something else is listening on 4319.** Then the goto succeeds and a
  stranger's server answers a question about our build. This project has that
  exact defect written down already: BLOCKERS.md B4, "the e2e suite silently
  runs against whatever is already on port 8000". This is it again, in the gate
  written three phases after it, and it was observed live this session: a
  leftover `vite preview` from a diagnostic run made the failure disappear, and
  the process holding the port was still there minutes later because
  `server.kill()` kills the `npx` wrapper and not the vite process under it.
- The port mismatch dates from `4aa77e5` (Phase 6.1's own wip commit), and the
  landing `act`s that trip it date from `cee06e9` (Phase 4). So it was live for
  the whole of Phase 6. **D6.1 recorded 6.1's adapt gate as "745 page-states
  across 35 surfaces, 0 findings", and there is no findings artifact in the tree
  to check it against** (`reports/redesign/p6-adapt/` exists and is empty, and
  nothing under it is committed or ignored). The most likely reading is that
  that run had a capture server on 4319 to lean on. Recorded as the honest
  reading rather than a certainty: what is certain is that the mismatch was live
  and that the number cannot be reproduced from this tree.

D6.1's own lesson was "a gate reporting zero and a gate reporting nonsense are
both consistent with a green ledger row". The gate that lesson came from was
this one.

**Fixed by deleting the restatement, not by syncing it.** `PORT`/`BASE` are
exported from `capture_surface.mjs` and imported by the audit, which is the rule
the surface registry already followed. Two further changes, both because the
diagnosis was harder than the bug:

- **The gate now refuses to measure a server it did not start.** With
  `--strictPort`, a busy port makes our server exit, and the wait loop's `fetch`
  would then be satisfied by whoever is already there. The child's `exitCode` is
  checked before the fetch is believed, and the failure names the port.
- **The gate keeps its server's output.** `stdio` was `["ignore","pipe","pipe"]`
  with neither pipe ever read, so vite's own `Error: Port 4319 is already in
  use` went into a buffer nobody emptied, and recovering it took a throwaway
  script. **A gate that discards the evidence of its own failure makes every
  failure look like a flake**, and a flake gets re-run rather than read.
  Draining the pipes also removes the 64KB-buffer stall a 25-minute run invites.

Pinned by four tests in `adaptRules.test.ts`: the port is declared once, the
audit imports it, the exit-code guard exists, and both pipes are drained.

### 2. Legal links: a description, not a policy (D6.8 default A)

D6.8 timed out unanswered after nine polls, so its default applied. `/data`,
"How your data is handled", linked once from the marketing footer. No terms of
service, no privacy policy, no placeholders.

The reasoning is worth keeping because it generalises past this page: **facts
about this product can be derived from this repository, and promises cannot.** A
policy is mostly promises, made by an operator who is not in the code, under a
jurisdiction nobody has chosen. Writing one unattended would be inventing
content in the one category where invention has legal consequences.

So the page says only what a named module does, and `dataHandling.ts` carries
the module beside every sentence, which is `data.ts`'s rule applied where the
cost of breaking it is higher. Six sections: what an account holds (no password
on the row; Supabase Auth holds the credential), the device registry and the
three-device limit, what an upload stores, **that the scan file itself is sent
to Google Gemini rather than text extracted from it locally**, who else can see
a student's work, and what the site does not do.

Three things are deliberately absent and their absence is the design: no legal
basis or controller identity, no retention period (there is no retention
machinery to describe), and **no contact address**, because inventing
`privacy@lemely` is the dead-link pattern wearing a serious face.

The panel at the foot is the one that matters. **There is no account deletion
and no way to remove a scan, and nothing expires on a schedule** — verified
across `lemely/` rather than assumed, and stated on the page in those words
rather than left out. It is in `warn` with a labelled chip, per §4's rule that a
caveat does not travel as a colour alone.

### 3. The page is gated against both ways it can stop being true

A page about the backend is a comment describing an intention: true the day it
is written, and nothing notices when it stops being. `dataHandling.test.ts` (20
tests) therefore reads the *backend*, not the page:

- **Every `@router.delete` path in `lemely/web/routers/` is parsed**, and the
  test fails if an account-deletion or scan-deletion route appears. Its message
  is an instruction, not a diff: the right response to it going red is to
  celebrate and then edit the page. Verified by inversion (pointed at
  `/devices/{device_id}`, it fails with that message), and it has its own
  not-vacuous check, because a regex that stops matching would make every
  assertion pass by finding nothing.
- A promise list: no "we will/never", no "your data is safe", no guarantee, no
  commitment, no retention period in days, no GDPR/controller language, no
  em-dash. **The fix for a failure there is never to reword.** It is to
  establish that the code does the thing, and then say what it does.
- Plus the facts the page exists to carry, asserted positively so it cannot pass
  by saying nothing.

### 4. Four registries, because a screen no list claims is a screen no gate reads

P4.10's finding, now applied preemptively rather than after the fact: the new
page is in `capture_surface.mjs`'s surface registry (so the adapt gate measures
it at all five widths and the screenshot rounds photograph it), in `audit.mjs`'s
a11y registry (axe and Lighthouse, signed out), and in all three file lists
(`RTL_CLEAN_FILES`, `MIGRATED_FILES`, `SCANNED_FILES`).

The third of those earned its place immediately: the migration gate failed the
new file for using `text-display-xs`, a compat-layer token, twice. A file added
to the lists on the day it is written is a file the lists actually cover.

### 5. What the gate found once it could see: 10 findings, both classes real

The first honest full run: **765 page-states across 36 surfaces, 10 findings,
66 exemptions** (all from the one OTP row that states its reason). Both classes
were in surfaces the gate had never reached.

**Four `overflow` findings, and the cause is a rule that does not do what its
name says.** `ChartDataTable` renders the accessible copy of every chart as
`<table className="sr-only">`. `sr-only` is `position:absolute; width:1px;
height:1px; overflow:hidden; clip-path:inset(50%)`, which yields a 1px box on a
block element. **On a table it does not**: CSS auto table layout treats a
specified width as a *minimum*, so the table expands to its content anyway. The
boxes measured **357px** wide on the student dashboard and **316px** on the
profile page, hanging off the right edge at 320px and 375px.

Nothing was visible (`clip-path` paints none of it) and nothing scrolled
(`overflow-x: clip` on html and body). So the only instrument in this repository
that could ever have seen it is a gate that measures element geometry through
that clip, which is precisely what this gate was built to do and had never once
reached those surfaces. Fixed by putting `sr-only` on a `<div>` wrapper, which
honours `width: 1px` and clips the table inside it; the accessibility tree is
unchanged.

Worth noting what was NOT done: the gate's `visible()` helper already exempts
screen-reader-only boxes, keyed to `clip-path` **and** a rect under 2px. Widening
that to "any clip-path, any size" would have turned all four findings green in
one line. It is the shape of waiver this mission has twice recorded as worse than
the defect, and the product was genuinely wrong.

**Six `twoLine` findings, all six caused by this phase's own footer link.**
Adding a third link made the row too wide for the 276px of content box a 320px
screen leaves, so "How your data is handled" wrapped onto two lines and pushed
"Parent sign in" onto two as well. Hallmark's non-negotiable is that clickable
text never wraps: the second line is a strip of link that reads as body copy,
and a thumb aimed between them hits neither. The footer links now stack into a
column below `sm`, so each gets the full width, one line, and a full-width
target.

That is the useful shape of this pair. **The gate caught this phase's own defect
in the same run that it caught a four-phase-old one**, which is the argument for
fixing a broken gate before the work rather than after it.

### 6. Small, and worth writing down

**A check that a word is absent cannot tell an implementation from a sentence
about one.** The first draft of "puts no auth guard on it" grepped `index.tsx`
for `RequireAuth` and failed, because that file states in a comment that it
deliberately contains none. It now walks the route element tree, which is what
`marketing.test.ts` already did.

### Gates

typecheck, lint (0 errors), **1,432 web unit tests (+29)**, `check:copy` 0, both
builds. Full `adapt` re-run, Python tests and `pre-commit run --all-files`
recorded with the commit.

## DA1 — H4: the frozen train/dev/test split policy, and the spec contradiction it had to resolve (#49, blocks #57/#47)

First decision of the accuracy programme; DA-numbered so the accuracy stream stays
separate from the redesign's D6 series. Recorded from a human interview on 2026-08-19.
It fixes the **rule**; the membership **list** is signed off separately, on #57, once
#44 has restored the corpus the rule partitions (spec §7: corpus restore → split
membership).

**Unit: the question, not the paper and not the leaf.** A leaf's root parent is
atomic — a multi-part question is never divided across splits — but two questions from
the same paper may land in different splits. This buys control over per-stratum leaf
counts at a budget of ~7–8 labelled papers, where paper-level assignment can only move
ground truth in ~40-leaf chunks. It is bought with leakage, and the leakage is recorded
rather than argued away: dev and test will share papers, so mark-scheme house style,
layout and scan quality carry across the boundary. **The H9 write-up therefore claims
"unseen questions", never "unseen papers".** The split manifest carries this sentence.

**Proportions: 10 / 60 / 30 ≈ 30 / 180 / 90 leaves.** `train` is the only place real
papers may be eyeballed freely — prompt work, threshold tuning, regression fixtures.
`dev` carries all A/B measurement. `test` is read once, at H9.

The arithmetic that forced the choice: §6 puts the paired-McNemar floor for 83.8% →
88.8% at n=219, and a ~90-leaf test split gives a 95% Wilson interval of roughly ±7.5pp.
A 300-leaf budget cannot fund both a provable dev improvement and a tight headline. Dev
at 180 sits **below** the McNemar floor deliberately, and the consequence is accepted in
advance: per M0.6, an improvement claim on dev prints as underpowered rather than as a
number. The alternative (0/70/30) would have reached the floor by deleting the tuning
pool — which does not remove the iteration, it just moves it onto dev leaves and
contaminates them silently. Raising the label budget to ~450 was offered and declined;
it remains the only way to get both.

**Strata: pre-label observables only.** Assignment stratifies on syllabus code
(0580/0606/0625) × parse path (det/Gemini) × tariff band (1 / 2 / 3+ marks).

This resolves a contradiction in the spec. §4 requires stratification to use "the
labeller's own type judgement, never the pipeline-emitted `question_type`" — but that
judgement is an **output of labelling pass 2**, and the freeze is what unblocks
labelling (#49 → #57 → #47). As written, §4 stratifies assignment on a variable that
cannot exist at assignment time. The resolution keeps both halves of the intent: the
labeller's type judgement drives the **published stratification table** in M2.4's
acceptance — which is a reporting requirement — while assignment uses only what is
observable before any label exists. The pipeline-emitted `question_type` is still never
used for either purpose; on the det path it is hardcoded to `recall`, which is the
defect §4 was guarding against. **§4 needs amending to say this**; raised on #43.

Two alternatives were rejected. Pilot-then-freeze (label ~40 leaves, observe the type
distribution, then freeze) makes the freeze a function of labels already seen, which is
the independence the freeze exists to protect. A command-word heuristic
("calculate"/"explain"/"draw"/"state") lifted from the question paper is closer to the
intended variable but unvalidated — and on the det path the stem text is precisely what
is least reliable.

**Assignment: a deterministic hash, not a seeded shuffle.**
`split = bucket(sha256(salt ‖ question_id))` within each stratum, with the salt recorded
in the manifest. No RNG state, no dependence on input ordering, no Python-version
sensitivity: a reviewer recomputes every assignment from the manifest alone and gets the
same answer. A seeded shuffle is reproducible only if the sort order and RNG
implementation are *also* pinned, which is three more things to get wrong. Hand-picking
was rejected outright — with n this small it would give the most balanced splits and no
defensible answer to "why is that hard paper in dev?".

**Amendments: drop-only, logged, never backfilled.** A leaf that turns out unlabellable
— corrupt scan, missing mark scheme, an unadjudicable question — is excluded with a
reason in the manifest, and its split simply loses a leaf. No replacement is drawn.
Backfilling is what lets a labeller shop for easy leaves, and deterministic backfill
only removes the shopping, not the post-freeze membership churn. Splits will therefore
land under their target n, and M0.5's exclusion funnel publishes the shortfall so the
shrinkage is visible rather than silent.

**Test-touch: the token gates evaluation joins, not file access.** Acceptance box 3 says
the test split is "read exactly once", but the labeller must read test-split papers to
label them at all, so the literal reading is unsatisfiable. What consumes the single
read is **any run that joins pipeline output against test labels** — the harness, the
pure analyses, `AccuracyMetrics`. Labelling a test-split paper is a ground-truth
*write*, is unrestricted, and cannot leak results because the labeller imports no
pipeline module (already asserted by a test, §6). One token, issued by the human at H9;
one ledger append; CI fails an untokened join. This is the contract M0.7a (#31) builds.

Gating every artefact access instead would put a token in #47's path and fill the ledger
with routine labelling entries, diluting the one entry that matters. Extending the gate
to reporting (a CI grep over `BUILD/` and `reports/` for test-split numbers before H9)
was considered and not adopted; the leak path it closes — running the join locally and
pasting the number — remains open, and is held by discipline rather than by CI.

**Status.** #49 acceptance boxes 1 and 3 are met by this record. Box 2 — membership
frozen in the manifest — stays open until #57 generates the manifest over the restored
corpus and the human signs off on the actual list, so that "human approved the
membership" remains a true statement rather than a pre-approved abstraction.

---

## DA2 — H7: the agreement ceiling becomes a two-labeller measurement (#51, blocked by #47)

**The figure is inter-annotator agreement, not self-agreement.** A second named person
(labeller B) marks the sample. This is the quantity the ceiling was always a proxy for:
*if a competent examiner labelled this leaf independently, would they reach the same
verdict?* Delayed self-agreement was the substitute the spec assumed because only one
labeller was thought to be available; with a real second person the substitute is
unnecessary. **§6's "self-agreement" paragraph needs amending**, along with #51's title
and acceptance wording; raised on #43.

**No delay, and why the delay existed.** With one labeller, re-marking a leaf soon after
measures recall, not judgement — agreement returns near 100%, every pipeline-vs-label
disagreement is then booked as pipeline error, and M3/M4 spend effort chasing headroom
that is really one person's inconsistency on one weekend. The delay was the only defence
against that. B has no memory of A's verdict to recall, so the defence is not needed and
its schedule cost (up to a fortnight between the end of #47 and any publishable figure)
is not paid.

**Sample: rule pre-committed, membership computed after labelling.** The manifest states,
before labelling begins, that the sample is the 10% of labelled leaves with the lowest
`sha256(relabel_salt ‖ question_id)`, drawn **per stratum** so the ceiling is not
computed entirely on 0580 tariff-1 recall items. Membership cannot be known during
labelling because the ranking needs the full set of labelled leaves, which does not exist
until #47 completes. Fixing membership up front was rejected: A would be labelling leaves
known to be watched, and the resulting figure would bound A's care rather than A's
consistency. This is the same rule/membership split as [[DA1]].

**Both passes, marking held against A's transcription.** B redoes transcription blind,
giving a transcription-agreement figure; B then marks against **A's** pass-1 text rather
than B's own. This yields two separately attributable ceilings — how consistently
handwriting is read, and how consistently the mark scheme is applied — with the marking
figure measured on identical input in both arms, so transcription drift cannot leak into
it. A fully independent re-run was rejected because a disagreement could then be either
layer and the ceiling gives no direction to improve in; marking-only was rejected because
it leaves handwriting reading, the pipeline's largest known gap, unmeasured.

**B is calibrated first.** B reads the complete #52 ruling log before marking. Rulings
are conventions with a right answer once someone decides; an uncalibrated B disagrees on
convention, that disagreement is counted as irreducible human variability, and the
ceiling comes out lower than the truth — which stops optimisation too early. The cost,
accepted: a convention that is unwritten but which A and B happen to share stays
invisible, so the log's own completeness is not tested by this exercise.

**Disagreements: A's label stands.** B's verdicts compute the agreement figure and
nothing else. Ground truth stays homogeneous — all ~300 leaves produced the same way —
so the accuracy number is not quietly better on the 10% that got two pairs of eyes, and
sampled leaves landing in the test split do not give the release number a mixed-quality
reference. Where a disagreement is systematic rather than a one-off judgement call it
goes to #52 as a new ruling applying to future labelling, which captures the value
without making the sample special. Accepted cost: labels known to be contested are
retained on roughly the disagreement rate of 30 leaves.

**Size stays at 10%, and the interval is published.** ~30 leaves. At 93% agreement the
95% Wilson interval is roughly ±10pp, so the ceiling is known only to lie somewhere from
the low eighties to the high nineties. That is enough to catch a catastrophic ceiling and
enough to print beside the headline number; it is **not** enough to justify a
fine-grained stop-optimising decision, and the interval must appear wherever the figure
does. Reaching ±4pp would need ~150 leaves — half the corpus — and was rejected as the
wrong place for that effort.

**Consequences for the issue.** #51's stated 45-minute effort is wrong: 1–2 h of B's
time across both passes, plus onboarding on the labeller UI. B's identity is recorded in
each label manifest (§6 already requires labeller identity). The published figure is
labelled *inter-annotator agreement, two labellers, calibrated, n≈30* — never compared
against or averaged with a single-labeller figure from any other regime.

---

## DA3 — H8: the ruling log is a record, not an authority (#52)

**What #52 actually adds.** The person raising a judgement question during labelling is
the same person ruling on it. #52 therefore adds no independent examiner authority, and
the issue should stop implying one. Its entire value is the **written record**: that
session 8 marks the same way as session 1, and that labeller B ([[DA2]]) can be
calibrated against something explicit rather than against A's memory.

**Storage.** `eval/rulings.jsonl` at repository root, append-only with a hash chain
exactly like the labels, deliberately outside the `lemely/eval/` package (§3.1). It is
published alongside the accuracy figures: the rulings are part of the ground-truth
definition, and the number is not reproducible without them.

**Scope is a machine-evaluable predicate.** Each ruling records its scope over a fixed
small set of fields already present on a label — syllabus code, tariff, parse path, the
labeller's own type judgement, and the presence of mark-scheme tokens such as `oe` or
`ecf`. The pre-freeze sweep then selects affected leaves automatically and provably
completely, which is the only version in which "the corpus is consistent under the final
rule set" is a checkable claim. Free-text scope plus hand-listed keys was rejected:
completeness would rest on the labeller recalling affected earlier leaves while
mid-labelling on a different one, so the sweep would systematically miss exactly the
cases most likely to be inconsistent. Free text alone was rejected because the sweep
becomes ~300 leaves × every ruling, by hand, immediately before the freeze — which under
time pressure gets abbreviated and the consistency claim quietly becomes false.

**Retroactivity: forward immediately, one deferred sweep before the freeze.** A ruling
governs labelling from the moment it is made. When #47's labelling completes, a single
sweep re-serves every earlier leaf inside some ruling's scope and re-marks it, appending
**supersede records** so the hash chain stays intact and the original verdict remains
visible. Forward-only was rejected: it leaves the corpus inconsistent in a systematic,
direction-carrying way, and that inconsistency is indistinguishable from pipeline error
in the accuracy figure. It would also corrupt [[DA2]] — B reads the *final* ruling log
while A's early leaves were marked under a partial one, so part of the measured
disagreement would be ruling drift rather than judgement, deflating the ceiling.
Immediate retroactive sweeps on every ruling were rejected because repeatedly
interrupting sessions to do rework is the pattern most likely to stop the labeller
raising questions at all.

**Mid-session: park and continue.** A judgement question writes the leaf as
`pending_ruling` and the session continues; parked leaves are resolved in a batch and
completed. This preserves flow across a 6–8 h job split over sessions. The parked tail
must reach zero before the split freeze, and any leaf never resolved is an **exclusion
that appears in the M0.5 funnel with its reason** — never silently dropped from the
denominator. Ruling provisionally in the moment was rejected: with the leaf already
marked there is no forcing function to revisit, and provisional rulings become permanent
by inertia. Stopping the session was rejected: a question needing real research into CAIE
conventions blocks for hours, and the pressure to unblock is what produces a hasty
ruling.

**Blindness holds during adjudication.** A ruling is never resolved by consulting what
the pipeline produced for that leaf. Adjudication is the natural place to breach §6's
structural blindness — the labeller is stuck, the pipeline's answer is available, and it
looks like evidence. It is not evidence; it is the thing being measured.

---

## DA4 — H9: what pre-commits the single test read, and what happens when it disappoints (#55)

**Both arms in one touch.** The acceptance requires a paired McNemar comparison, which
needs the release candidate *and* its baseline scored on the same test leaves. Both
arms execute inside the **same authorised touch**, from a single command, with both
results written to the ledger together. Running the baseline first "to have it ready"
spends the one read, and the candidate's number is then the second.

**Release candidate: human choice from dev-evaluated candidates.** Candidates are
measured on dev and the human picks one. Selecting on dev is what dev is for, and the
test split stays untouched throughout — this is not a leak. It does carry a cost that
must be handled explicitly, because selection is otherwise invisible: many dev
comparisons inflate the winner's dev figure through selection, so the test number is
*expected* to regress downward. Two guardrails, both written into #55: the candidates
considered and their dev figures are published alongside the result, and the expected
downward regression is stated **before** the read so the gap does not read as failure
when it appears. The candidate's git SHA is recorded before authorisation is issued.

A fully pre-committed mechanical checklist was offered and not taken; it would remove
discretion at the decision that matters most, at the price of being unable to ship
something that misses one box for a good reason.

**A disappointing result is published and the split is spent.** The number goes out with
its Wilson interval and the McNemar comparison, whatever it says. The test split is then
burned: all subsequent work is measured on dev only, and any future release needing a
fresh test figure requires a **new test split drawn from currently unlabelled corpus** —
more labelling, more of B's time for a fresh ceiling ([[DA2]]), and real schedule cost.
Deciding this now is the whole mechanism; the cost has to be accepted before it is a live
temptation. A disclosed re-run was rejected: it degrades the guarantee from "read once"
to "read twice", and the second number is selected on knowledge of the first, so its
interval understates the real uncertainty and the McNemar comparison is no longer clean.
Leaving the response open was rejected because the decision would then be made by whoever
is looking at a disappointing number under release pressure, which is the exact
circumstance the mechanism exists to remove it from.

**Enforcement** is the M0.7a token and ledger from [[DA1]]: one token issued by the human
at H9, one ledger append, CI failing any untokened join of pipeline output against test
labels.

**Issue hygiene.** #55 carries no milestone, unlike #51 and #52; it needs the release
milestone set so it cannot be picked up early by accident.

---

## DA5 — Ordering: B labels after the ruling sweep (#51 after #52, both after #47)

[[DA2]] requires labeller B to read the complete ruling log, and [[DA3]] leaves the
corpus consistent only after the pre-freeze sweep. B must therefore mark **after** that
sweep, not merely after #47's labelling. Neither issue states this and neither does
spec §7. The constraint belongs in §7's strict-orderings table:

| first | then | why |
|---|---|---|
| ruling sweep (#52) | agreement sample (#51) | Otherwise part of the A–B gap is ruling drift, not judgement, and the ceiling is deflated |

Raised on #43 together with the §6 amendment.

---

## DA6 — What a distinct leaf's outcome *is* when its variants disagree (#25, M0.1/M0.6)

**The gap.** Spec §2.3(b) and §3.3 settle the *denominator* and nothing else. §2.3(b):
"Observations within a family are not independent, so every interval and power
calculation quoted on n=68 is invalid." §3.3: "every interval or power calculation
collapses to **distinct leaves** first." Verified against the corpus this run: the 10
golden case dirs hold 68 answer rows, and stripping the `_correct`/`_partial`/`_wrong`
suffix yields exactly 7+6+8+7 = **28** distinct `(paper, question)` leaves, matching
§2.3(b) exactly.

What no line of the spec states is **which record represents a leaf once three variants
of the same question collapse into one row**. That is not a detail: `_distinct_leaves`
feeds `wilson`, `risk_coverage`, `exclusion_funnel` and `review_rate`, so the surviving
row supplies the **numerator**, not merely the count.

**Why the obvious fix is a trap.** #25's review prescribed "a deterministic (not
first-seen) collapse rule". Taken literally — sort and keep the first — the variants sort
`correct` < `partial` < `wrong`, so every leaf would be represented by its **correct**
variant and measured accuracy would approach 100% by construction. That pairs an honest
denominator with a dishonest numerator, which is worse than the inert collapse it
replaces, because it looks rigorous. The programme already has a name for this shape
(D18, §2): a number that improves because of how it was counted.

**Decision.** A leaf's outcome is **derived from all of its variant records, never
sampled from them**. For the binary analyses, a distinct leaf counts as `correct` iff
**every** scored record for that leaf is `correct`; otherwise it counts as not-correct.
Properties that make this the defensible default: it is order-independent and
deterministic; it consumes all 68 records rather than discarding 40; it cannot be gamed
by sort order; and it errs **conservative** — it can only lower a reported accuracy,
never flatter it (§14).

**The alternative, recorded rather than silently discarded.** The textbook treatment of
clustered binary data is a design-effect correction: the point estimate uses all 68
records, while the interval's `n` is the 28 independent leaves. That preserves more
information than unanimity does and is arguably the more accurate estimator. It is
**not** adopted here because it changes `wilson`'s contract rather than its input, and
because M1's gate is non-regression (§2), where the conservative direction is the safe
one. If the human prefers the design-effect form, it supersedes this record and #25's
analyses change shape.

**Scope.** Applies to `wilson`, `review_rate` and any future leaf-level binary analysis.
`ablation_2x2` and `mcnemar` collapse per arm via `_distinct_leaves_by_arm` and take the
same unanimity rule within each arm. `exclusion_funnel` counts leaves and is unaffected
by the outcome rule.

Flagged to the human on #25 and the accuracy topic, because it moves every published
accuracy figure and the spec genuinely does not decide it.

## DA6a — Amendment: the DA6 scope sentence about `exclusion_funnel` was wrong (#25)

**The error.** DA6's Scope paragraph above states "`exclusion_funnel` counts leaves and
is unaffected by the outcome rule." That sentence is **false as implemented**, and this
record does not silently rewrite it — DA6 stays as written above for the historical
record, and this amendment supersedes only that one clause.

**Why it was wrong.** DA6's Scope sentence assumed `exclusion_funnel`'s leaf set and
`wilson`'s leaf set were built the same way. They were not. `wilson`, `review_rate` and
`risk_coverage` all call `_scored()` — which drops `excluded` records — **before**
collapsing to distinct leaves via `_distinct_leaves`. `exclusion_funnel` collapsed to
distinct leaves directly, with no `_scored()` prefilter, because its whole job is to
report the excluded count that `_scored()` elsewhere throws away. That difference is
exactly where DA6's unanimity rule bites: take a leaf with two fixture-variant records,
one `excluded` (that variant's extraction failed) and one `correct` (the other variant
was scored correct). `wilson` drops the `excluded` record via `_scored()` first, so the
surviving single `correct` record makes the leaf count as scored-and-correct. But
`exclusion_funnel`, collapsing both records together, applies DA6 unanimity over "all of
the leaf's records" as written — not all `correct`, so it picks a non-`correct`
representative, which here is the `excluded` record, so the SAME leaf is reported as
excluded by the funnel. The funnel — which exists to *explain* `wilson`'s denominator —
could disagree with the denominator it was supposed to justify. Spec §9 gate 7 requires
every reported rate to name its denominator and its exclusions; a funnel that can
contradict the number it exists to explain fails that gate by construction.

**Decision.** A leaf is `excluded` in `exclusion_funnel` iff **every** record for that
leaf is `excluded` — i.e. the leaf has no scored record at all. If any record for the
leaf was scored, the leaf is scored, not excluded: one variant's extraction failing is
not evidence the question was never attempted, when another variant proves it was
(spec §3.3's outcome-semantics table defines `excluded` as "never attempted"). For a
scored leaf, the outcome is still derived by DA6 unanimity, but over its **scored**
records only — `excluded` records are discarded first and never allowed to make an
otherwise-scored leaf non-correct, because an `excluded` record carries no marking-
accuracy evidence; letting it poison the outcome would understate accuracy for a reason
unrelated to marking, which is a different-shaped dishonest numerator than the one DA6
was written to prevent.

**The checkable invariant.** `exclusion_funnel`'s scored-leaf count must equal the `n`
that `wilson` reports on the same records. This is pinned by a regression test over the
real `tests/golden` corpus (`tests/eval/test_analyses.py`,
`test_exclusion_funnel_scored_count_matches_wilson_n`), not synthetic rows, so the two
can never silently drift apart again.

**Scope (superseding DA6's).** `exclusion_funnel` now collapses leaves via a
scored-aware variant of the DA6 rule (`_distinct_leaves_scored_aware` /
`_collapse_leaf_group_scored_aware` in `lemely/eval/analyses.py`), not the plain
`_distinct_leaves`/`_collapse_leaf_group` that `wilson` and `review_rate` use on their
already-`_scored()`-filtered input. `risk_coverage` was checked against the same
question and does **not** have this bug: it filters `_scored()` before collapsing,
exactly like `wilson` and `review_rate`, so it needs no change.

Flagged to the human on #25 and the accuracy topic, alongside DA6, because it corrects a
claim in that same record.

## DA6b — Amendment: DA6's corpus counts (68 rows / 28 leaves) are pre-#32 (#32, M0.8)

**What changed.** DA6 above records "the 10 golden case dirs hold 68 answer rows, and
stripping the `_correct`/`_partial`/`_wrong` suffix yields exactly 7+6+8+7 = **28**
distinct `(paper, question)` leaves". That was verified and true when written. M0.8
(#32) added an 11th case dir, `tests/golden/0625_w21_qp_32_theory_nested`, which carries
three leaves (`1a_i`, `1a_ii`, `1b`) and has no `_correct`/`_partial`/`_wrong` variants
to collapse. DA6's sentence is **not** rewritten — it stays as the historical record;
this amendment supersedes only its two numbers.

**The current counts, re-verified against the corpus this run:** 11 case dirs hold
**71** answer rows, collapsing to 7+6+8+7+3 = **31** distinct `(paper, question)`
leaves. Anything citing 68/28 as *current* is stale; 68/28 remains correct as the
pre-#32 baseline.

**Why this is bookkeeping, not a change of rule.** The unanimity collapse rule DA6
decides is untouched — only the corpus it runs over grew. The numbers are load-bearing
anyway, because `n=31` is the denominator every Wilson interval and power calculation
in M0.6 is quoted on, and the `review_rate` denominator moves with it. The two asserts
that pin these counts live in `tests/eval/test_analyses.py`
(`test_wilson_n_is_31_distinct_leaves` and
`test_exclusion_funnel_scored_count_matches_wilson_n`), so a future fixture addition
that moves them again fails the suite by name rather than drifting silently.

**Note on `review_rate`.** The 19.1% figure in `BUILD/ACCURACY-STATE.md` was measured on
the pre-#32 corpus and is therefore quoted on the old denominator. It is left as-is here
rather than recomputed, because M0.9's ratchet (#33) is unarmed and §2 forbids any
baseline run until M0.8 merges — the first post-#32 measurement re-establishes it.

## DA-M0.9 — #33's real `review_rate` baseline diverges hugely from the pre-#32 figure DA6b left in place

**What was measured.** A single `lemely measure-accuracy` dev-split sweep (default split,
`gemini-2.5-flash`, prompt versions extraction=5/correction=4/mark_scheme=3) was run against
the current 11-case-dir / 31-distinct-leaf golden corpus (DA6b), through the accuracy-measure
costed-preflight workflow, at commit `f7be062`. Cost: **$0.0642** (74 Gemini calls, summed
from the run's `gemini_call` log events), well under both the per-run token ceiling
(2,000,000) and the `$25` total USD ceiling already configured. Result saved to
`tests/golden/results/2026-08-22-f7be062.json` (gitignored; a summary is committed at
`BUILD/review-rate-baseline.json` since the gate and CI need something durable to read).

**The funnel (do not skip a stage).** 71 raw question-level answer rows collapse (DA6) to 31
distinct `(paper_id, question_id)` leaves. Of the 71 raw rows, 12 carry a non-empty `triggers`
list. Those 12 flagged rows land on only 9 distinct leaves (some leaves have more than one
flagged fixture-variant record). That gives three legitimately different candidate numbers,
and none of them is unambiguously "the" review rate for a corpus that mixes synthetic
correct/partial/wrong fixture variants per leaf — this decision states which was chosen and
why, not that it is uniquely correct:

| candidate | formula | value | what it answers |
|---|---|---|---|
| row-level | 12 flagged rows / 71 rows | **16.9%** | "of every row we ever wrote a mark against, how many were flagged" — inflated by leaves with multiple fixture-variant rows, and not what `review_rate()`'s contract (question-level, distinct-leaf) promises |
| leaf-union (**chosen**) | 9 flagged leaves / 31 leaves | **29.03%** | "of every distinct question a student answered, was ANY record of it flagged" — matches `review_rate()`'s stated denominator (DA6 distinct leaves) with a numerator that doesn't silently drop trigger evidence living on a sibling fixture-variant record |
| representative-only (superseded, was the pre-fix bug) | 1 flagged representative leaf / 31 leaves | **3.23%** | an artifact of reading `triggers` off the single DA6-collapsed representative row `min()` happens to pick — see below |

**Why representative-only (3.23%) was wrong, not just different.** The original #33 landing
(`f7be062`) computed `review_rate()`'s numerator by reading `triggers` off the same
DA6-collapsed representative row `_distinct_leaves()` already produces for the denominator.
DA6's representative-picker is free to choose ANY record among a leaf's unanimously-`correct`
fixture variants — so whenever a leaf's variants were all `correct`, whichever variant `min()`
happened to pick decided whether that leaf's trigger was visible to the gate at all. 8 of the
9 actually-flagged leaves in this corpus were invisible to `review_rate()` under that logic —
not a rounding difference, a **~9x undercount** (3.23% vs the real 29.03%) that was previously,
and wrongly, described here as "the real, current, correctly-denominatored number" and "6x
smaller than the stale 19.1% figure." Both of those claims are retracted: the 3.23% figure was
never correctly denominatored, and comparing it favourably to the pre-#32 19.1% row-level
figure compared a broken numerator to a different corpus on a different basis — neither
comparison told us anything about review burden. `review_rate()` (`lemely/eval/analyses.py`)
now unions `triggers` across a leaf's raw records before collapsing, so the numerator can no
longer depend on which record the DA6 collapse happens to keep as representative; see
`test_counts_leaf_via_trigger_union_not_representative` in `tests/eval/test_analyses.py`.

**The pre-#32 19.1% figure is separately stale.** `BUILD/ACCURACY-STATE.md` and the #33 issue
body both quoted 19.1% (13 of 68 rows, Wilson [11.5%, 30.0%]) as the "starting" review rate.
That number predates #25/M0.1's `review_rate()` implementation entirely and was computed on
the pre-#32 68-row/28-leaf corpus — it is not comparable to any of the three candidates above,
which all use the current 71-row/31-leaf corpus. Anything citing 19.1%/13-of-68/Wilson-[11.5%,
30.0%] as the *current* baseline is stale as of this decision, independent of the
representative-vs-union numerator question.

**What was chosen and why.** `review_rate_last_merged = 0.2903` (leaf-union, truncated down
from 0.29032258... so the ratchet ceiling only ever tightens) — because it is the number
`review_rate()`'s own documented contract (question-level, distinct-leaf) actually produces
once the numerator bug is fixed, and because using row-level (16.9%) would double-count leaves
with multiple flagged fixture variants against a denominator that has already collapsed them.
The **honest caveat**: this corpus mixes synthetic correct/partial/wrong fixture variants per
leaf specifically to exercise DA6's collapse logic, so its flagged-leaf rate is a property of
the fixture design as much as of the underlying marking behaviour — treat 29.03% as this
golden corpus's *measured* baseline for the ratchet to tighten from, not as a claim about the
review burden of a real deployment.

**`per_paper_p95` moves too.** Under the union numerator, `per_paper_p95` is **83.33%**
(up from the representative-only run's 16.67%), because several papers now correctly show more
than one reviewed leaf once sibling fixture-variant triggers are counted. It breaches the 15%
target by a wide margin. Exactly as before, the gate (`lemely/eval/review_gate.py`) records
this breach in `breaches` on every run; because the ratchet starts **unarmed**
(`review_rate_ratchet_armed=false`), it does not fail `measure-accuracy` or CI today, but it is
not silently dropped — it prints, and `scripts/check_review_rate_gate.py`'s output still lists
it as a named breach.

**Storage location.** `last_merged_review_rate` lives on `AccuracyEvalSettings` (mirroring
every other accuracy-eval target: `mark_accuracy_target` et al.), not a dedicated JSON file or
an overload of `BUILD/ACCURACY-STATE.md`'s free-text `ratchet` field — that field is updated
too, but only as the human-readable mirror `scripts/accuracy_board.py` already treats
`ACCURACY-STATE.md`'s header as (see that file's own "Contract" section: GitHub-adjacent
tracker state does not duplicate there, but this is measurement state the supervisor's grep
needs at a glance). The gate's actual source of truth is `lemely.toml`
(`[accuracy_eval] review_rate_last_merged = 0.2903`, default baked into
`AccuracyEvalSettings.review_rate_last_merged`) and the committed
`BUILD/review-rate-baseline.json` artifact `scripts/check_review_rate_gate.py`/CI fall back to
when no fresh `tests/golden/results/*.json` exists (that directory is gitignored); that
artifact now also carries `run_id`/`corpus_digest` provenance so a locally-preferred fresh run
that diverges from the committed baseline's corpus prints a warning instead of silently gating
on different data (`scripts/check_review_rate_gate.py`'s `_baseline_provenance`).

**M0-unarmed / M1-armed semantics.** `review_rate_ratchet_armed` defaults to `false`. Unarmed,
`evaluate_review_rate_gate()` still computes and reports every limb's pass/fail and the
ratchet direction, but `blocking_failure` is forced `False` regardless of breaches — the run
is observed, not gated, which is why this real (breaching-on-p95) baseline can be recorded and
merged today without contradicting "never weaken a gate to get green." Arming
(`review_rate_ratchet_armed = true`) is spec §7's M1 acceptance step, gated on M0.9 landing
first (`M0.9 | M1.1`), and is out of scope for #33 itself.
## DA7 — The McNemar n-floor: why `MCNEMAR_IMPROVEMENT_N_FLOOR = 219` is quoted, not recomputed (#30, M0.6)

**The requirement.** Spec §6: "paired McNemar can prove an improvement to 88.8% with
n=219 where unpaired needs 741 per arm" — the sample size to detect an improvement from
the 83.8% legacy baseline to an 88.8% target at alpha=0.05, power=0.80. Spec §4 M0.6: "a
metric below its n-floor prints as underpowered rather than as a number." Neither passage
states the formula or the discordant-pair-rate assumption behind 219; it is given as a
fact, not derived in the spec text.

**Why 219 is quoted, not recomputed from first principles.** The paired-proportion
(McNemar) sample-size formula (Connor 1987 / Fleiss) needs the *discordant-pair
proportion* between the two arms — how often `oracle+mark` and `extract+mark` disagree on
the same leaf — not just the two marginal accuracy rates (83.8%, 88.8%). That rate is an
empirical property of how correlated the two arms' scoring is; this codebase has no
measurement of it yet (the golden corpus is 31 leaves, nowhere near paired-McNemar scale).
Reverse-engineering a discordant-pair-rate parameter that makes the formula spit out
exactly 219 would be curve-fitting a number to match a target, which is precisely the kind
of invented measurement the programme forbids elsewhere (§2, D18-adjacent). So
`MCNEMAR_IMPROVEMENT_N_FLOOR = 219` in `lemely/eval/analyses.py` is taken **directly from
spec §6**, not computed. The constant is named `..._IMPROVEMENT_N_FLOOR`, not `..._N_FLOOR`
— see the orchestrator's adjudication below for why that distinction is load-bearing.

**What is computed: an independently-checkable lower bound.** `paired_proportion_min_n`
implements the Connor/Fleiss favourable-case bound — the discordant-pair proportion `psi`
set to its minimum possible value `psi = d = |p2 - p1|` (the case where every discordant
pair moves in the `p1 -> p2` direction and none reverse, the smallest paired sample any
real correlation structure could need for this effect size):

```
n = ceil((z_alpha*sqrt(d) + z_beta*sqrt(d*(1-d)))**2 / d**2)
```

Evaluated at `paired_proportion_min_n(0.838, 0.888, alpha=0.05, power=0.80)`, this returns
`155`, which is `<= MCNEMAR_IMPROVEMENT_N_FLOOR` (219). That inequality is the checkable
relationship: if the lower bound ever exceeded 219, `MCNEMAR_IMPROVEMENT_N_FLOOR` would not
actually be power-respecting for this effect size and the constant would need to move.
`_inverse_normal_cdf` (Acklam's rational approximation) turns `alpha`/`power` into z-scores
without a scipy dependency, matching `mcnemar`'s own no-scipy p-value calculation.

*(Correction, this pass.)* The formula previously implemented here divided by `d`, not
`d**2`, and dropped the `sqrt(psi)`/`sqrt(psi - d**2)` weighting entirely — it was not
actually the Connor/Fleiss bound its docstring claimed, just a number that happened to
land under 219 (157, by coincidence of the missing terms roughly cancelling at this `d`).
That has been fixed to the formula above (now pinned at 155 by
`test_paired_proportion_min_n_pinned_value_and_monotonicity`, plus a monotonicity check:
larger effect size -> smaller n, higher power -> larger n), so the docstring's "lower
bound" claim is now true rather than merely plausible.

**Orchestrator adjudication: `chi2`/`p_value` are always computed, never `None`.** The
first pass of this issue made `mcnemar()` return `chi2: float | None` / `p_value: float |
None`, both `None` whenever `underpowered` — i.e. the floor gated the *computation*, not
just the *presentation*, of the statistic. That conflates two different things: (1) whether
a paired comparison has enough pairs to trust as an IMPROVEMENT CLAIM against the spec §6
target (83.8% -> 88.8%), which is what `MCNEMAR_IMPROVEMENT_N_FLOOR` actually measures, and
(2) whether the chi-square/p-value arithmetic is well-defined, which it is at any `n_pairs
>= 1` (and trivially at `b + c == 0`, where `chi2 = 0.0`, `p_value = 1.0`). Nulling the
numeric fields below the floor makes `mcnemar()` unusable for anything BUT the one
spec-§6-shaped improvement claim — a caller doing its own ablation breakdown, or plotting
the discordant-pair counts, gets `None` for no statistical reason. The fix: `mcnemar()`
always returns real floats for `chi2`/`p_value`; `underpowered` stays exactly as before
(`n_pairs < MCNEMAR_IMPROVEMENT_N_FLOOR`, reading the same `_distinct_leaves_by_arm`-derived
`n_pairs`, never a hardcoded leaf count). The refusal to present the number as an
improvement claim now lives in exactly one place — the new, pure reporting-layer function
`mcnemar_improvement_p_value(result) -> float | Literal["underpowered"]` — rather than
inside the statistic's own computation. `wilson()` is untouched: spec §3.3 says Wilson
intervals are reported on every rate, and its own width is the honesty signal — Wilson has
no refusal behaviour, only the McNemar improvement claim does.

**Tests.** `tests/eval/test_analyses.py::TestNFloor` — the real ~31-leaf golden corpus
(well under 219) is asserted `underpowered` AND to carry real `chi2`/`p_value` floats, with
`b`/`c` pinned to their actual golden-corpus values (`b=31`, `c=0`); synthetic paired data
at exactly `MCNEMAR_IMPROVEMENT_N_FLOOR` returns a numeric, non-underpowered result (proving
the branch is real, not vacuous); a pinned-value-plus-monotonicity test proves
`paired_proportion_min_n` actually implements the bound its docstring claims, not just
`0 < n <= 219`. `TestReportingLayer` exercises `mcnemar_improvement_p_value` directly, one
test per branch (underpowered -> `"underpowered"`; powered -> the numeric `p_value`
unchanged). `test_mcnemar_signature_rejects_unpaired_rate_summaries` uses
`inspect.signature(mcnemar)` to pin the sole parameter as `records: list[EvalRecord]` (AC1
— no code path accepts two independent rate summaries and returns a p-value).
`TestWilson::test_diverges_from_clamped_normal_approximation` pins Wilson's bound at n=10,
100% correct (lower=0.7225) against a clamped normal approximation that degenerates to
`[1.0, 1.0]` at the same input, so the suite actually falsifies "clamped normal
approximation" rather than merely being satisfiable by one. The pre-existing
`test_leaf_count_is_derived_not_hardcoded` (raw-rows-vs-leaves) was removed: it duplicated
`TestMcnemar::test_collapses_duplicate_question_level_rows_to_one_leaf` and the DA6/DA6b
golden-corpus tests below with no content specific to the n-floor, and it only ever failed
pre-fix via the module-level `ImportError` from the renamed constant, not a real behavioural
difference. Two pre-existing `TestMcnemar` tests
(`test_discordant_pairs_produce_nonzero_statistic`,
`test_no_discordant_pairs_gives_zero_statistic`) remain padded with concordant filler pairs
to reach the floor, since they exist to test the chi2/p-value math on a non-underpowered
result.
## DA8 — M0.5: D18 fixed (honest denominators), and the two figures this supersedes (#29)

**The bug (D18).** `measure_accuracy()`'s per-case loop iterated
`correction.questions` and `continue`d past any question the extractor never returned
an answer for (`harness.py:596`, pre-#29). That question was dropped from the run
entirely — no `EvalRecord`, no denominator entry, nothing but a footnote in
`id_match_rate`. A run that extracted FEWER answers therefore scored on a SMALLER,
self-selected denominator, and could score *higher* than a run that extracted more —
the fewer-answers-cannot-score-higher regression test
(`test_fewer_extracted_questions_cannot_score_higher`,
`tests/test_accuracy_harness.py`) reproduces this: pre-fix, a run returning one correct
answer out of three scored 1.0, strictly above a run returning all three (one wrong)
scoring 0.667.

**The fix.** The loop now iterates `case.ground_truth` — every ground-truth leaf the
case attempted — not `correction.questions`. Each leaf produces exactly one
`EvalRecord`: `correct`/`over`/`under` when `correct_paper` marked it and the extractor
returned an id for it; `unmatched` (`predicted_marks=None`, stays in the denominator,
never counted as correct) when `correct_paper` marked it but the extractor did not
return it; `excluded` (dropped from `_scored()`/`wilson`/`review_rate` via the existing
DA6a-aware machinery in `lemely/eval/analyses.py` — no change there was needed) only
when `correct_paper` produced no `CorrectedQuestion` for the leaf at all, e.g. a
ground-truth id that names no leaf in the mark scheme. A five-stage exclusion funnel
(`leaves -> extracted -> matched -> marked -> scored`) is now tracked in
`measure_accuracy()` (`FunnelCounts`) and printed by `format_report()`, with `scored`
read from `analyses.exclusion_funnel()` — the single source of truth — rather than
recomputed.

**Two figures, not one.** The historical **83.8%** (`docs/ACCURACY-STRATEGIES.md`,
D2.5, 10-fixture corpus, n=68 rows) predates this fix and multiple corpus additions
(DA6b); it is recorded here as **legacy** and is the number §6's paired-McNemar floor
(n=219, DA1) is quoted on — that floor is *not* recomputed here, per the accepted
#29 risk note; recomputing it against a new baseline is separate work.

The **honest baseline**, re-run over the current 11-case, 71-row / 31-leaf golden
corpus (DA6b) with the D18 fix in place (`run_id=run-ef443fc2931e`,
`corpus_digest=e982c884f7f30cd7`, saved to
`tests/golden/results/2026-08-22-79f5fa8.json`):

- `measure_accuracy()`'s own `AccuracyMetrics.mark_accuracy` (raw per-row, no DA6
  fixture-variant collapse): **90.1%** (64/71 rows correct — unchanged in value from
  the pre-#29 run recorded the same day, because this corpus's `id_match_rate` is
  100%: no leaf in it currently exercises the `unmatched` or `excluded` path, per the
  #29 risk note. D18 protects future runs where extraction misses ids; it is not a
  retroactive correction of this corpus's number).
- `analyses.wilson()` over the same `eval_records`, DA6-collapsed to distinct
  `(paper_id, question_id)` leaves: **77.4%** (24/31 leaves; 95% Wilson
  [60.2%, 88.6%]). This is materially lower than the raw 90.1% because DA6 unanimity
  requires every fixture variant of a leaf to be correct for the leaf to count as
  correct, and several leaves in this corpus have a `wrong`-variant miss.

Both numbers are published, not just the flattering one — hiding the DA6-collapsed
77.4% behind the raw 90.1% would recreate exactly the denominator-shell-game D18 was
about. **The honest baseline going forward is the pair (90.1% raw n=71 /
77.4% DA6-collapsed n=31), not the legacy 83.8%**; no code path in this change presents
83.8% as current.

**Open governance item: spend for `run-ef443fc2931e` is unmeasured, not zero.**
The re-run used `manifest.cache_mode="read_write"` (a real, billable sweep, not a
cache-only replay), but the saved manifest (`tests/golden/results/2026-08-22-79f5fa8.json`,
gitignored) carries no cost field — `RunManifest` does not record spend at all. Checking
`lemely/io/cost_ledger.py`: `CostLedger` persists only a single cumulative-USD counter
across the whole process/machine lifetime (no per-run breakdown, no ledger JSON file
present on this checkout), so there is no before/after snapshot to diff and recover this
run's actual cost from. Recording it as **0.4026** (per this issue's plan text) would be
assuming the ledger's cumulative figure at some other point in time is this run's cost,
which it is not shown to be — that number is not adopted here. The correct statement is:
this run's `spend_usd` is **unmeasured**. A future fix should add a per-run cost field to
`RunManifest` (populated from the ledger delta around the run) so this stops recurring.

**The other two headline metrics moved too, and downward.** The first #29 pass
qualified `mark_accuracy`'s legacy 83.8% as historical and published the honest
90.1% beside it — but left `flag_recall` (27.3%) and `flag_precision_high`
(91.7%) stated in the present tense, unqualified, in `DELIVERY.md`,
`CHANGELOG.md` and `docs/ACCURACY-STRATEGIES.md`. The same honest run
(`run-ef443fc2931e`) reports **`flag_recall` 14.29%** and
**`flag_precision_high` 89.8%**.

So the only metric that received the "historical, superseded" treatment was the
one that moved in the *flattering* direction, while the two that moved
unfavourably kept their better-looking legacy numbers. That is selective
disclosure, and it is the same family of defect as D18 — the failure this very
issue exists to fix — so it is recorded here rather than quietly corrected. All
three metrics now carry the qualifier and the honest figure in all three files.

**Open, non-blocking risk: two funnel implementations.** `FunnelCounts` in
`lemely/accuracy/harness.py` was added rather than extending
`lemely/eval/analyses.py::exclusion_funnel()`, contrary to this issue's
binding note. They do not currently disagree (`scored` is read from
`analyses.exclusion_funnel()`), but nothing enforces that, and `funnel` is not
serialised by `save_result()`, so `extracted` is **not recoverable from a saved
run**. Unify them before the funnel is used as published evidence.

`extracted` is also **not a nested stage** of the funnel: it counts leaves the
extractor returned an id for, while `matched` counts leaves `correct_paper`
produced a `CorrectedQuestion` for. Neither implies the other, so printing them
in sequence could emit a chain that *rises* (e.g. `extracted=2 -> matched=3`),
reading as a denominator growing mid-funnel. The printed chain is now
`leaves -> matched -> marked -> scored`, with `extracted` reported separately
and pinned by `test_printed_funnel_chain_never_rises`.

**Provenance correction.** DA8 describes the honest-baseline artifact as
produced "with the D18 fix in place", but its manifest records
`git_sha=79f5fa8`, which is the **pre-fix** commit (the fix landed in
`761231c`). The figures reproduce exactly (`mark_accuracy` 0.90140845; Wilson
n=31, 77.4% [60.2%, 88.6%]) because this corpus contains no `unmatched` or
`excluded` rows at all — the D18 path is simply never exercised by it. The
number is therefore correct, but it is **not evidence that the fix works**;
the behavioural tests are.

**Numbering note (2026-08-23).** This entry was authored as `DA7` on the #29
branch while #30 independently authored a different `DA7` (the McNemar n-floor)
on a branch cut in parallel. #30 landed first, so it keeps `DA7` and this entry
was renumbered to `DA8` at merge time. References in `CHANGELOG.md`,
`DELIVERY.md` and `docs/ACCURACY-STRATEGIES.md` were updated with it; the `DA7`
citation in `lemely/eval/analyses.py` points at #30's entry and is unchanged.

---

## DA9 — The A/A churn floor: 11.6% of leaf outcomes flip at constant configuration (#27, M0.3)

**The measurement.** Ten repeats of the full golden set at byte-identical
configuration, cache bypassed (`--cache-mode bypass`, the #77 seam), run
2026-08-23 as `aa-floor-2026-08-23-a` over git sha `b364bf76`, model
`gemini-2.5-flash`, split `dev (pre-M0.7a)`. Raw evidence is committed under
`BUILD/accuracy-runs/aa-floor-2026-08-23-a/` — ten `records-repeat-NN.jsonl`
files of 71 `EvalRecord` rows each (710 rows), ten per-repeat manifests, and a
run manifest recording `cache_hit_detected=false` on every repeat across ~740
real API calls. Cost $0.958711 at corrected GA pricing (1,186,229 in /
241,137 out; `thoughts_token_count` was 0 on every call), against a $1.58
preflight estimate.

**The floor.** Collapsing each repeat to distinct `(paper_id, question_id)`
leaves with the production DA6 rule (`_group_by_leaf` /
`_collapse_leaf_group`) gives 31 leaves per repeat, an identical leaf set
every time. Over all C(10,2) = 45 repeat-pairs:

| figure | value |
|---|---|
| **pairwise leaf-outcome churn** | **11.61%** (162 / 1395 pair-leaf comparisons) |
| per-pair spread | 0.0% – 19.35% |
| leaves that ever churned | 9 of 31, 95% Wilson **[16.1%, 46.6%]** |
| `det` parse path | **0.0%** (0 / 360) |
| `gemini` parse path | **15.65%** (162 / 1035) |

**No Wilson interval is quoted on 162/1395.** The 45 pairs re-use the same 10
runs, so those comparisons are not independent and a binomial interval over
them would be fiction. The honest spread on that statistic is the per-pair
range, 0.0%–19.35%. The Wilson interval above is quoted on the one figure that
*is* a clean binomial: 9 of 31 independent leaves ever churning.

**All churn is on the gemini path; the det path is exactly deterministic.**
0 of 360 det pair-leaf comparisons differed. That is a floor of 0.0 on the det
path measured at n=360, not an assumption — and it means an A/B that moves only
det-path behaviour is not subject to this floor. Quote the path-specific floor,
not the pooled 11.6%, whenever an arm touches only one path.

**The rule this establishes (acceptance box 4).** Any A/B delta on the gemini
path smaller than **11.6 percentage points** is **within noise** and must be
reported as noise — not as a small improvement, not as a trend, not as
directionally encouraging. The det-path floor is 0.0%. This applies to every
later comparison in the programme, and it is the floor §2 of the mission
requires exist before any A/B claim is interpretable.

**What this run is NOT.** Single-arm, so it shows no A/B effect of any kind.
n=31 leaves against the n=219 paired-McNemar floor (DA7), so it could not carry
an improvement claim even if it had two arms. Split is `dev (pre-M0.7a)`, i.e.
the membership is not yet frozen (#57 waits on #44). Nothing here licenses an
accuracy claim.

### DA9a — Two published single-run figures are now shown to be draws from a wide distribution

This run re-measures, ten times, two numbers the programme had published from a
**single run each**. Both survive, but neither is as sharp as one run made it look.

**DA8's honest baseline (77.4%, 24/31 leaves).** Pooled over ten repeats the
leaf accuracy is **75.8%** (235/310), per-repeat range **67.7% – 80.6%**,
stdev 3.5pp. DA8's 24/31 is the *modal* draw — it came up 5 times in 10 — so it
is representative rather than lucky, and DA8 is **not** retracted. But a single
run of this corpus reports a number carrying roughly a 13pp spread, and the
per-repeat Wilson intervals at n=31 are ~0.50–0.91 wide. **This corpus cannot
resolve anything finer than about 10pp**, before the churn floor is even applied.
Quote 75.8% (235/310) as the better-estimated figure from here on, and cite DA8's
24/31 as the single-run draw it is.

**DA-M0.9's `review_rate` (29.03%).** Recomputed live with the production
`lemely.eval.analyses.review_rate` on all ten records files: mean
`review_rate_total` = **32.58%**, per-repeat **29.03% – 41.94%**; `signal` and
`total` are identical here because no `random_audit` trigger fired. Per-paper
p95 averages 82.1% (range 66.7%–85.7%).

**This is the fresh live sweep on post-#29 denominators that the resume pointer
said M0.9 needed, and it changes the picture materially.** The committed
constant is 29.03% (`lemely/runtime/config.py:168`,
`BUILD/review-rate-baseline.json`) — and 29.03% is **the bottom of the observed
range**, the value that came up on the 3 luckiest of 10 repeats. It is not a
central estimate; it is a best case.

**Consequence for arming the M0.9 ratchet (binding on #36).** Arming
`min(10%, last_merged_review_rate)` against 29.03% would gate the build on a
figure that identical-config re-runs exceed **7 times in 10**, with no code
change whatsoever. That is a gate that fails on noise, and the failure would be
blamed on whatever diff happened to be in flight. Before the ratchet is armed,
`last_merged_review_rate` must be restated as a distribution-aware figure — the
mean 32.58%, or an upper bound over the observed range — not the single lucky
draw. This *raises* the recorded number, which looks like weakening the gate and
is the opposite: it stops the gate firing at random. Both limbs are breached in
every one of the ten repeats regardless (ceiling is `min(10%, 29.03%)` = 10%;
p95 target 15% against an observed ~82%), so the breach itself is not in doubt
and stays recorded-not-blocking while the ratchet is unarmed at M0.

**Not fixed here.** This entry does not touch `config.py`,
`BUILD/review-rate-baseline.json`, or `scripts/check_review_rate_gate.py`.
#27 is a measurement issue; changing the gate's constant is #36's work, and
doing it inside a measurement commit would make "did the instrument change
between runs?" unanswerable later. The numbers are handed over on #36.

**Correcting the standing "the gate has zero test coverage" note while we are
here.** That claim, carried in the resume pointer and posted as part of the
M0.9 constraint on #36, is imprecise and overstates the risk:

- The gate's **decision logic**, `lemely.eval.review_gate.
  evaluate_review_rate_gate`, is well covered — 13 tests in
  `tests/eval/test_review_gate.py`, over synthetic `ReviewRateResult` dicts,
  covering both limbs armed and unarmed.
- What is genuinely untested is the **script wrapper**,
  `scripts/check_review_rate_gate.py` — its `main`, `_baseline_provenance` and
  `_load_review_rate_result`. Nothing in `tests/` references it (checked by
  symbol search, not grep over prose).

So the exposure is not "an untested gate". It is that the wrapper reads
`BUILD/review-rate-baseline.json` and a **saved** golden run rather than
recomputing from a live sweep — confirmed by observation, not inference: on
this branch the gate still prints `review_rate 0.2903` while this run's live
records give 29.03%–41.94%. The number the gate judges cannot respond to a code
change. That is the thing #36 must fix before arming, and it is a wiring
problem, not a missing-tests problem.

## DA10 — M1.5: the coherence gate's "reconcile" semantics for empty matched_point_ids and is_alternative/is_optional groups (#40)

M1.5 adds a fourth, confidence-independent review reason to
`_build_ai_corrected` (`lemely/io/correction_ai.py`): the marker's claimed
`matched_point_ids` must (a) all resolve in `question.answer_points` and (b)
reconcile with `awarded_marks`. Several sub-decisions were left unspecified
by the issue and had to be made explicitly rather than defaulted, per
binding constraint #6 on the board comment. **This entry was corrected in a
repair pass** (three review MUST-FIXes) after the original version of
Decision 1 and Decision 3 shipped with defects; both the original text and
the correction are recorded below so the history is honest.

**Decision 1 — no `answer_points` at all, scoped to question TYPE, not to
list emptiness.** The coherence check is skipped entirely — regardless of
`awarded_marks` or `matched_point_ids` — only when
`question.type in {QuestionType.LEVELS_BASED, QuestionType.INDICATIVE_CONTENT,
QuestionType.MCQ}` AND `question.answer_points` is empty. These three types'
marking is not decomposed into discrete points by design, so there is
genuinely nothing to reconcile against. **Every other type** with empty
`answer_points` is a data gap, not an intentional shape, and falls through
to the ordinary dangling-id / empty-matched-list rules below (an empty
`points_by_id` map makes every id in `matched_point_ids` dangling by
definition, so this needs no separate branch in the implementation).

*Original defect (MUST-FIX 2 of the repair pass):* the shipped version
tested `if not question.answer_points: return None` — unconditionally, for
ANY question type — and this check ran BEFORE the dangling-id check. A
question of a non-exempt type (recall, calculation, explanation, diagram,
list, multi_step, …) with an empty `answer_points` list therefore accepted
wholly fabricated `matched_point_ids` plus a non-zero `awarded_marks` with
`needs_teacher_review=False`, silently defeating acceptance bullet 2 ("every
referenced point id must exist in the mark scheme"). *Prevalence, reproduced
against this tree's own corpus* (13 scheme files — 11 `tests/golden/**/
mark_scheme.json` plus 2 `Sources/**/*_ms_*.json` — 152 leaf questions; NOT
the review's unreproducible 799/1410 over 35 schemes, which this repair pass
could not confirm and does not repeat): **53/152 (34.9%)** leaf questions have
empty `answer_points`.

**CORRECTION (2026-08-23).** An earlier revision of this entry claimed "every
one of those 53 is a non-exempt type" and that the exempt set is "disjoint from
the empty-points set", and billed it as reproduced ground truth. **That was
false, and the error originated with the orchestrator, not with the
implementer** — it was asserted from a type histogram taken over *all* leaves
rather than over the empty-`answer_points` subset, and then passed downstream
as if it had been computed. The actual breakdown of the 53, recomputed
directly over that subset: **48 `mcq`, 3 `explanation`, 1 `list`,
1 `multi_step`**. `QuestionType.MCQ` **is** in `_COHERENCE_EXEMPT_TYPES`, so
**48 of the 53 remain exempt** after the repair. The type-scoped exemption
newly covers **5 of 152 leaves (3.3%)**, not 53/152 — the earlier text
overstated the closed gap by roughly 10x.

Narrower still on the evaluation corpus proper: over the 11 golden
`mark_scheme.json` files alone (71 leaves) there are **8** empty-`answer_points`
leaves and **all 8 are `mcq`**, so on that corpus the type-scoped exemption
changes the empty-points population by **nothing**. Its value there is the
dangling-id check on questions that *do* carry `answer_points`, plus the range
rule below — not the empty-points path. The direction of the fix is still
right (an `explanation`/`list`/`multi_step` leaf with empty points no longer
gets a free pass); its measured reach on today's corpus is small, and saying so
is the point of this record.

The corpus also has 7 leaf questions with ≥1 `is_alternative`/`is_optional`
matched point and 6 with >1 (relevant to Decision 3 below).

Also corrects a false citation in the original text: it claimed this
decision "matches `Question.validate_mark_point_sum`'s own guard, which
exempts `LEVELS_BASED`/`INDICATIVE_CONTENT` questions outright." That
function (`lemely/core/loose_schemas.py`) is an INEQUALITY check over
primary (non-alternative/non-optional) points only — it never computes a
`max()` and was never the provenance for a max-based rule; see the
correction to Decision 3 below for the actual defect this false citation
was propping up.

**Decision 2 — `matched_point_ids` empty/absent, but `question.answer_points`
is non-empty (unchanged by the repair pass).**

- `awarded_marks == 0` and `matched_point_ids == []`: **coherent.** Nothing
  was matched, nothing was awarded — this is the ordinary "no credit given"
  case and must not be flagged.
- `awarded_marks > 0` and `matched_point_ids == []`: **incoherent.** Marks
  were awarded with nothing cited to justify them. Flagged with a message
  containing `"matched_point_ids is empty"`. Decision 1's type-scoped
  exemption now extends this same rule to non-exempt types whose
  `answer_points` is ALSO empty — see Decision 1.

**Decision 3 — `is_alternative`/`is_optional` reconciliation is a RANGE, not
a point estimate.** Points flagged `is_alternative` (OR/EITHER…OR) or
`is_optional` (a "any N from" pool) are non-additive by construction
(`AnswerPoint` docstrings, `loose_schemas.py`). `AnswerPoint` carries no
group identifier, so the number of distinct OR-groups among a set of
*matched* non-additive points is unknowable from the data alone:

```
implied_min = sum(marks of matched points where NOT is_alternative and NOT is_optional)
            + max(marks of matched points where is_alternative OR is_optional, default 0)
implied_max = sum(marks of matched points where NOT is_alternative and NOT is_optional)
            + sum(marks of matched points where is_alternative OR is_optional)
```

`awarded_marks` (post-out-of-range-clamp) is coherent iff
`implied_min <= awarded_marks <= implied_max`; only a value OUTSIDE that
interval is flagged, with a message that names the interval (e.g.
`"matched_point_ids implies between 1 and 3 mark(s)"`), never a single
number.

*Original defect (MUST-FIX 1 of the repair pass):* the shipped version used
`implied = sum(primary marks) + max(non_additive marks, default 0)` — a
single GLOBAL `max()` over every matched alternative/optional point,
compared to `awarded_marks` for exact equality. Because a global max cannot
distinguish one OR-group from several (no group id exists), this collapsed
any legitimate "any 3 from 5" award, or two independent OR-groups matched
together, down to "implies 1 mark(s)" and forced `needs_teacher_review` on
correctly-marked questions — a false-positive machine, not a coherence gate.
The false `validate_mark_point_sum` citation in the original Decision 1 text
was covering for this: that function really is an inequality
(`sum(primary) <= question.marks`, no max, no equality requirement), so it
was never evidence that a global-max/exact-equality rule was the right
shape.

**Detection convention for the separate trigger (bullet 4, unchanged by the
repair pass).** Rather than threading a second boolean through
`CorrectedQuestion`/`QuestionResult` end-to-end, every message
`_check_coherence` returns contains the shared constant
`lemely.io.correction_ai.COHERENCE_TRIGGER_MARKER` (`"matched_point_ids"`; no
other review reason in `_build_ai_corrected` — `out_of_range`,
`value_mismatch`, `low_confidence` — uses that phrase), and
`lemely.accuracy.harness._review_triggers` imports that same constant
(repair-pass SHOULD-FIX: previously a bare literal duplicated on the harness
side, so a reworded message could desync the two sides with every test still
green) to append the distinct `"coherence_mismatch"` trigger alongside the
generic `"needs_teacher_review"` one, end-to-end-tested in
`tests/test_accuracy_harness.py::CoherenceTriggerWiringTests`.
`lemely.eval.analyses.coherence_trigger_rate` then reports that trigger's own
DA6-collapse-aware leaf rate, separately from
`review_rate_signal`/`review_rate_total` — it does not touch, arm, or feed
into the M0.9 ratchet (`review_rate_ratchet_armed` stays `False`;
`lemely/runtime/config.py` and `scripts/check_review_rate_gate.py` are
untouched by this issue or its repair pass).

**Bullet 4 (the coherence trigger's own contribution to `review_rate`,
measured and reported separately): UNMET, and the original excuse for
skipping it was false.** The original text claimed "the saved ... EvalRecord
JSONL does not carry `matched_point_ids`... so this gate's real-corpus
contribution to review volume cannot be measured from on-disk data" and
implied no cached data existed to try. That is false: `.lemely-cache/gemini/`
holds 212 cached Gemini payloads, of which **181 are `AIMarkResponse`-shaped
(carry `matched_point_ids` and `awarded_marks`)** — verified by inspecting
every file's keys in this repair pass, not assumed. The repair pass
genuinely attempted the join. It fails for a different, real reason:

- Every cached payload is bare — the 181 `AIMarkResponse` files' only keys
  are `matched_point_ids`, `awarded_marks`, `feedback`, `confidence`. There
  is no `question_id`, paper id, or any other field linking a cached mark
  back to the `Question`/`answer_points` it was computed against.
- The cache filename is the hex digest of `_cache_key()`
  (`lemely/io/gemini.py`), a hash of the model, full system+user prompt
  text, prompt version, file paths, and a params fingerprint — opaque and
  not reversible to a question id without reconstructing the exact prompt
  that produced it.
- There is no manifest or index file anywhere under `.lemely-cache/`
  mapping cache keys back to question/paper identity (checked: none
  present).
- The only way to recover the linkage is to recompute `_cache_key()` for
  every candidate `(question, extracted answer, prompt version, model,
  params)` in the corpus and check which hashes exist on disk — i.e. replay
  the correction step across the dev-split corpus. `generate_structured`
  (`lemely/io/gemini.py:305-365`) has exactly three `cache_mode` values —
  `"read_write"`, `"bypass"`, `"refresh"` — and NONE of them is a
  cache-hit-only mode that skips or errors cleanly on a miss instead of
  falling through to `_check_cost_ceiling()` and a live paid call. Building
  and running such a replay would either require a production code change
  to `gemini.py` (out of scope for #40 and its repair pass, and itself a
  change that would need its own review) or risk exactly the live spend this
  repair pass is barred from (hard constraint: "No live sweep, no spend").

So the true obstacle is not "the data is absent" — 181 relevant cache
entries exist — it is that **the cache carries no question-identity linkage,
and the client offers no zero-spend way to recover one.** `coherence_trigger_rate`
remains implemented and unit-tested; its number against the real dev-split
corpus remains an open measurement gap. Closing it for real requires either
a `gemini.py` change adding a cache-hit-only replay mode (a separate,
reviewable piece of work) or plumbing `matched_point_ids` through to
`EvalRecord` going forward so future sweeps carry the linkage from the
start — neither was in scope for this repair pass.
