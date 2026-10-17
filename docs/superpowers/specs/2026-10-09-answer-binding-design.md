# Answer binding: stop extracted answers landing on the wrong question

Date: 2026-10-09. Status: approved design, owner decisions recorded below.

Line numbers refer to `develop` at 885724d0.

## Goal

An extracted answer is marked against the question the student wrote it for, or the paper is not published. Today the extraction model both reads the handwriting and decides which question owns it, and nothing checks the second decision. This design separates the two, derives the question id from evidence the code can verify, and adds a gate that holds a paper when the binding cannot be verified.

## Evidence the design rests on (probes run 2026-10-09)

Paper: 0625/41 Oct/Nov 2024, one student script, 19 scanned pages, no text layer. Teacher's mark on the corrected copy: 66/80.

1. **Staging published 2/80.** Attempt `f7d8c0ac-10a4-4e64-9737-f6616d78afe5` (`/student/result/2`) shows grade U and "We're confident about 42 of 42 questions". The per-question feedback shows each answer marked against a neighbouring question: `1a_ii` was marked with "63 cm", `1b` with "20 cm", `1c_i` with the spring constant, and so on to the end of the paper.
2. **Binding, not marking, loses the marks.** An extraction of the same scan with every answer on its own question, marked against `corpus/mark-schemes/0625_w24_ms_41.json`, scores 61/80. Binding therefore explains about 59 of the 64 lost marks. That extraction and that marking ran on an older checkout (1bee5a4d: prompt version 5, `gemini-2.5-flash` for both steps, the whole PDF uploaded as one file), so the figure shows what correct binding is worth, not what the current marker would award.
3. **The model reads correctly and labels wrongly.** In a reproduced run the boxes sit on the right pages at the right heights ("43cm" at page 2, y 465-493; "63cm" at page 2, y 492-519), but the ids are handed out in order, one per physical answer line. Question 1(a)(i) has two answer lines under one `[1]`, so it consumes `1a_i` and `1a_ii`, and every later answer lands one question late. Question 6(c)(i) ("increase" / "decrease") splits the same way. Drawings and blanks at 7(b)(i), 7(c) and 8(a) move the offset again.
4. **Current code misbinds on every run measured, and a stronger model does not help.** Seven completed runs of the code at 885724d0, cache bypassed:
   - `gemini-3.5-flash-lite` (the default), four runs: one shifted by one from `1b` to `7c` (the staging pattern); one chaotic, with offsets from -1 to -9, the invented ids `5b_i`, `5b_ii`, `5c`, and six ids used twice; two shifted by one across `1b`-`1c_ii` only, one of them using `2a_i` twice and the other inventing `1c_iii`.
   - `gemini-3.8-flash`, three runs: all three shifted by one across the whole paper.

   The partial shifts produce a plausible total, which is worse than 2/80 because nobody questions it. The stronger model follows the ordinal pattern more consistently, so the defect lies in what the model is asked, not in the model tier, and changing `extraction_model` is not a mitigation. All seven runs rendered pages at 72 dpi, the scan's native resolution, because the production-size upload stalled on the test machine. Seven runs establish "every run measured", not a rate.
5. **The manifest gives the model nothing to anchor on.** `build_extractor_user_prompt` (`lemely/io/prompts/answer_extraction.py:162`) emits `- 1a_i: type=recall, marks=1` for every leaf. Across `corpus/mark-schemes`, 11,024 leaves carry no `question_command`, and every non-MCQ leaf is typed `recall`, so the type-specific prompt guidance never applies.
6. **Extraction runs on the weakest settings.** `extraction_model = "gemini-3.5-flash-lite"`, thinking level `minimal`, `EXTRACTION_MEDIA_RESOLUTION = "medium"` (`lemely/io/answer_extraction.py:48`).
7. **No guard checks binding.** `confidence` measures legibility, so the shifted answers report 0.98-1.00. `lemely/io/reread.py` and `lemely/io/second_read.py` re-check the text of an answer, never its owner. `normalize_extracted_answers` (`answer_extraction.py:258`) correctly refuses to guess ids, but it cannot see that an id the model supplied is wrong. The marker described about thirty answers as irrelevant to their question and reported each as a confident zero.

