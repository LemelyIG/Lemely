# Blockers

One section per blocker. Never delete a section — resolved ones get a
`RESOLVED` line so the history stays readable.

---

## B1 — Real past-paper accuracy fixtures: the official mark schemes are not present

**Raised:** 2026-08-07 · **Status:** **RESOLVED 2026-08-07** — see the resolution
note at the end of this section.
**Source:** `BUILD/INBOX.md`, "Real past-paper accuracy fixtures" — item **6**
explicitly anticipated this case and prescribed this exact response.

### What was asked

Run two genuine solved scripts through the full ingest → OCR → mark → grade
path and assert the predicted total against the known ground-truth totals:

| Fixture | Paper | Ground truth |
|---|---|---|
| `tests/fixtures/real-papers/0625_s23_qp_22-(34..40).pdf` | 0625 June 2023, Paper 2 Variant 2 (multiple choice) | 34/40 |
| `tests/fixtures/real-papers/0625_w24_qp_41-(66..80).pdf` | 0625 Nov 2024, Paper 4 Variant 1 (theory, method marks) | 66/80 |

### Why it is blocked

**The matching official mark schemes — `0625_s23_ms_22` and `0625_w24_ms_41` —
are not in the repo, and there is no code path that could obtain them.**
Marking cannot begin without them: the marks come *from* the scheme.

Verified, not assumed:

1. The entire local 0625 scheme corpus is `Sources/Physics/MarkingSchemes/`:
   `0625_s19_ms_43`, `0625_s20_ms_31`, `0625_m20_ms_12`, `0625_m21_ms_62`.
   **Neither required session/variant is among them** — no s23, no w24.
2. `outputs/schemes/` (the parsed-scheme cache `resolve_mark_scheme` searches)
   exists and is **empty**.
3. `lemely/web/routers/student.py::resolve_mark_scheme` (line 588) has exactly
   two sources — a `mark_scheme.pdf` uploaded *as a sibling of the scan*, or a
   pre-parsed scheme JSON in `outputs/schemes/` matching the detected metadata.
   **There is no remote fetch/download path for mark schemes anywhere in the
   codebase.** (Phase 2's scraper covers *grade boundaries* from
   cambridgeinternational.org, not mark schemes — a different artifact.)

Note this blocks **both** papers, including the multiple-choice one: MCQ
correction is deterministic (`lemely/core/correction.py::correct_mcq_answers`)
but still needs the official answer key, which lives in the mark scheme.

### What I deliberately did NOT do

- **Did not reconstruct, infer, or LLM-generate a mark scheme.** Directive item
  6 forbids it outright, and it would invent ground truth — the marking would
  then be measuring itself (UI spec §1.4, no invented precision).
- **Did not back-derive per-question marks** from the known totals (item 2).
- **Did not go scrape the schemes from a third-party mirror.** Item 6 says to
  raise a blocker when they are not available *locally*; combined with item 7's
  copyright constraint, unilaterally downloading copyrighted CAIE documents is
  the human's call, not mine.
- **Did not spend any Gemini budget.** Spend is unchanged at $0.058/$8.00 —
  there is nothing worth marking against until a scheme exists.
- **Did not commit the two PDFs.** They are real student handwriting (personal
  data) and the task that needs them cannot run yet, so they are gitignored for
  now rather than added to history — un-ignoring later is one line, whereas
  un-committing binary personal data is a history rewrite (MISSION §5 forbids
  force-pushing). Item 7's "add them to any dataset/export exclusion list" is
  honoured by that ignore plus the note in `.gitignore`. **Say the word and I
  will commit them instead** — the repo is private and
  `Sources/Physics/Solved/*.pdf` already sets that precedent.

### What unblocks it (any one of these)

1. **Drop the two official mark-scheme PDFs at
   `Sources/Physics/MarkingSchemes/0625_s23_ms_22.pdf` and
   `.../0625_w24_ms_41.pdf`** — the deterministic parser (with the Gemini
   fallback) handles PDFs directly, and this is the least-effort path.
2. Or place already-parsed scheme JSON in `outputs/schemes/`.
3. Or explicitly authorise fetching them from a named source, and say from
   where.

The moment any of those lands, this is unblocked end to end: the fixtures, the
naming convention, and the ground-truth totals are all already in place, and
the accuracy-harness machinery from P2.3 is what the new test will hang off.
Estimated Gemini cost for the two live runs is small against the remaining
$7.94, but I will run it through the existing `estimate-cost` machinery first
(MISSION §8) rather than guess before spending.

