# Real past-paper accuracy — INBOX-2026-08-07-ACC

Two genuine solved CAIE 0625 (Physics) student scripts, run through the real
ingest to OCR (Gemini vision extraction) to mark to grade pipeline
(`lemely.web.services.grading.extract_answers` + `grade_paper`) - no mocked
Gemini, no reconstructed mark scheme. Run via `scripts/run_real_paper_accuracy.py`;
artefacts cached at `reports/accuracy-real/<fixture-id>/` (gitignored - see
"Personal data" below). This document is the only committed artefact from
that directory.

The two papers are reported separately throughout and never averaged
(directive item 5). Averaging their signed errors (+3 and -3) would produce a
fabricated "no bias" claim, exactly the invented-precision trap directive
item 2 warns against, so that number does not appear anywhere below.

## Tolerance (fixed before any result was seen)

Plus or minus 10% of each paper's own maximum mark: plus or minus 4 marks on
paper 22 (40 max), plus or minus 8 marks on paper 41 (80 max). Justification:
adjacent CAIE grade boundaries on these papers sit roughly 6-10% of the
maximum apart, so a total error inside this band risks at most one grade
band - the smallest error size that still means something to a student. This
number was fixed by policy, is implemented in
`lemely/accuracy/real_papers.py::tolerance_marks`, and was not tuned to
either result. Paper 22 would have needed an error of 5 or more marks
(predicted 29 or below, or 39 or above) to fail; paper 41 would have needed
an error of 9 or more marks (predicted 57 or below, or 75 or above).

## Paper 22 - `0625_s23_qp_22` (MCQ, 34/40)

| Metric | Value |
|---|---|
| Predicted total | 37/40 |
| Ground truth | 34/40 |
| Signed error | +3 (over-awarded) |
| Absolute error / MAE (n=1) | 3.0 |
| Tolerance | 4.0 - within |
| Confidence distribution (marks) | high: 40, medium: 0, low: 0 |
| Marks flagged needs_teacher_review | 0 |
| Predicted grade | A (grade_confidence: medium) |
| Marking path | MCQ - deterministic marking; Gemini used only for vision extraction |
| Gemini calls | 1 (vision extraction only; correct_mcq_answers is deterministic) |

### The most important finding on this paper

MCQ marking (`correct_mcq_answers`) is deterministic - it does exact string
comparison against the official answer key. There is no marking-judgement
error possible on this path. All 3 marks of error on this paper are vision or
transcription error: the extraction step misread or mis-attributed at least
one student mark to the wrong option.

And the system did not know it was wrong. Every one of the 40 marks came
back at confidence 1.0 / band high, and zero marks were flagged for teacher
review. The pipeline was confidently wrong - full-scale false confidence on a
paper where the marking logic itself is provably correct. This is a direct,
concrete instance of what UI spec section 1.4 ("visible confidence") exists
to catch, and is the single most useful thing this exercise produced: a wrong
total that looked maximally trustworthy by every signal the system currently
surfaces.

Contrast with paper 41 below, where the system landed the same absolute error
(3 marks) but did signal uncertainty honestly.

## Paper 41 - `0625_w24_qp_41` (theory w/ method marks, 66/80)

| Metric | Value |
|---|---|
| Predicted total | 63/80 |
| Ground truth | 66/80 |
| Signed error | -3 (under-awarded) |
| Absolute error / MAE (n=1) | 3.0 |
| Tolerance | 8.0 - within |
| Confidence distribution (marks) | high: 60, medium: 20, low: 0 |
| Marks flagged needs_teacher_review | 20 |
| Predicted grade | A (grade_confidence: low) |
| Marking path | Theory with method marks - AI marking (one Gemini call per leaf question, 43 leaf questions) + Gemini vision extraction |
| Gemini calls | 1 vision extraction + 1 correction call per leaf question |

Here the pipeline's confidence signal is doing its job: 20 of 80 marks (25%)
were assigned medium confidence and flagged for teacher review, and the
paper-level grade_confidence came back low rather than the medium paper 22
got despite paper 22's lower internal-question uncertainty. A human reviewing
this paper would be pointed at the right quarter of it to double-check. Same
absolute error as paper 22 (3 marks), opposite direction, honestly flagged
instead of silently confident.

## What this does NOT show - per-question accuracy is not measured

Ground truth for these fixtures is the paper total only (34/40 and 66/80 -
see the fixture filenames,
`SubjectCode_SeasonYear_qp_PaperVariant-(AchievedMark..MaxMark)`). No
per-question ground truth exists, none was fabricated, and none was
back-derived from the pipeline's own output (directive item 2 - that would be
invented precision).

This means the totals above cannot rule out cancelling errors. Paper 22's
"predicted 37 vs truth 34" is consistent with a single 3-mark over-credit -
but it is equally consistent with, say, 5 marks over-credited and 2 marks
under-credited elsewhere, which would still sum to +3 and would still read as
"only 3 off" from the total alone. A correct total made of two cancelling
errors is a failure, not a pass (directive item 4), and the total alone
cannot distinguish the two cases.

This is exactly why the per-question breakdown and rendered annotation
overlay artefacts exist (directive item 4) - they are the human's spot-check
route, not this document. They are deliberately not committed (see below); a
human with access to the local artefacts should open
`reports/accuracy-real/<fixture-id>/annotation_overlay.pdf` and
`per_question.json` before treating either total as validated
question-by-question.

## Cost

Cumulative Gemini spend before this task: $0.138 (parsing the two mark
schemes, prior session). This run added roughly $0.021 (1 vision extraction
call per paper plus 43 correction calls for paper 41's non-MCQ questions),
bringing cumulative spend to $0.15864705 / $8.00. Nowhere near the $1.00
stop-and-report threshold this task was gated on, let alone the $8 hard cap.

## Personal-data handling

The per-question JSON (`per_question.json`, `raw_run.json`) contains the
student's transcribed handwriting (extracted answers / working-out text), and
`annotation_overlay.pdf` renders the actual scan pages. Both are personal
data of a minor, extending the same judgment already applied to the source
fixture PDFs (`tests/fixtures/real-papers/`, gitignored). They are written
under `reports/accuracy-real/<fixture-id>/` and that directory's contents are
gitignored (see `.gitignore`); only this numbers-only `REPORT.md` is
committed. It contains no transcribed answer text and no imagery. Satisfies
directive items 3, 4, and 7.

## Test coverage

- `lemely/accuracy/real_papers.py` - pure measurement layer (absolute/signed
  error, tolerance check, MAE, marks-weighted confidence distribution,
  review-flagged-marks total), no I/O, no Gemini. mypy-strict clean.
- `tests/test_accuracy_real_papers.py` - hermetic unit tests over the above
  (always run) plus two live-gated end-to-end tests (`LEMELY_LIVE_ACCURACY=1`
  plus a resolvable Gemini key), one per paper, asserting the tolerance from a
  real pipeline run (or a replayed cached artefact - see
  `scripts/run_real_paper_accuracy.py`'s idempotency note). Both currently
  pass (`within_tolerance: true` for both papers, as shown above). Per
  directive item 8: if a future re-run misses tolerance, these tests must
  stay red - no loosening, no skip, no xfail; the gap goes in
  `BUILD/DECISIONS.md` instead.