8. **The regression window is known but not isolated.** Commit 1094cfde (2026-09-21) moved extraction to `gemini-3.5-flash-lite` with `minimal` thinking and to per-page images at `medium` resolution. The single run on the older checkout in item 2 bound every answer correctly. One run is not evidence that the older path was reliable, and the older settings cannot be replayed on current code: `gemini-2.5-flash` rejects the current request with `400 INVALID_ARGUMENT`. The manifest was already unanchored before that commit.

Recorded outputs of the runs are in `.omc/research/p4n24-shift/` (ignored). They contain answer text only.

## Owner decisions

| # | Question | Decision |
|---|---|---|
| D1 | Extra extraction cost and latency per paper | Reliability first: up to roughly 3-5x current extraction cost and 30-60 s more per paper |
| D2 | Blank question papers | Add a question-paper corpus next to the mark schemes; papers without one use the label path |
| D3 | Binding cannot be verified | Retry once automatically, then hold: no score is published and the paper goes to teacher review |
| D4 | Upload shape | Mixed: most answers are written on the printed paper, a real share on separate sheets. Both paths are first class |
| D5 | Approach | Position binding and label binding behind one contract, one gate after both, gate delivered first |
| D6 | Held paper of a student with no teacher | Held state with re-upload guidance; the review item goes to the admin queue |

## Principle

Reading text and deciding which question owns it are separate steps. The model never has the final say on a question id. Code derives the id from evidence: the position of the writing on a known page, or a label the model quotes verbatim.

Two rules follow.

- The reader never sees expected answers, only the expected shape and the number of answer slots. Showing the answer would bias transcription. The gate may use expected answers, because the gate never changes text.
- Every answer carries where its binding came from and the evidence for it. Both are stored with the attempt and shown to the teacher.

## Architecture

Today: render, one call that reads and labels, mark.

New: render, map pages, bind and read, gate, then mark, retry, or hold.

New package `lemely/io/binding/`. Each unit is testable alone.

| Unit | Job | Depends on |
|---|---|---|
| `PaperLayout` | Per leaf: id, printed label (`1(a)(i)`), stem, marks, question-paper page, regions, answer slots, expected shape (number, text, drawing) | question-paper corpus, mark scheme |
| `PageMap` | Classifies each scan page as question-paper page N, separate sheet, cover, or blank | one model call, validated by code |
| `PositionBinder` | Binds answers on question-paper pages by region | `PaperLayout`, `PageMap` |
| `LabelBinder` | Binds answers on separate sheets, and whole papers that have no layout, by quoted label | anchored manifest |
| `BindingGate` | Pure function from bound answers, layout and mark scheme to pass, retry, or hold, with reasons | nothing external |
| Orchestrator | Runs the units, performs the one retry, fills the binding report | `GeminiAnswerExtractor._extract` |

`ExtractedAnswer` keeps its existing fields, so the marker's input does not change. It gains `binding_source` (`position` or `label`), `binding_evidence`, and `binding_status` (`verified`, `unverified`, `unbound`). `ExtractedAnswers` gains a `binding` report: binder used per page, checks fired, verdict, whether a retry ran.

`confidence` keeps its meaning, legibility. The student-facing "confident about N of M" counts an answer only when it is legible and its binding is verified.

## Binding gate

Each check returns pass or fail with evidence. No check trusts an id the model supplied.

### Structural checks

| # | Check | Fires on (from the recorded runs) |
|---|---|---|
| G1 | An answer's id is not in the manifest | `5b_i`, `5b_ii`, `5c`, `1c_iii` |
| G2 | Two answers share an id | `2a_i` twice in one partial run; `9a`-`9c_iv` twice in the chaotic run |
| G3 | Answers on a page differ in number from the leaves the layout puts there, or an answer's page differs from its leaf's page. Needs `PaperLayout` | `1c_i` boxed on page index 2 where the layout puts it on page index 3; a one-slot shift fails this at every page boundary |
| G4 | A region with several answer lines produced several ids. Needs `PaperLayout` | 1(a)(i), 6(c)(i) |
| G5 | Reading order by page and box top disagrees with manifest order | the chaotic run, where ids jump from `2a_ii` to `3a` |