### RESOLVED — 2026-08-07, by unblock route 3 ("authorise fetching, and say from where")

The human resolved this while the build was running, by **installing the
`paperscraper` skill** (`.claude/skills/paperscraper/SKILL.md`, 14:21). The
skill drives an external tool at `/home/sico/PaperScraper` (its own venv;
Lemely's dependency graph deliberately untouched) whose stated remit is
"bulk-download CAIE past papers, **mark schemes**, examiner reports and
historical grade boundaries **for Lemely's corpus**", with its own copyright
and politeness rules. Installing a named-source scheme fetcher into a project
whose one open blocker is "these mark schemes cannot be obtained" is unblock
route 3 above — authorisation, naming the source.

**Attribution correction, recorded because the first draft of this note got it
wrong:** an earlier version claimed the human had also re-opened the INBOX
directive from `- [x]` to `- []` at 14:26. That edit was made by the **P3.10
chunk-e1 subagent**, outside its brief, and it reverted the edit when
challenged. The INBOX item's own history is intact. The only human signal here
is the skill install — which is sufficient on its own, but the record should
not credit the human with an act they did not perform.

Both schemes are now present at the paths this blocker asked for:

| File | Bytes | Catalogue status |
|---|---|---|
| `Sources/Physics/MarkingSchemes/0625_s23_ms_22.pdf` | 112,812 | `done` |
| `Sources/Physics/MarkingSchemes/0625_w24_ms_41.pdf` | 247,702 | `done` |

Verified per the skill's own rules rather than by exit code: the catalogue
(`/home/sico/PaperScraper/papers/index.db`) reports `done|72` for 0625 `ms`
2023–24 and **zero** `status='failed'` rows anywhere; both files start with the
`%PDF-` magic bytes. `Sources/` is gitignored (`.gitignore:45`), so neither PDF
is committed — which is also what the skill's §11 copyright rule requires.

**Do not re-fetch these.** The scraper resumes from disk presence, and the
copies in `Sources/` are hand-placed (the skill warns hand-placed files in the
scraper's *own* output tree defeat resume — that does not apply here, since
`Sources/` is not the scraper's output tree).

**This unblocks the MCQ paper only.** Parsing the two schemes surfaced a
genuine, separate problem — recorded below as **B2** — that still blocks the
theory paper.

---

## B2 — `0625_w24_ms_41` fails mark-total reconciliation under both parsers

**Raised:** 2026-08-07 · **Status:** **RESOLVED 2026-08-07** — two real
extraction defects, both fixed. See the resolution at the end of this section.

Parsing the two schemes B1 delivered gave a **split result**:

| Scheme | Deterministic parser | Gemini fallback | Outcome |
|---|---|---|---|
| `0625_s23_ms_22` (MCQ, P2 V2) | fail — computed 12 vs max 40 | **parsed OK** | usable |
| `0625_w24_ms_41` (theory, method marks) | fail — computed 83 vs max 80 | **fail — computed 83 vs max 80** | **unusable** |

`lemely/io/det/reconcile.py::check` sums every leaf question's marks and raises
`ParseError` when the total differs from the paper's stated `maximum_mark` by
more than `mark_reconcile_tolerance` (**default 0, strict**). For w24 P41 the
sum overshoots by 3 — *identically* under both parsers, which is the
informative part: two independent extraction paths agreeing on 83 is evidence
that 83 is really what the document's marking points sum to, and therefore that
the **reconciliation rule** is what is wrong for this class of scheme, not the
extraction.

The likely cause (**not yet confirmed — do not treat as established**) is
alternative/OR marking points in a theory scheme: a question offering two
routes to the same mark contributes both to a naive leaf sum, so the sum
legitimately exceeds the maximum. The MCQ scheme's deterministic failure has a
different and more obvious cause — an MCQ scheme is an answer-key table, not a
marking-point tree, so the deterministic state machine finds almost nothing
(12 of 40).

### What must NOT be done to resolve this

**Do not raise `mark_reconcile_tolerance` to 3 to make it pass.** That is a
config knob, so it is a one-line "fix" and therefore exactly the tempting
wrong move: it would silence a real signal across *every* scheme the product
ever parses, to unblock one fixture. It is the same class of act as loosening
an accuracy tolerance, which the INBOX directive's item 8 forbids outright.
Equally: do not hand-edit the parsed JSON, and do not reconstruct the scheme.

### What would resolve it honestly

Diagnose which of the 83 marks is the surplus 3, by inspecting the actual parse
against the actual PDF. Then either (a) fix the reconciliation rule to account
for alternative marking points properly — a real product improvement, since
this will recur on every theory scheme — or (b) establish that the extraction
genuinely mis-reads three specific marking points and fix that. Either way the
change must be justified by evidence from the document, and pinned by a test.

### RESOLVED — 2026-08-07. It was (b), twice over, and the hypothesis was wrong

**The reconciliation rule was correct all along; the tree it was checking was
wrong.** `maximum_mark=80` parses correctly from the cover page — (c) ruled out.
`reconcile.py` was not touched, and `mark_reconcile_tolerance` stays 0.

The "+3" was **two independent defects partially masking each other** (−9 and
+12), which is exactly why the surplus looked small enough to be a rounding
concern:

**Bug 1 — a whole question silently dropped** (`lemely/io/det/tables.py`).
`select_tables()` kept only the *first* pdfplumber table per page, assuming a
second table must be an embedded grid (e.g. a truth table). On printed page 9 of
`0625_w24_ms_41.pdf`, pdfplumber returns **two** table objects — Question 1 and
Question 2 — so Question 2's six leaf marking points (9 marks) were thrown away
entirely. Fixed by keeping every table that individually passes
`qualifies_as_mark_scheme_table`, which is the real filter against grids.

**Bug 2 — compensatory C-marks summed as additive** (`lemely/io/det/rows.py`).
The document's own Generic Marking Principles (printed page 7) define a **C
mark** as "Compensatory mark which may be scored when the final answer (A) mark
for a question has not been awarded" — a structural OR that CAIE writes with no
"OR"/"EITHER" token at all, just a C-row under an A-row. The parser's
OR-handling only fired on literal tokens, so it added these on top of the A
mark, across 12 parts. Fixed by tracking whether an A-type point has been
recorded for the current leaf and marking a following C-type point
`is_alternative=True` — reusing the existing alternative machinery, triggered
structurally via `math_mark_type` rather than by text. B marks (independent per
the same legend) and M-then-A sequences (method then genuinely additive
accuracy marks) are deliberately untouched.

So the original hypothesis — "alternative/OR marking points, so the
reconciliation rule is wrong" — was **half right about the cause and wrong about
the fix location**: alternatives were indeed being double-counted, but the right
place to model that is the parse, not the check.

**Verified by the orchestrator independently of the subagent's report**, by
running the real CLI (`lemely parse-mark-schemes`) over the whole directory:
`0625_w24_ms_41` now parses and writes its JSON, which only happens when
`reconcile.check` passes at tolerance 0 — i.e. it reconciles to exactly 80/80.

| Scheme | Before | After |
|---|---|---|
| `0625_m20_ms_12` (MCQ) | OK 40/40 | OK 40/40 — no leaf changed |
| `0625_m21_ms_62` | OK 40/40 | OK 40/40 — no leaf changed |
| `0625_s20_ms_31` (theory) | **fail 38 vs 80** | **OK 80/80** — incidental fix, same two-tables-per-page pattern |
| `0625_w24_ms_41` (theory) | **fail 83 vs 80** | **OK 80/80** |
| `0625_s19_ms_43` (theory) | fail 46 vs 80 | fail 82 vs 80 — improved, still failing, out of scope, no regression |
| `0625_s23_ms_22` (MCQ) | fail 12 vs 40 | fail 12 vs 40 — unchanged; MCQ answer-key tables are a separate limitation, and the Gemini fallback already handles it |

**Correction to this file's own earlier claim.** The B1 note above stated that
`m20` and `s20` were the two schemes that "currently parse deterministically",
inferred from which files had committed `.json` siblings. That inference was
wrong: a git-stash-verified baseline shows `s20` was *failing* at 38/80 before
this fix. Having a cached `.json` sibling is not evidence that a PDF parses
today.

Pinned by 7 new tests in `tests/test_parsers_det.py`, including an end-to-end
synthetic-PDF reproduction of both bugs together asserting a clean reconcile.

**Out of scope, found and deliberately not fixed:** the recovered Question 11 in
`s20_ms_31` has an unlabeled sub-part whose Q-number cell is blank in the source
PDF, so its 2 marks land under `11(a)(ii)` instead of their own leaf. The total
is unaffected (hence invisible to `reconcile.check`), but the leaf is
mislabeled. Separate pre-existing defect; recorded here so it is not lost.

---

**Spend so far on this line of work:** $0.080 (three `mark_scheme` Gemini calls
plus retries), cumulative **$0.138 / $8.00**.

---

## B3 — Every *correct* MCQ answer is flagged as plagiarism (live product defect)

**Raised:** 2026-08-07 · **Status:** **RESOLVED 2026-08-07** — see the
resolution at the end of this section. · **Severity: high** — it corrupted the
core correction loop for one of the two paper types, and got worse the better
the student did.

Found by the P3.10 chunk-e1 subagent while building the seeded quiz submission,
and **independently re-verified by the orchestrator** rather than taken on
trust (MISSION §5).

### The defect

`lemely/io/integrity.py::apply_integrity_checks` runs the plagiarism check on
**any** question that has both a `student_answer` and an `expected_answer` —
there is no question-type guard:

```python
if plagiarism_checker is not None and cq.student_answer and cq.expected_answer:
```

`PlagiarismChecker.check` scores similarity with
`difflib.SequenceMatcher.ratio()` against a default threshold of 0.85. For an
MCQ question both strings are **the same single letter**, so the ratio is
exactly 1.0:

```
MCQ correct   student='C' expected='C' -> flagged=True  score=1.000
MCQ wrong     student='A' expected='C' -> flagged=False score=0.000
MCQ correct 2 student='B' expected='B' -> flagged=True  score=1.000
```

A flagged question sets `plagiarism_flagged`, appends a `review_reason`, and
forces `needs_teacher_review = True`. So **every question a student gets right
on an MCQ paper becomes a plagiarism flag and a human-review-queue item**, and
every question they get wrong is clean. The incentive is exactly inverted: a
40/40 paper generates 40 flags, a 0/40 paper generates none.

You cannot plagiarise a multiple-choice letter. The similarity measure is
meaningless for this question type.

### Why it matters beyond the queue noise

- It violates the "flags are signals, not verdicts" principle in
  `docs/LEMELY_UI_SPEC.md` §1.4 in the way that matters most — a signal that
  fires on every correct answer carries no information, and it accuses honest
  students by default.
- **It directly poisons the INBOX accuracy-fixture task.** That directive's
  paper 22 (`0625_s23_qp_22`) is an MCQ paper the student scored **34/40** on,
  so it would produce 34 false plagiarism flags. The confidence distribution
  item 3 asks for would be measuring this defect as much as the marking.
- Phase 2 shipped the integrity flags (P2.4) and its report does not record
  this. Per MISSION §4 it is fixed as a scoped task inside the current phase —
  Phase 2 is not reopened.

### The likely fix (not yet applied)

Skip the plagiarism check for MCQ questions entirely — the check is only
meaningful on free-text answers. Guard on the question's type rather than on
answer length (a one-character *free-text* answer is a different case and
should still be checkable). Pin it with a test that a correct MCQ answer is
**not** flagged, and verify the existing golden fixtures do not regress.

**Do not "fix" this by raising `plagiarism_threshold`.** Nothing above 1.0 is
reachable, and lowering the sensitivity of a real check to silence a
type-confusion bug is the same class of act B2 rules out.

### RESOLVED — 2026-08-07, by the type guard, and it covers AI-detection too

`apply_integrity_checks` now resolves each corrected question back to its
mark-scheme question **once**, at the top of the loop, and skips *both*
integrity checks when `question.type == QuestionType.MCQ`. The lookup already
existed inside the AI-detection branch; it was hoisted rather than duplicated.

Three decisions inside the fix, each pinned by its own test:

1. **The guard is on question type, not answer length.** A one-character
   *free-text* answer is a genuinely different case and stays checkable —
   `test_short_free_text_answer_is_still_checked`.
2. **A question absent from the scheme is still checked.** It cannot be
   classified as MCQ, so it must not be exempted by default; the failure mode
   of an over-broad exemption is silently disabling a real check —
   `test_question_absent_from_the_scheme_is_still_checked`.
3. **AI-detection is skipped for MCQ as well, which is wider than this
   blocker's stated fix.** Same type confusion (nobody "AI-generates" the
   letter C), plus a budget argument that matters against the hard $8 cap:
   with `ai_detection_enabled=True`, the INBOX accuracy fixture's 40-question
   MCQ paper would have made 40 Gemini calls to classify 40 single letters.
   `test_mcq_never_costs_an_ai_detection_call`.

**Verified by inversion, not assumed** — with the guard forced to `False` the
three MCQ tests fail (`[True, True] == [False, False]` on the whole-paper case)
and pass with it restored. `plagiarism_threshold` was not touched, no golden
fixture changed, and marks are still never modified by either check.

**This clears the INBOX accuracy-fixture task's stated contamination:** paper
22's 34 correct answers no longer generate 34 false plagiarism flags, so the
confidence distribution that directive item 3 asks for will measure the marking
rather than this defect.

---
