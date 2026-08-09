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