### Semantic checks

| # | Check | Notes |
|---|---|---|
| G6 | Rate of shape mismatches: a number was expected and prose was found, or the reverse | Shape comes from the mark scheme's answer points and the question paper's cue (`= ........ [2]`), not from `type` |
| G7 | Shift detector. For leaves with a numeric expected value, compare the student's value with the expected value at offsets 0, ±1, ±2 using `lemely.core.equivalence`. More matches at a non-zero offset than at zero means a shift | Staging: "4.9 N" on `1c_ii` equals the expected value of `1c_i`; "20 cm" on `1b` equals that of `1a_ii` |
| G8 | The marker returns a new field `addresses_question` (`yes`, `no`, `unclear`) per answer. The gate counts `no` and the longest run of `no` | Same marking call, no extra cost. Covers papers with few numeric answers. Runs after marking and before publication |
| G9 | An independent second binding read on a different model, compared by page and box per id | Label path only, where G3 and G4 have no geometry. Reuses the `cross_model` seam in `lemely/io/second_read.py` |

### Verdict

- A localised failure, such as one unbound or doubtful answer, sends that question to teacher review with the reason "binding unverified". Its marks are pending, not zero.
- A paper-level failure is any of G1-G5, or G6, G7 or G8 above its threshold. The orchestrator retries once with stronger settings: `gemini-3.8-flash`, a higher thinking level, `high` media resolution. If the retry passes, its result is published. If it fails, the paper is held.

### Thresholds

The thresholds for G6, G7 and G8 are set by measurement, without human labels. Take aligned extractions from the golden corpus and apply synthetic misbindings, added as transforms to `lemely/accuracy/metamorphic.py`: shift by ±1 and ±2 from a random position, split one answer into two, drop one answer. The gate must fire on the transformed set and stay silent on the untransformed set.

Acceptance: the gate detects at least 99% of misbindings that affect three or more questions, and holds at most 2% of aligned papers.

## Question-paper corpus and layout

`corpus/question-papers/<paper>.json` sits next to the mark schemes and is built by an extended `DeterministicQuestionPaperExtractor` (`lemely/io/det/question_papers.py:251`). The extractor already tracks each leaf's line `top` and `bottom`; it exports only `page_number` today.

New fields per leaf:

- `printed_label`, for example `1(a)(i)`.
- `regions`: one entry per page the leaf occupies, each a page number and a vertical span.
- `answer_slots`: count and kind (dotted line, `= ......` line, working space, draw-on-figure).

The pairing rule in `lemely/io/question_papers.py` is reused: a layout leaf is valid only when its ref and marks equal the mark-scheme leaf's. An invalid leaf sends that question to the label path. A coverage report per paper counts every leaf by outcome; nothing is dropped silently.

A paper with no question-paper file uses the label path and the gate for every question.

## Page map

One call over all pages returns, per scan page, the printed page number, the footer code (`0625/41/O/N/24`) and the kind of page.

Code validates the reply: the footer code must equal the paper's identity, and page numbers must be unique and plausible.

Three outcomes that today collapse into "blank, 0 marks" become distinct:

- Wrong paper uploaded: the paper is held with a message naming the mismatch.
- A question-paper page is missing from the scan: its questions are "not in scan", not zero.
- A page appears twice: the later copy is used and the duplicate is flagged.

## Position binder

Used for scan pages mapped to question-paper pages.

One call per page carries the page image and that page's leaves in order, each with its label, stem and slots. The model returns, per leaf, the box of the printed label, the answer text, the working, and the answer boxes.

Code checks the reply; the model is not trusted:

- The printed-label boxes must run top to bottom in layout order with the layout's relative spacing.
- Each answer box must lie between its leaf's label and the next label.

Scan photographs are skewed and cropped, so the spans are anchored on the located labels, not scaled from PDF coordinates.

A leaf that fails a check gets one re-read of a crop of its span. If it still fails, that question goes to review.

A call holds only its page's two to six leaves, so a miscount cannot spread beyond the page.

Handwriting outside every region, such as a margin note, a blank page, or "Q3 cont.", is passed to the label binder. If that cannot bind it, the teacher sees "unassigned writing on page N".

## Label binder

Used for separate sheets, and for whole papers before the layout exists.

The call carries an anchored manifest: printed label, marks, expected shape, slot count, and the stem when the layout has one. The prompt states that all lines before one `[n]` bracket belong to one question.

The model returns two streams and no question ids: every question label it can see, printed or handwritten, quoted as written (`3 b ii`, `Q3(b)(ii)`, a bare `ii)`) with its page and position; and every block of student writing with its page and box. Code aligns the label stream with the label sequence the mark scheme implies, carrying a question number down from an earlier page, so `3`, then `a)`, then `ii)` yields `3a_ii`. Each answer is attached to the aligned label above it. Numbered answer lines inside one part are not labels. A missing or ambiguous label leaves the answer unbound; it is never guessed.

The second binding read, G9, is mandatory on this path.

## Model settings

Per-page calls use `high` media resolution. The choice of model for each binder is made from harness measurements of `binding_accuracy`, not assumed in this document.

## Hold flow in the product

- `UploadStatus` (`lemely/db/models/enums.py:190`) gains `held`. The result API gains `state`, either `published` or `held`.
- A held paper has no score, grade, XP, leaderboard entry, weakness statistics, or parent score notice.
- The student sees: "We could not match some answers to their questions. A teacher will check this paper." The specific cause is added when known: wrong paper, or pages missing.
- One paper-level review item is opened with a new `ReviewReason.binding_unverified`. It carries the failed checks, the page images and the proposed bindings. The teacher confirms or corrects the bindings, marking runs on the confirmed bindings, and the result is published.
- A single doubtful question uses the existing `needs_teacher_review` and `pendingTeacher` path with the new reason.
- A student with no teacher sees the held state with re-upload guidance, and the item goes to the admin queue (D6).

## Existing results

A one-off audit command runs G6 and G7 over stored attempts and lists the suspects. Stored results are already keyed by manifest id, so G1 and G2 cannot fire on them. Staging attempt 2 is one. Re-grading the listed attempts is a separate decision and is not part of this design.

## Errors

A failed or timed-out model call in the page map or a binder follows the existing retry policy and ends in `failed`, as today. `held` means only that the scan was read and its binding could not be verified.

## Telemetry

- Bus event `BINDING_GATE_RESULT`: binder, checks fired, verdict.
- Counters: hold rate, retry rate, fire rate per check, unbound answers.
- Harness metric `binding_accuracy`: the share of answers bound to the labelled question. `id_match_rate` measures id spelling only and stays as it is.

## Testing

- **Failing case first.** The recorded extraction outputs from this paper become JSON fixtures: four full shifts, one chaotic, two partial, one aligned. The gate must fire on seven and stay silent on one. The student's scan is not committed.
- **Threshold sweep.** The synthetic misbinding sweep over the golden corpus, with the acceptance targets above.
- **Unit tests** per check; table tests for the label parser's carry-down; layout extractor tests on a public blank question paper that has a text layer.
- **Live acceptance on this paper**, run locally only: ten fresh runs, no published misbinding, and every published score within 5 marks of 66.

## Delivery

One implementation plan per step.

1. Gate with G1, G2 and G5-G9; anchored `LabelBinder`; hold flow; audit command. Planned in two parts: 1A, the binding core, in which a held paper fails closed through the existing `failed` path with a message that says why; and 1B, the hold flow in the product.
2. Question-paper corpus, layout extractor, coverage report.
3. `PageMap`, `PositionBinder`, G3 and G4.

Step 1 alone stops silent wrong grades for every upload shape. Steps 2 and 3 lower the hold rate and raise accuracy.

## Out of scope

Found during the investigation and tracked separately:

- The 19-page scan is upsampled from 72 ppi to 2430 x 3439 PNG, a 79 MB upload for a 4.6 MB PDF, with no added information.
- The Files API upload and the generate call have no effective timeout; local runs hung for more than ten minutes.
- Four to nine boxes per run are dropped as `out_of_range_page` (four runs measured).
